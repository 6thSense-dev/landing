"""Remove only archived Raw versions after independently verified Clean import.

Dedicated Lambda/role: no Batch submission, no archive mutation. New uploads are
never deleted by key; only the exact versions in a verified archive receipt.
"""
import json
import os
import time
from botocore.exceptions import ClientError
import coordinator as c


def validate_receipt(state, receipt):
    if receipt.get('schema') != '6thsense-archive-receipt/1' or receipt.get('verified') is not True:
        raise ValueError('Verified archive receipt required')
    if receipt.get('recording') != state['recording'] or receipt.get('fingerprint') != state['fingerprint']:
        raise ValueError('Archive receipt belongs to another source set')
    expected = {c.digest(c.source_identity(r)):r for r in state['archive_plan']['objects']}
    actual = {}
    for item in receipt['objects']:
        src,dst = item['source'],item['destination']
        identity = c.digest(c.source_identity(src))
        if identity in actual: raise ValueError('Duplicate archive source identity')
        if src['bucket'] != c.RAW or src['key'] not in {r['key'] for r in state['snapshot']}:
            raise ValueError('Archive source is outside authorized recording inventory')
        if identity not in expected or src['bytes'] != expected[identity]['bytes'] or src['etag'] != expected[identity]['etag']:
            raise ValueError('Archived source differs from pinned inventory')
        if dst['bucket'] != state['archive_plan']['archive_bucket'] or dst['sha256'] != src['sha256'] or dst['bytes'] != src['bytes']:
            raise ValueError('Archive destination differs from source')
        if dst.get('version_id') in (None,'','null'): raise ValueError('Archive destination is not versioned')
        actual[identity] = item
    if set(actual) != set(expected): raise ValueError('Incomplete archive inventory')
    return actual


def validate_imports(state, receipt, episode):
    if episode.get('deleted'): raise ValueError('Operator-deleted recording cannot be retired by this flow')
    imports = episode.get('imports',[])
    if not imports: raise ValueError('Portal has not imported verified Clean')
    imported_sets = [{(s['sha256'], s.get('size_bytes',s.get('bytes'))) for s in r['sources']} for r in imports]
    archived = {c.digest(c.source_identity(x['source'])):x['source'] for x in receipt['objects']}
    # Empty terminal camera placeholders contain no frames to import. They still
    # participate in the complete archive receipt and all pre-deletion checks.
    media = [r for r in state['snapshot'] if r['bytes'] > 0 and r['key'].lower().endswith(('.mp4','.mov','.m4v','.webm','.h265','.hevc','.egoc'))]
    if not media: raise ValueError('No source media to reconcile')
    current = {(archived[c.digest(c.source_identity(ref))]['sha256'], ref['bytes']) for ref in media}
    if not any(current <= hashes for hashes in imported_sets):
        raise ValueError('Some Raw media is not represented by one imported Clean run; originals retained')


def handler(event, context):
    cfg,_=c.read_json(c.ARTIFACTS,os.environ.get('CONFIG_KEY','raw-lifecycle/v1/config.json'))
    dry_run=event.get('dry_run') is True
    if not cfg.get('enabled') or (not cfg.get('retirement_enabled') and not dry_run) or time.time() >= cfg['run_deadline_epoch']: return {'retired':False,'reason':'disabled'}
    rec=event['recording']
    if not c.RECORDING.fullmatch(rec) or rec in c.EXCLUDED: raise ValueError('Invalid or deleted recording')
    state,_=c.read_json(c.PROCESSED,c.PREFIX+'states/'+rec+'.json')
    if state['fingerprint'] != event['fingerprint'] or state['phase'] != 'imported':
        raise ValueError('Source changed or not imported')
    ref=state['archive_receipt']
    receipt,actual=c.read_json(ref['bucket'],ref['key'],ref['version_id'])
    if actual['sha256'] != ref['sha256']: raise ValueError('Archive receipt digest mismatch')
    entries=validate_receipt(state,receipt)
    episode=next((e for e in c.api(cfg,'inventory')['episodes'] if e['recording']==rec),None)
    if not episode: raise ValueError('Portal source missing')
    validate_imports(state,receipt,episode)
    for job in state.get('jobs',{}).values():
        if c.job_status(job) not in ('SUCCEEDED','FAILED'):
            raise ValueError('An existing worker still needs the Raw sources')
    # Verify every archived file version before touching a single Raw version.
    for item in entries.values():
        dst=item['destination']
        h=c.s3.head_object(Bucket=dst['bucket'],Key=dst['key'],VersionId=dst['version_id'])
        if h['ContentLength'] != dst['bytes'] or h.get('Metadata',{}).get('source-sha256') != dst['sha256']:
            raise ValueError('Archive object is missing or changed')
    known_keys={r['key'] for r in state['snapshot']}
    if any(obj['Key'] not in known_keys for obj in c.discover().get(rec, [])):
        raise ValueError('New Raw key arrived; cleanup deferred until it is archived and verified')
    # A new current upload is not in this authorized snapshot. Abort cleanup so
    # the next coordinator observation can reconcile it without losing context.
    for ref in state['snapshot']:
        try: head=c.s3.head_object(Bucket=c.RAW,Key=ref['key'])
        except ClientError as exc:
            if exc.response['Error']['Code'] in c.MISSING: continue  # resumed partial retirement
            raise
        versions={x['source']['version_id'] for x in entries.values() if x['source']['key']==ref['key']}
        if head['VersionId'] not in versions: raise ValueError('New upload arrived; Raw cleanup deferred')
    deleted=[]
    if dry_run:
        return {'retired':False,'verified':True,'recording':rec,'fingerprint':state['fingerprint'],
                'archive_receipt':state['archive_receipt'],'versions_verified':len(entries),'dry_run':True}
    for item in entries.values():
        src=item['source']
        c.s3.delete_object(Bucket=c.RAW,Key=src['key'],VersionId=src['version_id'])
        deleted.append(c.source_identity(src))
    for ref in deleted:
        try: c.s3.head_object(Bucket=c.RAW,Key=ref['key'],VersionId=ref['version_id'])
        except ClientError as exc:
            if exc.response['Error']['Code'] in c.MISSING or exc.response['Error']['Code']=='NoSuchVersion': continue
            raise
        raise ValueError('Raw version removal not verified')
    result={'schema':'6thsense-raw-retirement/1','recording':rec,'fingerprint':state['fingerprint'],
            'retired':True,'archive_receipt':state['archive_receipt'],
            'deleted_versions':deleted,'verified_at':c.now(),'clean_runs':[r['run_id'] for r in episode['imports']]}
    # Coordinator owns publication; this function has no archive write permission.
    return result
