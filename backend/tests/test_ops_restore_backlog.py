"""Restoring operator-removed footage returns it to backlog before the next scan."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.ops_processing import reconcile
from app.core.ops_raw import INVENTORY_KEY
from app.core.ops_s3 import get_settings
from app.models import OpsSetting, ProcessingJob, Wearer
from tests.test_ops_routes import app, _client, _episode, _sid, ORIGIN


@pytest.mark.asyncio
async def test_restored_footage_returns_to_total_and_source_backlog_then_revalidates(app, db_session):
    sid = await _sid(db_session, 'ops')
    person = Wearer(name='Restored source')
    db_session.add(person)
    await db_session.flush()
    e = await _episode(db_session, 'restored', duration_s=1800, wearer_id=person.id)
    take = dict(prefixes=['sessions/s/restored/'], media=[{'key': 'sessions/s/restored/video.mp4', 'bytes': 10}],
                meta={'duration_s': 1800}, error='', uploaded=datetime.now(timezone.utc) - timedelta(hours=1))
    takes = {'restored': take}
    db_session.add(OpsSetting(key=INVENTORY_KEY, value=json.dumps({
        'bucket': get_settings().bucket, 'takes': {'restored': {'media': take['media']}}
    })))
    await reconcile(db_session, takes, [], [])
    await db_session.commit()
    job = await db_session.get(ProcessingJob, 'restored')
    original_fingerprint = job.fingerprint
    async with _client(app) as client:
        deleted = await client.post('/api/ops/episodes/restored/delete', cookies={'sid': sid},
                                    headers={'Origin': ORIGIN}, json={'kind': 'soft', 'reason': 'Review'})
        assert deleted.status_code == 200
        assert deleted.json()['raw_backlog']['pending_episodes'] == 0
        await db_session.refresh(e)
        await reconcile(db_session, takes, [], [])
        await db_session.commit()
        assert job.state == 'rejected'
        restored = await client.post('/api/ops/episodes/restored/restore', cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert restored.status_code == 200
        backlog = restored.json()['raw_backlog']
        assert backlog['known_seconds'] == 1800 and backlog['pending_episodes'] == 1
        assert backlog['sources'][0]['name'] == 'Restored source'
        assert backlog['sources'][0]['known_seconds'] == 1800
        assert restored.json()['episodes'][0]['processing']['state'] == 'uploading'
    await db_session.refresh(e)
    await db_session.refresh(job)
    assert job.fingerprint == original_fingerprint
    assert job.lease_token is None and job.lease_until is None
    await reconcile(db_session, takes, [], [])
    assert job.state == 'queued'


@pytest.mark.asyncio
@pytest.mark.parametrize('deleted,reason,state', [
    (True, 'Irrecoverable source corruption', 'rejected'),
    (False, 'Previously removed by an operator: Review', 'rejected'),
    (True, 'Processing source', 'running'),
])
async def test_restore_does_not_override_other_rejections_or_retry_active_episodes(app, db_session, deleted, reason, state):
    sid = await _sid(db_session, 'ops')
    await _episode(db_session, 'preserve', deleted_at=datetime.now(timezone.utc) if deleted else None,
                   delete_kind='soft' if deleted else None)
    lease = 'active-lease' if state == 'running' else None
    lease_until = datetime.now(timezone.utc) + timedelta(hours=1) if lease else None
    job = ProcessingJob(recording='preserve', state=state, reason=reason, fingerprint='source', input_json='{}',
                        lease_token=lease, lease_until=lease_until)
    db_session.add(job)
    await db_session.commit()
    async with _client(app) as client:
        restored = await client.post('/api/ops/episodes/preserve/restore', cookies={'sid': sid}, headers={'Origin': ORIGIN})
    assert restored.status_code == 200
    assert restored.json()['episodes'][0]['processing']['state'] == state
    await db_session.refresh(job)
    assert job.reason == reason
    assert job.lease_token == lease and job.lease_until == lease_until
