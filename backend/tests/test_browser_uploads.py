"""Account isolation, delivery integrity and retries against real Postgres."""
import base64
import json
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.core import uploads, upload_storage as storage
from app.models import (ContributorCameraClaim, ContributorDeletion, Episode, UploadBatch,
                        UploadFile, UploadPart, Wearer)
from app.schemas.uploads import BatchIn, PART_BYTES
from tests.test_ops_routes import app, _client, _sid
from tests.test_contributor_mobile import setup, accept, identity, SUBJECT, OTHER

REC = 'ego_20260917_110000_ABC123'
SHA = base64.b64encode(b'x' * 32).decode()
ETAG = '"' + 'a' * 32 + '"'


def manifest(recording=REC):
    return {'recording': recording, 'files': [
        {'path': path, 'size': size, 'fingerprint': 'a' * 64, 'modified_ms': 1000}
        for path, size in [('metadata.json', 100), ('video.mp4', PART_BYTES + 1)]]}


async def ready(db, app, monkeypatch):
    monkeypatch.setenv('OPS_BROWSER_UPLOAD_ENABLED', 'true')
    account = await setup(db)
    await accept(db)
    db.add(ContributorCameraClaim(id=str(uuid4()), subject=SUBJECT, device_id='ABC123',
        status='approved', effective_at=uploads.now() - timedelta(days=1)))
    await db.commit()
    identity(app)
    return account


async def test_signin_approval_and_deletion_gates(app, db_session, monkeypatch):
    monkeypatch.setenv('OPS_BROWSER_UPLOAD_ENABLED', 'true')
    sid = await _sid(db_session, 'ops')
    async with _client(app) as c:
        assert (await c.get('/api/uploads/info', cookies={'sid': sid})).status_code == 401
        identity(app)
        assert (await c.get('/api/uploads/info')).json()['detail'] == 'enrollment_required'
        account = await setup(db_session)
        assert (await c.get('/api/uploads/info')).json()['detail'] == 'consent_required'
        await accept(db_session)
        assert (await c.get('/api/uploads/info')).json()['detail'] == 'camera_approval_required'
        db_session.add(ContributorCameraClaim(id=str(uuid4()), subject=SUBJECT, device_id='ABC123',
            status='approved', effective_at=uploads.now() - timedelta(days=1)))
        await db_session.commit()
        assert (await c.get('/api/uploads/info')).status_code == 200
        db_session.add(ContributorDeletion(subject=SUBJECT, id=str(uuid4()), receipt_hash='a'*64))
        await db_session.commit()
        assert (await c.post('/api/uploads/batches', json=manifest())).status_code == 403


async def test_manifest_retries_scope_and_camera(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    async with _client(app) as c:
        first = await c.post('/api/uploads/batches', json=manifest())
        assert first.status_code == 200, first.text
        batch = first.json()
        again = await c.post('/api/uploads/batches', json=manifest())
        assert again.json() == batch
        assert (await c.get('/api/uploads/info')).json()['remaining_bytes'] == 500*1024**3 - PART_BYTES - 101
        changed = manifest(); changed['files'][0]['fingerprint'] = 'b'*64
        assert (await c.post('/api/uploads/batches', json=changed)).status_code == 409
        assert (await c.post('/api/uploads/batches', json=manifest(REC.replace('ABC123', 'ABC124')))).status_code == 403
        other = await setup(db_session, OTHER)
        assert (await uploads.batch_for(db_session, account, batch['id'])).id == batch['id']
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            await uploads.batch_for(db_session, other, batch['id'])
        assert error.value.status_code == 404


async def test_existing_deleted_episode_cannot_be_resurrected(app, db_session, monkeypatch):
    await ready(db_session, app, monkeypatch)
    db_session.add(Episode(recording=REC, session='old', device_id='ABC123', deleted_at=uploads.now(), delete_kind='soft'))
    await db_session.commit()
    async with _client(app) as c:
        assert (await c.post('/api/uploads/batches', json=manifest())).status_code == 409
    assert not (await db_session.execute(select(UploadBatch))).scalars().all()


async def test_completion_receipts_retry_and_uploader_not_owner(app, db_session, monkeypatch):
    account = await ready(db_session, app, monkeypatch)
    objects, published = {}, []
    monkeypatch.setattr(storage, 'head', lambda b, f: objects.get(f.id))
    monkeypatch.setattr(storage, 'initiate', lambda b, f: 'multipart-' + f.id)
    monkeypatch.setattr(storage, 'upload_exists', lambda b, f: True)
    monkeypatch.setattr(storage, 'presign', lambda b, f, p: 'https://example.invalid/part')
    def complete(b, f, parts):
        assert all(p.etag == ETAG and p.checksum == SHA for p in parts)
        objects[f.id] = {'VersionId': 'version-' + f.id, 'ETag': ETAG}
        return objects[f.id]
    monkeypatch.setattr(storage, 'complete', complete)
    monkeypatch.setattr(storage, 'metadata', lambda b, f: {'device_id': 'ABC123', 'complete': True})
    monkeypatch.setattr(storage, 'publish_receipt', lambda b, fs: published.append(b.id))
    async with _client(app) as c:
        batch = (await c.post('/api/uploads/batches', json=manifest())).json()
        bp = '/api/uploads/batches/' + batch['id']
        assert (await c.post(bp + '/complete')).status_code == 409
        for file in batch['files']:
            path = bp + '/files/' + file['id']
            assert (await c.post(path + '/start')).status_code == 200
            assert (await c.post(path + '/complete', json={'received': []})).status_code == 409
            count = (file['size'] + PART_BYTES - 1)//PART_BYTES
            parts = [{'number': i, 'checksum': SHA} for i in range(1, count+1)]
            assert (await c.post(path + '/parts', json={'parts': parts})).status_code == 200
            wrong = [{'number': 1, 'checksum': base64.b64encode(b'y'*32).decode()}]
            assert (await c.post(path + '/parts', json={'parts': wrong})).status_code == 409
            received = [{'number': p['number'], 'etag': ETAG} for p in parts]
            assert (await c.post(path + '/complete', json={'received': received})).status_code == 200
            assert (await c.post(path + '/start')).json()['complete'] is True
        for _ in range(2):
            r = await c.post(bp + '/complete'); assert r.status_code == 200, r.text
        assert published == [batch['id']]
    episode = (await db_session.execute(select(Episode))).scalars().one()
    assert episode.wearer_id is None and episode.deleted_at is None
    assert episode.prefix.startswith('sessions/web-')
    assert (await uploads.upload_sources(db_session))[REC]['wearer_id'] == account.wearer_id


@pytest.mark.parametrize('path', ['../metadata.json', '_upload_complete.json', 'dir/.hidden', '/video.mp4', 'a//b'])
def test_unsafe_paths_rejected(path):
    from pydantic import ValidationError
    body = manifest(); body['files'][0]['path'] = path
    with pytest.raises(ValidationError): BatchIn.model_validate(body)


def test_scanner_hides_partial_browser_copy_even_with_legacy_duplicate(monkeypatch):
    import io
    from app.core import ops_scan
    keys = [f'sessions/legacy/{REC}/metadata.json', f'sessions/web-abc/{REC}/video.mp4',
            f'sessions/web-def/{REC}X/metadata.json']
    class S3:
        def get_paginator(self, name): return self
        def paginate(self, **kw): return [{'Contents': [{'Key': k, 'Size': 100} for k in keys]}]
        def get_object(self, **kw): return {'Body': io.BytesIO(b'{}')}
    monkeypatch.setattr(ops_scan, '_client', lambda cfg: S3())
    takes = ops_scan.walk_bucket()
    assert len(takes) == 1 and takes[REC]['files'] == 1
    assert takes[REC]['media'] == []
    keys = [f'sessions/web-abc/{REC}/metadata.json', f'sessions/web-abc/{REC}/video.mp4']
    assert ops_scan.walk_bucket() == {}
    keys.append(f'sessions/web-abc/{REC}/_upload_complete.json')
    assert ops_scan.walk_bucket()[REC]['files'] == 3
    keys.append(f'sessions/legacy/{REC}/video.mp4')
    conflict = ops_scan.walk_bucket()[REC]
    assert conflict['upload_source_conflict'] is True
    assert conflict['prefix'] == f'sessions/web-abc/{REC}/'
    assert [item['key'] for item in conflict['media']] == [f'sessions/web-abc/{REC}/video.mp4']
