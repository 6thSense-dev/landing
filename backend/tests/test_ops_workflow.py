import json
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.core.ops_ledger import friday, previous_week, sunday, last_sunday, calculation_week, price
from app.core.ops_processing import diagnose
from app.api.routes.ops_payments import eligible
from app.models import CleanRun, Wearer, PayoutRecipient, PayoutItem
from tests.test_ops_routes import app, _sid, _client, ORIGIN
from tests.test_ops_clean import manifest


def test_friday_korea_cutoff_and_previous_week():
    due = friday(datetime(2026, 9, 14, 0, tzinfo=timezone.utc))
    assert due == datetime(2026, 9, 18, 9, tzinfo=timezone.utc)
    assert previous_week(due) == ("2026-09-07", "2026-09-14")
    assert friday(due) == due + timedelta(days=7)


def entry(**kw):
    return dict(
        run_id="a",
        recording="a",
        legacy_paid=False,
        payout_id=None,
        retained_seconds=14400,
        review_status="reviewed",
        collection_date="2026-09-01",
        rate_krw_hour=11000,
        allocated_krw=44000,
        **kw,
    )


def test_sunday_cutoff_includes_exact_time_and_uses_korea_week():
    due = sunday(datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert due == datetime(2026, 9, 20, 14, 59, tzinfo=timezone.utc)
    assert calculation_week(due) == ('2026-09-14', '2026-09-21')
    assert sunday(due) == last_sunday(due) == due
    assert last_sunday(due - timedelta(microseconds=1)) == due - timedelta(days=7)
    assert sunday(due + timedelta(microseconds=1)) == due + timedelta(days=7)


def test_accumulated_threshold_inclusive_and_excludes_future_unreviewed_reserved():
    due = sunday(datetime(2026, 9, 14, tzinfo=timezone.utc))
    a = entry()
    assert eligible([a], due, "accumulated")[0] == [a]
    a = {**a, 'retained_seconds': 14399}
    assert not eligible([a], due, "accumulated")[0]
    b = {**a, "recording": "b", "retained_seconds": 1, "allocated_krw": 3}
    assert len(eligible([a, b], due, "accumulated")[0]) == 2
    assert not eligible([a, b], due, "weekly")[0]
    for field, value in [
        ("review_status", "needs_review"),
        ("payout_id", "reserved"),
        ("collection_date", None),
        ("collection_date", "2026-09-21"),
    ]:
        assert not eligible([a, {**b, field: value}], due, "accumulated")[0]
    assert price([a, b]) == 44003


def test_missing_metadata_recovers_and_transient_failure_never_rejects():
    now = datetime.now(timezone.utc)
    base = {
        "uploaded": now - timedelta(hours=7),
        "media": [{"key": "s/video.mp4", "bytes": 100}],
        "meta": {},
    }
    assert diagnose(base, now)[0] == "recovering"
    assert diagnose({**base, "error": "AccessDenied"}, now)[0] == "retry"
    assert diagnose({**base, "media": []}, now)[0] == "recovering"
    assert diagnose({**base, "media": [], "uploaded": now}, now)[0] == "uploading"


@pytest.mark.asyncio
async def test_payment_requires_review_fences_recipient_reserves_once_and_locks_review(
    app, db_session, monkeypatch
):
    monkeypatch.setenv("WISE_PROFILE_ID", "123")
    monkeypatch.setenv("WISE_SOURCE_CURRENCY", "USD")
    sid = await _sid(db_session, "ops")
    person = Wearer(name="Test contributor", rate_krw_hour=11000)
    db_session.add(person)
    await db_session.flush()
    doc = manifest()
    doc.update(source_seconds=18000, retained_seconds=18000, rejected_seconds=0)
    rec = doc["recordings"][0]
    rec["source_seconds"] = 18000
    rec["intervals"] = [{"start_s": 0, "end_s": 18000, "disposition": "keep"}]
    run = CleanRun(
        run_id="factory-test",
        device_id="ABC123",
        wearer_id=person.id,
        manifest_key="x",
        manifest_version="v1",
        manifest_sha256="a" * 64,
        manifest_json=json.dumps(doc),
        retained_seconds=18000,
        rejected_seconds=0,
        rate_krw_hour=11000,
    )
    db_session.add_all(
        [
            run,
            PayoutRecipient(
                wearer_id=person.id,
                wise_recipient_id="321",
                verified_name="Test contributor",
                updated_by="test",
                wise_profile_id="123",
                wise_environment="sandbox",
                recipient_hash="h",
            ),
        ]
    )
    await db_session.commit()
    review = {
        "run_id": run.run_id,
        "recording": rec["recording"],
        "manifest_sha256": "a" * 64,
        "decision": "reviewed",
        "collection_date": "2026-09-01",
        "watched_all": True,
    }
    body = {
        "wearer_id": person.id,
        "entries": [{k: review[k] for k in ["run_id", "recording", "manifest_sha256"]}],
        "expected_amount_krw": 55000,
        "approve_payment": True,
    }
    async with _client(app) as c:

        async def post(path, body):
            return await c.post(
                "/api/ops/payments/" + path,
                json=body,
                cookies={"sid": sid},
                headers={"Origin": ORIGIN},
            )

        initial = await c.get("/api/ops/payments/state", cookies={"sid": sid})
        body["expected_recipient_revision"] = initial.json()["contributors"][0]["recipient"]["revision"]
        assert len(body["expected_recipient_revision"]) == 64
        missing_revision = {k: v for k, v in body.items() if k != "expected_recipient_revision"}
        assert (await post("approve", missing_revision)).status_code == 422
        assert (await post("approve", body)).status_code == 409
        assert (
            await post("review", {**review, "watched_all": False})
        ).status_code == 422
        r = await post("review", review)
        assert r.status_code == 200, r.text
        # Another operator can change bank details for the same Wise ID or
        # replace that recipient entirely while this operator's page is open.
        from app.core.wise import WiseClient
        monkeypatch.setenv("WISE_API_TOKEN", "test-only")
        latest_revision = body["expected_recipient_revision"]
        for recipient_id, recipient_hash in [(321, "new-bank-details"), (999, "replacement")]:
            monkeypatch.setattr(WiseClient, "recipient", lambda self, rid, digest=recipient_hash: {
                "active": True, "hash": digest, "currency": "KRW",
                "profileId": 123, "name": {"fullName": "Verified contributor"},
            })
            changed = await post("recipient", {
                "wearer_id": person.id, "recipient_id": recipient_id, "confirm_recipient": True,
            })
            assert changed.status_code == 200, changed.text
            latest_revision = changed.json()["contributors"][0]["recipient"]["revision"]
            stale = await post("approve", body)
            assert stale.status_code == 409 and "recipient changed" in stale.text
            assert not (await db_session.execute(select(PayoutItem))).scalars().all()
        body["expected_recipient_revision"] = latest_revision
        r = await post("approve", body)
        assert r.status_code == 200, r.text
        assert r.json()["payouts"][0]["status"] == "approved"
        assert (await post("approve", body)).status_code == 409
        assert (
            await post("review", {**review, "decision": "needs_review"})
        ).status_code == 409
        assert (
            await c.post(
                "/api/ops/episodes/foo/pay",
                json={"value": True},
                cookies={"sid": sid},
                headers={"Origin": ORIGIN},
            )
        ).status_code == 410
    assert len((await db_session.execute(select(PayoutItem))).scalars().all()) == 1
    assert not run.paid


@pytest.mark.parametrize("field,value", [
    ("wise_recipient_id", "new-id"), ("recipient_hash", "new-hash"),
    ("wise_profile_id", "new-profile"), ("wise_environment", "production"),
    ("verified_name", "New name"), ("wearer_id", 2),
])
def test_recipient_revision_covers_all_approval_identity_fields(field, value):
    from types import SimpleNamespace
    from app.api.routes.ops_payments import recipient_revision
    recipient = SimpleNamespace(wearer_id=1, wise_recipient_id="321", recipient_hash="hash",
                                wise_profile_id="123", wise_environment="sandbox", verified_name="Name")
    original = recipient_revision(recipient)
    setattr(recipient, field, value)
    assert recipient_revision(recipient) != original


@pytest.mark.asyncio
async def test_guest_cannot_review_pay_or_claim(app, db_session):
    sid = await _sid(db_session, "guest")
    async with _client(app) as c:
        assert (
            await c.get("/api/ops/payments/state", cookies={"sid": sid})
        ).status_code == 403
        assert (
            await c.post("/api/ops/processing/claim", headers={"Origin": ORIGIN})
        ).status_code == 403


@pytest.mark.asyncio
async def test_contributor_time_uses_decoded_clean_not_raw_flags(app, db_session):
    from app.core.ops_ledger import contributor_summary
    from app.models import Episode, OpsCamera

    p = Wearer(name="Contributor")
    db_session.add(p)
    await db_session.flush()
    db_session.add_all(
        [
            Episode(
                recording="raw-one", wearer_id=p.id, duration_s=9999999, approved=True
            ),
            OpsCamera(device_id="ABC123", wearer_id=p.id),
        ]
    )
    await db_session.commit()
    stats = await contributor_summary(
        db_session,
        [
            {
                "wearer_id": p.id,
                "recording": "done",
                "source_seconds": 100,
                "retained_seconds": 60,
                "rejected_seconds": 40,
                "payment_status": "unapproved",
                "review_status": "needs_review",
                "collection_date": None,
            }
        ],
    )
    assert stats[0]["source_seconds"] == 100 and stats[0]["retained_seconds"] == 60
    assert stats[0]["dates_unconfirmed"] == 1 and stats[0]["pending_recordings"] == 1


@pytest.mark.asyncio
async def test_worker_leases_reject_stale_results_and_operator_removed_sources(
    app, db_session, monkeypatch
):
    from app.models import Episode, ProcessingJob

    monkeypatch.setenv("OPS_PROCESSOR_TOKEN", "test-worker")
    person = Wearer(name="Worker test")
    db_session.add(person)
    await db_session.flush()
    episode = Episode(recording="worker-rec", wearer_id=person.id)
    job = ProcessingJob(
        recording="worker-rec",
        fingerprint="a" * 64,
        state="queued",
        reason="Ready",
        input_json="{}",
    )
    db_session.add_all([episode, job])
    await db_session.commit()
    headers = {"Origin": ORIGIN, "Authorization": "Bearer test-worker"}
    async with _client(app) as c:
        claimed = await c.post("/api/ops/processing/claim", headers=headers)
        assert claimed.status_code == 200, claimed.text
        j = claimed.json()["job"]
        assert j["recording"] == episode.recording
        assert (await c.post("/api/ops/processing/claim", headers=headers)).json()[
            "job"
        ] is None
        result = {k: j[k] for k in ("recording", "fingerprint", "lease_token")}
        result.update(outcome="completed", run_id="nonexistent")
        assert (
            await c.post("/api/ops/processing/result", json=result, headers=headers)
        ).status_code == 409
        result.update(outcome="heartbeat", lease_token="stale")
        assert (
            await c.post("/api/ops/processing/result", json=result, headers=headers)
        ).status_code == 409
        result.update(lease_token=j["lease_token"])
        assert (
            await c.post("/api/ops/processing/result", json=result, headers=headers)
        ).status_code == 200
        episode.deleted_at = datetime.now(timezone.utc)
        episode.delete_kind = "soft"
        await db_session.commit()
        assert (
            await c.post("/api/ops/processing/result", json=result, headers=headers)
        ).status_code == 409
        sid = await _sid(db_session, "ops")
        assert (
            await c.post(
                "/api/ops/processing/worker-rec/retry",
                cookies={"sid": sid},
                headers={"Origin": ORIGIN},
            )
        ).status_code == 409


@pytest.mark.asyncio
async def test_changed_source_reopens_a_blocked_job_without_changing_contributor(
    db_session,
):
    from app.models import Episode, ProcessingJob
    from app.core.ops_processing import reconcile

    p = Wearer(name="Original owner")
    db_session.add(p)
    await db_session.flush()
    e = Episode(recording="changed", wearer_id=p.id)
    j = ProcessingJob(
        recording="changed",
        fingerprint="old",
        state="blocked",
        reason="A prior worker error",
        input_json="{}",
        attempts=3,
    )
    db_session.add_all([e, j])
    await db_session.commit()
    take = {
        "prefixes": ["s/"],
        "uploaded": datetime.now(timezone.utc) - timedelta(hours=7),
        "media": [{"key": "s/video.mp4", "bytes": 100}],
        "meta": {},
    }
    await reconcile(db_session, {"changed": take}, [], [])
    assert j.state == "recovering" and j.attempts == 0 and e.wearer_id == p.id
    j.state = "blocked"
    j.reason = "Still needs human investigation"
    await reconcile(db_session, {"changed": take}, [], [])
    assert j.state == "blocked"


@pytest.mark.asyncio
async def test_automatic_import_skips_unassigned_result_and_preserves_original_contributor(
    app, db_session, monkeypatch
):
    from app.api.routes import ops_clean
    from app.models import Episode, OpsCamera
    from tests.test_ops_artifacts import multimodal_manifest

    original = Wearer(name="Original contributor", rate_krw_hour=11000)
    current = Wearer(name="Current camera holder", rate_krw_hour=22000)
    db_session.add_all([original, current])
    await db_session.flush()
    doc = multimodal_manifest()
    rec = doc["recordings"][0]["recording"]
    db_session.add_all(
        [
            Episode(recording=rec, wearer_id=original.id),
            OpsCamera(device_id=doc["device_id"], wearer_id=current.id),
        ]
    )
    await db_session.commit()
    unknown = manifest()
    unknown["run_id"] = "unassigned"
    unknown["device_id"] = "DEF456"
    unknown["recordings"][0]["recording"] = "ego_20260907_180803_DEF456"
    monkeypatch.setattr(
        ops_clean,
        "committed_results",
        lambda: [(unknown, "bad", "v1", "b" * 64), (doc, "good", "v1", "a" * 64)],
    )
    result = await ops_clean.scan(None, db_session, skip_invalid=True)
    assert result["imported"] == 1 and len(result["scan_errors"]) == 1
    assert result["runs"][0]["wearer_id"] == original.id
    assert result["runs"][0]["rate_krw_hour"] == 11000


@pytest.mark.asyncio
@pytest.mark.parametrize("second_owner", ["missing", "unassigned", "different"])
async def test_clean_batch_requires_every_recording_to_have_the_same_resolved_owner(
    db_session, monkeypatch, second_owner
):
    import copy
    from app.api.routes import ops_clean
    from app.core.ops_clean import validate_manifest
    from app.models import Episode, OpsCamera
    from tests.test_ops_artifacts import multimodal_manifest

    original = Wearer(name="Original contributor", rate_krw_hour=11000)
    current = Wearer(name="Current camera holder", rate_krw_hour=22000)
    db_session.add_all([original, current])
    await db_session.flush()
    doc = multimodal_manifest()
    first_name = doc["recordings"][0]["recording"]
    second_name = first_name.replace("120000", "130000")
    second = copy.deepcopy(doc["recordings"][0])
    second["recording"] = second_name
    second["sources"][0]["key"] = second["sources"][0]["key"].replace(first_name, second_name)
    second["sources"][0]["sha256"] = "c" * 64
    doc["recordings"].append(second)
    for output in list(doc["outputs"]):
        item = copy.deepcopy(output)
        item["recording"] = second_name
        prefix, filename = item["key"].rsplit("/", 1)
        item["key"] = prefix + "/second-" + filename
        doc["outputs"].append(item)
    for field in ("source_seconds", "retained_seconds", "rejected_seconds"):
        doc[field] *= 2
    validate_manifest(doc)
    db_session.add_all([
        Episode(recording=first_name, wearer_id=original.id),
        OpsCamera(device_id=doc["device_id"], wearer_id=current.id),
    ])
    second_episode = None
    if second_owner != "missing":
        second_episode = Episode(
            recording=second_name,
            wearer_id=current.id if second_owner == "different" else None,
        )
        db_session.add(second_episode)
    await db_session.commit()
    monkeypatch.setattr(ops_clean, "committed_results", lambda: [(doc, "result", "v1", "d" * 64)])

    held = await ops_clean.scan(None, db_session, skip_invalid=True)
    assert held["imported"] == 0 and len(held["scan_errors"]) == 1
    expected = "multiple contributors" if second_owner == "different" else "confirmed contributor"
    assert expected in held["scan_errors"][0]["error"]
    assert not (await db_session.execute(select(CleanRun))).scalars().all()
    if second_owner == "different":
        assert second_episode.wearer_id == current.id
        return

    # Only explicitly resolving the missing episode owner allows this batch;
    # today's different camera holder must never fill in this evidence.
    if second_episode is None:
        second_episode = Episode(recording=second_name)
        db_session.add(second_episode)
    second_episode.wearer_id = original.id
    await db_session.commit()
    imported = await ops_clean.scan(None, db_session, skip_invalid=True)
    assert imported["imported"] == 1 and not imported["scan_errors"]
    assert imported["runs"][0]["wearer_id"] == original.id
    assert imported["runs"][0]["rate_krw_hour"] == 11000


@pytest.mark.asyncio
async def test_new_attribution_gate_preserves_existing_paid_historical_ledger(db_session, monkeypatch):
    from app.api.routes import ops_clean
    from app.models import OpsCamera

    original = Wearer(name="Historical contributor", rate_krw_hour=11000)
    current = Wearer(name="New camera holder", rate_krw_hour=22000)
    db_session.add_all([original, current])
    await db_session.flush()
    doc = manifest()
    paid_at = datetime(2026, 9, 10, tzinfo=timezone.utc)
    historical = CleanRun(
        run_id=doc["run_id"], device_id=doc["device_id"], wearer_id=original.id,
        manifest_key="historical", manifest_version="v1", manifest_sha256="a" * 64,
        manifest_json=json.dumps(doc), retained_seconds=60, rejected_seconds=40,
        rate_krw_hour=11000, paid=True, paid_at=paid_at, amount_krw=183,
    )
    # No Episode owner remains to resolve; already imported, paid history is
    # still authoritative even after this camera changes hands.
    db_session.add_all([historical, OpsCamera(device_id=doc["device_id"], wearer_id=current.id)])
    await db_session.commit()
    monkeypatch.setattr(ops_clean, "committed_results", lambda: [(doc, "historical", "v1", "a" * 64)])
    result = await ops_clean.scan(None, db_session)
    assert result["imported"] == 0 and not result["scan_errors"]
    await db_session.refresh(historical)
    assert (historical.wearer_id, historical.rate_krw_hour, historical.paid,
            historical.paid_at, historical.amount_krw) == (original.id, 11000, True, paid_at, 183)


@pytest.mark.asyncio
async def test_sent_transfer_still_counts_as_not_confirmed_paid(db_session):
    from app.core.ops_ledger import contributor_summary

    p = Wearer(name="Awaiting receipt")
    db_session.add(p)
    await db_session.commit()
    entry = dict(
        wearer_id=p.id,
        recording="sent",
        source_seconds=100,
        retained_seconds=60,
        rejected_seconds=40,
        payment_status="sent",
        review_status="reviewed",
        collection_date="2026-09-01",
    )
    stats = await contributor_summary(db_session, [entry])
    assert stats[0]["unpaid_seconds"] == 60
    entry["payment_status"] = "paid"
    assert (await contributor_summary(db_session, [entry]))[0]["unpaid_seconds"] == 0
