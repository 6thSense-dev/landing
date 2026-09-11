"""GET-only learning views. Same person, explicit role projection, no impersonation."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth_deps import current_user
from app.core.workspace_access import workspace_enabled, workspace_owner
from app.core.catalog_redact import CATALOG_ROLES
from app.core.db import get_session
from app.models import User
from app.api.routes import catalog, ops

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

@router.get("/capability")
async def capability(user: User = Depends(current_user)):
    return JSONResponse({"enabled": workspace_enabled(user)}, headers={"Cache-Control": "private, no-store"})


def catalog_role(role: str) -> str:
    if role not in CATALOG_ROLES:
        raise HTTPException(status_code=404, detail="No catalog for this role.")
    return role


@router.get("/catalog/{role}")
async def manifest(role: str, request: Request, user: User = Depends(workspace_owner)):
    return await catalog.manifest_for_role(request, user, catalog_role(role), f"/api/workspace/catalog/{role}")


@router.get("/catalog/{role}/clips/{clip_id}")
async def clip(role: str, clip_id: str, request: Request, user: User = Depends(workspace_owner)):
    return await catalog.clip_for_role(clip_id, request, user, catalog_role(role), f"/api/workspace/catalog/{role}")


@router.get("/ops/state")
async def ops_state(user: User = Depends(workspace_owner), db: AsyncSession = Depends(get_session)):
    return JSONResponse(await ops.get_state(user, db), headers={"Cache-Control": "private, no-store"})


@router.get("/ops/episodes/{recording}/files")
async def ops_files(recording: str, user: User = Depends(workspace_owner), db: AsyncSession = Depends(get_session)):
    return JSONResponse(await ops.list_episode_files(recording, user, db), headers={"Cache-Control": "private, no-store"})
