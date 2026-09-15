"""Staff supervision for mobile enrollment. Existing Ops authentication and CSRF apply."""
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.ops import require_ops, _put_setting
from app.api.routes.contributor import AGREEMENTS, RECORDS_BUCKET, has_consent
from app.core.contributor_auth import REGIONS
from app.core.db import get_session
from app.models import ContributorAccount, ContributorCameraClaim, ContributorConsent, ContributorRecipientAttempt, OpsCamera, OpsSetting, User, Wearer

router = APIRouter(prefix="/api/ops/contributors", tags=["ops"])


class RecipientResolutionIn(BaseModel):
    resolution: Literal["found", "not_created"]
    recipient_id: int | None = Field(default=None, gt=0)
    verified_owner: bool = False
    confirmed_not_created: bool = False
    note: str = Field(min_length=10, max_length=500)


@router.post("/recipients/{attempt_id}/resolve")
async def resolve_recipient(attempt_id: str, body: RecipientResolutionIn,
                            operator: User = Depends(require_ops),
                            db: AsyncSession = Depends(get_session)):
    """Reconcile provider evidence; linking a payout recipient is a separate approval."""
    note = body.note.strip()
    if len(note) < 10:
        raise HTTPException(422, "Record the verification evidence without bank details.")
    if body.resolution == "found":
        if not body.recipient_id or not body.verified_owner or body.confirmed_not_created:
            raise HTTPException(422, "Verify that the found recipient belongs to this contributor.")
    elif body.recipient_id is not None or not body.confirmed_not_created:
        raise HTTPException(422, "Confirm with Wise that this attempt created no recipient.")

    await db.execute(text("SELECT pg_advisory_xact_lock(61306133)"))
    attempt = await db.get(ContributorRecipientAttempt, attempt_id)
    if not attempt:
        raise HTTPException(404, "Unknown recipient submission.")
    audit_key = "contributor_bank_audit_" + attempt.id
    prior = await db.get(OpsSetting, audit_key)
    if prior:
        evidence = json.loads(prior.value)
        if (evidence["resolution"] != body.resolution
                or evidence["recipient_id"] != body.recipient_id):
            raise HTTPException(409, "This submission already has a recorded resolution.")
        return {"id": attempt.id, "status": attempt.status}

    if attempt.status not in ("submitting", "needs_reconciliation", "needs_review"):
        raise HTTPException(409, "This submission cannot be reconciled.")
    # Creation has a 25-second provider timeout. Never release an active request
    # for retry; the longer interval also covers worker shutdown and DB recovery.
    if (attempt.status == "submitting"
            and attempt.created_at > datetime.now(timezone.utc) - timedelta(minutes=5)):
        raise HTTPException(409, "Submission is still in progress; reconcile it after five minutes.")
    if attempt.recipient_id and (body.resolution == "not_created"
                                or attempt.recipient_id != str(body.recipient_id)):
        raise HTTPException(409, "A known recipient cannot be replaced or marked uncreated.")

    account = await db.get(ContributorAccount, attempt.subject)
    region = next((r for r in REGIONS if r["routing_version"] == account.routing_version), None)
    profile = os.getenv("WISE_PROFILE_ID", "")
    environment = os.getenv("WISE_ENVIRONMENT", "sandbox")
    if not region or not profile.isdigit() or environment not in ("sandbox", "production"):
        raise HTTPException(409, "Configure the contributor region and Wise account before reconciliation.")
    if body.resolution == "found":
        from app.core.wise import WiseClient
        try:
            info = await asyncio.to_thread(WiseClient().recipient, body.recipient_id)
        except Exception:
            raise HTTPException(503, "Wise recipient verification is unavailable; submission remains held.") from None
        if (not isinstance(info, dict) or info.get("active") is not True
                or str(info.get("id")) != str(body.recipient_id)
                or str(info.get("profileId")) != profile
                or info.get("currency") != region["currency"]
                or not info.get("hash")):
            raise HTTPException(409, "The recipient must be active and match the configured Wise profile and currency.")

    previous_status = attempt.status
    if body.resolution == "found":
        attempt.recipient_id = str(body.recipient_id)
        attempt.status = "needs_review"
    else:
        attempt.status = "retry_allowed"
    # Insert once under the same lock as submission. Retries read this record;
    # no endpoint overwrites it or copies provider responses/bank fields into it.
    db.add(OpsSetting(key=audit_key, value=json.dumps({
        "attempt_id": attempt.id, "subject": account.subject, "wearer_id": account.wearer_id,
        "resolution": body.resolution, "recipient_id": body.recipient_id,
        "previous_status": previous_status, "status": attempt.status,
        "wise_profile_id": profile, "wise_environment": environment,
        "verified_owner": body.verified_owner, "confirmed_not_created": body.confirmed_not_created,
        "operator": operator.email, "resolved_at": datetime.now(timezone.utc).isoformat(), "note": note,
    })))
    await db.commit()
    return {"id": attempt.id, "status": attempt.status}

@router.get("")
async def state(_: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    accounts = (await db.execute(select(ContributorAccount))).scalars().all()
    claims = (await db.execute(select(ContributorCameraClaim))).scalars().all()
    banks = (await db.execute(select(ContributorRecipientAttempt))).scalars().all()
    return {"accounts": [{"subject": a.subject, "wearer_id": a.wearer_id, "routing_version": a.routing_version} for a in accounts], "claims": [{"id": c.id, "subject": c.subject, "device_id": c.device_id, "status": c.status, "effective_at": c.effective_at, "ended_at": c.ended_at} for c in claims], "recipients": [{"id": b.id, "subject": b.subject, "recipient_id": b.recipient_id, "status": b.status, "summary": json.loads(b.summary)} for b in banks]}

class ApproveIn(BaseModel):
    physically_verified: bool

@router.post("/cameras/{claim_id}/approve")
async def approve_camera(claim_id: str, body: ApproveIn, operator: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    if not body.physically_verified:
        raise HTTPException(422, "Physical provisioning is required.")
    await db.execute(text("SELECT pg_advisory_xact_lock(61306130)"))
    claim = await db.get(ContributorCameraClaim, claim_id)
    if not claim or claim.ended_at or claim.status not in ("pending", "approved"):
        raise HTTPException(409, "This request is not active.")
    account = await db.get(ContributorAccount, claim.subject)
    wearer = await db.get(Wearer, account.wearer_id)
    if not wearer or not wearer.is_active:
        raise HTTPException(409, "The contributor account is inactive.")
    region = next(r for r in REGIONS if r["routing_version"] == account.routing_version)
    if not await has_consent(account, region, db):
        raise HTTPException(409, "Current agreements must be accepted first.")
    camera = await db.get(OpsCamera, claim.device_id)
    other = (await db.execute(select(ContributorCameraClaim).where(ContributorCameraClaim.device_id == claim.device_id, ContributorCameraClaim.status == "approved", ContributorCameraClaim.ended_at.is_(None), ContributorCameraClaim.id != claim.id))).scalars().first()
    if other or (camera and camera.wearer_id not in (None, account.wearer_id)):
        raise HTTPException(409, "Camera already assigned. End its existing assignment first.")
    if claim.status != "approved":
        claim.status, claim.effective_at, claim.operator = "approved", datetime.now(timezone.utc), operator.email
        if camera:
            camera.wearer_id = account.wearer_id
        else:
            db.add(OpsCamera(device_id=claim.device_id, wearer_id=account.wearer_id))
        await db.commit()
    return {"id": claim.id, "status": claim.status, "effective_at": claim.effective_at}

class TermsDocument(BaseModel):
    agreement: str = Field(pattern="^(participation|privacy|collection)$")
    locale: str = Field(pattern="^(en|ko)$")
    version: str = Field(pattern="^[a-zA-Z0-9._-]{1,80}$")
    key: str = Field(max_length=500)
    object_version: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")

class TermsIn(BaseModel):
    approved_for_publication: bool
    documents: list[TermsDocument] = Field(min_length=3, max_length=6)

@router.post("/terms/{routing_version}")
async def publish_terms(routing_version: str, body: TermsIn, operator: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    regions = [r for r in REGIONS if r["routing_version"] == routing_version]
    if not regions or not body.approved_for_publication:
        raise HTTPException(422, "Approved regional documents required.")
    docs = [d.model_dump() for d in body.documents]
    if len({(d["agreement"], d["locale"]) for d in docs}) != len(docs) or any({d["agreement"] for d in docs if d["locale"] == locale} != AGREEMENTS for locale in {d["locale"] for d in docs}):
        raise HTTPException(422, "Each published language needs all three agreements.")
    def verify():
        from app.core import ops_s3
        s3 = ops_s3._client(ops_s3.get_settings())
        for doc in docs:
            expected = f"terms/{regions[0]['region']}/{doc['agreement']}/{doc['version']}/"
            if not doc["key"].startswith(expected) or doc["object_version"] == "null":
                raise ValueError()
            obj = s3.get_object(Bucket=RECORDS_BUCKET, Key=doc["key"], VersionId=doc["object_version"])
            data = obj["Body"].read(5_000_001)
            if len(data) > 5_000_000 or hashlib.sha256(data).hexdigest() != doc["sha256"]:
                raise ValueError()
    try:
        await asyncio.to_thread(verify)
    except Exception:
        raise HTTPException(422, "Versioned document contents could not be verified.") from None
    for doc in docs:
        doc.update(approved_by=operator.email, published_at=datetime.now(timezone.utc).isoformat())
    await db.execute(text("SELECT pg_advisory_xact_lock(61306132)"))
    await _put_setting(db, "contributor_terms_" + routing_version, json.dumps(docs))
    await db.commit()
    return {"published": True}

@router.post("/consents/export")
async def export_consents(_: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    receipts = (await db.execute(select(ContributorConsent))).scalars().all()
    def export():
        from botocore.exceptions import ClientError
        from app.core import ops_s3
        s3 = ops_s3._client(ops_s3.get_settings())
        for c in receipts:
            try:
                s3.put_object(Bucket=RECORDS_BUCKET, Key=f"consent-receipts/{c.subject}/{c.id}.json", Body=c.snapshot.encode(), ContentType="application/json", IfNoneMatch="*")
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("PreconditionFailed", "412"):
                    raise
    try:
        await asyncio.to_thread(export)
    except Exception:
        raise HTTPException(503, "Export pending; original receipts remain in the database.") from None
    return {"exported": len(receipts)}
