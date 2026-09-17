"""Transactional browser uploads; uploaded-by is distinct from filmed-by."""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from app.models import (ContributorAccount, ContributorDeletion, Episode, UploadBatch,
                        UploadFile, UploadPart, Wearer, ContributorCameraClaim)
from app.core import upload_storage as storage
from app.schemas.uploads import PART_BYTES, MAX_BATCH_BYTES


def now():
    return datetime.now(timezone.utc)


def enabled():
    if os.getenv('OPS_BROWSER_UPLOAD_ENABLED') != 'true':
        raise HTTPException(503, 'Participant uploads are not available yet. Please contact 6thSense.')


async def ensure_wearer(db, wearer_id):
    wearer = await db.get(Wearer, wearer_id)
    deleted = (await db.execute(select(ContributorDeletion.subject).join(
        ContributorAccount, ContributorAccount.subject == ContributorDeletion.subject
    ).where(ContributorAccount.wearer_id == wearer_id).limit(1))).scalar_one_or_none()
    if not wearer or not wearer.is_active or deleted:
        raise HTTPException(410, 'This contributor is not currently enabled for uploads.')
    return wearer


async def authenticate(identity, db):
    from app.api.routes.contributor import account_for, has_consent
    enabled()
    account = await account_for(identity, db)
    if not await has_consent(account, identity['region'], db, verified_phone=identity.get('verified_phone')):
        raise HTTPException(403, 'consent_required')
    # A returned camera may still have undelivered SD-card footage. Historical
    # claims allow delivery; complete_batch enforces its capture-time ownership.
    claims = (await db.execute(select(ContributorCameraClaim).where(
        ContributorCameraClaim.subject == account.subject,
        ContributorCameraClaim.status == 'approved',
        ContributorCameraClaim.effective_at <= now()))).scalars().all()
    if not claims:
        raise HTTPException(403, 'camera_approval_required')
    return account


async def allowance(db, account):
    used, count = (await db.execute(select(func.coalesce(func.sum(UploadBatch.total_bytes), 0),
        func.count()).where(UploadBatch.subject == account.subject,
                           UploadBatch.created_at >= now() - timedelta(hours=24)))).one()
    return max(0, MAX_BATCH_BYTES - used), count


async def batch_for(db, account, batch_id, *, lock=False):
    query = select(UploadBatch).where(UploadBatch.id == batch_id, UploadBatch.subject == account.subject)
    if lock:
        query = query.with_for_update()
    batch = (await db.execute(query)).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, 'Upload not found.')
    return batch


async def file_for(db, batch, file_id):
    file = (await db.execute(select(UploadFile).where(
        UploadFile.id == file_id, UploadFile.batch_id == batch.id).with_for_update())).scalar_one_or_none()
    if not file:
        raise HTTPException(404, 'File not found.')
    return file


async def files_for(db, batch):
    return list((await db.execute(select(UploadFile).where(UploadFile.batch_id == batch.id)
                                 .order_by(UploadFile.path))).scalars())


def batch_json(batch, files):
    return {'id': batch.id, 'recording': batch.recording, 'total_bytes': batch.total_bytes,
            'complete': batch.completed_at is not None,
            'files': [{'id': f.id, 'path': f.path, 'size': f.size,
                       'complete': f.completed_at is not None} for f in files]}


async def create_batch(db, account, body):
    # Same lock as Raw attribution/import: no second request can reserve the
    # same recording, resurrect a deletion or race an account's byte allowance.
    await db.execute(text('SELECT pg_advisory_xact_lock(61306130)'))
    existing = (await db.execute(select(UploadBatch).where(UploadBatch.recording == body.recording))).scalar_one_or_none()
    if existing:
        if existing.subject != account.subject or existing.manifest_hash != body.digest():
            raise HTTPException(409, 'This episode was already registered with different files or another contributor account.')
        return batch_json(existing, await files_for(db, existing))
    if (await db.execute(select(Episode.id).where(Episode.recording == body.recording))).scalar_one_or_none():
        raise HTTPException(409, 'This episode is already in the ledger. Existing or deleted episodes cannot be uploaded again.')
    device = body.recording.split('_')[3].upper()
    # This reserves transport, not attribution. An ended claim must later pass
    # the full historical capture-interval check before Raw receives the episode.
    claim = (await db.execute(select(ContributorCameraClaim.id).where(
        ContributorCameraClaim.subject == account.subject,
        ContributorCameraClaim.status == 'approved',
        ContributorCameraClaim.effective_at <= now(),
        ContributorCameraClaim.device_id == device).limit(1))).scalar_one_or_none()
    if not claim:
        raise HTTPException(403, 'This camera is not approved for your account. Contact 6thSense.')
    total = sum(f.size for f in body.files)
    remaining, count = await allowance(db, account)
    if total > remaining or count >= 500:
        raise HTTPException(409, 'Your 24-hour upload allowance has been reached. Resume existing uploads or try again later.')
    batch = UploadBatch(id=uuid4().hex, subject=account.subject, wearer_id=account.wearer_id,
                        recording=body.recording, manifest_hash=body.digest(), total_bytes=total)
    db.add(batch)
    await db.flush()
    files = [UploadFile(id=uuid4().hex, batch_id=batch.id, **f.model_dump()) for f in body.files]
    db.add_all(files)
    await db.commit()
    return batch_json(batch, files)


async def parts_for(db, file):
    return list((await db.execute(select(UploadPart).where(UploadPart.file_id == file.id)
                                 .order_by(UploadPart.number))).scalars())


def mark_file(file, receipt):
    file.version_id, file.etag = receipt['VersionId'], receipt['ETag']
    file.completed_at = now()


async def start_file(db, batch, file):
    if not file.completed_at:
        existing = await asyncio.to_thread(storage.head, batch, file)
        if existing:
            mark_file(file, existing)
        else:
            if file.upload_id and not await asyncio.to_thread(storage.upload_exists, batch, file):
                # S3 lifecycle may have removed an abandoned multipart upload.
                # Restart only this unfinished file; completed objects stay put.
                file.upload_id = None
                await db.execute(delete(UploadPart).where(UploadPart.file_id == file.id))
            if not file.upload_id:
                file.upload_id = await asyncio.to_thread(storage.initiate, batch, file)
    await db.commit()
    parts = await parts_for(db, file)
    return {'complete': file.completed_at is not None, 'part_bytes': PART_BYTES,
            'received': [{'number': p.number, 'etag': p.etag, 'checksum': p.checksum} for p in parts if p.etag]}


def acknowledge(parts, received):
    by_number = {p.number: p for p in parts}
    for entry in received:
        part = by_number.get(entry.number)
        if part is None:
            raise HTTPException(409, 'This part was not registered for upload.')
        etag = '"' + entry.etag.strip('"').lower() + '"'
        if part.etag and part.etag != etag:
            raise HTTPException(409, 'Part receipt changed. Reselect the original files.')
        part.etag = etag


async def prepare_parts(db, batch, file, body):
    if file.completed_at:
        return {'complete': True, 'parts': []}
    if not file.upload_id:
        raise HTTPException(409, 'Start this file before requesting upload parts.')
    existing = await parts_for(db, file)
    acknowledge(existing, body.received)
    indexed = {p.number: p for p in existing}
    signed = []
    for item in body.parts:
        storage.part_size(file, item.number)
        part = indexed.get(item.number)
        if part and part.checksum != item.checksum:
            raise HTTPException(409, 'The selected file differs from the original upload. Select the original episode folder.')
        if not part:
            part = UploadPart(file_id=file.id, number=item.number, checksum=item.checksum)
            indexed[part.number] = part
            db.add(part)
        signed.append({'number': part.number, 'checksum': part.checksum,
                       'etag': part.etag, 'url': None if part.etag else storage.presign(batch, file, part)})
    await db.commit()
    return {'complete': False, 'parts': signed}


async def complete_file(db, batch, file, body):
    if file.completed_at:
        return {'complete': True}
    parts = await parts_for(db, file)
    acknowledge(parts, body.received)
    if ([p.number for p in parts] != list(range(1, storage.part_count(file) + 1))
            or any(not p.etag for p in parts)):
        raise HTTPException(409, 'Some file parts have not finished uploading.')
    # Persist our own S3-returned ETags before completion. We do not construct
    # CompleteMultipartUpload from a listing of arbitrary remote parts.
    await db.flush()
    receipt = await asyncio.to_thread(storage.complete, batch, file, parts)
    mark_file(file, receipt)
    await db.commit()
    return {'complete': True}


async def complete_batch(db, account, batch):
    if batch.completed_at:
        return {'complete': True, 'recording': batch.recording}
    files = await files_for(db, batch)
    if any(not f.completed_at for f in files):
        raise HTTPException(409, 'Some files have not finished uploading.')
    # Verify every immutable object version before exposing an episode to Raw.
    for offset in range(0, len(files), 8):
        heads = await asyncio.gather(*(asyncio.to_thread(storage.head, batch, f) for f in files[offset:offset+8]))
        if any(h is None for h in heads):
            raise HTTPException(409, 'A stored file is missing. Keep your originals and contact 6thSense.')
    meta = await asyncio.to_thread(storage.metadata, batch, next(f for f in files if f.path == 'metadata.json'))
    from app.core.contributor_deletion import lock as deletion_lock
    await deletion_lock(db)
    await db.execute(text('SELECT pg_advisory_xact_lock(61306130)'))
    await ensure_wearer(db, account.wearer_id)
    episode = (await db.execute(select(Episode).where(Episode.recording == batch.recording))).scalar_one_or_none()
    if episode and (episode.deleted_at or episode.prefix != storage.prefix(batch)):
        raise HTTPException(409, 'This episode already exists or was removed. Contact 6thSense.')
    if not episode:
        from app.core.ops_scan import facts_from
        from app.core.contributor_attribution import owner_at_capture
        take = {'session': 'web-' + batch.id, 'prefix': storage.prefix(batch), 'meta': meta,
                'recording': batch.recording, 'meta_key': storage.prefix(batch) + 'metadata.json',
                'uploaded': now(), 'bytes': batch.total_bytes, 'files': len(files)}
        # Attribute by the verified capture interval, exactly as Raw import does.
        # The signed-in uploader is separate and never grants footage approval.
        facts = facts_from(take)
        owner = await owner_at_capture(db, facts)
        active_claim = (await db.execute(select(ContributorCameraClaim.id).where(
            ContributorCameraClaim.subject == account.subject,
            ContributorCameraClaim.device_id == batch.recording.split('_')[3].upper(),
            ContributorCameraClaim.status == 'approved',
            ContributorCameraClaim.effective_at <= now(),
            ContributorCameraClaim.ended_at.is_(None)).limit(1))).scalar_one_or_none()
        if not active_claim and owner != account.wearer_id:
            raise HTTPException(409, 'This camera assignment has ended. Capture time must match your approved assignment. Keep your files and contact 6thSense.')
        db.add(Episode(recording=batch.recording, wearer_id=owner, **facts))
    await asyncio.to_thread(storage.publish_receipt, batch, files)
    batch.completed_at = now()
    await db.commit()
    return {'complete': True, 'recording': batch.recording}


async def upload_sources(db):
    # Registration commits identity before any bytes arrive. If S3 publishes
    # the receipt but the final DB commit is lost, Raw may recover the episode;
    # its exact prefix still identifies the durable uploader without a retry.
    rows = (await db.execute(select(UploadBatch, Wearer).join(
        Wearer, UploadBatch.wearer_id == Wearer.id))).all()
    return {b.recording: {'wearer_id': w.id, 'name': w.name, 'prefix': storage.prefix(b),
                          'received_at': b.completed_at.isoformat() if b.completed_at else None} for b, w in rows}
