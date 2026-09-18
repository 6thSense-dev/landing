"""Episode previews preserve storage provenance, task evidence and Ops access."""
import io

import pytest
from botocore.exceptions import ReadTimeoutError

from app.core import ops_sieve as sieve, ops_sieve_episode as viewer
from tests.test_ops_sieve import fixture
from tests.test_ops_routes import app, _sid, _client


def episode_fixture():
    s3, row = fixture()
    imu = next(o for o in row['doc']['outputs'] if o['role'] == 'imu')
    data = ('segment_id,clean_time_us,timestamp_us,ax_ms2,ay_ms2,az_ms2,gx_degs,gy_degs,gz_degs\n' +
            ''.join(f'0,{i*3333},{2000000+i*3333},1,2,3,4,5,6\n' for i in range(3000))).encode()
    ref = s3.add(imu['key'], data)
    imu.update({k: ref[k] for k in ('version_id', 'sha256', 'bytes')})
    tasks = {'schema': '6thsense-episode-tasks/1', 'taxonomy': '6thsense-task-taxonomy/1', 'human_verified': False,
             'models': {'nova': {'episodes': [{'episode_id': row['recording'], 'task_labels': ['cut:paper', 'pack:package'],
                        'dominant_observed_task': 'cut:paper', 'environments': ['print_shop'], 'review_required': True,
                        'coverage': {'full_episode': False, 'selected_seconds': 10, 'annotated_selected_seconds': 8},
                        'events': [{'task_id': 'cut:paper', 'source_navigation_start_s': 2, 'source_navigation_end_s': 8}]}]}}}
    task_ref = s3.add(f"qc-results/{row['run_id']}/scene-episode-tasks.json", sieve.encoded(tasks))
    row['doc'].setdefault('policy', {})['episode_tasks'] = task_ref
    ref = s3.add(row['manifest_key'], sieve.encoded(row['doc']))
    row.update(manifest_version=ref['version_id'], manifest_sha256=ref['sha256'])
    s3.add(f"qc-results/{row['run_id']}/_SUCCESS.json", sieve.encoded({'manifest': ref}))
    cached = sieve.copy_recording(s3, row)
    original_get = s3.get_object

    def ranged_get(**kw):
        byte_range = kw.pop('Range', None)
        response = original_get(**kw)
        if byte_range:
            body = response['Body'].read()[:int(byte_range.split('-')[-1]) + 1]
            response['Body'].close()
            response.update(Body=io.BytesIO(body), ContentLength=len(body))
        return response
    s3.get_object = ranged_get
    s3.signed = []

    def sign(operation, Params, ExpiresIn):
        s3.signed.append(Params)
        return 'https://example.test/' + Params['Key']
    s3.generate_presigned_url = sign
    return s3, row, cached


def test_viewer_joins_sieve_assets_and_clean_imu_tasks_without_writes():
    s3, row, cached = episode_fixture()
    before = len(s3.copies), len(s3.objects)
    result = viewer.preview(s3, row, cached)
    assert (len(s3.copies), len(s3.objects)) == before
    assert {v['storage'] for v in result['videos']} == {'Sieve'}
    assert result['metadata']['data'] == {'device': 'ABC123'}
    assert result['calibration']['data']['device_id'] == 'ABC123'
    assert result['imu']['status'] == 'available' and result['imu']['storage'] == 'Clean'
    assert len(result['imu']['rows']) == viewer.IMU_ROWS
    assert result['imu']['rows'][0]['ax_ms2'] == 1
    assert result['imu']['scope'] == 'first_samples'
    assert result['tasks']['models'][0]['task_labels'] == ['cut:paper', 'pack:package']
    assert result['tasks']['models'][0]['coverage']['full_episode'] is False
    assert not result['tasks']['human_verified']
    assert result['operator_task'] == 'Unclassified'
    assert all(p['VersionId'] for p in s3.signed)
    assert {p['Bucket'] for p in s3.signed} == {sieve.BUCKET, '6thsense-processed'}


def test_linked_pipeline_annotations_do_not_become_missing_operator_labels():
    _, row, cached = episode_fixture()
    state = sieve.summarize([row], {'recordings': {row['recording']: cached}})
    assert state['recordings'][0]['pipeline_tasks'] == 'linked'
    assert state['recordings'][0]['operator_task'] is None
    assert state['totals']['task_reports'] == 1


@pytest.mark.parametrize('fault', ['receipt_bucket', 'receipt_prefix', 'receipt_digest', 'revision', 'manifest'])
def test_untrusted_or_stale_receipts_cannot_sign_artifacts(fault):
    s3, row, cached = episode_fixture()
    if fault == 'receipt_bucket': cached['receipt']['bucket'] = '6thsense-raw'
    if fault == 'receipt_prefix': cached['receipt']['key'] = 'inherited/v1/other/manifest.json'
    if fault == 'receipt_digest': cached['receipt']['sha256'] = 'f' * 64
    if fault == 'revision': row['revision'] = 'new'
    if fault == 'manifest': row['manifest_version'] = 'new'
    with pytest.raises(ValueError):
        viewer.preview(s3, row, cached)
    assert not s3.signed


@pytest.mark.parametrize('fault', ['task_hash', 'task_missing', 'task_foreign', 'task_recording', 'task_timeout', 'imu_malformed'])
def test_optional_failures_preserve_video_and_are_unavailable_not_absent(fault):
    s3, row, cached = episode_fixture()
    if fault.startswith('task'):
        ref = row['doc']['policy']['episode_tasks']
        body, stored, meta = s3.objects[ref['bucket'], ref['key']]
        if fault == 'task_hash': body = body.replace(b'cut:paper', b'cut:other')
        if fault == 'task_recording': body = body.replace(row['recording'].encode(), b'wrong-episode')
        if fault in ('task_hash', 'task_recording'):
            s3.objects[ref['bucket'], ref['key']] = (body, stored, meta)
        if fault == 'task_missing': del s3.objects[ref['bucket'], ref['key']]
        if fault == 'task_timeout':
            original_get = s3.get_object
            def timeout(**kw):
                if kw['Key'] == ref['key']:
                    raise ReadTimeoutError(endpoint_url='https://storage.example.test')
                return original_get(**kw)
            s3.get_object = timeout
        if fault == 'task_foreign':
            # A committed manifest can contain an unsafe optional ref. Bind a
            # new receipt to it so this tests the task-ref boundary itself.
            ref['bucket'] = '6thsense-raw'
            new = s3.add(row['manifest_key'], sieve.encoded(row['doc']))
            row.update(manifest_version=new['version_id'], manifest_sha256=new['sha256'])
            s3.add(f"qc-results/{row['run_id']}/_SUCCESS.json", sieve.encoded({'manifest': new}))
            row['revision'] = 'foreign-task-revision'
            cached = sieve.copy_recording(s3, row)
    else:
        ref = next(o for o in row['doc']['outputs'] if o['role'] == 'imu')
        body, stored, meta = s3.objects['6thsense-processed', ref['key']]
        s3.objects['6thsense-processed', ref['key']] = (body.replace(b',1,2,3,', b',nan,2,'), stored, meta)
    result = viewer.preview(s3, row, cached)
    assert len(result['videos']) == 2
    assert result['tasks' if fault.startswith('task') else 'imu']['status'] == 'unavailable'


def test_task_events_are_bounded_and_other_episodes_are_excluded():
    document = {'schema': '6thsense-episode-tasks/1', 'models': {'m': {'episodes': [
        {'episode_id': 'other', 'events': [], 'task_labels': ['other']},
        {'episode_id': 'wanted', 'events': [{}] * 201, 'task_labels': ['cut:paper']}]}}}
    model = viewer.task_models(document, 'wanted')['models'][0]
    assert model['task_labels'] == ['cut:paper']
    assert model['event_count'] == 201 and len(model['events']) == 200
    with pytest.raises(ValueError): viewer.task_models(document, 'missing')


@pytest.mark.asyncio
async def test_episode_api_auth_pending_and_deleted(app, db_session, monkeypatch):
    s3, row, cached = episode_fixture()
    rows = [row]
    async def inventory(db): return rows
    async def state(db): return {'recordings': {row['recording']: cached}}
    monkeypatch.setattr(sieve, 'inventory', inventory)
    monkeypatch.setattr(sieve, 'saved_state', state)
    def storage_client(*, bounded):
        assert bounded is True
        return s3
    monkeypatch.setattr(sieve, 'storage_client', storage_client)
    monkeypatch.setattr(sieve, 'availability', lambda: {'visible': True})
    ops, guest = await _sid(db_session, 'ops'), await _sid(db_session, 'guest')
    path = '/api/ops/sieve/episodes/' + row['recording']
    async with _client(app) as client:
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, cookies={'sid': guest})).status_code == 403
        result = await client.get(path, cookies={'sid': ops})
        assert result.status_code == 200 and result.headers['cache-control'] == 'private, no-store'
        def unavailable(*, bounded):
            assert bounded is True
            raise ReadTimeoutError(endpoint_url='https://storage.example.test')
        monkeypatch.setattr(sieve, 'storage_client', unavailable)
        assert (await client.get(path, cookies={'sid': ops})).status_code == 503
        monkeypatch.setattr(sieve, 'storage_client', storage_client)
        cached['status'] = 'pending'
        assert (await client.get(path, cookies={'sid': ops})).status_code == 409
        cached['status'] = 'inherited'
        original = viewer.preview
        def delete_during_read(*args):
            result = original(*args)
            rows.clear()
            return result
        monkeypatch.setattr(viewer, 'preview', delete_during_read)
        assert (await client.get(path, cookies={'sid': ops})).status_code == 409
        assert (await client.get(path, cookies={'sid': ops})).status_code == 404
        monkeypatch.setattr(sieve, 'availability', lambda: {'visible': False})
        assert (await client.get(path, cookies={'sid': ops})).status_code == 410
