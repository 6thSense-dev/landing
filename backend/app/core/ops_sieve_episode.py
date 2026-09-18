"""Read-only episode inspection, bound to the active Clean and Sieve receipts."""
import csv
import hashlib
import io
import json
import math
import re
from botocore.exceptions import BotoCoreError

from app.core import ops_sieve as sieve
from app.core.ops_clean import browser_previews, clean_bucket, validate_manifest

JSON_LIMIT = 16 * 1024 * 1024
IMU_BYTES = 64 * 1024
IMU_ROWS = 200
TTL = 900


def validate_ref(ref, bucket, prefix):
    if (not isinstance(ref, dict) or ref.get('bucket') != bucket
            or not isinstance(ref.get('key'), str) or not ref['key'].startswith(prefix)
            or any(part in ('', '.', '..') for part in ref['key'].split('/'))
            or not isinstance(ref.get('version_id'), str) or ref['version_id'] in ('', 'null')
            or not re.fullmatch(r'[a-f0-9]{64}', str(ref.get('sha256', '')))
            or type(ref.get('bytes')) is not int or ref['bytes'] <= 0):
        raise ValueError('Artifact reference does not belong to this episode')
    return ref


def read_document(s3, ref):
    if ref['bytes'] > JSON_LIMIT:
        raise ValueError('JSON is too large to preview; use the artifact download')
    response = s3.get_object(Bucket=ref['bucket'], Key=ref['key'], VersionId=ref['version_id'])
    try:
        body = response['Body'].read(JSON_LIMIT + 1)
    finally:
        response['Body'].close()
    if (response.get('VersionId') != ref['version_id'] or response['ContentLength'] != ref['bytes']
            or len(body) != ref['bytes'] or hashlib.sha256(body).hexdigest() != ref['sha256']):
        raise ValueError('Artifact content differs from the pinned receipt')
    return json.loads(body)


def signed(s3, ref, name):
    return {'name': name, 'storage': 'Sieve' if ref['bucket'] == sieve.BUCKET else 'Clean',
            'bytes': ref['bytes'], 'sha256': ref['sha256'], 'version_id': ref['version_id'],
            'url': s3.generate_presigned_url('get_object', Params={
                'Bucket': ref['bucket'], 'Key': ref['key'], 'VersionId': ref['version_id']}, ExpiresIn=TTL)}


def validate_task_episode(episode):
    """Malformed optional annotations must not reach the rendering boundary."""
    def optional(value, kind):
        return value is None or type(value) is kind

    def number(value):
        return value is None or (type(value) in (int, float) and math.isfinite(value))

    for field in ('task_labels', 'environments'):
        values = episode.get(field, [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError('Invalid task labels or environments')
    if (not optional(episode.get('dominant_observed_task'), str)
            or not optional(episode.get('review_required'), bool)):
        raise ValueError('Invalid task description or review flag')
    coverage = episode.get('coverage')
    if coverage is not None and (not isinstance(coverage, dict)
            or not optional(coverage.get('full_episode'), bool)
            or any(not number(coverage.get(k)) for k in ('selected_seconds', 'annotated_selected_seconds'))):
        raise ValueError('Invalid task coverage')
    events = episode.get('events', [])
    if not isinstance(events, list):
        raise ValueError('Invalid task event list')
    for event in events:
        if (not isinstance(event, dict)
                or any(not optional(event.get(k), str) for k in ('task_id', 'action', 'object', 'evidence'))
                or not optional(event.get('review_required'), bool)
                or any(not number(event.get(k)) for k in ('source_navigation_start_s', 'source_navigation_end_s'))):
            raise ValueError('Invalid task event')


def task_models(document, recording):
    if document.get('schema') != '6thsense-episode-tasks/1' or not isinstance(document.get('models'), dict):
        raise ValueError('Unknown pipeline task report')
    models = []
    for name, model in document['models'].items():
        if not isinstance(model, dict) or not isinstance(model.get('episodes', []), list):
            raise ValueError('Invalid task model episodes')
        episodes = model.get('episodes', [])
        if any(not isinstance(e, dict) for e in episodes):
            raise ValueError('Invalid task episode')
        matches = [e for e in episodes if e.get('episode_id') == recording]
        if len(matches) > 1:
            raise ValueError('Ambiguous task annotation identity')
        if matches:
            episode = matches[0]
            validate_task_episode(episode)
            models.append({'model': name, **{k: episode.get(k) for k in (
                'task_labels', 'dominant_observed_task', 'environments', 'coverage', 'review_required')},
                'event_count': len(episode.get('events', [])), 'events': episode.get('events', [])[:200]})
    if not models:
        raise ValueError('Task report does not contain this episode')
    return {'status': 'available', 'taxonomy': document.get('taxonomy'),
            'human_verified': document.get('human_verified') is True, 'models': models}


def imu_preview(s3, ref):
    """Bounded beginning-of-file preview, never represented as full coverage."""
    response = s3.get_object(Bucket=ref['bucket'], Key=ref['key'], VersionId=ref['version_id'],
                             Range=f'bytes=0-{IMU_BYTES - 1}')
    try:
        raw = response['Body'].read(IMU_BYTES + 1)
    finally:
        response['Body'].close()
    if (response.get('VersionId') != ref['version_id'] or len(raw) != min(ref['bytes'], IMU_BYTES)
            or response['ContentLength'] != len(raw)):
        raise ValueError('IMU preview version or size differs')
    # A byte range may end mid-row. CSV is numeric ASCII; discard the partial row.
    if len(raw) < ref['bytes']:
        raw = raw.rsplit(b'\n', 1)[0] + b'\n'
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    columns = reader.fieldnames or []
    if not columns or len(columns) > 32 or any(len(c) > 100 for c in columns):
        raise ValueError('Invalid IMU columns')
    rows = []
    for index, row in enumerate(reader):
        if index >= IMU_ROWS:
            break
        if None in row or any(v is None for v in row.values()):
            raise ValueError('Invalid IMU row')
        values = {}
        for key, value in row.items():
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('Invalid IMU measurement')
            values[key] = number
        rows.append(values)
    if not rows:
        raise ValueError('No IMU samples in preview')
    return {'columns': columns, 'rows': rows, 'scope': 'first_samples', 'sample_limit': IMU_ROWS}


def preview(s3, row, cached):
    """Use only current receipts; never accept arbitrary object keys from clients."""
    run, name = row['run_id'], row['recording']
    clean_prefix = f'clean/{run}/'
    receipt_prefix = f'{sieve.PREFIX}{run}/{name}/'
    receipt_ref = validate_ref(cached['receipt'], sieve.BUCKET, receipt_prefix)
    receipt = read_document(s3, receipt_ref)
    if (receipt.get('schema') != sieve.SCHEMA or receipt.get('source') != 'Clean'
            or receipt.get('run_id') != run or receipt.get('recording') != name
            or receipt.get('revision') != row['revision']):
        raise ValueError('Sieve receipt does not match the current episode')
    manifest = validate_ref(receipt['manifest'], clean_bucket(), f'qc-results/{run}/')
    if any(manifest[k] != row[field] for k, field in (
            ('key', 'manifest_key'), ('version_id', 'manifest_version'), ('sha256', 'manifest_sha256'))):
        raise ValueError('Sieve copy belongs to an older Clean manifest')
    doc = read_document(s3, manifest)
    if doc != row['doc']:
        raise ValueError('Clean manifest changed')
    validate_manifest(doc)
    marker, _ = sieve.read_json(s3, f'qc-results/{run}/_SUCCESS.json')
    if any(marker.get('manifest', {}).get(k) != manifest[k] for k in ('key', 'version_id', 'sha256')):
        raise ValueError('Clean completion changed; refresh the collection')
    files = {}
    for item in receipt['files']:
        filename = item['name']
        if filename not in ('left.mp4', 'right.mp4', 'native.mp4', 'metadata.json', 'calibration.json', 'metadata-provenance.json'):
            continue
        if filename in files:
            raise ValueError('Duplicate episode artifact')
        ref = validate_ref(item['destination'], sieve.BUCKET, receipt_prefix)
        if ref['key'].rsplit('/', 1)[-1] != filename:
            raise ValueError('Episode artifact filename differs')
        sieve.verify_head(s3, ref)
        files[filename] = ref
    if not {'metadata.json', 'calibration.json'} <= files.keys() or not (
            {'left.mp4', 'right.mp4'} <= files.keys() or 'native.mp4' in files):
        raise ValueError('Sieve receipt is incomplete')
    videos = [signed(s3, ref, filename) for filename, ref in files.items() if filename.endswith('.mp4')]
    result = {'recording': name, 'run_id': run, 'revision': row['revision'], 'expires_in': TTL,
              'videos': videos, 'browser_preview': None, 'warnings': [],
              'metadata': None, 'calibration': None, 'imu': {'status': 'absent'},
              'tasks': {'status': 'absent'}, 'operator_task': row['activity']}
    for field, filename in (('metadata', 'metadata.json'), ('calibration', 'calibration.json')):
        ref = files[filename]
        result[field] = signed(s3, ref, filename)
        try:
            result[field]['data'] = read_document(s3, ref)
        except (ValueError, BotoCoreError, sieve.ClientError):
            result[field]['error'] = 'JSON preview unavailable. Refresh to retry.'
    # Existing browser-compatible copies preserve the full retained timeline.
    try:
        previews = browser_previews(s3, doc, {k: manifest[k] for k in ('key', 'version_id', 'sha256')})
        match = next((p for p in previews if p['recording'] == name), None)
        if match:
            result['browser_preview'] = signed(s3, match, 'Browser preview (stereo)')
    except (ValueError, BotoCoreError, sieve.ClientError):
        result['warnings'].append('Browser-compatible preview unavailable; original videos remain accessible.')
    outputs = [o for o in doc['outputs'] if o.get('recording') == name and o.get('role') == 'imu']
    if outputs:
        result['imu'] = {'status': 'unavailable'}
        try:
            if len(outputs) != 1 or name not in outputs[0]['key'].split('/')[2:-1]:
                raise ValueError('Ambiguous IMU recording')
            ref = validate_ref({'bucket': clean_bucket(), **outputs[0]}, clean_bucket(), clean_prefix)
            sieve.verify_head(s3, ref)
            result['imu'].update(signed(s3, ref, 'imu.csv'))
            result['imu'].update(imu_preview(s3, ref))
            result['imu'].update(status='available', total_samples=row['rec'].get('media', {}).get('imu_samples'),
                                 units=row['rec'].get('media', {}).get('imu_units', {}))
        except (ValueError, BotoCoreError, sieve.ClientError):
            result['imu']['error'] = 'IMU exists in Clean, but its preview could not be read.'
    task_ref = doc.get('policy', {}).get('episode_tasks')
    if task_ref:
        result['tasks'] = {'status': 'unavailable'}
        try:
            ref = validate_ref(task_ref, clean_bucket(), f'qc-results/{run}/')
            result['tasks'].update(task_models(read_document(s3, ref), name), artifact=signed(s3, ref, 'episode-tasks.json'))
        except (ValueError, KeyError, TypeError, AttributeError, BotoCoreError, sieve.ClientError):
            result['tasks']['error'] = 'Pipeline task report is linked, but could not be verified. Refresh to retry.'
    return result
