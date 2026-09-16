"""Scheduled, single-writer Raw -> archive + Batch -> verified portal imports.

State and plans live in versioned S3. Batch submissions have durable intents;
uncertain submissions are reconciled by job name, never blindly retried.
"""
import concurrent.futures
import hashlib
import json
import os
import re
import time
import traceback
import urllib.request
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

RAW = '6thsense-raw'
PROCESSED = '6thsense-processed'
ARTIFACTS = '6thsense-deploy-artifacts'
PREFIX = 'raw-lifecycle/v1/'
RECORDING = re.compile(r'^ego_[0-9]{8}_[0-9]{6}_[A-Fa-f0-9]{6}(?:_s[0-9]{2,4})?$')
MISSING = {'404', 'NoSuchKey', 'NotFound'}
EXCLUDED = {'ego_20260909_073656_16A4A5', 'ego_20260912_103922_4A636A', 'ego_20260915_150420_4A636A'}
CLIENT_CFG = Config(connect_timeout=10, read_timeout=60, max_pool_connections=16, retries={'max_attempts': 4})
s3 = boto3.client('s3', config=CLIENT_CFG)
batch = boto3.client('batch', config=CLIENT_CFG)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def source_identity(ref):
    return {k: ref[k] for k in ('bucket', 'key', 'version_id')}


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(bucket, key, version=None):
    args = {'Bucket': bucket, 'Key': key}
    if version: args['VersionId'] = version
    obj = s3.get_object(**args)
    if obj['ContentLength'] > 32*1024**2:
        obj['Body'].close()
        raise ValueError('JSON exceeds size limit')
    body = obj['Body'].read()
    return json.loads(body), {'bucket': bucket, 'key': key, 'version_id': obj['VersionId'],
                             'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def read_pinned(ref):
    if ref.get('version_id') in (None, '', 'null') or not re.fullmatch(r'[0-9a-f]{64}', ref.get('sha256', '')):
        raise ValueError('Pinned source reference required')
    doc, actual = read_json(ref['bucket'], ref['key'], ref['version_id'])
    if actual['sha256'] != ref['sha256'] or actual['version_id'] != ref['version_id']:
        raise ValueError('Pinned source digest/version mismatch')
    size = ref.get('bytes', ref.get('size_bytes'))
    if size is not None and actual['bytes'] != size:
        raise ValueError('Pinned source size mismatch')
    return doc


def optional_json(bucket, key):
    try: return read_json(bucket, key)[0]
    except ClientError as exc:
        if exc.response['Error']['Code'] not in MISSING: raise
        return None


def put_json(bucket, key, doc, immutable=False):
    body = encoded(doc)
    args = dict(Bucket=bucket, Key=key, Body=body, ContentType='application/json', Metadata={'sha256': hashlib.sha256(body).hexdigest()})
    if immutable: args['IfNoneMatch'] = '*'
    try:
        result = s3.put_object(**args)
        version = result['VersionId']
    except ClientError as exc:
        if not immutable or exc.response['Error']['Code'] not in ('412', 'PreconditionFailed'): raise
        existing, ref = read_json(bucket, key)
        if encoded(existing) != body: raise ValueError('Immutable document conflict')
        return ref
    return dict(bucket=bucket, key=key, version_id=version, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))


def api(cfg, path, body=None):
    secret = boto3.client('secretsmanager').get_secret_value(SecretId=cfg['token_secret'])['SecretString']
    req = urllib.request.Request(cfg['api_url']+'/api/ops/pipeline/'+path,
        data=encoded(body) if body is not None else None,
        headers={'Authorization': 'Bearer '+secret, 'Content-Type': 'application/json', 'Origin': 'https://6thsense.dev'})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def save(state):
    state['updated_at'] = now()
    put_json(PROCESSED, PREFIX+'states/'+state['recording']+'.json', state)


def status(cfg, state, phase, reason):
    state['phase'], state['reason'] = phase, reason
    save(state)
    mapped = 'blocked' if phase == 'hold' else 'awaiting_verification' if phase == 'imported' else 'running'
    try: api(cfg, 'status', {'recording': state['recording'], 'state': mapped, 'reason': reason})
    except Exception as exc: print(json.dumps({'recording': state['recording'], 'status_sync_error': type(exc).__name__}))


def find_recording(key):
    if not key.startswith('sessions/'): return None
    parts = key.split('/')
    # Files may be nested, but ownership is the nearest recording folder.
    return next((p for p in reversed(parts[2:-1]) if RECORDING.fullmatch(p)), None)


def discover():
    groups = {}
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=RAW, Prefix='sessions/'):
        for obj in page.get('Contents', []):
            rec = find_recording(obj['Key'])
            if rec and rec not in EXCLUDED:
                groups.setdefault(rec, []).append(obj)
    return groups


def pin_objects(objects):
    def head(obj):
        h = s3.head_object(Bucket=RAW, Key=obj['Key'])
        if h.get('VersionId') in ('null', '', None): raise ValueError('Raw versioning required')
        if h['ETag'] != obj['ETag'] or h['ContentLength'] != obj['Size']:
            raise ValueError('Upload changed during inventory')
        return dict(bucket=RAW, key=obj['Key'], version_id=h['VersionId'], bytes=h['ContentLength'], etag=h['ETag'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        return sorted(pool.map(head, objects), key=lambda r: r['key'])


def metadata(snapshot):
    refs = [o for o in snapshot if o['key'].endswith('/metadata.json')]
    if not refs: raise ValueError('Original metadata missing')
    values = [read_json(r['bucket'], r['key'], r['version_id']) for r in refs]
    if len({r['sha256'] for _, r in values}) != 1: raise ValueError('Conflicting original metadata')
    return values[0][0], [r for _, r in values]


def archive_versions(snapshot):
    # Preserve noncurrent versions of present files too; never resurrect keys whose
    # latest version is a deletion marker.
    keys = {r['key'] for r in snapshot}
    prefixes = {k.rsplit('/', 1)[0]+'/' for k in keys}
    refs = {}
    for prefix in sorted(prefixes):
        for page in s3.get_paginator('list_object_versions').paginate(Bucket=RAW, Prefix=prefix):
            for obj in page.get('Versions', []):
                if obj['Key'] in keys:
                    ref = dict(bucket=RAW, key=obj['Key'], version_id=obj['VersionId'], bytes=obj['Size'], etag=obj['ETag'])
                    refs[obj['Key'], obj['VersionId']] = ref
    if not {(r['key'], r['version_id']) for r in snapshot} <= set(refs):
        raise ValueError('Source version disappeared during archive planning')
    return sorted(refs.values(), key=lambda r: (r['key'], r['version_id']))


def submit(cfg, state, lane, plan, queue, definition):
    existing = state.get('jobs', {}).get(lane)
    if existing and existing.get('job_id'): return existing
    if not existing:
        plan_ref = put_json(ARTIFACTS, 'clean-plans/raw-lifecycle-v1/'+state['recording']+'/'+state['fingerprint']+'/'+lane+'.json', plan, True)
        name = ('raw-life-'+lane+'-'+state['recording']+'-'+state['fingerprint'][:12])[:128]
        existing = {'name': name, 'plan_ref': plan_ref, 'submitted_at': now(), 'queue': queue, 'status': 'SUBMITTING'}
        state.setdefault('jobs', {})[lane] = existing
        save(state)  # A crash from this point must reconcile, never blindly submit.
    else:
        matches = []
        for page in batch.get_paginator('list_jobs').paginate(jobQueue=queue, filters=[{'name':'JOB_NAME','values':[existing['name']]}]):
            matches.extend(page.get('jobSummaryList', []))
        if len(matches) > 1: raise ValueError('Duplicate Batch submissions need reconciliation')
        if matches:
            existing['job_id'], existing['status'] = matches[0]['jobId'], matches[0]['status']
            save(state); return existing
        raise ValueError('Uncertain Batch submission; manual reconciliation required before retry')
    response = batch.submit_job(jobName=existing['name'], jobQueue=queue, jobDefinition=definition,
        containerOverrides={'environment':[{'name':'TASK_PLAN_REF','value':json.dumps(existing['plan_ref'])}]},
        tags={'purpose':'raw-lifecycle-v1', 'recording': state['recording']}, propagateTags=True)
    existing['job_id'], existing['status'] = response['jobId'], 'SUBMITTED'
    save(state)
    return existing


def job_status(job):
    if not job.get('job_id'): return job.get('status', 'UNKNOWN')
    rows = batch.describe_jobs(jobs=[job['job_id']])['jobs']
    if not rows: raise ValueError('Batch job not returned; do not resubmit')
    job['status'] = rows[0]['status']
    job['reason'] = rows[0].get('statusReason', '')
    return job['status']


def conversion_plan(cfg, state, episode):
    meta, _ = metadata(state['snapshot'])
    if meta.get('complete') is not True: raise ValueError('Capture completion not confirmed; source preserved')
    media = [r for r in state['snapshot'] if r['bytes'] > 0 and r['key'].lower().endswith(('.mp4','.h265','.hevc','.egoc'))]
    if not media: raise ValueError('Source media missing')
    if any(r['key'].endswith('.egoc') for r in media):
        raise ValueError('EgoC source requires container extraction plan; archive preserved for recovery')
    if any(r['key'].lower().endswith(('.h265','.hevc')) for r in media):
        raise ValueError('Native HEVC stream requires matching portal inventory support; archive preserved')
    if any(r['key'].endswith(('/left.mp4','/right.mp4')) for r in media):
        raise ValueError('Legacy split source requires measured exposure-grid recovery')
    if len({r['key'].rsplit('/',1)[-1] for r in media}) != len(media):
        raise ValueError('Multiple delivered source sets require deduplication review')
    calibrations = [r for r in state['snapshot'] if r['key'].endswith('/calibration.json')]
    if not calibrations: raise ValueError('Source calibration missing')
    cals = [read_json(r['bucket'],r['key'],r['version_id']) for r in calibrations]
    if len({r['sha256'] for _,r in cals}) != 1: raise ValueError('Conflicting camera calibrations')
    cal, cal_ref = cals[0]
    from ops_calibration import validate_calibration
    mapping = validate_calibration(cal, state['recording'])
    size = cal['image_size']
    layout = {'width': max(v[1] for v in cal['eye_crop_x'].values()), 'height':size[1], 'rotation_degrees':0,
              'provenance':'Version-pinned calibration of the recording camera'}
    for side,sensor in mapping['eye_mapping'].items(): layout[side] = [cal['eye_crop_x'][sensor][0],0,*size]
    validate_calibration(cal,state['recording'],layout)
    if layout['width'] != 4000 or layout['height'] != 1200 or size != [1920,1200]:
        raise ValueError('Camera geometry requires supported extraction runtime')
    return {'schema':'6thsense-raw-conversion/1','task':'raw-lifecycle-v1','recording':state['recording'],
            'kind':'stereo_video','sources':media,'calibration':cal_ref,'layout':layout,
            'metadata_frame_count':meta.get('frame_count'),'source_complete_flag':True}


def supplement_metadata(state, manifest):
    rec = manifest['recordings'][0]
    _, originals = metadata(state['snapshot'])
    ref = originals[0]
    obj = s3.get_object(Bucket=ref['bucket'], Key=ref['key'], VersionId=ref['version_id'])
    raw = obj['Body'].read()
    key = f"clean/{manifest['run_id']}/{state['recording']}/metadata.json"
    try:
        result = s3.put_object(Bucket=PROCESSED,Key=key,Body=raw,ContentType='application/json',Metadata={'sha256':ref['sha256']},IfNoneMatch='*')
        dest = dict(ref,bucket=PROCESSED,key=key,version_id=result['VersionId'])
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ('412','PreconditionFailed'): raise
        _,dest = read_json(PROCESSED,key)
        if dest['sha256'] != ref['sha256']: raise ValueError('Conflicting preserved metadata')
    provenance = {'schema':'6thsense-clean-source-metadata/1','run_id':manifest['run_id'],'recording':state['recording'],
                  'copy_mode':'byte_exact_from_versioned_source','metadata':dest,'source_metadata':originals,
                  'source_media':[source_identity(r) for r in rec['sources']]}
    pkey = key.replace('metadata.json','metadata-provenance.json')
    existing = optional_json(PROCESSED,pkey)
    if existing:
        if existing.get('metadata',{}).get('sha256') != dest['sha256'] or {digest(source_identity(r)) for r in existing['source_media']} != {digest(source_identity(r)) for r in rec['sources']}:
            raise ValueError('Conflicting metadata provenance')
    else: put_json(PROCESSED,pkey,provenance,True)
    _, provenance_ref = read_json(PROCESSED,pkey)
    return provenance_ref


def adopt(state, old_conversion, old_clean):
    name = state['recording']
    media = {digest(source_identity(r)) for r in state['snapshot'] if r['key'].lower().endswith(('.mp4','.h265','.hevc','.egoc'))}
    for lane,control,kind in [('conversion',old_conversion,'conversion'),('clean',old_clean,'clean')]:
        if state.get('jobs', {}).get(lane): continue
        matches = [j for j in control.get('jobs',[]) if j.get('kind') == kind and j.get('recording') == name]
        if matches:
            if len(matches) != 1: raise ValueError('Historical job ambiguity')
            job = matches[0]
            ref = job.get('plan_ref') or job.get('plan')
            plan = read_pinned(ref)
            spec = plan if lane == 'conversion' else plan['conversion_plan']
            if spec['recording'] != name or {digest(source_identity(r)) for r in spec['sources']} != media:
                raise ValueError('Existing job source versions differ from current Raw inventory')
            state.setdefault('jobs',{})[lane] = dict(job,adopted=True)
            if lane == 'conversion': state['conversion_plan'] = spec
            else: state['run_id'] = plan['run_id']; state['clean_plan_ref'] = ref
    outcome = old_clean.get('outcomes',{}).get(name,{})
    reason = outcome.get('reason') if outcome.get('status') == 'hold' else old_clean.get('holds',{}).get(name)
    if reason: state['technical_hold'] = reason


def _source_map(sources, label):
    if not isinstance(sources, list) or not sources:
        raise ValueError(label+' sources are missing')
    mapped = {}
    try:
        for source in sources:
            identity = digest(source_identity(source))
            if identity in mapped: raise ValueError(label+' repeats a source')
            mapped[identity] = source
    except (KeyError, TypeError) as exc:
        raise ValueError(label+' source identity is incomplete') from exc
    return mapped


def _metadata_proof(imported, provenance_ref):
    return {'schema':'6thsense-lifecycle-metadata-proof/1','run_id':imported['run_id'],
            'manifest_key':imported['manifest_key'],'manifest_version':imported['manifest_version'],
            'manifest_sha256':imported['manifest_sha256'],'provenance':provenance_ref}


def verify_metadata_proof(state, manifest, imported):
    proof = state.get('metadata_proof')
    if not isinstance(proof, dict) or proof != _metadata_proof(imported, proof.get('provenance')):
        return False
    provenance = read_pinned(proof['provenance'])
    rec = manifest['recordings'][0]
    if (provenance.get('schema') != '6thsense-clean-source-metadata/1'
            or provenance.get('copy_mode') != 'byte_exact_from_versioned_source'
            or provenance.get('run_id') != manifest['run_id']
            or provenance.get('recording') != state['recording']):
        raise ValueError('Preserved metadata provenance identity mismatch')
    clean_metadata = provenance.get('metadata')
    expected_key = f"clean/{manifest['run_id']}/{state['recording']}/metadata.json"
    if (not isinstance(clean_metadata, dict) or clean_metadata.get('bucket') != PROCESSED
            or clean_metadata.get('key') != expected_key):
        raise ValueError('Preserved metadata reference is outside the Clean recording')
    read_pinned(clean_metadata)
    media = _source_map(provenance.get('source_media'), 'Preserved metadata provenance')
    manifested = _source_map(rec.get('sources'), 'Adopted Clean manifest')
    if set(media) != set(manifested):
        raise ValueError('Preserved metadata belongs to different source media')
    originals = _source_map(provenance.get('source_metadata'), 'Preserved source metadata')
    snapshot = _source_map([r for r in state['snapshot'] if r['key'].endswith('/metadata.json')], 'Raw metadata snapshot')
    if set(originals) != set(snapshot):
        raise ValueError('Preserved metadata belongs to different Raw metadata versions')
    for identity, original in originals.items():
        if (original.get('bytes') != snapshot[identity].get('bytes')
                or original.get('bytes') != clean_metadata.get('bytes')
                or original.get('sha256') != clean_metadata.get('sha256')
                or not re.fullmatch(r'[0-9a-f]{64}', original.get('sha256', ''))):
            raise ValueError('Preserved metadata size or digest differs from durable proof')
    return True


def supplement_adopted_import(state, imports):
    """Repair metadata only after binding a generic import to its adopted job."""
    clean = state.get('jobs', {}).get('clean')
    run = state.get('run_id') or state.get('metadata_proof', {}).get('run_id')
    matches = [row for row in imports if row.get('run_id') == run]
    if len(matches) != 1:
        if not clean or not (state.get('clean_plan_ref') or clean.get('plan_ref')):
            return True  # Preserve imports outside this lifecycle coordinator.
        raise ValueError('Adopted Clean import does not uniquely match its run')
    imported = matches[0]
    if (imported.get('manifest_key') in (None, '')
            or imported.get('manifest_version') in (None, '', 'null')
            or not re.fullmatch(r'[0-9a-f]{64}', imported.get('manifest_sha256', ''))):
        raise ValueError('Adopted Clean import lacks a pinned manifest')
    manifest, actual = read_json(PROCESSED, imported['manifest_key'], imported['manifest_version'])
    if (actual['version_id'] != imported['manifest_version']
            or actual['sha256'] != imported['manifest_sha256']):
        raise ValueError('Adopted Clean import manifest changed')
    recordings = manifest.get('recordings')
    if (manifest.get('run_id') != run or not isinstance(recordings, list)
            or len(recordings) != 1 or recordings[0].get('recording') != state['recording']):
        raise ValueError('Adopted Clean manifest identity mismatch')
    rec = recordings[0]
    manifested = _source_map(rec.get('sources'), 'Adopted Clean manifest')
    recorded = _source_map(imported.get('sources'), 'Portal import')
    if set(recorded) != set(manifested):
        raise ValueError('Adopted Clean sources differ from the portal import')
    if any(recorded[k].get('size_bytes') != source.get('size_bytes')
            or recorded[k].get('sha256') != source.get('sha256')
            for k,source in manifested.items()):
        raise ValueError('Portal import source size or hash differs from the manifest')
    if state.get('metadata_proof'):
        return verify_metadata_proof(state, manifest, imported)
    plan_ref = state.get('clean_plan_ref') or (clean or {}).get('plan_ref')
    if not clean or not plan_ref:
        return True  # Preserve imports outside this lifecycle coordinator.
    if job_status(clean) != 'SUCCEEDED':
        raise ValueError('Lifecycle Clean job is not successful')
    plan = read_pinned(plan_ref)
    conversion = plan.get('conversion_plan')
    if (plan.get('schema') != '6thsense-clean-finalize/1' or plan.get('run_id') != run
            or not isinstance(conversion, dict)
            or conversion.get('recording') != state['recording']):
        raise ValueError('Adopted Clean plan identity mismatch')
    planned = _source_map(conversion.get('sources'), 'Adopted Clean plan')
    snapshot = _source_map([r for r in state['snapshot'] if r['bytes'] > 0 and r['key'].lower().endswith(('.mp4','.h265','.hevc','.egoc'))], 'Raw media snapshot')
    if (set(planned) != set(snapshot)
            or any(planned[k].get('bytes') != snapshot[k].get('bytes') for k in planned)):
        raise ValueError('Adopted Clean plan differs from the Raw state snapshot')
    if set(manifested) != set(planned):
        raise ValueError('Adopted Clean sources differ from the pinned plan')

    receipt_ref = plan.get('conversion_receipt')
    if rec.get('source_provenance', {}).get('conversion_receipt') != receipt_ref:
        raise ValueError('Adopted Clean manifest has different conversion provenance')
    report = read_pinned(receipt_ref)
    if (report.get('schema') != '6thsense-raw-conversion-result/1'
            or report.get('recording') != state['recording']
            or report.get('task') != conversion.get('task')):
        raise ValueError('Adopted Clean conversion receipt identity mismatch')
    converted = _source_map(report.get('sources'), 'Conversion receipt')
    if set(converted) != set(planned):
        raise ValueError('Conversion receipt sources differ from the pinned plan')
    for identity, expected in planned.items():
        result, source, portal = converted[identity], manifested[identity], recorded[identity]
        if (result.get('bytes') != expected.get('bytes')
                or source.get('size_bytes') != expected.get('bytes')
                or portal.get('size_bytes') != source.get('size_bytes')
                or result.get('sha256') != source.get('sha256')
                or portal.get('sha256') != source.get('sha256')
                or not re.fullmatch(r'[0-9a-f]{64}', source.get('sha256', ''))):
            raise ValueError('Adopted Clean source size or hash differs from trusted evidence')
    provenance_ref = supplement_metadata(state, manifest)
    state['metadata_proof'] = _metadata_proof(imported, provenance_ref)
    return verify_metadata_proof(state, manifest, imported)


def validate_retirement_result(state, result):
    expected = {digest(source_identity(r)) for r in state['archive_plan']['objects']}
    actual = [digest(source_identity(r)) for r in result.get('deleted_versions',[])]
    if result.get('schema') != '6thsense-raw-retirement/1' or result.get('retired') is not True or result.get('recording') != state['recording'] or result.get('fingerprint') != state['fingerprint'] or result.get('archive_receipt') != state['archive_receipt'] or len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Retirement audit conflicts with source state')


def restore_retirement(cfg, state):
    if state.get('retirement_started'):
        completed = optional_json(cfg['archive_bucket'], f"retirement/{state['recording']}/{state['fingerprint']}.json")
        if completed:
            validate_retirement_result(state, completed)
            state['retired'] = True; state['retirement'] = completed; save(state)
            return True
    return False


def advance(cfg,state,episode,old_conversion,old_clean):
    if state.get('retired') or restore_retirement(cfg,state): return
    retirement_key = f"retirement/{state['recording']}/{state['fingerprint']}.json"
    if not state.get('archive_plan'):
        versions = archive_versions(state['snapshot'])
        state['archive_plan'] = {'schema':'6thsense-archive-plan/1','recording':state['recording'],
            'fingerprint':state['fingerprint'],'archive_bucket':cfg['archive_bucket'],'objects':versions,
            'receipt_key':f"receipts/{state['recording']}/{state['fingerprint']}.json"}
        save(state)
    if not state.get('archive_receipt'):
        aj = submit(cfg,state,'archive',state['archive_plan'],cfg['cpu_queue'],cfg['archive_definition'])
        astatus = job_status(aj)
        if astatus == 'SUCCEEDED':
            receipt, ref = read_json(cfg['archive_bucket'],state['archive_plan']['receipt_key'])
            if receipt.get('verified') is not True or receipt['fingerprint'] != state['fingerprint']:
                raise ValueError('Archive receipt is not verified for this input')
            state['archive_receipt'] = ref
        elif astatus == 'FAILED': raise ValueError('Archive job failed; Raw preserved')
    adopt(state,old_conversion,old_clean)
    if episode.get('imports'):
        state['imports'] = episode['imports']
        metadata_ready = supplement_adopted_import(state,episode['imports'])
        if not metadata_ready:
            status(cfg,state,'hold','Existing Clean import lacks lifecycle metadata evidence; Raw preserved.')
        else:
            status(cfg,state,'imported','Verified company Clean exists; archive/retirement reconciliation running.')
    elif state.get('technical_hold') or episode.get('attribution_hold'):
        status(cfg,state,'hold',state.get('technical_hold') or episode['attribution_hold'])
    else:
        cj = state.get('jobs',{}).get('conversion')
        if not cj:
            plan = conversion_plan(cfg,state,episode)
            state['conversion_plan'] = plan
            cj = submit(cfg,state,'conversion',plan,cfg['gpu_queue'],cfg['conversion_definition'])
        cstatus = job_status(cj)
        if cstatus == 'FAILED':
            state['technical_hold'] = 'Source conversion failed: '+cj.get('reason','')
            status(cfg,state,'hold',state['technical_hold'])
        elif cstatus == 'SUCCEEDED':
            if not state.get('conversion_plan'):
                ref = cj.get('plan_ref')
                state['conversion_plan'] = read_pinned(ref)
            plan = state['conversion_plan']
            task = plan['task']
            report, receipt_ref = read_json(PROCESSED,f"clean/{task}/staging/{state['recording']}/conversion.json")
            if report.get('schema') != '6thsense-raw-conversion-result/1' or report.get('recording') != state['recording'] or report.get('task') != task:
                raise ValueError('Conversion result identity mismatch')
            expected_sources = {digest(source_identity(r)): r for r in plan['sources']}
            actual_sources = {digest(source_identity(r)): r for r in report['sources']}
            if set(expected_sources) != set(actual_sources) or len(actual_sources) != len(report['sources']):
                raise ValueError('Conversion receipt belongs to different source versions')
            if any(actual_sources[k]['bytes'] != r['bytes'] or not re.fullmatch(r'[0-9a-f]{64}',actual_sources[k].get('sha256','')) for k,r in expected_sources.items()):
                raise ValueError('Conversion source size/hash mismatch')
            if report['timeline']['imu_conflicting_measurements']:
                state['technical_hold'] = 'Conflicting IMU measurements require source recovery'
                status(cfg,state,'hold',state['technical_hold'])
            elif plan['kind'] != 'stereo_video' or plan.get('source_complete_flag') is not True:
                state['technical_hold'] = 'Missing measured source timing or completion evidence'
                status(cfg,state,'hold',state['technical_hold'])
            else:
                clean = state.get('jobs',{}).get('clean')
                if not clean:
                    party = episode.get('counterparty')
                    from ops_regions import clean_region
                    country = party['country'] if party else clean_region({'recordings':[{'sources':state['snapshot']}]})['key']
                    if country not in ('india','korea','china','vietnam'):
                        raise ValueError('Confirmed source country required before Clean import')
                    run = 'raw-clean-auto-'+state['recording'].removeprefix('ego_')+'-'+state['fingerprint'][:10]
                    cp = {'schema':'6thsense-clean-finalize/1','recording':state['recording'],'run_id':run,
                        'conversion_plan':plan,'conversion_receipt':receipt_ref,'country':country,
                        'runtime_sha256':cfg['clean_runtime']['sha256'],'canary':False}
                    if party: cp['counterparty'] = party
                    state['run_id'] = run
                    clean = submit(cfg,state,'clean',cp,cfg['cpu_queue'],cfg['clean_definition'])
                if job_status(clean) == 'SUCCEEDED':
                    run = state['run_id']
                    marker,_ = read_json(PROCESSED,f'qc-results/{run}/_SUCCESS.json')
                    mref = marker['manifest']
                    manifest,actual = read_json(PROCESSED,mref['key'],mref['version_id'])
                    if actual['sha256'] != mref['sha256']: raise ValueError('Manifest hash mismatch')
                    provenance_ref = supplement_metadata(state,manifest)
                    result = api(cfg,'import',{'run_id':run})
                    if result['manifest_sha256'] != mref['sha256']:
                        raise ValueError('Portal import manifest differs from committed Clean result')
                    state['imports'] = [{'run_id':run,'manifest_sha256':result['manifest_sha256'],
                        'manifest_key':mref['key'],'manifest_version':mref['version_id'],'sources':manifest['recordings'][0]['sources']}]
                    state['metadata_proof'] = _metadata_proof(state['imports'][0],provenance_ref)
                    if not verify_metadata_proof(state,manifest,state['imports'][0]):
                        raise ValueError('Clean metadata proof was not durably established')
                    status(cfg,state,'imported','Verified Clean import complete; originals archived before Raw cleanup.')
                elif clean['status'] == 'FAILED':
                    state['technical_hold'] = 'Clean extraction failed: '+clean.get('reason','')
                    status(cfg,state,'hold',state['technical_hold'])
                else: status(cfg,state,'processing','AWS Clean extraction running or queued.')
        else: status(cfg,state,'converting','AWS source conversion running or queued.')
    save(state)
    if state.get('archive_receipt') and state['phase'] == 'imported' and cfg.get('retirement_enabled'):
        if not state.get('retirement_started'):
            state['retirement_started'] = now()
            save(state)
            saved,_ = read_json(PROCESSED,PREFIX+'states/'+state['recording']+'.json')
            if saved != state: raise ValueError('Retirement intent readback mismatch')
        # Dedicated retirement function independently verifies archive and portal.
        response = boto3.client('lambda').invoke(FunctionName=cfg['retirement_function'],InvocationType='RequestResponse',
            Payload=encoded({'recording':state['recording'],'fingerprint':state['fingerprint']}))
        result = json.load(response['Payload'])
        if response.get('FunctionError'): raise ValueError('Retirement verification failed')
        if result.get('retired'):
            validate_retirement_result(state,result)
            put_json(cfg['archive_bucket'],retirement_key,result,True)
            state['retired'] = True; state['retirement'] = result; save(state)


def handler(event,context):
    cfg,_ = read_json(ARTIFACTS,os.environ.get('CONFIG_KEY','raw-lifecycle/v1/config.json'))
    if not cfg.get('enabled'): return {'enabled':False}
    if time.time() >= cfg['run_deadline_epoch']:
        return {'paused':'run spending window expired; no new work submitted'}
    inventory = api(cfg,'inventory')
    episodes = {e['recording']:e for e in inventory['episodes']}
    old_conversion = optional_json(PROCESSED,'conversion-staging/raw-h265-all-20260915/_CONTROL.json') or {}
    old_clean = optional_json(PROCESSED,'clean/raw-clean-finalize-20260915/_CONTROL.json') or {}
    groups = discover()
    summary = {'checked_at':now(),'recordings':len(groups),'advanced':0,'holds':[]}
    # A bounded number of active records per tick prevents Lambda timeouts. Rotate
    # oldest states first so a large backlog cannot starve later recordings.
    candidates=[]
    for rec,objects in groups.items():
        ep=episodes.get(rec)
        if not ep or ep['deleted'] or rec in EXCLUDED: continue
        if max(o['LastModified'].timestamp() for o in objects) > time.time()-cfg.get('settle_seconds',600): continue
        state=optional_json(PROCESSED,PREFIX+'states/'+rec+'.json')
        candidates.append((state.get('updated_at','') if state else '',rec,objects,state,ep))
    # A crash after the last delete must not strand an unfinished retirement just
    # because the recording is no longer discoverable in temporary Raw storage.
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=PROCESSED,Prefix=PREFIX+'states/'):
        for obj in page.get('Contents',[]):
            rec=obj['Key'].rsplit('/',1)[-1].removesuffix('.json')
            ep=episodes.get(rec)
            if rec in groups or not ep or ep['deleted'] or rec in EXCLUDED: continue
            state=optional_json(PROCESSED,obj['Key'])
            if state and state.get('retirement_started') and not state.get('retired'):
                candidates.append((state.get('updated_at',''),rec,[],state,ep))
    for _,rec,objects,state,ep in sorted(candidates):
        if context and context.get_remaining_time_in_millis() < 90000: break
        try:
            if state and not state.get('retired') and restore_retirement(cfg,state) and not objects:
                summary['advanced']+=1
                continue
            snapshot=pin_objects(objects); fingerprint=digest([source_identity(r) for r in snapshot])
            if state and state.get('retirement_started') and not state.get('retired'):
                archived={digest(source_identity(r)):r for r in state['archive_plan']['objects']}
                if any(digest(source_identity(r)) not in archived or any(r[k] != archived[digest(source_identity(r))][k] for k in ('bytes','etag')) for r in snapshot):
                    raise ValueError('New source arrived during retirement; review before cleanup')
            elif not state or state['fingerprint'] != fingerprint:
                if state and not state.get('retired') and ep.get('imports'):
                    raise ValueError('New source versions arrived during processing; review before supersession')
                if state and state.get('jobs') and not state.get('retired'):
                    archive_only = not ep.get('imports') and set(state['jobs']) == {'archive'} and not state.get('retirement_started')
                    if not archive_only:
                        raise ValueError('New source versions arrived during processing; review before supersession')
                    current={digest(source_identity(r)):r for r in snapshot}
                    if any(digest(source_identity(r)) not in current or any(r[k] != current[digest(source_identity(r))][k] for k in ('bytes','etag')) for r in state['snapshot']):
                        raise ValueError('New source versions arrived during processing; review before supersession')
                    if job_status(state['jobs']['archive']) not in ('SUCCEEDED','FAILED'):
                        raise ValueError('Updated upload waits for its earlier archive job to finish')
                previous=state.get('fingerprint') if state else None
                state={'recording':rec,'fingerprint':fingerprint,'snapshot':snapshot,'phase':'observed','observed_at':now(),'jobs':{},'supersedes_fingerprint':previous}
                save(state)
                continue  # Observe the same source set on two separate ticks.
            advance(cfg,state,ep,old_conversion,old_clean)
            summary['advanced']+=1
        except Exception as exc:
            traceback.print_exc()
            reason=str(exc)[:300] if isinstance(exc,ValueError) else type(exc).__name__
            summary['holds'].append({'recording':rec,'reason':reason})
            if state: status(cfg,state,'hold',reason)
    put_json(PROCESSED,PREFIX+'status.json',summary)
    print(json.dumps(summary))
    return summary
