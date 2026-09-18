"""Read-only playback of verified private EgoC review copies, never Clean approval."""
import hashlib
import json
from botocore.exceptions import ClientError

BUCKET = '6thsense-processed'
MISSING = {'NoSuchKey', 'NoSuchVersion', '404', 'NotFound'}


def _read(s3, key, ref=None):
    args = {'Bucket': BUCKET, 'Key': key}
    if ref:
        if ref.get('bucket') != BUCKET or ref.get('version_id') in (None, '', 'null'):
            raise ValueError('Unpinned Raw review evidence')
        args['VersionId'] = ref['version_id']
    obj = s3.get_object(**args)
    try:
        if obj['ContentLength'] > 4 * 1024**2:
            raise ValueError('Raw review evidence too large')
        raw = obj['Body'].read()
    finally:
        obj['Body'].close()
    if ref and (len(raw) != ref['bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']):
        raise ValueError('Raw review evidence changed')
    return json.loads(raw)


def decoded_playback(recording, sources, raw_s3, cfg, *, processed_s3=None):
    if len(sources) != 1 or not sources[0]['key'].lower().endswith('.egoc'):
        return []
    if processed_s3 is None:
        from app.core.ops_sieve import storage_client
        processed_s3 = storage_client(bounded=True)
    try:
        state = _read(processed_s3, 'raw-lifecycle/v1/states/' + recording + '.json')
        if (state.get('recording') != recording or not state.get('review_preview')
                or state.get('operator_rejection') or state.get('scene_disposition')
                or state.get('rejected_archive_receipt') or state.get('retired')):
            return []
        ref = state['conversion_receipt']
        report = _read(processed_s3, ref['key'], ref)
        plan = state['conversion_plan']
        expected = f"clean/{plan['task']}/staging/{recording}/preview.mp4"
        preview = state['review_preview']
        check = report.get('verification', {}).get('preview', {})
        if (report.get('schema') != '6thsense-raw-conversion-result/1'
                or report.get('status') != 'converted_staging'
                or report.get('recording') != recording or report.get('task') != plan['task']
                or preview not in report.get('outputs', []) or preview.get('key') != expected
                or preview.get('bucket') != BUCKET or preview.get('version_id') in (None, '', 'null')
                or check.get('codec') != 'h264' or check.get('all_frames_decoded') is not True
                or check.get('all_timestamps_checked') is not True
                or check.get('frames', 0) <= 0 or check['frames'] != report.get('decoded_frame_count')):
            raise ValueError('Raw review preview has not passed verification')
        original = report.get('sources', [])
        if len(original) != 1 or original[0]['key'] != sources[0]['key'] or original[0]['bucket'] != cfg.bucket:
            return []
        original = original[0]
        head = raw_s3.head_object(Bucket=cfg.bucket, Key=original['key'])
        if (head.get('VersionId') != original['version_id']
                or head['ContentLength'] != original['bytes']
                or head['ContentLength'] != sources[0]['bytes']
                or head['ETag'].strip('"') != sources[0]['etag'].strip('"')):
            return []  # New delivery: never show a stale recording under current Raw.
        head = processed_s3.head_object(Bucket=BUCKET, Key=expected, VersionId=preview['version_id'])
        if head['ContentLength'] != preview['bytes'] or head.get('Metadata', {}).get('sha256') != preview['sha256']:
            raise ValueError('Raw review preview bytes differ from verified output')
        return [{'name': 'Decoded full recording (review only).mp4', 'key': expected,
                 'bytes': preview['bytes'], 'review_only': True,
                 'url': processed_s3.generate_presigned_url('get_object',
                     Params={'Bucket': BUCKET, 'Key': expected, 'VersionId': preview['version_id']},
                     ExpiresIn=cfg.presign_ttl)}]
    except ClientError as exc:
        if exc.response['Error']['Code'] in MISSING:
            return []
        raise
