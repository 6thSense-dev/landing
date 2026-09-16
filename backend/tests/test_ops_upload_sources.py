"""Dedicated business uploads retain source identity without creating wages."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api.routes import ops, ops_clean, ops_pipeline
from app.core import contributor_attribution
from app.core.ops_sources import ATTRIBUTIONS_KEY, source_registry
from app.models import CleanRun, Episode, OpsCamera, OpsSetting, ProcessingJob, Wearer
from tests.test_ops_routes import app, _client, _episode, _sid, ORIGIN
from tests.test_ops_sources import business_manifest, mock_result, RECORDING

PARTY = dict(kind='business', id='psdn', name='PSDN', country='korea', payment_model='b2b_contract')
UPLOAD_SOURCES_KEY = 'ops_upload_sources_v1'
SESSION = 'psdn-korea'
PREFIX = f'sessions/{SESSION}/ego_0915/leather_workshop/{RECORDING}/'


def take(recording=RECORDING, prefix=PREFIX):
    return dict(recording=recording, session=SESSION, prefix=prefix, prefixes=[prefix],
                bytes=100, files=1, meta_key=prefix+'metadata.json', error='',
                media=[dict(key=prefix+'video.mp4', bytes=100)],
                uploaded=datetime.now(timezone.utc)-timedelta(hours=7),
                meta=dict(device_id='ABC123', duration_s=60, complete=True, clock_source='ntp',
                          start_time='2026-09-01T12:00:00+00:00'))


async def configure(db):
    db.add(OpsSetting(key=UPLOAD_SOURCES_KEY, value=json.dumps({SESSION: dict(
        bucket='6thsense-raw', prefix=f'sessions/{SESSION}/', counterparty=PARTY)})))
    await db.commit()


def mock_scan(monkeypatch, takes):
    monkeypatch.setattr(ops, 'walk_bucket', lambda: takes)
    monkeypatch.setattr(ops, 'refresh_source_receipts', lambda *args: [])


@pytest.mark.asyncio
async def test_scan_attributes_new_and_existing_uploads_before_camera_owner_filling(app, db_session, monkeypatch):
    sid = await _sid(db_session, 'ops')
    await configure(db_session)
    person = Wearer(name='Unrelated camera holder', rate_krw_hour=11000)
    db_session.add(person)
    await db_session.flush()
    db_session.add(OpsCamera(device_id='ABC123', wearer_id=person.id))
    existing = await _episode(db_session, RECORDING)
    existing.session, existing.prefix = SESSION, PREFIX
    await db_session.commit()
    next_rec = 'ego_20260901_130000_ABC123'
    takes = {RECORDING: take(), next_rec: take(next_rec, PREFIX.replace(RECORDING, next_rec))}
    mock_scan(monkeypatch, takes)
    async def no_individual_guess(*args):
        raise AssertionError('Business upload must bypass individual attribution')
    monkeypatch.setattr(contributor_attribution, 'owner_at_capture', no_individual_guess)
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert response.status_code == 200, response.text
        assert response.json()['totals']['unassigned'] == 0
        for row in response.json()['episodes']:
            assert row['counterparty'] == PARTY and row['wearer_id'] is None
            assert row['processing']['state'] == 'queued'
            assert not row['paid'] and row['amount_krw'] == 0
        before = (await db_session.get(OpsSetting, ATTRIBUTIONS_KEY)).value
        response = await client.post('/api/ops/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert response.status_code == 200
        assert (await db_session.get(OpsSetting, ATTRIBUTIONS_KEY)).value == before
        # Source ownership survives Raw retirement and disabling future intake.
        takes.clear()
        config = await db_session.get(OpsSetting, UPLOAD_SOURCES_KEY)
        config.value = '{}'
        await db_session.commit()
        response = await client.post('/api/ops/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert response.status_code == 200
        assert all(row['counterparty'] == PARTY for row in response.json()['episodes'])
        response = await client.post(f'/api/ops/episodes/{RECORDING}/assign',
            cookies={'sid': sid}, headers={'Origin': ORIGIN}, json={'wearer_id': person.id})
        assert response.status_code == 409
    inventory = await ops_pipeline.inventory(db_session)
    assert all(e['counterparty'] == PARTY and not e['attribution_hold'] for e in inventory['episodes'])
    assert not (await db_session.execute(select(CleanRun))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['owner', 'paid', 'amount', 'session', 'device', 'other_delivery', 'other_business', 'paid_clean'])
async def test_scan_refuses_to_rewrite_conflicting_source_or_payment_history(app, db_session, monkeypatch, fault):
    sid = await _sid(db_session, 'ops')
    await configure(db_session)
    episode = await _episode(db_session, RECORDING)
    episode.session, episode.prefix = SESSION, PREFIX
    t = take()
    if fault == 'owner':
        person = Wearer(name='Confirmed contributor', rate_krw_hour=11000)
        db_session.add(person)
        await db_session.flush()
        episode.wearer_id = person.id
    if fault == 'paid': episode.paid = True
    if fault == 'amount': episode.amount_krw = 1000
    if fault == 'session': episode.session = 'another-session'
    if fault == 'device': episode.device_id = 'FFFFFF'
    if fault == 'other_delivery': t['prefixes'].append(PREFIX.replace(SESSION, 'personal-korea'))
    if fault == 'other_business':
        db_session.add(OpsSetting(key=ATTRIBUTIONS_KEY, value=json.dumps({RECORDING: dict(
            recording=RECORDING, session=SESSION, device_id='ABC123', counterparty={**PARTY, 'id':'another'})})))
    if fault == 'paid_clean':
        doc = business_manifest()
        db_session.add(CleanRun(run_id=doc['run_id'], device_id='ABC123', manifest_key='qc-results/x/result.json',
            manifest_version='v1', manifest_sha256='a'*64, manifest_json=json.dumps(doc), retained_seconds=60,
            rejected_seconds=40, rate_krw_hour=11000, paid=True, amount_krw=183))
    await db_session.commit()
    before = (episode.wearer_id, episode.paid, episode.amount_krw, episode.session, episode.device_id)
    mock_scan(monkeypatch, {RECORDING:t})
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid':sid}, headers={'Origin':ORIGIN})
    assert response.status_code == 409, response.text
    await db_session.refresh(episode)
    assert (episode.wearer_id, episode.paid, episode.amount_krw, episode.session, episode.device_id) == before
    registry = await source_registry(db_session)
    assert RECORDING not in registry or registry[RECORDING]['counterparty']['id'] == 'another'


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['unconfigured', 'lookalike', 'deleted'])
async def test_channel_must_be_explicit_and_does_not_restore_deleted_recordings(app, db_session, monkeypatch, case):
    sid = await _sid(db_session, 'ops')
    t = take()
    if case != 'unconfigured': await configure(db_session)
    if case == 'lookalike':
        t = take(prefix=PREFIX.replace(SESSION, SESSION+'-other'))
        t['session'] = SESSION+'-other'
    if case == 'deleted':
        e = await _episode(db_session, RECORDING, deleted_at=datetime.now(timezone.utc), delete_kind='hard')
        e.session, e.prefix = SESSION, PREFIX
        await db_session.commit()
    mock_scan(monkeypatch, {RECORDING:t})
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid':sid}, headers={'Origin':ORIGIN})
    assert response.status_code == 200, response.text
    assert response.json()['episodes'][0]['counterparty'] is None
    assert RECORDING not in await source_registry(db_session)
    if case == 'deleted': assert response.json()['episodes'][0]['deleted_at']


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', [None, 'different_folder', 'different_session'])
async def test_nested_business_import_uses_observed_delivery_and_never_creates_wages(app, db_session, monkeypatch, fault):
    sid = await _sid(db_session, 'ops')
    await configure(db_session)
    mock_scan(monkeypatch, {RECORDING:take()})
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid':sid}, headers={'Origin':ORIGIN})
        assert response.status_code == 200, response.text
        doc = business_manifest()
        doc.update(country='korea', counterparty=copy.deepcopy(PARTY))
        source = doc['recordings'][0]['sources'][0]
        source['key'] = PREFIX+'video.mp4'
        if fault == 'different_folder': source['key'] = source['key'].replace('leather_workshop', 'unobserved')
        if fault == 'different_session': source['key'] = source['key'].replace(SESSION, SESSION+'-other')
        mock_result(monkeypatch, doc)
        response = await client.post('/api/ops/clean/scan', cookies={'sid':sid}, headers={'Origin':ORIGIN})
        assert response.status_code == (409 if fault else 200), response.text
        if fault:
            assert not (await db_session.execute(select(CleanRun))).scalars().all()
        else:
            row = response.json()['runs'][0]
            assert row['counterparty'] == PARTY and row['region']['key'] == 'korea'
            assert row['wearer_id'] is None and row['rate_krw_hour'] is None
            assert response.json()['ledger'][0]['allocated_krw'] is None
            assert response.json()['ledger'][0]['payment_status'] == 'b2b_contract'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason,expected', [
    ('Contributor or business attribution required', 'queued'),
    ('Assign the source camera to a contributor in Users or resolve its business attribution.', 'queued'),
    ('New source versions arrived during processing; review before supersession', 'blocked'),
])
async def test_resolved_business_attribution_releases_only_attribution_holds(app, db_session, monkeypatch, reason, expected):
    sid = await _sid(db_session, 'ops')
    await configure(db_session)
    mock_scan(monkeypatch, {RECORDING:take()})
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid':sid}, headers={'Origin':ORIGIN})
        assert response.status_code == 200
        job = await db_session.get(ProcessingJob, RECORDING)
        job.state, job.reason = 'blocked', reason
        await db_session.commit()
        response = await client.post('/api/ops/scan', cookies={'sid':sid}, headers={'Origin':ORIGIN})
        assert response.status_code == 200
        row = response.json()['episodes'][0]
        assert row['counterparty'] == PARTY and row['processing']['state'] == expected
        if expected == 'blocked': assert row['processing']['reason'] == reason
