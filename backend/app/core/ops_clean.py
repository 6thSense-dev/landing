"""Read committed QC evidence and sign only its verified clean outputs."""
import hashlib
import json
import math
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from app.core.ops_s3 import _client, get_settings
from app.core.ops_artifacts import SCHEMA as MULTIMODAL_SCHEMA, validate_artifacts

SCHEMA = '6thsense-clean-qc/1'


def clean_bucket():
    return os.environ.get('OPS_CLEAN_S3_BUCKET', '6thsense-processed')


def estimate_krw(seconds, rate):
    if rate is None:
        return None
    return int((Decimal(str(seconds)) * Decimal(rate) / Decimal(3600)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def validate_manifest(doc):
    if not isinstance(doc, dict):
        raise ValueError('QC document must be an object')
    if doc.get('schema') not in (SCHEMA, MULTIMODAL_SCHEMA) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,120}', doc.get('run_id', '')):
        raise ValueError('Unknown QC schema or invalid run ID')
    if not re.fullmatch(r'[A-F0-9]{6}', doc.get('device_id', '')):
        raise ValueError('Invalid source camera')
    for name in ('retained_seconds', 'rejected_seconds', 'source_seconds'):
        value = doc.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'Invalid {name}')
    if abs(doc['retained_seconds'] + doc['rejected_seconds'] - doc['source_seconds']) > .05:
        raise ValueError('QC time does not balance')
    recordings = doc.get('recordings')
    if not isinstance(recordings, list) or not recordings:
        raise ValueError('Source recordings are required')
    seen = set()
    source_ids = set()
    source_hashes = set()
    kept = rejected = 0
    for rec in recordings:
        if not isinstance(rec, dict) or not isinstance(rec.get('source_seconds'), (int, float)) or not math.isfinite(rec['source_seconds']) or rec['source_seconds'] < 0:
            raise ValueError('Invalid recording duration')
        if not isinstance(rec.get('recording'), str) or rec['recording'] in seen:
            raise ValueError('Duplicate or missing recording identity')
        if not re.fullmatch(r'ego_[0-9]{8}_[0-9]{6}_[A-Fa-f0-9]{6}', rec['recording']) or rec['recording'].rsplit('_', 1)[-1].upper() != doc['device_id']:
            raise ValueError('Recording identity must identify its source camera')
        seen.add(rec['recording'])
        intervals = rec.get('intervals', [])
        cursor = 0
        for interval in intervals:
            start, end = interval.get('start_s'), interval.get('end_s')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)):
                raise ValueError('Invalid interval time')
            if abs(start - cursor) > .02 or end <= start or interval.get('disposition') not in ('keep', 'reject'):
                raise ValueError('Intervals must partition the decoded timeline without overlaps or gaps')
            if interval['disposition'] == 'keep':
                kept += end - start
            else:
                rejected += end - start
            cursor = end
        if abs(cursor - rec.get('source_seconds', 0)) > .05:
            raise ValueError('Incomplete recording timeline')
        for source in rec.get('sources', []):
            if source.get('bucket') != '6thsense-raw' or not source.get('key', '').startswith('sessions/'):
                raise ValueError('Invalid source location')
            if source['key'].split('/')[-2] != rec['recording']:
                raise ValueError('Source key does not belong to this recording')
            identity = (source['bucket'], source['key'], source.get('version_id'))
            if identity in source_ids or source.get('sha256') in source_hashes:
                raise ValueError('Duplicate source footage')
            source_ids.add(identity)
            source_hashes.add(source.get('sha256'))
            if source.get('version_id') in (None, '', 'null') or not re.fullmatch(r'[a-f0-9]{64}', source.get('sha256', '')):
                raise ValueError('Unpinned source evidence')
        if cursor and not rec.get('sources'):
            raise ValueError('Decoded footage requires source evidence')
    if abs(kept - doc['retained_seconds']) > .05 or abs(rejected - doc['rejected_seconds']) > .05:
        raise ValueError('Interval totals do not match summary')
    outputs = doc.get('outputs', [])
    if kept and not outputs:
        raise ValueError('Retained footage has no clean outputs')
    output_keys = set()
    for output in outputs:
        key = output.get('key', '')
        if key in output_keys:
            raise ValueError('Duplicate output reference')
        output_keys.add(key)
        if not key.startswith(f"clean/{doc['run_id']}/") or any(p in ('', '.', '..') for p in key.split('/')):
            raise ValueError('Output outside this clean run')
        extensions = ('.mp4', '.m3u8') if doc['schema'] == SCHEMA else ('.mp4', '.tar', '.csv', '.json')
        if not key.endswith(extensions) or output.get('version_id') in (None, '', 'null') or type(output.get('bytes')) is not int or output['bytes'] <= 0:
            raise ValueError('Invalid output reference')
        if not re.fullmatch(r'[a-f0-9]{64}', output.get('sha256', '')):
            raise ValueError('Output digest is required')
    if doc['schema'] == MULTIMODAL_SCHEMA:
        validate_artifacts(doc)
    return doc


def _json(s3, key, version=None):
    args = {'Bucket': clean_bucket(), 'Key': key}
    if version:
        args['VersionId'] = version
    response = s3.get_object(**args)
    if response['ContentLength'] > 16 * 1024 * 1024:
        response['Body'].close()
        raise ValueError('QC document exceeds size limit')
    body = response['Body'].read()
    return json.loads(body), body, response.get('VersionId')


class VerifiedResults(list):
    def __init__(self):
        super().__init__()
        self.errors = []


def _committed_result(s3, key):
    marker, _, _ = _json(s3, key)
    ref = marker.get('manifest', {})
    if ref.get('key') != key.rsplit('/', 1)[0] + '/result.json' or ref.get('version_id') in (None, '', 'null'):
        raise ValueError('Invalid QC completion marker')
    doc, body, version = _json(s3, ref['key'], ref['version_id'])
    digest = hashlib.sha256(body).hexdigest()
    if digest != ref.get('sha256'):
        raise ValueError('QC result digest mismatch')
    validate_manifest(doc)
    if key != f"qc-results/{doc['run_id']}/_SUCCESS.json":
        raise ValueError('Run identity does not match completion marker')
    for output in doc.get('outputs', []):
        head = s3.head_object(Bucket=clean_bucket(), Key=output['key'], VersionId=output['version_id'])
        if head['ContentLength'] != output['bytes'] or head.get('Metadata', {}).get('sha256') != output['sha256']:
            raise ValueError('Clean output does not match its committed inventory')
    return doc, ref['key'], version, digest


def committed_results():
    from botocore.exceptions import ClientError
    s3 = _client(get_settings())
    results = VerifiedResults()
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=clean_bucket(), Prefix='qc-results/'):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if not key.endswith('/_SUCCESS.json'):
                continue
            try:
                results.append(_committed_result(s3, key))
            except (ClientError, ValueError, KeyError, TypeError, AttributeError) as exc:
                results.errors.append({'marker': key, 'error': type(exc).__name__})
    return results


def playback(doc):
    validate_manifest(doc)
    s3 = _client(get_settings())
    return [{**item, 'url': s3.generate_presigned_url('get_object', Params={
        'Bucket': clean_bucket(), 'Key': item['key'], 'VersionId': item['version_id']},
        ExpiresIn=get_settings().presign_ttl)} for item in doc.get('outputs', []) if item['key'].endswith('.mp4')]
