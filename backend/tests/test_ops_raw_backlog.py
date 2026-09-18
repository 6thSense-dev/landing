"""Raw backlog is footage duration, not file duration or the lifetime ledger."""
import json
from datetime import datetime, timezone

import pytest

from app.core.ops_raw import INVENTORY_KEY, pending_duration, raw_statuses
from app.models import Episode, OpsSetting, ProcessingJob


def episode(recording, duration=3600, **values):
    return Episode(recording=recording, duration_s=duration, **values)


def test_backlog_counts_stereo_and_repeated_deliveries_once():
    inventory = {'stereo': {'media': [
        {'key': key, 'bytes': 10} for key in ('left.mp4', 'right.mp4', 'copy/left.mp4')
    ]}}
    raw = raw_statuses(inventory, [], [])
    assert pending_duration([episode('stereo')], raw, {}) == {
        'known_seconds': 3600, 'known_episodes': 1, 'unknown_episodes': 0,
        'partial_episodes': 0, 'pending_episodes': 1,
    }


def test_backlog_includes_running_and_blocked_but_excludes_history_and_empty_uploads():
    episodes = [episode(name) for name in (
        'queued', 'running', 'blocked', 'retry', 'recovering', 'uploading',
        'awaiting_verification', 'rejected', 'finished', 'empty', 'absent', 'deleted',
    )]
    episodes[-1].deleted_at = datetime.now(timezone.utc)
    raw = {e.recording: {'status': 'pending', 'pending_files': 2} for e in episodes}
    raw['finished'] = {'status': 'processed', 'pending_files': 0}
    raw['empty'] = {'status': 'unavailable', 'pending_files': 0}
    del raw['absent']
    jobs = {e.recording: {'state': e.recording} for e in episodes}
    summary = pending_duration(episodes, raw, jobs)
    assert summary['pending_episodes'] == summary['known_episodes'] == 7
    assert summary['known_seconds'] == 7 * 3600
    assert summary['unknown_episodes'] == 0


@pytest.mark.parametrize('duration', [None, 0, -60, float('nan'), float('inf'), True, 'bad'])
def test_missing_or_invalid_duration_remains_unknown(duration):
    summary = pending_duration([episode('raw', duration)], {'raw': {'pending_files': 1}}, {})
    assert summary['unknown_episodes'] == summary['pending_episodes'] == 1
    assert summary['known_seconds'] == summary['known_episodes'] == 0


def test_partial_imports_never_count_the_whole_episode_as_remaining():
    raw = {'partial': {'status': 'partial', 'pending_files': 1, 'processed_files': 2},
           'replaced': {'status': 'partial', 'pending_files': 3, 'processed_files': 0}}
    summary = pending_duration([episode('partial'), episode('replaced')], raw, {})
    assert summary['unknown_episodes'] == summary['partial_episodes'] == 2
    assert summary['known_seconds'] == 0


def test_clean_job_cannot_hide_new_or_unverified_raw_sources():
    source = {'key': 'video.mp4', 'version_id': 'v1', 'sha256': 'abc', 'size_bytes': 10}
    manifest = {'recordings': [{'recording': 'raw', 'sources': [source]}]}
    receipt = dict(source, source_key=source['key'], source_version_id='v1', etag='original')
    inventory = {'raw': {'media': [{'key': 'video.mp4', 'etag': 'original', 'bytes': 10}]}}
    episodes, jobs = [episode('raw')], {'raw': {'state': 'clean'}}
    assert pending_duration(episodes, raw_statuses(inventory, [manifest], [receipt]), jobs)['pending_episodes'] == 0
    inventory['raw']['media'][0]['etag'] = 'replacement'
    summary = pending_duration(episodes, raw_statuses(inventory, [manifest], [receipt]), jobs)
    assert summary['pending_episodes'] == summary['unknown_episodes'] == 1


@pytest.mark.asyncio
async def test_state_exposes_current_raw_total_separately_from_lifetime_ledger(db_session):
    from app.api.routes.ops import _state
    from app.core.ops_s3 import get_settings
    db_session.add_all([
        episode('raw', 90, session='s', device_id='A'),
        episode('old', 3600, session='s', device_id='A'),
        episode('rejected', 1800, session='s', device_id='A'),
        ProcessingJob(recording='rejected', fingerprint='x', state='rejected', reason='Rejected', input_json='{}'),
        OpsSetting(key=INVENTORY_KEY, value=json.dumps({'bucket': get_settings().bucket, 'takes': {
            name: {'media': [{'key': name + '/video.mp4', 'bytes': 10}]} for name in ('raw', 'rejected')
        }})),
    ])
    await db_session.commit()
    state = await _state(db_session)
    assert state['raw_backlog']['known_seconds'] == 90
    assert state['raw_backlog']['pending_episodes'] == 1
    assert state['totals']['minutes'] == 91.5


@pytest.mark.asyncio
@pytest.mark.parametrize('snapshot', [None, {'bucket': 'another-bucket', 'takes': {}}])
async def test_missing_or_wrong_bucket_inventory_is_not_an_empty_backlog(db_session, snapshot):
    from app.api.routes.ops import _state
    if snapshot is not None:
        db_session.add(OpsSetting(key=INVENTORY_KEY, value=json.dumps(snapshot)))
        await db_session.commit()
    assert (await _state(db_session))['raw_backlog'] is None


def test_scanned_empty_backlog_has_zero_duration():
    assert pending_duration([], {}, {}) == {
        'known_seconds': 0, 'known_episodes': 0, 'unknown_episodes': 0,
        'partial_episodes': 0, 'pending_episodes': 0,
    }
