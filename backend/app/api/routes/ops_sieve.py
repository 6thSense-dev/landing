"""Temporary, ops-only view of Clean inheritance into Sieve."""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Response
from botocore.exceptions import BotoCoreError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.ops import require_ops
from app.core.db import get_session
from app.core import ops_pipeline_progress, ops_sieve, ops_sieve_episode
from app.models import User

router = APIRouter(prefix='/api/ops/sieve', tags=['ops'])


@router.get('/availability')
async def availability(_: User = Depends(require_ops)):
    return ops_sieve.availability()


@router.get('/state')
async def state(_: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    schedule = ops_sieve.availability()
    if not schedule['visible']:
        raise HTTPException(410, 'The temporary Sieve dashboard ended September 25.')
    return {**ops_sieve.summarize(await ops_sieve.inventory(db), await ops_sieve.saved_state(db)), **schedule}


@router.get('/pipeline')
async def pipeline(_: User = Depends(require_ops)):
    return await ops_pipeline_progress.pipeline_progress()


@router.get('/episodes/{recording}')
async def episode(recording: str, response: Response, _: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    response.headers['Cache-Control'] = 'private, no-store'
    if not ops_sieve.availability()['visible']:
        raise HTTPException(410, 'The temporary Sieve dashboard ended September 25.')
    rows = {r['recording']: r for r in await ops_sieve.inventory(db)}
    row = rows.get(recording)
    if not row:
        raise HTTPException(404, 'Episode is not in the active Sieve collection.')
    cached = (await ops_sieve.saved_state(db)).get('recordings', {}).get(recording, {})
    if cached.get('status') != 'inherited' or cached.get('revision') != row['revision']:
        raise HTTPException(409, 'This episode is awaiting a verified Sieve copy. Refresh after the next copy check.')
    try:
        def read():
            return ops_sieve_episode.preview(ops_sieve.storage_client(bounded=True), row, cached)
        result = await asyncio.wait_for(asyncio.to_thread(read), timeout=30)
    except (TimeoutError, BotoCoreError, ops_sieve.ClientError):
        raise HTTPException(503, 'Episode storage is unavailable. Please retry.') from None
    except (ValueError, KeyError, TypeError, AttributeError):
        logging.getLogger(__name__).warning('Sieve episode verification failed for %s', recording)
        raise HTTPException(409, 'Episode artifacts could not be verified. Refresh the collection and retry.') from None
    # Do not issue URLs after deletion, supersession, or attribution changes while reading S3.
    db.expire_all()
    current = {r['recording']: r for r in await ops_sieve.inventory(db)}.get(recording)
    if not current or current['revision'] != row['revision']:
        raise HTTPException(409, 'Episode changed while loading. Refresh the collection.')
    return result
