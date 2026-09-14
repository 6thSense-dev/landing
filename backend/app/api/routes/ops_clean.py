"""Ops-only clean footage and camera attribution. Review and payment use separate ledgers."""
import asyncio
import json
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.ops import require_ops, _wearer_json, _setting, _put_setting
from app.core.db import get_session
from app.core.ops_clean import committed_results, estimate_krw, playback
from app.core.ops_collections import COLLECTIONS_KEY, validate_collection, collection_playback
from app.models import CleanRun, OpsCamera, Episode, Wearer, User

router = APIRouter(prefix='/api/ops/clean', tags=['ops'])


async def viewing_collections(db, runs):
    valid, errors = [], 0
    try:
        configured = json.loads(await _setting(db, COLLECTIONS_KEY) or '[]')
        if not isinstance(configured, list):
            raise ValueError('Invalid collection configuration')
    except (ValueError, TypeError):
        return [], 1
    seen = set()
    for doc in configured:
        try:
            validate_collection(doc, runs)
            if doc['collection_id'] in seen:
                raise ValueError('Duplicate collection')
            seen.add(doc['collection_id'])
            valid.append(doc)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            errors += 1
    return valid, errors


async def state(db):
    runs = (await db.execute(select(CleanRun).order_by(CleanRun.created_at.desc()))).scalars().all()
    wearers = (await db.execute(select(Wearer).order_by(Wearer.name))).scalars().all()
    cameras = (await db.execute(select(OpsCamera).order_by(OpsCamera.device_id))).scalars().all()
    rows = []
    for run in runs:
        doc = json.loads(run.manifest_json)
        rows.append({'run_id': run.run_id, 'device_id': run.device_id, 'wearer_id': run.wearer_id,
                     'retained_seconds': run.retained_seconds, 'rejected_seconds': run.rejected_seconds,
                     'source_seconds': doc['source_seconds'], 'recording_count': len(doc['recordings']),
                     'rate_krw_hour': run.rate_krw_hour, 'estimated_krw': estimate_krw(run.retained_seconds, run.rate_krw_hour),
                     'paid': run.paid, 'amount_krw': run.amount_krw,
                     'policy': doc.get('policy', {}), 'warnings': doc.get('warnings', []),
                     'review_intervals': doc.get('review_intervals', []),
                     'recordings': [{'recording': r['recording'], 'source_seconds': r.get('source_seconds', 0),
                                     'retained_seconds': sum(i['end_s'] - i['start_s'] for i in r.get('intervals', []) if i['disposition'] == 'keep'),
                                     'status': r.get('status', 'completed')} for r in doc['recordings']]})
    collections, collection_errors = await viewing_collections(db, runs)
    from app.core.ops_ledger import footage_ledger
    return {'ledger': await footage_ledger(db), 'runs': rows, 'collections': [{k: c[k] for k in ('collection_id', 'wearer_id', 'label', 'retained_seconds', 'source_runs', 'recordings')} for c in collections],
            'scan_errors': json.loads(await _setting(db, 'clean_scan_errors') or '[]'), 'collection_errors': collection_errors, 'wearers': [_wearer_json(w) for w in wearers],
            'cameras': [{'device_id': c.device_id, 'wearer_id': c.wearer_id} for c in cameras]}


@router.get('/state')
async def get_state(_: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    return await state(db)


class CameraIn(BaseModel):
    device_id: str = Field(min_length=6, max_length=32)
    wearer_id: int
    assign_unassigned_recordings: bool = False


@router.post('/cameras')
async def assign_camera(body: CameraIn, _: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    device = body.device_id.strip().upper().removeprefix('EGO-')
    if not re.fullmatch(r'[A-F0-9]{6}', device):
        raise HTTPException(422, 'Enter a six-character camera ID, for example EGO-ABC123.')
    await db.execute(text('SELECT pg_advisory_xact_lock(61306130)'))
    wearer = await db.get(Wearer, body.wearer_id)
    if wearer is None or not wearer.is_active:
        raise HTTPException(404, 'Unknown active contributor.')
    camera = await db.get(OpsCamera, device)
    if camera is None:
        db.add(OpsCamera(device_id=device, wearer_id=wearer.id))
    else:
        camera.wearer_id = wearer.id
    if body.assign_unassigned_recordings:
        normalized = func.replace(func.upper(func.trim(Episode.device_id)), 'EGO-', '')
        same_camera = or_(normalized == device, and_(func.coalesce(normalized, '') == '', func.upper(func.right(Episode.recording, 7)) == '_' + device))
        episodes = (await db.execute(select(Episode).where(same_camera, Episode.wearer_id.is_(None), Episode.paid.is_(False), Episode.deleted_at.is_(None)).with_for_update())).scalars().all()
        for episode in episodes:
            episode.wearer_id = wearer.id
    # Previously imported clean collections keep their original attribution and rate.
    await db.commit()
    return await state(db)


@router.post('/scan')
async def scan(_: User = Depends(require_ops), db: AsyncSession = Depends(get_session), skip_invalid: bool = False):
    try:
        results = await asyncio.to_thread(committed_results)
    except Exception as exc:
        raise HTTPException(502, f'Clean results could not be verified ({type(exc).__name__}).') from exc
    # Serialize import/overlap checks across operators and requests.
    await db.execute(text('SELECT pg_advisory_xact_lock(61306130)'))
    existing = (await db.execute(select(CleanRun))).scalars().all()
    by_id = {r.run_id: r for r in existing}
    used = {rec['recording'] for run in existing for rec in json.loads(run.manifest_json)['recordings'] if rec.get('source_seconds', 0) > 0}
    used_hashes = {s['sha256'] for run in existing for rec in json.loads(run.manifest_json)['recordings'] for s in rec.get('sources', [])}
    errors = list(getattr(results, 'errors', []))
    added = 0
    for doc, key, version, digest in results:
        try:
            if doc['run_id'] in by_id:
                if by_id[doc['run_id']].manifest_sha256 != digest:
                    raise HTTPException(409, 'An existing QC run changed; its earnings were not replaced.')
                continue
            names = {r['recording'] for r in doc['recordings'] if r.get('source_seconds', 0) > 0}
            hashes = {s['sha256'] for r in doc['recordings'] for s in r.get('sources', [])}
            if names & used or hashes & used_hashes:
                raise HTTPException(409, 'These recordings already have a clean result. Review supersession before importing another payable run.')
            paid_raw = (await db.execute(select(Episode.recording).where(Episode.recording.in_(names), Episode.paid.is_(True)))).scalars().all()
            if paid_raw:
                raise HTTPException(409, 'Some source recordings are already paid in the raw ledger. Reconcile those payments before importing an unpaid estimate.')
            camera = await db.get(OpsCamera, doc['device_id'])
            # An existing recording's contributor wins over today's camera holder.
            owners = set((await db.execute(select(Episode.wearer_id).where(Episode.recording.in_(names), Episode.wearer_id.is_not(None)))).scalars())
            if len(owners) > 1:
                raise HTTPException(409, 'This QC batch contains multiple contributors; split the batch before importing.')
            owner = next(iter(owners)) if owners else camera.wearer_id if camera else None
            wearer = await db.get(Wearer, owner) if owner else None
            if wearer is None or not wearer.is_active:
                raise HTTPException(409, f"Assign EGO-{doc['device_id']} to a contributor before importing clean footage.")
            imported_run = CleanRun(run_id=doc['run_id'], device_id=doc['device_id'], wearer_id=wearer.id,
                            manifest_key=key, manifest_version=version, manifest_sha256=digest,
                            manifest_json=json.dumps(doc), retained_seconds=doc['retained_seconds'],
                            rejected_seconds=doc['rejected_seconds'], rate_krw_hour=wearer.rate_krw_hour)
            db.add(imported_run)
            by_id[doc['run_id']] = imported_run
            used |= names
            used_hashes |= hashes
            added += 1
        except HTTPException as exc:
            if not skip_invalid:
                raise
            errors.append({'run_id': doc['run_id'], 'error': str(exc.detail)})
    await _put_setting(db, 'clean_scan_errors', json.dumps(errors))
    await db.commit()
    return {**await state(db), 'imported': added, 'scan_errors': errors}


@router.get('/runs/{run_id}/files')
async def files(run_id: str, _: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    run = await db.get(CleanRun, run_id)
    if run is None:
        raise HTTPException(404, 'Unknown clean run.')
    try:
        return {'files': await asyncio.to_thread(playback, json.loads(run.manifest_json))}
    except Exception as exc:
        raise HTTPException(502, 'Clean playback is temporarily unavailable.') from exc


@router.get('/collections/{collection_id}/files')
async def collection_files(collection_id: str, _: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    runs = (await db.execute(select(CleanRun))).scalars().all()
    collections, _errors = await viewing_collections(db, runs)
    doc = next((c for c in collections if c['collection_id'] == collection_id), None)
    if doc is None:
        raise HTTPException(404, 'This viewing collection is unavailable or its source results changed.')
    try:
        return {'files': await asyncio.to_thread(collection_playback, doc)}
    except Exception as exc:
        raise HTTPException(502, 'Combined playback is temporarily unavailable.') from exc
