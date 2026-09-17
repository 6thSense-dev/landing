"""Worker claims are leased and fenced; completion must reference committed QC evidence."""

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from app.api.routes.ops import require_ops, _state
from app.core.db import get_session
from app.core.contributor_deletion import lock as deletion_lock, ensure_wearer_active
from app.models import ProcessingJob, CleanRun, Episode
from app.core.ops_artifacts import REQUIREMENT, validate_artifacts
from app.core.ops_clean import validate_manifest
from app.core.ops_sources import source_registry, business_source


async def source_party(db, episode):
    try:
        party = business_source(episode, await source_registry(db)) if episode else None
    except ValueError as exc:
        raise HTTPException(409, "Source business attribution must be reconciled.") from exc
    if not episode or episode.deleted_at or (not episode.wearer_id and not party):
        raise HTTPException(409, "Source is removed or contributor/business attribution is unresolved.")
    if episode.wearer_id is not None:
        await ensure_wearer_active(db, episode.wearer_id)
    return party

router = APIRouter(prefix="/api/ops/processing", tags=["ops"])


def worker_auth(authorization: str = Header(default="")):
    expected = os.getenv("OPS_PROCESSOR_TOKEN", "")
    if not expected or not secrets.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(403, "Worker authentication required.")


@router.post("/claim")
async def claim(_=Depends(worker_auth), db=Depends(get_session)):
    await deletion_lock(db)
    now = datetime.now(timezone.utc)
    await db.execute(text("SELECT pg_advisory_xact_lock(61306132)"))
    jobs = (
        await db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.state.in_(["queued", "recovering", "retry", "running"])
            )
            .order_by(ProcessingJob.updated_at)
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    for j in jobs:
        if json.loads(j.input_json).get('upload_source_conflict'):
            j.state, j.reason = 'blocked', 'Conflicting upload locations require source review before processing.'
            j.lease_token = j.lease_until = None
            continue
        episode = (
            await db.execute(select(Episode).where(Episode.recording == j.recording))
        ).scalar_one_or_none()
        try:
            party = await source_party(db, episode)
        except HTTPException as exc:
            j.state = "blocked"
            j.reason = exc.detail
            continue
        if j.lease_until and j.lease_until > now:
            continue
        if j.attempts >= 3:
            j.state = "blocked"
            j.reason = "Worker retry limit reached."
            continue
        j.state = "running"
        j.attempts += 1
        j.lease_token = str(uuid.uuid4())
        j.lease_until = now + timedelta(minutes=30)
        await db.commit()
        return {
            "job": {
                "recording": j.recording,
                "fingerprint": j.fingerprint,
                "lease_token": j.lease_token,
                "input": json.loads(j.input_json),
                "output_requirement": REQUIREMENT,
                "counterparty": party,
                "lease_until": j.lease_until.isoformat(),
            }
        }
    await db.commit()
    return {"job": None}


class ResultIn(BaseModel):
    recording: str
    fingerprint: str
    lease_token: str
    outcome: str
    reason: str = Field(default="", max_length=2000)
    run_id: str | None = None


@router.post("/result")
async def result(body: ResultIn, _=Depends(worker_auth), db=Depends(get_session)):
    await deletion_lock(db)
    j = await db.get(ProcessingJob, body.recording, with_for_update=True)
    now = datetime.now(timezone.utc)
    if (
        not j
        or json.loads(j.input_json).get('upload_source_conflict')
        or j.fingerprint != body.fingerprint
        or j.lease_token != body.lease_token
        or not j.lease_until
        or j.lease_until <= now
    ):
        raise HTTPException(409, "Worker lease expired or source changed.")
    episode = (
        await db.execute(select(Episode).where(Episode.recording == body.recording))
    ).scalar_one_or_none()
    party = await source_party(db, episode)
    if body.outcome == "heartbeat":
        j.lease_until = now + timedelta(minutes=30)
    elif body.outcome == "completed":
        run = await db.get(CleanRun, body.run_id) if body.run_id else None
        if not run or body.recording not in {
            r["recording"] for r in json.loads(run.manifest_json)["recordings"]
        }:
            raise HTTPException(
                409,
                "Import and verify committed clean output before completing the job.",
            )
        try:
            doc = json.loads(run.manifest_json)
            validate_manifest(doc)
            validate_artifacts(doc)
            if doc.get("counterparty") != party or (party and (run.wearer_id is not None or run.rate_krw_hour is not None)):
                raise ValueError("Clean result does not match source commercial attribution")
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(409, "Worker completion requires verified stereo videos, IMU, full frame sequences and a shared timeline.") from exc
        # A clean run with the same episode name alone is insufficient. Scan reconciliation
        # verifies receipts for the current input fingerprint before removing Raw backlog.
        j.state = "awaiting_verification"
        j.reason = "QC output imported; awaiting exact source receipt reconciliation."
        j.result_run_id = run.run_id
        j.lease_until = None
    elif body.outcome in ("irrecoverable", "retry", "blocked"):
        if not body.reason.strip():
            raise HTTPException(422, "A diagnosis is required.")
        j.state = "rejected" if body.outcome == "irrecoverable" else body.outcome
        j.reason = body.reason
        j.lease_until = None
    else:
        raise HTTPException(422, "Invalid outcome.")
    await db.commit()
    return {"ok": True}


@router.post("/{recording}/retry")
async def retry(recording: str, _=Depends(require_ops), db=Depends(get_session)):
    await deletion_lock(db)
    j = await db.get(ProcessingJob, recording, with_for_update=True)
    if not j:
        raise HTTPException(404, "Scan the bucket first.")
    if json.loads(j.input_json).get('upload_source_conflict'):
        raise HTTPException(409, 'Resolve conflicting upload locations and rescan before retrying.')
    episode = (
        await db.execute(select(Episode).where(Episode.recording == recording))
    ).scalar_one_or_none()
    if not episode or episode.deleted_at:
        raise HTTPException(409, "An operator-removed source cannot be retried.")
    if episode.wearer_id is not None:
        await ensure_wearer_active(db, episode.wearer_id)
    if j.state in ("running", "clean"):
        raise HTTPException(409, "This job cannot be retried in its current state.")
    j.state = "retry"
    j.reason = "Operator requested revalidation."
    j.attempts = 0
    j.lease_token = None
    j.lease_until = None
    await db.commit()
    return await _state(db)
