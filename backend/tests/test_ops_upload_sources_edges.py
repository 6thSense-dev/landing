"""Upload-channel edge cases preserve decisions and fail closed on conflicts."""
import copy
import json

import pytest
from sqlalchemy import select

from app.core.ops_sources import (
    ATTRIBUTIONS_KEY, UPLOAD_SOURCES_KEY, business_source_key,
    register_upload_sources, source_registry,
)
from app.core.ops_processing import reconcile
from app.models import CleanRun, Episode, OpsSetting, ProcessingJob
from tests.test_ops_routes import app, _client, _episode, _sid, ORIGIN
from tests.test_ops_sources import business_manifest, RECORDING
from tests.test_ops_upload_sources import PARTY, PREFIX, SESSION, configure, mock_scan, take


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['invalid_json', 'list', 'invalid_session', 'prefix', 'bucket', 'party'])
async def test_invalid_upload_configuration_returns_conflict_without_importing(app, db_session, monkeypatch, fault):
    sid = await _sid(db_session, 'ops')
    channel = dict(bucket='6thsense-raw', prefix=f'sessions/{SESSION}/', counterparty=copy.deepcopy(PARTY))
    config = {SESSION: channel}
    if fault == 'invalid_session': config = {'../psdn': channel}
    if fault == 'prefix': channel['prefix'] = 'sessions/'
    if fault == 'bucket': channel['bucket'] = '6thsense-processed'
    if fault == 'party': channel['counterparty']['payment_model'] = 'hourly'
    if fault == 'list': config = []
    db_session.add(OpsSetting(key=UPLOAD_SOURCES_KEY, value='{' if fault == 'invalid_json' else json.dumps(config)))
    await db_session.commit()
    mock_scan(monkeypatch, {RECORDING: take()})
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
    assert response.status_code == 409, response.text
    assert response.json()['detail']
    assert await source_registry(db_session) == {}
    assert not (await db_session.execute(select(Episode))).scalars().all()
    assert not (await db_session.execute(select(ProcessingJob))).scalars().all()


@pytest.mark.asyncio
async def test_two_configured_deliveries_cannot_claim_the_same_recording(app, db_session, monkeypatch):
    sid = await _sid(db_session, 'ops')
    await configure(db_session)
    row = await db_session.get(OpsSetting, UPLOAD_SOURCES_KEY)
    channels = json.loads(row.value)
    channels['other-korea'] = dict(bucket='6thsense-raw', prefix='sessions/other-korea/', counterparty=PARTY)
    row.value = json.dumps(channels)
    await db_session.commit()
    delivery = take()
    delivery['prefixes'].append(PREFIX.replace(SESSION, 'other-korea'))
    mock_scan(monkeypatch, {RECORDING: delivery})
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
    assert response.status_code == 409
    assert 'conflicting business upload destinations' in response.json()['detail']
    assert await source_registry(db_session) == {}


@pytest.mark.asyncio
async def test_later_conflict_rolls_back_earlier_attribution_in_same_scan(app, db_session, monkeypatch):
    sid = await _sid(db_session, 'ops')
    await configure(db_session)
    second = 'ego_20260901_130000_ABC123'
    episode = await _episode(db_session, second)
    episode.session = SESSION
    episode.paid = True
    await db_session.commit()
    mock_scan(monkeypatch, {RECORDING: take(), second: take(second, PREFIX.replace(RECORDING, second))})
    async with _client(app) as client:
        response = await client.post('/api/ops/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
    assert response.status_code == 409
    assert await source_registry(db_session) == {}
    assert (await db_session.execute(select(Episode).where(Episode.recording == RECORDING))).scalar_one_or_none() is None
    await db_session.refresh(episode)
    assert episode.paid


@pytest.mark.asyncio
async def test_manual_registry_evidence_remains_byte_identical(db_session):
    await configure(db_session)
    manual = dict(recording=RECORDING, device_id='ABC123', session=SESSION,
                  counterparty=PARTY, confirmed_at='2026-09-01T00:00:00+00:00',
                  basis='Operator verified the contract and original upload receipt.', receipt='original-evidence')
    serialized = json.dumps({RECORDING: manual}, indent=2)
    db_session.add(OpsSetting(key=ATTRIBUTIONS_KEY, value=serialized))
    await db_session.commit()
    registry = await register_upload_sources(db_session, {RECORDING: take()}, {}, bucket='6thsense-raw')
    await db_session.commit()
    assert registry[RECORDING] == manual
    assert (await db_session.get(OpsSetting, ATTRIBUTIONS_KEY)).value == serialized


@pytest.mark.asyncio
async def test_new_delivery_path_extends_evidence_without_losing_original_confirmation(db_session):
    await configure(db_session)
    before = await register_upload_sources(db_session, {RECORDING: take()}, {}, bucket='6thsense-raw')
    await db_session.commit()
    old_confirmation = before[RECORDING]['confirmed_at']
    new_prefix = PREFIX.replace('leather_workshop', 'second-delivery')
    # The old source may already have left Raw when a second delivery arrives.
    after = await register_upload_sources(db_session, {RECORDING: take(prefix=new_prefix)}, {}, bucket='6thsense-raw')
    await db_session.commit()
    assert after[RECORDING]['confirmed_at'] == old_confirmation
    assert after[RECORDING]['upload_source']['recording_prefixes'] == sorted([PREFIX, new_prefix])
    for prefix in (PREFIX, new_prefix):
        assert business_source_key(dict(bucket='6thsense-raw', key=prefix+'video.mp4'), RECORDING, SESSION, after[RECORDING])


@pytest.mark.asyncio
async def test_matching_imported_business_history_is_preserved(db_session):
    await configure(db_session)
    doc = business_manifest()
    doc['counterparty'] = copy.deepcopy(PARTY)
    run = CleanRun(run_id=doc['run_id'], device_id='ABC123', manifest_key='qc-results/business/result.json',
        manifest_version='original-version', manifest_sha256='a'*64, manifest_json=json.dumps(doc),
        retained_seconds=60, rejected_seconds=40, wearer_id=None, rate_krw_hour=None)
    db_session.add(run)
    await db_session.commit()
    before = (run.manifest_json, run.manifest_version, run.manifest_sha256, run.retained_seconds)
    registry = await register_upload_sources(db_session, {RECORDING: take()}, {}, bucket='6thsense-raw')
    await db_session.commit()
    await db_session.refresh(run)
    assert registry[RECORDING]['counterparty'] == PARTY
    assert (run.manifest_json, run.manifest_version, run.manifest_sha256, run.retained_seconds) == before
    assert run.wearer_id is None and run.rate_krw_hour is None


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['traversal', 'empty_segment', 'missing_slash', 'wrong_recording'])
async def test_channel_does_not_trust_malformed_observed_paths(db_session, fault):
    await configure(db_session)
    prefix = PREFIX
    if fault == 'traversal': prefix = PREFIX.replace('/leather_workshop/', '/../')
    if fault == 'empty_segment': prefix = PREFIX.replace('/leather_workshop/', '//')
    if fault == 'missing_slash': prefix = PREFIX[:-1]
    if fault == 'wrong_recording': prefix = PREFIX.replace(RECORDING, 'ego_20260901_130000_ABC123')
    with pytest.raises(ValueError, match='conflicting upload provenance'):
        await register_upload_sources(db_session, {RECORDING: take(prefix=prefix)}, {}, bucket='6thsense-raw')
    assert await source_registry(db_session) == {}


def test_source_key_validation_preserves_legacy_layout_and_rejects_unobserved_nested_keys():
    def allowed(key, entry=None, bucket='6thsense-raw'):
        return business_source_key(dict(key=key, bucket=bucket), RECORDING, SESSION, entry or {})
    root = f'sessions/{SESSION}/'
    assert allowed(root+RECORDING+'/video.mp4')
    assert allowed(root+'EGO-FFFFFF/'+RECORDING+'/video.mp4')
    assert not allowed(PREFIX+'video.mp4')
    assert not allowed(root+'not-a-camera/'+RECORDING+'/video.mp4')
    entry = dict(upload_source=dict(bucket='6thsense-raw', prefix=root, recording_prefixes=[PREFIX]))
    assert allowed(PREFIX+'video.mp4', entry)
    assert not allowed(PREFIX+'video.mp4', entry, bucket='6thsense-processed')
    assert not allowed(PREFIX+'video.mp4', {**entry, 'upload_source': {**entry['upload_source'], 'prefix': 'sessions/'}})
    assert not allowed(PREFIX.replace('/leather_workshop/', '/../')+'video.mp4', entry)


@pytest.mark.asyncio
async def test_other_bucket_cannot_register_a_raw_upload_channel(db_session):
    await configure(db_session)
    assert await register_upload_sources(db_session, {RECORDING: take()}, {}, bucket='unrelated-bucket') == {}
    assert await db_session.get(OpsSetting, ATTRIBUTIONS_KEY) is None


@pytest.mark.asyncio
async def test_attribution_hold_stays_blocked_until_a_source_is_confirmed(db_session):
    episode = await _episode(db_session, RECORDING)
    episode.session, episode.prefix = SESSION, PREFIX
    takes = {RECORDING: take()}
    jobs = await reconcile(db_session, takes, [], [])
    await db_session.commit()
    job = jobs[RECORDING]
    fingerprint = job.fingerprint
    job.state, job.reason = 'blocked', 'Contributor or business attribution required'
    await db_session.commit()
    await reconcile(db_session, takes, [], [])
    await db_session.commit()
    assert job.state == 'blocked' and 'Assign the source camera' in job.reason
    assert job.fingerprint == fingerprint
    assert episode.wearer_id is None
