"""S3-only data plane; the API handles manifests, receipts and short-lived grants."""
import json
import math
import os
from botocore.config import Config
from botocore.exceptions import ClientError
from app.core.ops_s3 import get_settings
from app.schemas.uploads import PART_BYTES, RECEIPT_NAME


def client():
    import boto3
    cfg = get_settings()
    if cfg.half_configured:
        raise RuntimeError('Incomplete upload storage credentials')
    credentials = dict(aws_access_key_id=cfg.access_key_id,
                       aws_secret_access_key=cfg.secret_access_key) if cfg.access_key_id else {}
    return boto3.client('s3', region_name=cfg.region, **credentials,
        config=Config(signature_version='s3v4', connect_timeout=10, read_timeout=60,
                      retries={'max_attempts': 3, 'mode': 'standard'},
                      s3={'use_accelerate_endpoint': os.getenv('OPS_UPLOAD_ACCELERATE', 'true') == 'true'}))


def prefix(batch):
    return f'sessions/web-{batch.id}/{batch.recording}/'


def key(batch, file):
    return prefix(batch) + file.path


def part_count(file):
    return math.ceil(file.size / PART_BYTES)


def part_size(file, number):
    if number < 1 or number > part_count(file):
        raise ValueError('Part number is outside this file.')
    return min(PART_BYTES, file.size - (number - 1) * PART_BYTES)


def missing(exc):
    return isinstance(exc, ClientError) and exc.response['Error']['Code'] in ('404', 'NoSuchKey', 'NotFound')


def head(batch, file):
    try:
        result = client().head_object(Bucket=get_settings().bucket, Key=key(batch, file))
    except ClientError as exc:
        if missing(exc):
            return None
        raise
    if (result['ContentLength'] != file.size
            or result.get('Metadata', {}).get('upload-file-id') != file.id
            or result.get('VersionId') in (None, '', 'null')):
        raise ValueError('Stored file does not match this upload. Contact 6thSense.')
    if file.version_id and result['VersionId'] != file.version_id:
        raise ValueError('The stored file version changed. Contact 6thSense.')
    return result


def initiate(batch, file):
    return client().create_multipart_upload(Bucket=get_settings().bucket, Key=key(batch, file),
        ContentType='application/octet-stream', ChecksumAlgorithm='SHA256',
        Metadata={'upload-file-id': file.id, 'upload-batch-id': batch.id,
                  'upload-fingerprint': file.fingerprint})['UploadId']


def upload_exists(batch, file):
    try:
        client().list_parts(Bucket=get_settings().bucket, Key=key(batch, file),
                            UploadId=file.upload_id, MaxParts=1)
        return True
    except ClientError as exc:
        if exc.response['Error']['Code'] == 'NoSuchUpload':
            return False
        raise


def presign(batch, file, part):
    return client().generate_presigned_url('upload_part', Params={
        'Bucket': get_settings().bucket, 'Key': key(batch, file), 'UploadId': file.upload_id,
        'PartNumber': part.number, 'ContentLength': part_size(file, part.number),
        'ChecksumSHA256': part.checksum}, ExpiresIn=900)


def complete(batch, file, parts):
    # Recover a successful S3 completion whose response/DB commit was lost.
    existing = head(batch, file)
    if existing:
        return existing
    client().complete_multipart_upload(Bucket=get_settings().bucket, Key=key(batch, file),
        UploadId=file.upload_id, IfNoneMatch='*', MultipartUpload={'Parts': [
            {'PartNumber': p.number, 'ETag': p.etag, 'ChecksumSHA256': p.checksum} for p in parts]})
    result = head(batch, file)
    if result is None:
        raise ValueError('Upload completion could not be verified. Please retry.')
    return result


def metadata(batch, file):
    result = client().get_object(Bucket=get_settings().bucket, Key=key(batch, file), VersionId=file.version_id)
    body = result['Body']
    try:
        raw = body.read(1024 ** 2 + 1)
    finally:
        body.close()
    if len(raw) > 1024 ** 2:
        raise ValueError('metadata.json exceeds the upload limit.')
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('metadata.json is not valid JSON. Keep your original files and contact 6thSense.') from exc
    if not isinstance(parsed, dict):
        raise ValueError('metadata.json must contain the original camera metadata object.')
    return parsed


def publish_receipt(batch, files):
    payload = {'schema': '6thsense.browser-upload.v1', 'batch_id': batch.id,
        'recording': batch.recording, 'uploader_wearer_id': batch.wearer_id,
        'sources': [{'path': f.path, 'bytes': f.size,
            'version_id': f.version_id, 'etag': f.etag} for f in files]}
    # Only the server can write this reserved filename. No presigned grant can
    # name it; Raw's scanner waits for it before considering a browser upload.
    client().put_object(Bucket=get_settings().bucket, Key=prefix(batch) + RECEIPT_NAME,
                        Body=json.dumps(payload, sort_keys=True).encode(), ContentType='application/json')
