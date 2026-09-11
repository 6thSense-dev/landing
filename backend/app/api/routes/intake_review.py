"""Internal synthetic review, using existing Catalog validators and session identity.

No writes, S3 access, accounting mutation, or arbitrary file paths. Enabling the
feature does not give a role to anyone: it additionally requires Ronak's existing
active authenticated admin account.
"""
from pathlib import Path
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.core.auth_deps import current_user
from app.models import User
from app.vendor.intake.workbench import parse, project_activity, export_revision

router = APIRouter(prefix="/api/ops/intake-review", tags=["internal-intake-review"])
FIXTURE = Path(__file__).resolve().parents[2] / "intake_fixture"
MAX_REQUEST = 65536
NO_STORE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def permitted(user: User) -> bool:
    return (
        os.environ.get("INTAKE_REVIEW_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        and user.is_active and user.role == "admin"
        and user.email == "ronak@6thsense.dev"
    )


async def require_review(user: User = Depends(current_user)) -> User:
    if not permitted(user):
        raise HTTPException(403, "Internal review is unavailable.", headers=NO_STORE)
    return user


def document():
    return parse((FIXTURE / "cohort.json").read_bytes())["activity"]


def json_response(value, *, attachment=False):
    headers = dict(NO_STORE)
    if attachment:
        headers["Content-Disposition"] = 'attachment; filename="synthetic-activity-proposal.json"'
    # Preserve native integer nanoseconds in the downloaded text. Do not round
    # a native artifact through JavaScript JSON.parse/stringify.
    return Response(json.dumps(value, ensure_ascii=False), media_type="application/json", headers=headers)


@router.get("/capability")
async def capability(user: User = Depends(current_user)):
    return json_response({"enabled": bool(permitted(user))})


@router.get("/activity")
async def activity(user: User = Depends(require_review)):
    return json_response(project_activity(document()))


@router.get("/preview")
async def preview(user: User = Depends(require_review)):
    return FileResponse(FIXTURE / "preview.webm", media_type="video/webm", headers=NO_STORE)


@router.post("/proposal")
async def proposal(request: Request, user: User = Depends(require_review)):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "JSON required.", headers=NO_STORE)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST:
            raise HTTPException(413, "Proposal too large.", headers=NO_STORE)
    try:
        payload = parse(bytes(body))
        if not isinstance(payload, dict) or "reviewer_id" in payload:
            raise ValueError("reviewer identity is supplied by the authenticated session")
        payload["reviewer_id"] = user.email
        result = export_revision(document(), payload)
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError) as exc:
        raise HTTPException(409, "Invalid or stale proposal: " + str(exc)[:180], headers=NO_STORE)
    return json_response(result, attachment=True)
