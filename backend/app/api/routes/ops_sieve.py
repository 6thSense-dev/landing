"""Temporary, ops-only view of Clean inheritance into Sieve."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.ops import require_ops
from app.core.db import get_session
from app.core import ops_pipeline_progress, ops_sieve
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
