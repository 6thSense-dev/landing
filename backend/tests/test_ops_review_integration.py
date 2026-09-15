"""Task declarations must leave current Operations ledgers and CMD fences intact."""
import json

import pytest
from sqlalchemy import select

from app.core.ops_clean import validate_manifest
from app.core.ops_ledger import footage_ledger, contributor_summary
from app.models import ActivityReview, CleanRun, Episode, FootageReview, Payout, PayoutItem, OpsCamera, Wearer
from tests.test_ops_routes import app, _client, _sid, ORIGIN
from tests.test_ops_artifacts import multimodal_manifest
from tests.test_ops_rounding import seed_run


@pytest.mark.asyncio
async def test_task_reviews_leave_split_payout_allocation_and_attestation_unchanged(app, db_session):
    person, run, recs = await seed_run(db_session)
    # Existing split-rounding fixture, augmented only with explicit synthetic pins.
    doc = json.loads(run.manifest_json)
    for i, rec in enumerate(doc['recordings']):
        rec['sources'] = [dict(bucket='6thsense-raw', key=f"sessions/fixture/{rec['recording']}/video.mp4",
                               version_id=f'source-{i}', sha256=str(i + 1) * 64)]
    run.manifest_json = json.dumps(doc)
    await db_session.commit()
    sid = await _sid(db_session, 'ops')
    before = await footage_ledger(db_session)
    stats = await contributor_summary(db_session)
    before_manifest = run.manifest_json
    assert sorted(row['allocated_krw'] for row in before) == [44183, 44184]
    async with _client(app) as client:
        cookies = {'sid': sid}
        headers = {'Origin': ORIGIN}
        payment_before = (await client.get('/api/ops/payments/state', cookies=cookies)).json()
        body = dict(task_id='manipulation', expected_revision=0, manifest_sha256=run.manifest_sha256,
                    criteria_version='v1', criteria_text='Synthetic deliberate manipulation criterion', intervals=[
                        dict(recording=recs[0]['recording'], start_ns='0', end_ns='2', judgment='accepted', reason='First view'),
                        dict(recording=recs[0]['recording'], start_ns='1', end_ns='3', judgment='accepted', reason='Overlapping view'),
                        dict(recording=recs[1]['recording'], start_ns='0', end_ns='1', judgment='excluded', reason='Waiting'),
                    ])
        path = f'/api/ops/clean/runs/{run.run_id}/activity-review'
        saved = await client.post(path, json=body, cookies=cookies, headers=headers)
        assert saved.status_code == 200, saved.text
        data = saved.json()
        assert [row['accepted_ns'] for row in data['recordings']] == ['3', '0']
        assert data['unique_usable_ns'] is None
        assert set(data['evidence_status'].values()) == {'unknown'}
        assert data['recordings'][0]['sources'] == doc['recordings'][0]['sources']
        payment_after = (await client.get('/api/ops/payments/state', cookies=cookies)).json()
        assert payment_after == payment_before
        assert payment_after['contributors'][0]['eligible_entries'] == []
        assert (await client.post(f"/api/ops/episodes/{recs[0]['recording']}/pay", json={'value': True}, cookies=cookies, headers=headers)).status_code == 410
    assert await footage_ledger(db_session) == before
    assert await contributor_summary(db_session) == stats
    await db_session.refresh(run)
    assert run.manifest_json == before_manifest and run.wearer_id == person.id and run.rate_krw_hour == 11000
    for model in (FootageReview, Payout, PayoutItem):
        assert not (await db_session.execute(select(model))).scalars().all()
    assert len((await db_session.execute(select(ActivityReview))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_multimodal_import_task_review_preserves_confirmed_owner_and_format_gate(app, db_session, monkeypatch):
    from app.api.routes import ops_clean
    original = Wearer(name='Original collector', rate_krw_hour=11000)
    current = Wearer(name='Current camera holder', rate_krw_hour=22000)
    db_session.add_all([original, current]); await db_session.flush()
    doc = multimodal_manifest(); validate_manifest(doc)
    recording = doc['recordings'][0]['recording']
    db_session.add_all([Episode(recording=recording, wearer_id=original.id),
                       OpsCamera(device_id=doc['device_id'], wearer_id=current.id)])
    await db_session.commit()
    monkeypatch.setattr(ops_clean, 'committed_results', lambda: [(doc, 'fixture', 'v1', 'a' * 64)])
    imported = await ops_clean.scan(None, db_session)
    assert imported['imported'] == 1
    sid = await _sid(db_session, 'ops')
    before = await footage_ledger(db_session)
    async with _client(app) as client:
        saved = await client.post(f"/api/ops/clean/runs/{doc['run_id']}/activity-review", cookies={'sid': sid}, headers={'Origin': ORIGIN}, json=dict(
            task_id='fixture', expected_revision=0, manifest_sha256='a' * 64,
            criteria_version='v1', criteria_text='Explicit synthetic task criteria', intervals=[]))
        assert saved.status_code == 200, saved.text
        assert saved.json()['recordings'][0]['unknown_ns'] == '100000000000'
    assert await footage_ledger(db_session) == before
    run = await db_session.get(CleanRun, doc['run_id'])
    assert run.wearer_id == original.id and run.rate_krw_hour == 11000
    assert validate_manifest(json.loads(run.manifest_json))['schema'] == doc['schema']
    # New source imports still require every modality, even after a task review.
    invalid = multimodal_manifest(); invalid['outputs'] = invalid['outputs'][:-1]
    with pytest.raises(ValueError): validate_manifest(invalid)
