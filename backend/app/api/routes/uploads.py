"""Contributor-account authenticated multipart control plane."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core import uploads
from app.core.contributor_auth import contributor_identity
from app.core.db import get_session
from app.core.limiter import limiter
from app.models import UploadBatch, Wearer
from app.schemas.uploads import BatchIn, CompleteIn, PartsIn, MAX_FILES, MAX_FILE_BYTES

logger = logging.getLogger(__name__)


def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'


router = APIRouter(tags=['uploads'], dependencies=[Depends(private_response)])


@router.get('/api/uploads/info')
@limiter.limit('60/minute')
async def info(request: Request, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    account = await uploads.authenticate(identity, db)
    wearer = await db.get(Wearer, account.wearer_id)
    batches = (await db.execute(select(UploadBatch).where(UploadBatch.subject == account.subject)
                               .order_by(UploadBatch.created_at.desc()).limit(100))).scalars()
    return {'name': wearer.name, 'remaining_bytes': (await uploads.allowance(db, account))[0],
            'max_files': MAX_FILES, 'max_file_bytes': MAX_FILE_BYTES,
            'batches': [{'id': b.id, 'recording': b.recording, 'bytes': b.total_bytes,
                         'complete': b.completed_at is not None} for b in batches]}


@router.post('/api/uploads/batches')
@limiter.limit('30/minute')
async def create_batch(body: BatchIn, request: Request, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    account = await uploads.authenticate(identity, db)
    return await uploads.create_batch(db, account, body)


async def file_action(identity, db, batch_id, file_id, action, body=None):
    account = await uploads.authenticate(identity, db)
    batch = await uploads.batch_for(db, account, batch_id)
    file = await uploads.file_for(db, batch, file_id)
    try:
        return await action(db, batch, file, body) if body is not None else await action(db, batch, file)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        logger.error('browser_upload_storage_error', extra={'upload_batch': batch.id, 'error_type': type(exc).__name__})
        raise HTTPException(503, 'Storage could not finish this request. Retry to resume; keep your original files.') from exc


@router.post('/api/uploads/batches/{batch_id}/files/{file_id}/start')
@limiter.limit('300/minute')
async def start_file(batch_id: str, file_id: str, request: Request, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    return await file_action(identity, db, batch_id, file_id, uploads.start_file)


@router.post('/api/uploads/batches/{batch_id}/files/{file_id}/parts')
@limiter.limit('300/minute')
async def parts(batch_id: str, file_id: str, body: PartsIn, request: Request, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    return await file_action(identity, db, batch_id, file_id, uploads.prepare_parts, body)


@router.post('/api/uploads/batches/{batch_id}/files/{file_id}/complete')
@limiter.limit('300/minute')
async def complete_file(batch_id: str, file_id: str, body: CompleteIn, request: Request, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    return await file_action(identity, db, batch_id, file_id, uploads.complete_file, body)


@router.post('/api/uploads/batches/{batch_id}/complete')
@limiter.limit('30/minute')
async def complete_batch(batch_id: str, request: Request, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    account = await uploads.authenticate(identity, db)
    batch = await uploads.batch_for(db, account, batch_id, lock=True)
    try:
        return await uploads.complete_batch(db, account, batch)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        logger.error('browser_upload_finalization_error', extra={'upload_batch': batch.id, 'error_type': type(exc).__name__})
        raise HTTPException(503, 'Delivery could not be confirmed. Retry to finish; keep your original files.') from exc
