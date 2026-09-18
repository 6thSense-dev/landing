"""Failures at storage/ledger boundaries must preserve identity and source holds."""
import json
from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.core import uploads, upload_storage as storage, ops_processing
from app.models import ContributorCameraClaim, Episode, OpsCamera, ProcessingJob, UploadBatch, UploadPart
from app.schemas.uploads import BatchIn, MAX_BATCH_BYTES
from tests.test_ops_routes import app, _client, _sid, ORIGIN
from tests.test_browser_uploads import ready, manifest, REC, SHA, ETAG
from tests.test_contributor_mobile import setup, OTHER


async def complete_files(db, account, monkeypatch, metadata=None):
    data = await uploads.create_batch(db, account, BatchIn.model_validate(manifest()))
    batch = await db.get(UploadBatch, data['id'])
    files = await uploads.files_for(db, batch)
    for f in files:
        f.completed_at, f.version_id, f.etag = uploads.now(), 'version-' + f.id, ETAG
    await db.commit()
    monkeypatch.setattr(storage, 'head', lambda b, f: {'VersionId': f.version_id})
    monkeypatch.setattr(storage, 'metadata', lambda b, f: metadata or {'device_id': 'ABC123', 'complete': True})
    return batch, files


async def test_expired_multipart_restarts_only_unfinished_file(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    data = await uploads.create_batch(db_session, account, BatchIn.model_validate(manifest()))
    batch = await db_session.get(UploadBatch, data['id'])
    file = (await uploads.files_for(db_session, batch))[0]
    file.upload_id = 'expired'
    db_session.add(UploadPart(file_id=file.id, number=1, checksum=SHA, etag=ETAG))
    await db_session.commit()
    monkeypatch.setattr(storage, 'head', lambda b, f: None)
    monkeypatch.setattr(storage, 'upload_exists', lambda b, f: False)
    monkeypatch.setattr(storage, 'initiate', lambda b, f: 'new-multipart')
    result = await uploads.start_file(db_session, batch, file)
    assert result['received'] == [] and file.upload_id == 'new-multipart'
    monkeypatch.setattr(storage, 'head', lambda b, f: {'VersionId': 'recovered-version', 'ETag': ETAG})
    monkeypatch.setattr(storage, 'initiate', lambda b, f: pytest.fail('must recover completed object'))
    assert (await uploads.start_file(db_session, batch, file))['complete'] is True
    assert file.version_id == 'recovered-version'


async def test_receipt_published_before_commit_failure_keeps_uploader(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    wearer_id = account.wearer_id
    batch, _ = await complete_files(db_session, account, monkeypatch)
    batch_id, prefix = batch.id, storage.prefix(batch)
    receipts = []
    monkeypatch.setattr(storage, 'publish_receipt', lambda b, f: receipts.append(b.id))
    async def failed_commit(): raise RuntimeError('simulated commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(db_session, 'commit', failed_commit)
        with pytest.raises(RuntimeError, match='commit failure'):
            await uploads.complete_batch(db_session, account, batch)
    await db_session.rollback()
    assert receipts == [batch_id]
    assert (await db_session.get(UploadBatch, batch_id)).completed_at is None
    # Raw can discover the reserved server receipt before the participant retries.
    db_session.add(Episode(recording=REC, session='web-'+batch_id, prefix=prefix, device_id='ABC123'))
    await db_session.commit()
    source = (await uploads.upload_sources(db_session))[REC]
    assert source['wearer_id'] == wearer_id and source['prefix'] == prefix
    assert source['received_at'] is None


async def test_delayed_capture_uses_historical_owner_not_current_camera(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    other = await setup(db_session, OTHER)
    claim = (await db_session.execute(select(ContributorCameraClaim))).scalars().one()
    claim.ended_at = uploads.now() - timedelta(hours=1)
    db_session.add(OpsCamera(device_id='ABC123', wearer_id=other.wearer_id))
    await db_session.commit()
    meta = {'device_id': 'ABC123', 'start_time': (uploads.now()-timedelta(hours=2)).isoformat(),
            'clock_source': 'ntp', 'duration_s': 60, 'complete': True}
    batch, _ = await complete_files(db_session, account, monkeypatch, meta)
    monkeypatch.setattr(storage, 'publish_receipt', lambda b, f: None)
    await uploads.complete_batch(db_session, account, batch)
    episode = (await db_session.execute(select(Episode))).scalars().one()
    assert episode.wearer_id == account.wearer_id != other.wearer_id


async def test_ended_camera_cannot_publish_new_capture(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    claim = (await db_session.execute(select(ContributorCameraClaim))).scalars().one()
    claim.ended_at = uploads.now() - timedelta(hours=1)
    await db_session.commit()
    meta = {'device_id': 'ABC123', 'start_time': (uploads.now()-timedelta(minutes=5)).isoformat(),
            'clock_source': 'ntp', 'duration_s': 60, 'complete': True}
    batch, _ = await complete_files(db_session, account, monkeypatch, meta)
    monkeypatch.setattr(storage, 'publish_receipt', lambda b, f: pytest.fail('must not publish'))
    with pytest.raises(HTTPException) as error:
        await uploads.complete_batch(db_session, account, batch)
    assert error.value.status_code == 409


async def test_quota_rolls_over_but_resumes_existing_batch(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    data = await uploads.create_batch(db_session, account, BatchIn.model_validate(manifest()))
    batch = await db_session.get(UploadBatch, data['id'])
    batch.total_bytes = MAX_BATCH_BYTES
    await db_session.commit()
    assert (await uploads.create_batch(db_session, account, BatchIn.model_validate(manifest())))['id'] == batch.id
    new = BatchIn.model_validate(manifest(REC.replace('110000', '110001')))
    with pytest.raises(HTTPException): await uploads.create_batch(db_session, account, new)
    batch.created_at = uploads.now() - timedelta(hours=25)
    await db_session.commit()
    assert (await uploads.create_batch(db_session, account, new))['recording'] == new.recording


@pytest.mark.parametrize('state', ['clean', 'running', 'blocked'])
async def test_conflict_hold_fences_fast_paths_and_clears_after_resolution(app, db_session, monkeypatch, state):
    account = await ready(db_session, app, monkeypatch)
    db_session.add(Episode(recording=REC, session='web-b', prefix=f'sessions/web-b/{REC}/',
                           device_id='ABC123', wearer_id=account.wearer_id))
    job = ProcessingJob(recording=REC, state=state, attempts=1, reason='test', fingerprint='old', input_json='{}',
                        lease_token='lease', lease_until=uploads.now()+timedelta(minutes=5))
    db_session.add(job); await db_session.commit()
    take = {'upload_source_conflict': True, 'prefixes': [], 'media': [], 'meta': {}, 'uploaded': uploads.now()}
    monkeypatch.setattr(ops_processing, 'raw_statuses', lambda *a: {REC: {'status': 'processed'}})
    await ops_processing.reconcile(db_session, {REC: take}, {}, {})
    assert job.state == 'blocked' and job.lease_token is None and job.lease_until is None
    assert json.loads(job.input_json)['upload_source_conflict'] is True
    await ops_processing.reconcile(db_session, {REC: {**take, 'upload_source_conflict': False}}, {}, {})
    assert job.state == 'clean' and 'upload_source_conflict' not in json.loads(job.input_json)


async def test_conflict_cannot_be_retried_claimed_or_reported(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    sid = await _sid(db_session, 'ops')
    db_session.add(Episode(recording=REC, session='web-b', device_id='ABC123', wearer_id=account.wearer_id))
    job = ProcessingJob(recording=REC, state='retry', attempts=0, reason='test', fingerprint='fingerprint',
                        input_json=json.dumps({'upload_source_conflict': True}), lease_token='lease',
                        lease_until=uploads.now()+timedelta(minutes=5))
    db_session.add(job); await db_session.commit()
    monkeypatch.setenv('OPS_PROCESSOR_TOKEN', 'worker-test')
    async with _client(app) as c:
        r = await c.post(f'/api/ops/processing/{REC}/retry', cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert r.status_code == 409
        c.cookies.clear()
        headers = {'Authorization': 'Bearer worker-test', 'Origin': ORIGIN}
        result = {'recording': REC, 'fingerprint': 'fingerprint', 'lease_token': 'lease', 'outcome': 'heartbeat'}
        assert (await c.post('/api/ops/processing/result', json=result, headers=headers)).status_code == 409
        assert (await c.post('/api/ops/processing/claim', headers=headers)).json()['job'] is None


async def test_manifest_size_cap_and_chunked_manifest(app, db_session, monkeypatch):
    await ready(db_session, app, monkeypatch)
    async with _client(app) as c:
        assert (await c.post('/api/uploads/batches', content=b'x'*(1024**2+1))).status_code == 413
        async def chunks():
            data = json.dumps(manifest()).encode()
            yield data[:100]
            yield data[100:]
        result = await c.post('/api/uploads/batches', content=chunks(), headers={'Content-Type': 'application/json'})
        assert result.status_code == 200, result.text
