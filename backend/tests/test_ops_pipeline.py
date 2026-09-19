"""Security and ledger invariants for the cloud pipeline bridge."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.routes import ops_pipeline
from app.core.ops_sources import ATTRIBUTIONS_KEY
from app.models import CleanRun, Episode, OpsSetting, Payout, PayoutItem, Wearer
from tests.test_ops_artifacts import multimodal_manifest
from tests.test_ops_routes import ORIGIN, _client, _episode, app
from tests.test_ops_sieve import fixture as sieve_fixture


TOKEN = "pipeline-test-only"
RECORDING = "ego_20260901_120000_ABC123"
SESSION = "korea-site"


@pytest.mark.asyncio
async def test_customer_inventory_requires_authentication(app, monkeypatch):
    monkeypatch.setenv('OPS_PIPELINE_TOKEN',TOKEN)
    async with _client(app) as client:
        assert (await client.get('/api/ops/pipeline/sieve-customer-inventory')).status_code==403
        result=await client.get('/api/ops/pipeline/sieve-customer-inventory',headers={'Authorization':f'Bearer {TOKEN}'})
    assert result.status_code==200
    assert result.json()['recordings']==[]


@pytest.mark.asyncio
async def test_customer_inventory_rechecks_exclusions_and_current_copy(app,db_session,monkeypatch):
    from app.core import ops_sieve
    monkeypatch.setenv('OPS_PIPELINE_TOKEN',TOKEN)
    _,row=sieve_fixture();doc=row['doc'];doc['country']='korea'
    person=Wearer(name='Private name must not be exported');db_session.add(person);await db_session.flush()
    db_session.add(CleanRun(run_id=doc['run_id'],device_id='ABC123',wearer_id=person.id,
        manifest_key=row['manifest_key'],manifest_version=row['manifest_version'],manifest_sha256=row['manifest_sha256'],
        manifest_json=json.dumps(doc),retained_seconds=60,rejected_seconds=0,rate_krw_hour=11000))
    db_session.add(Episode(recording=row['recording'],wearer_id=person.id));await db_session.commit()
    current=(await ops_sieve.inventory(db_session))[0]
    setting=OpsSetting(key=ops_sieve.STATE_KEY,value=json.dumps({'recordings':{row['recording']:{
        'status':'inherited','revision':current['revision'],'receipt':{'bucket':'6thsense-sieve','key':'private','version_id':'v'}}}}))
    db_session.add(setting);await db_session.commit()
    async with _client(app) as client:
        response=await client.get('/api/ops/pipeline/sieve-customer-inventory',headers={'Authorization':f'Bearer {TOKEN}'})
        assert response.status_code==200 and len(response.json()['recordings'])==1
        assert 'Private name' not in response.text
        assert response.json()['recordings'][0]['operator_key']==f'wearer:{person.id}'
        db_session.add(OpsSetting(key=ops_sieve.EXCLUSIONS_KEY,value=json.dumps({
            'schema':'6thsense-sieve-delivery-exclusions/1','wearers':{str(person.id):{'reason':'Residential exclusion'}}})))
        await db_session.commit()
        response=await client.get('/api/ops/pipeline/sieve-customer-inventory',headers={'Authorization':f'Bearer {TOKEN}'})
        assert response.json()['recordings']==[]


def _result(doc):
    digest = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    evidence = {
        "provenance": {"version_id": "provenance-v1"},
        "metadata": {"version_id": "metadata-v1"},
        "source_metadata": [{"version_id": "raw-metadata-v1"}],
    }
    return doc, f"qc-results/{doc['run_id']}/result.json", "manifest-v1", digest, evidence


def _business(country="india"):
    return {
        "kind": "business",
        "id": "factory-example",
        "name": "Example factory",
        "country": country,
        "payment_model": "b2b_contract",
    }


def _manifest(country="korea"):
    doc = multimodal_manifest()
    doc["country"] = country
    doc["recordings"][0]["sources"][0]["key"] = doc["recordings"][0]["sources"][0]["key"].replace(
        "sessions/site/", f"sessions/{country}-site/"
    )
    return doc


@pytest.mark.asyncio
async def test_pipeline_requires_the_dedicated_bearer_token(app, monkeypatch):
    monkeypatch.setenv("OPS_PIPELINE_TOKEN", TOKEN)
    async with _client(app) as client:
        assert (await client.get("/api/ops/pipeline/inventory")).status_code == 403
        assert (await client.get("/api/ops/pipeline/inventory", headers={"Authorization": "Bearer wrong"})).status_code == 403
        assert (await client.get("/api/ops/pipeline/inventory", headers={"Authorization": TOKEN})).status_code == 403
        response = await client.get(
            "/api/ops/pipeline/inventory", headers={"Authorization": f"Bearer {TOKEN}"}
        )
    assert response.status_code == 200
    assert response.json() == {"episodes": []}


@pytest.mark.asyncio
async def test_paid_personal_import_is_idempotent_and_duplicate_source_hash_is_held(
    app, db_session, monkeypatch
):
    monkeypatch.setenv("OPS_PIPELINE_TOKEN", TOKEN)
    monkeypatch.setattr(ops_pipeline, "_validate_new_source", lambda _doc, _episode: None)
    person = Wearer(name="Paid contributor", rate_krw_hour=11000)
    db_session.add(person)
    await db_session.flush()
    paid_at = datetime(2026, 9, 10, tzinfo=timezone.utc)
    episode = await _episode(
        db_session,
        RECORDING,
        wearer_id=person.id,
        paid=True,
        paid_at=paid_at,
        amount_krw=4321,
    )
    episode.session = SESSION
    await db_session.commit()

    first = _manifest()
    second = copy.deepcopy(first)
    second["run_id"] = "same-content-second-run"
    second_recording = "ego_20260901_130000_ABC123"
    second["recordings"][0]["recording"] = second_recording
    second["recordings"][0]["sources"][0]["key"] = second["recordings"][0]["sources"][0]["key"].replace(
        RECORDING, second_recording
    )
    other = await _episode(db_session, second_recording, wearer_id=person.id)
    other.session = SESSION
    await db_session.commit()
    results = {first["run_id"]: _result(first), second["run_id"]: _result(second)}
    monkeypatch.setattr(ops_pipeline, "verified_result", lambda run_id: results[run_id])

    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    async with _client(app) as client:
        imported = await client.post(
            "/api/ops/pipeline/import", headers=headers, json={"run_id": first["run_id"]}
        )
        again = await client.post(
            "/api/ops/pipeline/import", headers=headers, json={"run_id": first["run_id"]}
        )
        changed_result = copy.deepcopy(results[first["run_id"]])
        changed_result[4]["provenance"]["version_id"] = "provenance-v2"
        results[first["run_id"]] = changed_result
        changed_retry = await client.post(
            "/api/ops/pipeline/import", headers=headers, json={"run_id": first["run_id"]}
        )
        duplicate = await client.post(
            "/api/ops/pipeline/import", headers=headers, json={"run_id": second["run_id"]}
        )

    assert imported.status_code == 200 and not imported.json()["already_imported"]
    assert again.status_code == 200 and again.json()["already_imported"]
    assert changed_retry.status_code == 409
    assert duplicate.status_code == 409
    assert "source footage already imported" in duplicate.json()["detail"]
    run = await db_session.get(CleanRun, first["run_id"])
    assert run.paid and run.paid_at == paid_at and run.amount_krw == 4321
    assert run.wearer_id == person.id and run.rate_krw_hour == 11000
    assert not (await db_session.execute(select(Payout))).scalars().all()
    assert not (await db_session.execute(select(PayoutItem))).scalars().all()


@pytest.mark.asyncio
async def test_paid_business_import_keeps_unknown_amount_and_rejects_country_mismatch(
    app, db_session, monkeypatch
):
    monkeypatch.setenv("OPS_PIPELINE_TOKEN", TOKEN)
    monkeypatch.setattr(ops_pipeline, "_validate_new_source", lambda _doc, _episode: None)
    party = _business("india")
    episode = await _episode(db_session, RECORDING, paid=True, amount_krw=9999)
    episode.session = SESSION
    db_session.add(
        OpsSetting(
            key=ATTRIBUTIONS_KEY,
            value=json.dumps(
                {
                    RECORDING: {
                        "recording": RECORDING,
                        "device_id": "ABC123",
                        "session": SESSION,
                        "counterparty": party,
                    }
                }
            ),
        )
    )
    await db_session.commit()

    good = _manifest("india")
    good.update(counterparty=party, country="india")
    wrong = copy.deepcopy(good)
    wrong["run_id"] = "wrong-country"
    wrong["country"] = "korea"
    results = {good["run_id"]: _result(good), wrong["run_id"]: _result(wrong)}
    monkeypatch.setattr(ops_pipeline, "verified_result", lambda run_id: results[run_id])

    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    async with _client(app) as client:
        mismatch = await client.post(
            "/api/ops/pipeline/import", headers=headers, json={"run_id": wrong["run_id"]}
        )
        imported = await client.post(
            "/api/ops/pipeline/import", headers=headers, json={"run_id": good["run_id"]}
        )

    assert mismatch.status_code == 409
    assert "attribution or country differs" in mismatch.json()["detail"]
    assert imported.status_code == 200
    run = await db_session.get(CleanRun, good["run_id"])
    assert run.paid and run.amount_krw is None
    assert run.wearer_id is None and run.rate_krw_hour is None
    assert not (await db_session.execute(select(Payout))).scalars().all()
    assert not (await db_session.execute(select(PayoutItem))).scalars().all()


def test_verified_result_rejects_changed_original_metadata(monkeypatch):
    storage, row = sieve_fixture()
    base = f"clean/{row['run_id']}/{row['recording']}/"
    key = ("6thsense-processed", base + "metadata.json")
    _body, ref, metadata = storage.objects[key]
    storage.objects[key] = (b'{"device":"FFFFFF"}', ref, metadata)
    monkeypatch.setattr(ops_pipeline, "_client", lambda _settings: storage)

    with pytest.raises(ValueError, match="object digest changed"):
        ops_pipeline.verified_result(row["run_id"])


def test_new_source_requires_exact_current_versions_conversion_hash_and_raw_metadata(monkeypatch):
    storage, row = sieve_fixture()
    doc, rec = row["doc"], row["rec"]
    source_key = f"sessions/{SESSION}/ABC123/{row['recording']}/video.mp4"
    source_ref = storage.add(source_key, b"raw-video", bucket="6thsense-raw")
    source = {
        **source_ref,
        "size_bytes": source_ref["bytes"],
    }
    rec["sources"] = [source]
    base = f"clean/{row['run_id']}/{row['recording']}/"
    clean_body, clean_ref, _ = storage.objects["6thsense-processed", base + "metadata.json"]
    raw_metadata = storage.add(
        f"sessions/{SESSION}/ABC123/{row['recording']}/metadata.json",
        clean_body,
        bucket="6thsense-raw",
    )
    provenance = {
        "schema": "6thsense-clean-source-metadata/1",
        "run_id": row["run_id"],
        "recording": row["recording"],
        "source_media": [{k: source[k] for k in ("bucket", "key", "version_id")}],
        "copy_mode": "byte_exact_from_versioned_source",
        "metadata": clean_ref,
        "source_metadata": [raw_metadata],
    }
    storage.add(base + "metadata-provenance.json", ops_pipeline.json.dumps(provenance).encode())
    report = {
        "schema": "6thsense-raw-conversion-result/1",
        "recording": row["recording"],
        "status": "converted_staging",
        "source_complete_flag": True,
        "sources": [{**source_ref, "bytes": source_ref["bytes"]}],
    }
    receipt = storage.add(
        f"clean/test/staging/{row['recording']}/conversion.json", json.dumps(report).encode()
    )
    rec["source_provenance"] = {"conversion_receipt": receipt}
    take = {
        "session": SESSION,
        "prefixes": [f"sessions/{SESSION}/ABC123/{row['recording']}/"],
        "media": [{"key": source_key, "bytes": source_ref["bytes"], "etag": "etag"}],
    }
    monkeypatch.setattr(ops_pipeline, "walk_bucket", lambda prefix: {row["recording"]: take})
    monkeypatch.setattr(ops_pipeline, "get_settings", lambda: SimpleNamespace(bucket="6thsense-raw"))
    monkeypatch.setattr(ops_pipeline, "_client", lambda _settings: storage)
    original_lookup = storage.lookup

    def allow_raw(Bucket, Key, VersionId=None):
        if Bucket != "6thsense-raw":
            return original_lookup(Bucket, Key, VersionId)
        body, ref, metadata = storage.objects[Bucket, Key]
        if VersionId and VersionId != ref["version_id"]:
            raise AssertionError("Wrong test object version")
        return body, ref, metadata

    storage.lookup = allow_raw
    episode = SimpleNamespace(recording=row["recording"], session=SESSION)

    ops_pipeline._validate_new_source(doc, episode)
    rec["sources"][0]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="conversion receipt"):
        ops_pipeline._validate_new_source(doc, episode)
    rec["sources"][0]["sha256"] = source_ref["sha256"]
    provenance["source_metadata"][0]["key"] = f"sessions/{SESSION}/ABC123/other/metadata.json"
    storage.add(base + "metadata-provenance.json", json.dumps(provenance).encode())
    with pytest.raises(ValueError, match="metadata is outside"):
        ops_pipeline._validate_new_source(doc, episode)


@pytest.mark.asyncio
async def test_pipeline_status_cannot_assert_clean(app, db_session, monkeypatch):
    monkeypatch.setenv("OPS_PIPELINE_TOKEN", TOKEN)
    await _episode(db_session, RECORDING)
    async with _client(app) as client:
        response = await client.post(
            "/api/ops/pipeline/status",
            headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN},
            json={"recording": RECORDING, "state": "clean", "reason": "trust me"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_summary_requires_token_and_excludes_deleted_episodes(app, db_session, monkeypatch):
    from app.models import ProcessingJob, OpsSetting
    monkeypatch.setenv('OPS_PIPELINE_TOKEN', TOKEN)
    monkeypatch.setenv('OPS_AUTOMATION_ENABLED', 'true')
    await _episode(db_session, RECORDING)
    removed = RECORDING + '_s11'
    ep = await _episode(db_session, removed)
    ep.deleted_at = datetime.now(timezone.utc)
    ep.delete_kind = 'soft'
    db_session.add_all([
        ProcessingJob(recording=RECORDING, fingerprint='a' * 64, input_json='{}', state='blocked', reason='private diagnostic'),
        ProcessingJob(recording=removed, fingerprint='b' * 64, input_json='{}', state='blocked', reason='removed'),
        OpsSetting(key='last_scan', value='2026-09-19T10:51:34+00:00'),
    ])
    await db_session.commit()
    async with _client(app) as client:
        assert (await client.get('/api/ops/pipeline/health')).status_code == 403
        assert (await client.get('/api/ops/pipeline/health', headers={'Authorization': 'Bearer wrong'})).status_code == 403
        response = await client.get('/api/ops/pipeline/health', headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 200
    result = response.json()
    assert result['processing_counts'] == {'blocked': 1}
    assert result['last_raw_scan'] == '2026-09-19T10:51:34+00:00'
    assert result['automatic_scan'] is True
    assert result['accumulated_data']['totals']['episodes'] == 1
    assert 'private diagnostic' not in response.text and RECORDING not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize('same_bucket', [False, True])
async def test_health_accumulation_uses_confirmed_source_and_all_upload_states(app, db_session, monkeypatch, same_bucket):
    from app.models import OpsSetting, ProcessingJob
    from app.core.ops_sources import ATTRIBUTIONS_KEY
    from app.core.ops_raw import INVENTORY_KEY
    monkeypatch.setenv('OPS_PIPELINE_TOKEN', TOKEN)
    first = await _episode(db_session, RECORDING)
    second = await _episode(db_session, RECORDING + '_s02')
    for ep in (first, second):
        ep.session = 'business-delivery'
        ep.prefix = f'sessions/business-delivery/ABC123/{ep.recording}/'
        ep.duration_s = 1800
        ep.size_bytes = 1_000_000_000
    registry = {ep.recording: dict(recording=ep.recording, device_id=ep.device_id, session=ep.session,
                 counterparty=dict(kind='business', id='example', name='Private company', country='india', payment_model='b2b_contract'))
                for ep in (first, second)}
    db_session.add_all([
        OpsSetting(key=ATTRIBUTIONS_KEY, value=json.dumps(registry)),
        # Only a snapshot from this bucket can supply conflicting source evidence.
        OpsSetting(key=INVENTORY_KEY, value=json.dumps({'bucket': ops_pipeline.get_settings().bucket if same_bucket else 'another-bucket', 'takes': {
            first.recording: {'prefixes': ['sessions/china-work/ABC123/one/']}}})),
        ProcessingJob(recording=first.recording, fingerprint='a' * 64, input_json='{}', state='clean', reason=''),
        ProcessingJob(recording=second.recording, fingerprint='b' * 64, input_json='{}', state='blocked', reason=''),
    ])
    await db_session.commit()
    async with _client(app) as client:
        response = await client.get('/api/ops/pipeline/health', headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 200
    result = response.json()['accumulated_data']
    assert result['totals']['episodes'] == 2
    india = next(row for row in result['countries'] if row['country'] == 'india')
    assert india['known_seconds'] == (1800 if same_bucket else 3600)
    assert india['uploaded_bytes'] == (1_000_000_000 if same_bucket else 2_000_000_000)
    if same_bucket:
        assert next(row for row in result['countries'] if row['country'] == 'unassigned')['episodes'] == 1
    assert 'Private company' not in response.text and RECORDING not in response.text


@pytest.mark.asyncio
async def test_deleted_source_cannot_be_imported_or_have_status_restored(
    app, db_session, monkeypatch
):
    monkeypatch.setenv("OPS_PIPELINE_TOKEN", TOKEN)
    monkeypatch.setattr(ops_pipeline, "_validate_new_source", lambda _doc, _episode: None)
    person = Wearer(name="Removed contributor", rate_krw_hour=11000)
    db_session.add(person)
    await db_session.flush()
    episode = Episode(
        recording=RECORDING,
        session=SESSION,
        device_id="ABC123",
        wearer_id=person.id,
        deleted_at=datetime.now(timezone.utc),
        delete_kind="soft",
    )
    db_session.add(episode)
    await db_session.commit()
    doc = _manifest()
    monkeypatch.setattr(ops_pipeline, "verified_result", lambda _run_id: _result(doc))
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}

    async with _client(app) as client:
        imported = await client.post(
            "/api/ops/pipeline/import", headers=headers, json={"run_id": doc["run_id"]}
        )
        status = await client.post(
            "/api/ops/pipeline/status",
            headers=headers,
            json={"recording": RECORDING, "state": "queued", "reason": "retry"},
        )

    assert imported.status_code == 409 and status.status_code == 409
    await db_session.refresh(episode)
    assert episode.deleted_at is not None and episode.delete_kind == "soft"
    assert await db_session.get(CleanRun, doc["run_id"]) is None
