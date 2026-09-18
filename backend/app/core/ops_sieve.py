"""Clean-only Sieve inheritance; versioned copies, no decoding or Raw reads."""
import asyncio
import hashlib
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError
from sqlalchemy import select, text
from app.core.db import get_engine, get_sessionmaker
from app.core.ops_calibration import validate_calibration
from app.core.ops_clean import clean_bucket, validate_manifest
from app.core.ops_regions import clean_region, REGIONS
from app.core.ops_s3 import get_settings
from app.models import CleanRun, Episode, OpsSetting, Task, Wearer

BUCKET = '6thsense-sieve'
PREFIX = 'inherited/v1/'
STATE_KEY = 'sieve_clean_sync_v1'
EXCLUSIONS_KEY = 'sieve_delivery_exclusions_v1'
SCHEMA = '6thsense-sieve-clean-inheritance/1'
ELIGIBLE_COUNTRIES = frozenset({'India', 'Korea'})
MISSING = {'NoSuchKey', 'NoSuchVersion', '404', 'NotFound'}
logger = logging.getLogger(__name__)


def storage_client(*, bounded=False):
    """Dedicated assumed role can read Clean and write only Sieve inheritance."""
    import boto3
    from botocore.config import Config
    role = os.getenv('OPS_SIEVE_ROLE_ARN')
    if not role:
        raise ValueError('Clean inheritance storage role is not configured')
    cfg = get_settings()
    request_config = (Config(connect_timeout=3, read_timeout=5, max_pool_connections=12,
                             retries={'total_max_attempts': 2, 'mode': 'standard'})
                      if bounded else None)
    sts = boto3.client('sts', region_name=cfg.region, config=request_config,
                       aws_access_key_id=cfg.access_key_id or None,
                       aws_secret_access_key=cfg.secret_access_key or None)
    credentials = sts.assume_role(RoleArn=role, RoleSessionName='sieve-clean-inheritance', DurationSeconds=3600)['Credentials']
    return boto3.client('s3', region_name=cfg.region, aws_access_key_id=credentials['AccessKeyId'],
                        aws_secret_access_key=credentials['SecretAccessKey'], aws_session_token=credentials['SessionToken'],
                        config=request_config or Config(connect_timeout=10, read_timeout=60, retries={'max_attempts': 4}))


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def availability(now=None):
    now = now or datetime.now(timezone.utc)
    return {'visible': now.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat() <= '2026-09-25',
            'contract_ends_on': '2026-09-22', 'dashboard_through': '2026-09-25', 'timezone': 'America/Los_Angeles'}


async def inventory(db):
    runs = (await db.execute(select(CleanRun).order_by(CleanRun.created_at.desc(), CleanRun.run_id))).scalars().all()
    people = {p.id: p for p in (await db.execute(select(Wearer))).scalars()}
    episodes = {e.recording: e for e in (await db.execute(select(Episode))).scalars()}
    tasks = {t.id: t.name for t in (await db.execute(select(Task))).scalars()}
    setting = await db.get(OpsSetting, EXCLUSIONS_KEY)
    excluded_wearers = set()
    if setting:
        policy = json.loads(setting.value)
        if (not isinstance(policy, dict) or policy.get('schema') != '6thsense-sieve-delivery-exclusions/1'
                or not isinstance(policy.get('wearers'), dict)):
            raise ValueError('Sieve exclusion policy is invalid; delivery held')
        for key, exclusion in policy['wearers'].items():
            if (not key.isdecimal() or int(key) <= 0 or str(int(key)) != key
                    or not isinstance(exclusion, dict) or not isinstance(exclusion.get('reason'), str)
                    or not exclusion['reason'].strip()):
                raise ValueError('Sieve wearer exclusion is invalid; delivery held')
            excluded_wearers.add(int(key))
    # A prior manifest or source alias must not bypass a contributor exclusion.
    excluded_recordings = {e.recording for e in episodes.values() if e.wearer_id in excluded_wearers}
    documents = [(run, json.loads(run.manifest_json)) for run in runs]
    for run, doc in documents:
        if run.wearer_id in excluded_wearers:
            excluded_recordings.update(rec['recording'] for rec in doc['recordings'])
    excluded_sources = {source['sha256'] for _, doc in documents for rec in doc['recordings']
                        if rec['recording'] in excluded_recordings for source in rec.get('sources', [])}
    rows, seen_names, seen_sources = [], set(), set()
    for run, doc in documents:
        party, person = doc.get('counterparty'), people.get(run.wearer_id)
        for rec in doc['recordings']:
            name = rec['recording']
            episode = episodes.get(name)
            if episode and episode.deleted_at:
                continue
            # Source aliases and historical run revisions cannot multiply hours.
            sources = {s['sha256'] for s in rec.get('sources', [])}
            if name in excluded_recordings or sources & excluded_sources:
                continue
            if name in seen_names or sources & seen_sources:
                continue
            seen_names.add(name)
            seen_sources.update(sources)
            seconds = sum(i['end_s']-i['start_s'] for i in rec['intervals'] if i['disposition'] == 'keep')
            if seconds <= 0:
                continue
            region = clean_region({**doc, 'recordings': [rec]})
            country = REGIONS.get(party['country'], 'Unclassified') if party else region['label'] if region['key'] in REGIONS else 'Unclassified'
            # Customer eligibility is narrower than the company's Clean inventory.
            if country not in ELIGIBLE_COUNTRIES:
                continue
            if party:
                entity = {'id': f"business:{party['id']}", 'name': party['name'], 'kind': 'Business'}
            elif person:
                entity = {'id': f'wearer:{person.id}', 'name': person.name + (f' / {person.workplace}' if person.workplace and person.workplace != person.name else ''), 'kind': 'Contributor'}
            else:
                entity = {'id': 'unassigned', 'name': 'Unassigned', 'kind': 'Unassigned'}
            row = {'run_id': run.run_id, 'recording': name, 'manifest_sha256': run.manifest_sha256,
                   'manifest_key': run.manifest_key, 'manifest_version': run.manifest_version,
                   'retained_seconds': seconds, 'country': country, 'entity': entity,
                   'camera': run.device_id, 'activity': tasks.get(episode.task_id, 'Unclassified') if episode else 'Unclassified',
                   'clean_date': run.created_at.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat(),
                   'format': 'Split stereo' if rec.get('media') else 'Native stereo', 'doc': doc, 'rec': rec}
            row['revision'] = digest({k: v for k, v in row.items() if k not in ('doc', 'rec')})
            rows.append(row)
    return rows


async def saved_state(db):
    setting = await db.get(OpsSetting, STATE_KEY)
    return json.loads(setting.value) if setting else {'recordings': {}}


async def save_state(db, value):
    setting = await db.get(OpsSetting, STATE_KEY)
    if setting:
        setting.value = encoded(value).decode()
    else:
        db.add(OpsSetting(key=STATE_KEY, value=encoded(value).decode()))
    await db.commit()


def summarize(rows, snapshot):
    public = []
    for row in rows:
        cached = snapshot.get('recordings', {}).get(row['recording'], {})
        current = cached.get('revision') == row['revision']
        item = {k: v for k, v in row.items() if k not in ('doc', 'rec', 'manifest_key', 'manifest_version')}
        item.update(status=cached.get('status', 'pending') if current else 'pending',
                    reason=cached.get('reason', '') if current else 'Awaiting Clean verification',
                    checked_at=cached.get('checked_at') if current else None,
                    copied_bytes=cached.get('copied_bytes', 0) if current and cached.get('status') == 'inherited' else 0)
        # Operator assignment and pipeline annotation are separate sources. A
        # missing Episode.task_id says nothing about the linked model report.
        item['pipeline_tasks'] = 'linked' if row.get('doc', {}).get('policy', {}).get('episode_tasks') else 'not_linked'
        item['operator_task'] = None if row['activity'] == 'Unclassified' else row['activity']
        public.append(item)
    inherited = [r for r in public if r['status'] == 'inherited']
    breakdowns = {}
    for field in ('country', 'entity', 'activity', 'camera', 'clean_date'):
        groups = {}
        for row in public:
            key = row[field]['id'] if field == 'entity' else row[field]
            group = groups.setdefault(key, {'label': row[field]['name'] if field == 'entity' else key, 'seconds': 0, 'inherited_seconds': 0, 'recordings': 0})
            group['seconds'] += row['retained_seconds']
            group['inherited_seconds'] += row['retained_seconds'] if row['status'] == 'inherited' else 0
            group['recordings'] += 1
        breakdowns[field] = sorted(groups.values(), key=lambda g: g['label'] if field == 'clean_date' else -g['seconds'])
    return {'recordings': public, 'breakdowns': breakdowns,
            'totals': {'clean_seconds': sum(r['retained_seconds'] for r in public),
                       'inherited_seconds': sum(r['retained_seconds'] for r in inherited),
                       'recordings': len(public), 'inherited_recordings': len(inherited),
                       'copied_bytes': sum(r['copied_bytes'] for r in inherited),
                       'countries': len({r['country'] for r in public} - {'Unclassified'}),
                       'entities': len({r['entity']['id'] for r in public} - {'unassigned'}),
                       'cameras': len({r['camera'] for r in public}),
                       'activities': len({r['activity'] for r in public} - {'Unclassified'}),
                       'task_reports': sum(r['pipeline_tasks'] == 'linked' for r in public),
                       'status_counts': dict(Counter(r['status'] for r in public))},
            'sync': {k: snapshot.get(k) for k in ('started_at', 'completed_at', 'error')},
            'automatic_sync': os.getenv('OPS_SIEVE_ENABLED', 'false') == 'true',
            'acceptance': {'status': 'not_recorded', 'seconds': 0},
            'bucket': BUCKET, 'prefix': PREFIX, 'source': 'Clean', 'updated_at': now_iso()}


def read_json(s3, key, *, bucket=None, version=None):
    args = {'Bucket': bucket or clean_bucket(), 'Key': key}
    if version:
        args['VersionId'] = version
    obj = s3.get_object(**args)
    try:
        if obj['ContentLength'] > 16*1024*1024:
            raise ValueError('JSON artifact exceeds size limit')
        body = obj['Body'].read()
    finally:
        obj['Body'].close()
    version = obj.get('VersionId')
    if not version or version == 'null':
        raise ValueError('Versioned artifacts are required')
    return json.loads(body), {'bucket': args['Bucket'], 'key': key, 'version_id': version,
                              'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def verify_head(s3, ref, *, current=False):
    head = s3.head_object(Bucket=ref['bucket'], Key=ref['key'], **({} if current else {'VersionId': ref['version_id']}))
    if head.get('VersionId') != ref['version_id'] or head['ContentLength'] != ref['bytes'] or head.get('Metadata', {}).get('sha256') != ref['sha256']:
        raise ValueError('Artifact version, size or digest changed')


def source_files(s3, row):
    """All GET/HEAD sources are Clean, including original-metadata provenance."""
    if row['entity']['id'] == 'unassigned':
        raise ValueError('Contributor or business attribution is required')
    run, name = row['run_id'], row['recording']
    marker, _ = read_json(s3, f'qc-results/{run}/_SUCCESS.json')
    manifest = {'key': row['manifest_key'], 'version_id': row['manifest_version'], 'sha256': row['manifest_sha256']}
    if manifest['key'] != f'qc-results/{run}/result.json' or any(marker.get('manifest', {}).get(k) != v for k, v in manifest.items()):
        raise ValueError('Clean manifest changed; re-import the committed result')
    doc, manifest_ref = read_json(s3, manifest['key'], version=manifest['version_id'])
    if manifest_ref['sha256'] != manifest['sha256'] or doc != row['doc']:
        raise ValueError('Clean manifest content changed')
    validate_manifest(doc)
    base = f'clean/{run}/{name}/'
    outputs = [o for o in doc['outputs'] if o.get('recording') == name]
    stereo = [o for o in outputs if o.get('role') in ('left_video', 'right_video')]
    if stereo:
        if Counter(o['role'] for o in stereo) != {'left_video': 1, 'right_video': 1}:
            raise ValueError('Both Clean eyes are required')
        videos = stereo
    else:
        videos = [o for o in outputs if o.get('role') == 'native_stereo']
        if len(videos) != 1:
            raise ValueError('Per-recording Clean MP4 is missing')
    files = []
    for output in videos:
        if (not output['key'].startswith(f'clean/{run}/') or name not in output['key'].split('/')[2:-1]
                or not output['key'].endswith('.mp4')):
            raise ValueError('MP4 must be inside this recording’s Clean prefix')
        files.append({'name': {'left_video': 'left.mp4', 'right_video': 'right.mp4', 'native_stereo': 'native.mp4'}[output['role']],
                      'source': {'bucket': clean_bucket(), **{k: output[k] for k in ('key', 'version_id', 'sha256', 'bytes')}}})
    provenance, provenance_ref = read_json(s3, base + 'metadata-provenance.json')
    identities = [dict(zip(('bucket', 'key', 'version_id'), s)) for s in sorted({(s['bucket'], s['key'], s['version_id']) for s in row['rec']['sources']})]
    if (provenance.get('run_id') != run or provenance.get('recording') != name
            or provenance.get('source_media') != identities):
        raise ValueError('Metadata provenance does not match Clean')
    meta_ref = provenance['metadata']
    if meta_ref['bucket'] != clean_bucket() or meta_ref['key'] != base + 'metadata.json':
        raise ValueError('Metadata must be inherited from Clean')
    metadata, actual = read_json(s3, meta_ref['key'], version=meta_ref['version_id'])
    if actual != meta_ref or not isinstance(metadata, dict):
        raise ValueError('Metadata digest does not match Clean')
    if provenance.get('schema') == '6thsense-clean-source-metadata/2':
        from app.core.ops_reconstructed_metadata import validate_reconstructed
        validate_reconstructed(metadata,provenance,row['rec'],meta_ref)
    elif (provenance.get('schema') != '6thsense-clean-source-metadata/1'
            or provenance.get('copy_mode') != 'byte_exact_from_versioned_source'
            or metadata.get('metadata_origin') == 'reconstructed'
            or row['rec'].get('source_provenance',{}).get('metadata_recovery') is not None
            or not provenance.get('source_metadata')
            or any(s['sha256'] != meta_ref['sha256'] for s in provenance['source_metadata'])):
        raise ValueError('Original metadata digest does not match Clean')
    files.extend([{'name': 'metadata.json', 'source': meta_ref}, {'name': 'metadata-provenance.json', 'source': provenance_ref}])
    calibrations = [o for o in outputs if o.get('role') == 'calibration']
    if len(calibrations) > 1:
        raise ValueError('Ambiguous Clean calibration')
    calibration, calibration_ref = read_json(s3, base + 'calibration.json', version=calibrations[0]['version_id'] if calibrations else None)
    if calibrations and any(calibration_ref[k] != calibrations[0][k] for k in ('key', 'version_id', 'sha256', 'bytes')):
        raise ValueError('Calibration differs from the Clean manifest')
    validate_calibration(calibration, name, row['rec'].get('media', {}).get('layout'))
    files.append({'name': 'calibration.json', 'source': calibration_ref})
    for f in files:
        verify_head(s3, f['source'], current=True)
    return manifest_ref, files


def immutable_json(s3, key, value):
    body = encoded(value)
    try:
        result = s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType='application/json', Metadata={'sha256': hashlib.sha256(body).hexdigest()}, IfNoneMatch='*')
        version = result['VersionId']
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ('PreconditionFailed', '412'):
            raise
        version = None
    actual, ref = read_json(s3, key, bucket=BUCKET, version=version)
    if actual != value:
        raise ValueError('Conflicting Sieve receipt; refusing overwrite')
    return ref


def copy_recording(s3, row):
    if row['country'] not in ELIGIBLE_COUNTRIES:
        raise ValueError('Sieve requires India or Korea country attribution')
    from boto3.s3.transfer import TransferConfig
    manifest, files = source_files(s3, row)
    fingerprint = digest({'revision': row['revision'], 'files': files})
    target = f"{PREFIX}{row['run_id']}/{row['recording']}/{fingerprint}/"
    copied = []
    for item in files:
        source, key = item['source'], target + item['name']
        verify_head(s3, source, current=True)
        identity = digest(source)
        # HEAD of a missing key returns 403 with prefix-scoped ListBucket
        # permission. Discover the exact key using an authorized prefix list;
        # never misclassify a real access failure as permission to overwrite.
        found = s3.list_objects_v2(Bucket=BUCKET, Prefix=key, MaxKeys=1)
        exists = any(obj['Key'] == key for obj in found.get('Contents', []))
        head = s3.head_object(Bucket=BUCKET, Key=key) if exists else None
        if head is None:
            s3.copy({'Bucket': source['bucket'], 'Key': source['key'], 'VersionId': source['version_id']}, BUCKET, key,
                    ExtraArgs={'MetadataDirective': 'REPLACE', 'Metadata': {'sha256': source['sha256'], 'clean-source': identity},
                               'ContentType': 'video/mp4' if key.endswith('.mp4') else 'application/json'},
                    Config=TransferConfig(multipart_threshold=128*1024**2, multipart_chunksize=128*1024**2, max_concurrency=4))
            head = s3.head_object(Bucket=BUCKET, Key=key)
        if head.get('Metadata', {}).get('clean-source') != identity:
            raise ValueError('Sieve destination has conflicting provenance')
        destination = {**source, 'bucket': BUCKET, 'key': key, 'version_id': head.get('VersionId')}
        if not destination['version_id'] or destination['version_id'] == 'null':
            raise ValueError('Sieve destination must be versioned')
        verify_head(s3, destination)
        if key.endswith('.json'):
            _, actual = read_json(s3, key, bucket=BUCKET, version=destination['version_id'])
            if actual != destination:
                raise ValueError('Sieve JSON content verification failed')
        copied.append({**item, 'destination': destination})
    receipt = {'schema': SCHEMA, 'source': 'Clean', 'run_id': row['run_id'], 'recording': row['recording'],
               'revision': row['revision'], 'manifest': manifest, 'files': copied, 'retained_seconds': row['retained_seconds'],
               'entity': row['entity'], 'country': row['country'], 'activity': row['activity'], 'camera': row['camera'], 'format': row['format'],
               'verification': 'version_pinned_s3_copy_and_destination_inventory; JSON_SHA256_readback', 'customer_acceptance': 'not_recorded'}
    ref = immutable_json(s3, target + 'manifest.json', receipt)
    return {'status': 'inherited', 'revision': row['revision'], 'receipt': ref,
            'copied_bytes': sum(f['destination']['bytes'] for f in copied), 'checked_at': now_iso(), 'reason': ''}


def safe_error(exc):
    if isinstance(exc, ClientError):
        return 'Clean artifact is missing' if exc.response['Error']['Code'] in MISSING else 'Storage access or copy failed; retry pending'
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return 'Clean inheritance verification failed; retry pending'


async def sync_once():
    """One elected worker, idempotent after retries/redeploys; no web request waits."""
    async with get_engine().connect() as lock:
        if not (await lock.execute(text('SELECT pg_try_advisory_lock(61306135)'))).scalar():
            return
        try:
            s3 = await asyncio.to_thread(storage_client)
            async with get_sessionmaker()() as db:
                snapshot = await saved_state(db)
                snapshot.update(started_at=now_iso(), error=None)
                await save_state(db, snapshot)
                rows = await inventory(db)
            results = {}
            for row in rows:
                # The initial inventory can wait behind earlier copies. Refresh
                # exclusions/ownership before sending this recording to Sieve.
                async with get_sessionmaker()() as db:
                    current = {r['recording']: r for r in await inventory(db)}
                    if current.get(row['recording'], {}).get('revision') != row['revision']:
                        continue
                try:
                    # Cancellation must not release the leader lock while a
                    # background S3 copy is still running in this process.
                    work = asyncio.create_task(asyncio.to_thread(copy_recording, s3, row))
                    try:
                        result = await asyncio.shield(work)
                    except asyncio.CancelledError:
                        await work
                        raise
                except Exception as exc:
                    result = {'status': 'blocked', 'revision': row['revision'], 'reason': safe_error(exc), 'checked_at': now_iso()}
                    logger.warning('sieve_inheritance_failed recording=%s error=%s', row['recording'], type(exc).__name__)
                async with get_sessionmaker()() as db:
                    current = {r['recording']: r for r in await inventory(db)}
                    if current.get(row['recording'], {}).get('revision') != row['revision']:
                        continue
                    results[row['recording']] = result
                    snapshot['recordings'][row['recording']] = result
                    await save_state(db, snapshot)
            async with get_sessionmaker()() as db:
                current = {r['recording']: r for r in await inventory(db)}
                snapshot['recordings'] = {name: result for name, result in results.items() if current.get(name, {}).get('revision') == result['revision']}
                index = {'schema': SCHEMA, 'source': 'Clean', 'updated_at': now_iso(),
                         'recordings': [{'recording': name, 'receipt': result['receipt']} for name, result in snapshot['recordings'].items() if result['status'] == 'inherited']}
                await asyncio.to_thread(s3.put_object, Bucket=BUCKET, Key=PREFIX+'latest.json', Body=encoded(index), ContentType='application/json', Metadata={'sha256': digest(index)})
                snapshot['completed_at'] = now_iso()
                await save_state(db, snapshot)
        finally:
            await lock.execute(text('SELECT pg_advisory_unlock(61306135)'))


async def run():
    while True:
        try:
            await sync_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('sieve_sync_failed')
            try:
                async with get_sessionmaker()() as db:
                    snapshot = await saved_state(db)
                    snapshot['error'] = 'Sieve sync failed; retrying automatically'
                    await save_state(db, snapshot)
            except Exception:
                logger.exception('sieve_error_state_unavailable')
        await asyncio.sleep(300)
