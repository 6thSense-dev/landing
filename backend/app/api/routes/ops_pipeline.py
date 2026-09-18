"""Authenticated cloud coordinator bridge. Never approves reviews or sends money."""
import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from app.core.db import get_session
from app.core.ops_clean import _committed_result, clean_bucket
from app.core.ops_artifacts import validate_artifacts
from app.core.ops_regions import REGIONS, clean_region
from app.core.ops_s3 import _client, get_settings
from app.core.ops_scan import parse_key, walk_bucket
from app.core.ops_sources import business_source, source_registry
from app.models import CleanRun, Episode, OpsSetting, ProcessingJob, Wearer

router = APIRouter(prefix='/api/ops/pipeline', tags=['ops'])


def authorize(authorization: str = Header(default='')):
    token = os.getenv('OPS_PIPELINE_TOKEN', '')
    if not token or not secrets.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(403, 'Pipeline authentication required.')


@router.get('/inventory', dependencies=[Depends(authorize)])
async def inventory(db=Depends(get_session)):
    from app.core.contributor_deletion import pending_wearers
    held_wearers = await pending_wearers(db)
    registry = await source_registry(db)
    episodes = (await db.execute(select(Episode))).scalars().all()
    runs = (await db.execute(select(CleanRun))).scalars().all()
    imported = {}
    for run in runs:
        doc = json.loads(run.manifest_json)
        for rec in doc['recordings']:
            imported.setdefault(rec['recording'], []).append({
                'run_id': run.run_id, 'manifest_sha256': run.manifest_sha256,
                'manifest_key': run.manifest_key, 'manifest_version': run.manifest_version,
                'sources': rec.get('sources', []), 'country': doc.get('country'),
            })
    rows = []
    for ep in episodes:
        try:
            party = business_source(ep, registry)
            reason = '' if party or ep.wearer_id else 'Contributor or business attribution required'
        except ValueError as exc:
            party, reason = None, str(exc)
        if ep.wearer_id in held_wearers:
            reason = 'Contributor account deletion requested.'
        rows.append({'recording': ep.recording, 'device_id': ep.device_id,
                     'session': ep.session, 'prefix': ep.prefix,
                     'deleted': bool(ep.deleted_at), 'counterparty': party,
                     'wearer_id': ep.wearer_id, 'attribution_hold': reason,
                     'paid': ep.paid, 'imports': imported.get(ep.recording, [])})
    return {'episodes': rows}


@router.get('/sieve-customer-inventory', dependencies=[Depends(authorize)])
async def sieve_customer_inventory(recording: str | None = None, db=Depends(get_session)):
    """Current Clean eligibility, checked again by cloud workers before upload.

    Uses the same source-alias and residential exclusion rules as inheritance.
    No bearer, personal names, payment state or customer acceptance is returned.
    """
    from app.core import ops_sieve
    from app.core.contributor_deletion import pending_wearers
    held = await pending_wearers(db)
    episodes = {e.recording: e for e in (await db.execute(select(Episode))).scalars()}
    runs = {r.run_id: r for r in (await db.execute(select(CleanRun))).scalars()}
    saved = await ops_sieve.saved_state(db)
    rows = []
    for row in await ops_sieve.inventory(db):
        if recording is not None and row['recording'] != recording:
            continue
        episode, run = episodes.get(row['recording']), runs[row['run_id']]
        if ((episode and (episode.deleted_at or episode.wearer_id in held))
                or run.wearer_id in held):
            continue
        inherited = saved.get('recordings', {}).get(row['recording'], {})
        if inherited.get('status') != 'inherited' or inherited.get('revision') != row['revision']:
            continue
        operator = episode.wearer_id if episode and episode.wearer_id else run.wearer_id
        rows.append({k: row[k] for k in ('recording', 'run_id', 'revision', 'manifest_sha256',
                    'manifest_key', 'manifest_version', 'camera', 'country', 'retained_seconds')} | {
            'entity_id': row['entity']['id'],
            'operator_key': f'wearer:{operator}' if operator else None,
            'inheritance_receipt': inherited['receipt'],
            'source_sha256': sorted(s['sha256'] for s in row['rec']['sources']),
        })
    return {'schema': '6thsense-sieve-customer-inventory/1',
            'checked_at': datetime.now(timezone.utc).isoformat(), 'recordings': rows}


def verified_result(run_id):
    s3 = _client(get_settings())
    doc, key, version, digest = _committed_result(s3, f'qc-results/{run_id}/_SUCCESS.json')
    validate_artifacts(doc)
    if len(doc['recordings']) != 1:
        raise ValueError('Automatic imports require one recording per run')
    rec = doc['recordings'][0]
    _metadata, provenance, _body, provenance_ref = _metadata_evidence(s3, doc)
    evidence = {'provenance': provenance_ref, 'metadata': provenance['metadata'],
                'source_metadata': provenance['source_metadata']}
    return doc, key, version, digest, evidence


def _read(s3, ref, *, limit=4 * 1024**2):
    if not isinstance(ref, dict) or any(ref.get(k) in (None, '', 'null') for k in ('bucket', 'key', 'version_id')):
        raise ValueError('Version-pinned object reference required')
    args = {'Bucket': ref['bucket'], 'Key': ref['key'], 'VersionId': ref['version_id']}
    obj = s3.get_object(**args)
    if obj['ContentLength'] > limit:
        obj['Body'].close()
        raise ValueError('Referenced document exceeds limit')
    raw = obj['Body'].read()
    if obj.get('VersionId') != ref['version_id']:
        raise ValueError('Referenced object version changed')
    if 'bytes' in ref and (type(ref['bytes']) is not int or len(raw) != ref['bytes']):
        raise ValueError('Referenced object size changed')
    if not isinstance(ref.get('sha256'), str) or hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('Referenced object digest changed')
    return raw


def _metadata_evidence(s3, doc):
    rec = doc['recordings'][0]
    base = f"clean/{doc['run_id']}/{rec['recording']}/"
    obj = s3.get_object(Bucket=clean_bucket(), Key=base + 'metadata-provenance.json')
    if obj['ContentLength'] > 4 * 1024**2:
        obj['Body'].close()
        raise ValueError('Metadata provenance exceeds limit')
    raw = obj['Body'].read()
    provenance_version = obj.get('VersionId')
    if provenance_version in (None, '', 'null'):
        raise ValueError('Metadata provenance must be versioned')
    provenance_ref = {'bucket': clean_bucket(), 'key': base + 'metadata-provenance.json',
                      'version_id': provenance_version, 'sha256': hashlib.sha256(raw).hexdigest(),
                      'bytes': len(raw)}
    provenance = json.loads(raw)
    if (provenance.get('run_id') != doc['run_id']
            or provenance.get('recording') != rec['recording']):
        raise ValueError('Original metadata provenance identity mismatch')
    expected = [(s['bucket'], s['key'], s['version_id']) for s in rec['sources']]
    media = provenance.get('source_media')
    if not isinstance(media, list):
        raise ValueError('Original metadata source media are missing')
    try:
        actual = [(s['bucket'], s['key'], s['version_id']) for s in media]
    except (KeyError, TypeError) as exc:
        raise ValueError('Original metadata source media are incomplete') from exc
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError('Original metadata is bound to different source media')
    ref = provenance.get('metadata')
    if not isinstance(ref, dict) or ref.get('bucket') != clean_bucket() or ref.get('key') != base + 'metadata.json':
        raise ValueError('Original metadata is outside the Clean recording')
    body = _read(s3, ref)
    try:
        metadata = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('Original metadata is not JSON') from exc
    if not isinstance(metadata, dict):
        raise ValueError('Original metadata must be an object')
    if provenance.get('schema') == '6thsense-clean-source-metadata/2':
        from app.core.ops_reconstructed_metadata import validate_reconstructed
        validate_reconstructed(metadata,provenance,rec,ref)
        return metadata,provenance,body,provenance_ref
    if (provenance.get('schema') != '6thsense-clean-source-metadata/1'
            or provenance.get('copy_mode') != 'byte_exact_from_versioned_source'
            or metadata.get('metadata_origin') == 'reconstructed'
            or rec.get('source_provenance',{}).get('metadata_recovery') is not None):
        raise ValueError('Original metadata provenance identity mismatch')
    originals = provenance.get('source_metadata')
    if not isinstance(originals, list) or not originals:
        raise ValueError('Original metadata source references are missing')
    for source in originals:
        if (not isinstance(source, dict) or source.get('sha256') != ref.get('sha256')
                or source.get('bytes') != ref.get('bytes')):
            raise ValueError('Original metadata was modified or conflicting')
    return metadata, provenance, body, provenance_ref


def _validate_recovery_source(s3, rec, metadata, metadata_body, provenance, report, take):
    """Read the immutable authorization and conversion evidence before import."""
    recovery = provenance['reconstruction']
    auth = json.loads(_read(s3,recovery['authorization']))
    if (take.get('meta_key') or auth.get('schema')!='6thsense-source-metadata-recovery/1'
            or auth.get('recording')!=rec['recording'] or auth.get('device_id')!=metadata['device_id']
            or auth.get('scope')!='available_source_only' or auth.get('capture_completeness')!='unknown'
            or not auth.get('basis') or auth.get('calibration')!=rec['calibration_source']
            or not auth.get('calibration_applicability',{}).get('basis')
            or auth['calibration_applicability']!=metadata['calibration_provenance'].get('applicability')):
        raise ValueError('Reconstruction authorization or original-metadata availability changed')
    expected = {(r['bucket'],r['key'],r['version_id']):(r['size_bytes'],r['sha256']) for r in rec['sources']}
    sources = auth.get('sources',[])
    if len(sources)!=len(expected):
        raise ValueError('Reconstruction authorization source count differs')
    seen = set()
    for source in sources:
        key = tuple(source.get(k) for k in ('bucket','key','version_id'))
        if (key in seen or key not in expected or source.get('bytes')!=expected[key][0]
                or source.get('sha256') not in (None,expected[key][1])):
            raise ValueError('Reconstruction authorization source identity differs')
        seen.add(key)
    ref = recovery['metadata']
    if (report.get('metadata_recovery_ref')!=recovery['authorization']
            or report.get('reconstructed_metadata')!=ref
            or [r for r in report.get('outputs',[]) if r.get('key','').endswith('/metadata.json')]!=[ref]
            or report.get('calibration_source')!=rec['calibration_source']
            or report.get('source_complete_flag') is not None
            or report.get('metadata_frame_count') is not None
            or report.get('frames_absent_against_capture_metadata') is not None
            or report.get('decoded_frame_count')!=metadata['frame_count']
            or report.get('sensor_decoder')!='native_luma/1'
            or _read(s3,ref)!=metadata_body):
        raise ValueError('Reconstructed metadata differs from the conversion evidence')
    timeline = report['timeline']
    sensor_fields = ('sensor_clock','imu_samples','imu_units','unreadable_sensor_frames',
                     'imu_conflicting_measurements','sensor_discontinuities','maximum_imu_gap_us')
    duration_fields = ('video_clock','chunk_join','recovered_chunk_display_clock')
    layout = rec['media']['layout']
    if (metadata.get('available_video_duration_us')!=timeline.get('duration_us')
            or metadata.get('sensor_observations')!={k:timeline[k] for k in sensor_fields}
            or metadata.get('duration_basis')!={k:timeline[k] for k in duration_fields}
            or metadata.get('image_size')!=[layout['width'],layout['height']]):
        raise ValueError('Reconstructed observations differ from conversion measurements')


def _validate_country(doc, party):
    if party:
        if doc.get('counterparty') != party or doc.get('country') != party['country']:
            raise ValueError('Business attribution or country differs from confirmed source')
        return
    region = clean_region(doc)
    if region['key'] not in REGIONS or doc.get('country') != region['key']:
        raise ValueError('Source country is missing, conflicting, or differs from the Clean result')


def _validate_new_source(doc, episode):
    """Bind a new import to current Raw objects and the worker's full-hash receipt."""
    rec = doc['recordings'][0]
    takes = walk_bucket(prefix=f'sessions/{episode.session}/')
    take = takes.get(episode.recording)
    if not take or take.get('session') != episode.session:
        raise ValueError('Current Raw inventory does not contain the confirmed recording')
    prefixes = set(take.get('prefixes', []))
    current_media = {m['key']: m for m in take.get('media', []) if m.get('bytes', 0) > 0}
    sources = rec.get('sources', [])
    if {s['key'] for s in sources} != set(current_media):
        raise ValueError('Clean sources do not exactly cover the current Raw media inventory')

    s3 = _client(get_settings())
    metadata, provenance, metadata_body, _provenance_ref = _metadata_evidence(s3, doc)
    receipt_ref = rec.get('source_provenance', {}).get('conversion_receipt')
    expected_suffix = f"/staging/{episode.recording}/conversion.json"
    if (not isinstance(receipt_ref, dict) or receipt_ref.get('bucket') != clean_bucket()
            or not str(receipt_ref.get('key', '')).startswith('clean/')
            or not str(receipt_ref.get('key', '')).endswith(expected_suffix)):
        raise ValueError('Pinned conversion receipt is required')
    report = json.loads(_read(s3, receipt_ref))
    reconstructed = provenance.get('schema') == '6thsense-clean-source-metadata/2'
    if (report.get('schema') != '6thsense-raw-conversion-result/1'
            or report.get('recording') != episode.recording
            or report.get('status') != 'converted_staging'
            or (not reconstructed and report.get('source_complete_flag') is not True)):
        raise ValueError('Conversion receipt identity mismatch')
    if reconstructed:
        _validate_recovery_source(s3,rec,metadata,metadata_body,provenance,report,take)
    trusted = {}
    for source in report.get('sources', []):
        try:
            identity = (source['bucket'], source['key'], source['version_id'])
        except (KeyError, TypeError) as exc:
            raise ValueError('Conversion receipt source is incomplete') from exc
        if identity in trusted:
            raise ValueError('Conversion receipt repeats a source')
        trusted[identity] = source

    cfg = get_settings()
    for source in sources:
        hit = parse_key(source['key'])
        if (source.get('bucket') != cfg.bucket or not hit
                or hit[0] != episode.session or hit[1] != episode.recording
                or hit[2] + '/' not in prefixes):
            raise ValueError('Clean source is outside the confirmed Raw delivery')
        listed = current_media[source['key']]
        if listed.get('bytes') != source.get('size_bytes'):
            raise ValueError('Clean source size differs from current Raw inventory')
        identity = (source['bucket'], source['key'], source['version_id'])
        receipt_source = trusted.get(identity)
        if (not receipt_source or receipt_source.get('sha256') != source.get('sha256')
                or receipt_source.get('bytes') != source.get('size_bytes')):
            raise ValueError('Clean source hash is not established by the conversion receipt')
        pinned = s3.head_object(Bucket=source['bucket'], Key=source['key'], VersionId=source['version_id'])
        current = s3.head_object(Bucket=source['bucket'], Key=source['key'])
        if (pinned.get('VersionId') != source['version_id']
                or current.get('VersionId') != source['version_id']
                or pinned.get('ContentLength') != source['size_bytes']
                or current.get('ContentLength') != source['size_bytes']):
            raise ValueError('Pinned Clean source is not the current Raw object')

    for source in provenance['source_metadata']:
        hit = parse_key(source.get('key', ''))
        if (source.get('bucket') != cfg.bucket or not hit
                or hit[0] != episode.session or hit[1] != episode.recording
                or hit[2] + '/' not in prefixes or source['key'].rsplit('/', 1)[-1] != 'metadata.json'):
            raise ValueError('Original metadata is outside the confirmed Raw delivery')
        if _read(s3, source) != metadata_body:
            raise ValueError('Clean metadata is not a byte-exact copy of Raw metadata')
        current = s3.head_object(Bucket=source['bucket'], Key=source['key'])
        if (current.get('VersionId') != source['version_id']
                or current.get('ContentLength') != source['bytes']):
            raise ValueError('Pinned metadata is not the current Raw object')
    if metadata.get('device_id') and str(metadata['device_id']).upper().removeprefix('EGO-') != doc['device_id']:
        raise ValueError('Original metadata identifies a different camera')


class ImportIn(BaseModel):
    run_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,120}$')


@router.post('/import', dependencies=[Depends(authorize)])
async def import_result(body: ImportIn, db=Depends(get_session)):
    try:
        doc, key, version, digest, metadata_evidence = await asyncio.to_thread(verified_result, body.run_id)
    except Exception as exc:
        raise HTTPException(409, f'Clean verification failed: {type(exc).__name__}') from exc
    rec = doc['recordings'][0]
    from app.core.contributor_deletion import lock as deletion_lock, ensure_wearer_active
    await deletion_lock(db)
    await db.execute(text('SELECT pg_advisory_xact_lock(61306130)'))
    ep = (await db.execute(select(Episode).where(Episode.recording == rec['recording']).with_for_update())).scalar_one_or_none()
    if not ep or ep.deleted_at:
        raise HTTPException(409, 'Source is missing or operator-deleted')
    source_job = await db.get(ProcessingJob, ep.recording)
    if source_job and json.loads(source_job.input_json).get('upload_source_conflict'):
        raise HTTPException(409, 'Resolve conflicting upload locations and rescan before importing Clean.')
    if ep.wearer_id is not None:
        await ensure_wearer_active(db, ep.wearer_id)
    if ep.device_id.strip().upper().removeprefix('EGO-') != doc['device_id']:
        raise HTTPException(409, 'Source camera differs from the confirmed recording')
    try:
        party = business_source(ep, await source_registry(db))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        _validate_country(doc, party)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    owner = None if party else ep.wearer_id
    if not party and not owner:
        raise HTTPException(409, 'Confirmed source contributor required')
    audit_key = 'pipeline_import_' + hashlib.sha256(body.run_id.encode()).hexdigest()[:40]
    existing = await db.get(CleanRun, body.run_id)
    if existing:
        audit = await db.get(OpsSetting, audit_key)
        try:
            recorded = json.loads(audit.value) if audit else None
        except (json.JSONDecodeError, TypeError):
            recorded = None
        if (existing.manifest_key != key or existing.manifest_version != version
                or existing.manifest_sha256 != digest or existing.wearer_id != owner
                or not recorded or recorded.get('metadata_evidence') != metadata_evidence):
            raise HTTPException(409, 'Previously imported result or attribution changed')
        return {'status': 'imported', 'run_id': body.run_id, 'manifest_sha256': digest, 'already_imported': True}
    source_hashes = {s['sha256'] for s in rec['sources']}
    for run in (await db.execute(select(CleanRun))).scalars():
        for other in json.loads(run.manifest_json)['recordings']:
            if other['recording'] == rec['recording'] or source_hashes & {s['sha256'] for s in other.get('sources', [])}:
                raise HTTPException(409, 'Recording or source footage already imported; supersession needs review')
    try:
        await asyncio.to_thread(_validate_new_source, doc, ep)
    except Exception as exc:
        raise HTTPException(409, f'Source verification failed: {type(exc).__name__}') from exc
    person = await db.get(Wearer, owner) if owner else None
    if owner and (not person or not person.is_active):
        raise HTTPException(409, 'Contributor is inactive or missing')
    run = CleanRun(run_id=body.run_id, device_id=doc['device_id'], wearer_id=owner,
                   manifest_key=key, manifest_version=version, manifest_sha256=digest,
                   manifest_json=json.dumps(doc), retained_seconds=doc['retained_seconds'],
                   rejected_seconds=doc['rejected_seconds'], rate_krw_hour=person.rate_krw_hour if person else None,
                   paid=ep.paid, paid_at=ep.paid_at, amount_krw=(ep.amount_krw if ep.paid and not party else None))
    db.add(run)
    # Keep the existing cash/payment ledger intact; record exactly what was carried.
    db.add(OpsSetting(key=audit_key, value=json.dumps({'run_id': body.run_id, 'recording': ep.recording,
        'manifest_sha256': digest, 'paid_preserved': ep.paid, 'paid_at': ep.paid_at.isoformat() if ep.paid_at else None,
        'amount_krw': run.amount_krw, 'metadata_evidence': metadata_evidence,
        'imported_at': datetime.now(timezone.utc).isoformat()})))
    job = await db.get(ProcessingJob, ep.recording)
    if job:
        job.state = 'awaiting_verification'
        job.reason = 'Cloud pipeline imported verified Clean; source receipts awaiting reconciliation.'
        job.result_run_id = body.run_id
        job.lease_until = None
    await db.commit()
    return {'status': 'imported', 'run_id': body.run_id, 'manifest_sha256': digest, 'already_imported': False}


class StatusIn(BaseModel):
    recording: str = Field(max_length=200)
    state: str = Field(pattern=r'^(queued|running|blocked|awaiting_verification|waiting_upload)$')
    reason: str = Field(max_length=2000)


@router.post('/status', dependencies=[Depends(authorize)])
async def update_status(body: StatusIn, db=Depends(get_session)):
    from app.core.contributor_deletion import lock as deletion_lock, ensure_wearer_active
    await deletion_lock(db)
    ep = (await db.execute(select(Episode).where(Episode.recording == body.recording))).scalar_one_or_none()
    if not ep or ep.deleted_at:
        raise HTTPException(409, 'Source missing or operator-deleted')
    if ep.wearer_id is not None:
        await ensure_wearer_active(db, ep.wearer_id)
    job = await db.get(ProcessingJob, body.recording, with_for_update=True)
    if job:
        if json.loads(job.input_json).get('upload_source_conflict'):
            raise HTTPException(409, 'Resolve conflicting upload locations and rescan before updating processing.')
        if job.state == 'clean':
            return {'updated': False}
        job.state, job.reason = body.state, body.reason
    await db.commit()
    return {'updated': bool(job)}
