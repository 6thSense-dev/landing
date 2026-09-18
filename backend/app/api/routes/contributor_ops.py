"""Staff supervision for mobile enrollment. Existing Ops authentication and CSRF apply."""
import asyncio
import hashlib
import json
import os
from datetime import date, datetime, timezone, timedelta
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.ops import require_ops
from app.api.routes.contributor import AGREEMENTS, RECORDS_BUCKET, has_consent
from app.core.contributor_auth import REGIONS
from app.core.contributor_deletion import lock as deletion_lock, ensure_active
from app.core.db import get_session
from app.models import ContributorAccount, ContributorCameraClaim, ContributorConsent, ContributorRecipientAttempt, OpsCamera, OpsSetting, User, Wearer

router = APIRouter(prefix="/api/ops/contributors", tags=["ops"])


class CameraPreapprovalIn(BaseModel):
    preapproval_id: str = Field(pattern='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    phone: str = Field(pattern=r'^\+8210[0-9]{8}$')
    wearer_id: int = Field(gt=0)
    device_id: str = Field(pattern='^[A-F0-9]{6}$')
    physically_verified: StrictBool
    camera_owner_verified: StrictBool
    permissions_verified: StrictBool
    note: str = Field(min_length=10, max_length=500)


@router.post('/camera-preapprovals')
async def preapprove_camera(body: CameraPreapprovalIn, operator: User = Depends(require_ops),
                            db: AsyncSession = Depends(get_session)):
    from app.api.routes.form_contracts import phone_digest
    from app.core import contributor_preapproval as pre
    from app.core.contributor_deletion import ensure_wearer_active
    if not all((body.physically_verified, body.camera_owner_verified, body.permissions_verified)) or len(body.note.strip()) < 10:
        raise HTTPException(422, 'camera_handover_verification_required')
    await ensure_wearer_active(db, body.wearer_id)
    await db.execute(text('SELECT pg_advisory_xact_lock(61306130)'))
    digest = phone_digest(body.phone)
    payload = {**body.model_dump(exclude={'phone'}), 'phone_digest': digest}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    prior = await db.get(OpsSetting, pre.approval_key(body.preapproval_id))
    if prior:
        saved = json.loads(prior.value)
        if saved['fingerprint'] != fingerprint:
            raise HTTPException(409, 'camera_preapproval_immutable_conflict')
        return {key: saved[key] for key in ('id', 'device_id', 'wearer_id', 'approved_at', 'expires_at')}
    wearer = await db.get(Wearer, body.wearer_id)
    if not wearer or not wearer.is_active:
        raise HTTPException(409, 'existing_contributor_unavailable')
    account = (await db.execute(select(ContributorAccount).where(ContributorAccount.wearer_id == wearer.id))).scalar_one_or_none()
    if account and account.routing_version != 'kr-2026-v1':
        raise HTTPException(409, 'contract_region_mismatch')
    previous = await pre.for_phone(db, digest)
    current = datetime.now(timezone.utc)
    if previous and not await db.get(OpsSetting, pre.consumption_key(previous['id'])) and datetime.fromisoformat(previous['expires_at']) > current:
        raise HTTPException(409, 'camera_preapproval_already_pending')
    device_index = await db.get(OpsSetting, 'form_pre_device_' + body.device_id)
    if device_index:
        prior_device = await db.get(OpsSetting, pre.approval_key(json.loads(device_index.value)))
        reserved = json.loads(prior_device.value) if prior_device else None
        if reserved and not await db.get(OpsSetting, pre.consumption_key(reserved['id'])) and datetime.fromisoformat(reserved['expires_at']) > current:
            raise HTTPException(409, 'camera_preapproval_already_pending')
    camera = await db.get(OpsCamera, body.device_id)
    active = (await db.execute(select(ContributorCameraClaim.id).where(
        ContributorCameraClaim.device_id == body.device_id,
        ContributorCameraClaim.status == 'approved', ContributorCameraClaim.ended_at.is_(None)))).scalars().all()
    if active or (camera and camera.wearer_id not in (None, wearer.id)):
        raise HTTPException(409, 'camera_assignment_conflict')
    if camera is None:
        camera = OpsCamera(device_id=body.device_id, wearer_id=wearer.id)
        db.add(camera)
    else:
        camera.wearer_id = wearer.id
    await db.flush()
    await db.refresh(camera)
    saved = {**payload, 'id': body.preapproval_id, 'fingerprint': fingerprint,
        'operator': operator.email, 'approved_at': current.isoformat(),
        'expires_at': (current + timedelta(days=7)).isoformat(), 'camera_updated_at': camera.updated_at.isoformat()}
    db.add(OpsSetting(key=pre.approval_key(body.preapproval_id), value=json.dumps(saved)))
    index = await db.get(OpsSetting, pre.phone_key(digest))
    if index:
        index.value = json.dumps(body.preapproval_id)
    else:
        db.add(OpsSetting(key=pre.phone_key(digest), value=json.dumps(body.preapproval_id)))
    if device_index:
        device_index.value = json.dumps(body.preapproval_id)
    else:
        db.add(OpsSetting(key='form_pre_device_' + body.device_id, value=json.dumps(body.preapproval_id)))
    await db.commit()
    return {key: saved[key] for key in ('id', 'device_id', 'wearer_id', 'approved_at', 'expires_at')}


async def require_terms_founder(user: User = Depends(require_ops)) -> User:
    """Staff roles alone never grant legal-document publication authority."""
    founders = {email.strip().casefold() for email in
                os.getenv("CONTRIBUTOR_TERMS_FOUNDER_EMAILS", "").split(",") if email.strip()}
    if user.email.strip().casefold() not in founders:
        raise HTTPException(403, "Only an explicitly authorized company founder may publish contributor terms.")
    return user


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

    await deletion_lock(db)
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
    await deletion_lock(db)
    await db.execute(text("SELECT pg_advisory_xact_lock(61306130)"))
    claim = await db.get(ContributorCameraClaim, claim_id)
    if not claim or claim.ended_at or claim.status not in ("pending", "approved"):
        raise HTTPException(409, "This request is not active.")
    await ensure_active(db, claim.subject)
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
    agreement: str = Field(pattern="^(participation|privacy|collection|international_transfer)$")
    locale: str = Field(pattern="^(en|ko)$")
    version: str = Field(pattern="^[a-zA-Z0-9._-]{1,80}$")
    key: str = Field(max_length=500)
    object_version: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")

class TermsIn(BaseModel):
    approved_for_publication: bool
    documents: list[TermsDocument] = Field(min_length=4, max_length=8)

@router.post("/terms/{routing_version}")
async def publish_terms(routing_version: str, body: TermsIn, operator: User = Depends(require_terms_founder), db: AsyncSession = Depends(get_session)):
    regions = [r for r in REGIONS if r["routing_version"] == routing_version]
    if not regions or not body.approved_for_publication:
        raise HTTPException(422, "Approved regional documents required.")
    docs = sorted((d.model_dump() for d in body.documents), key=lambda d: (d["agreement"], d["locale"]))
    if len({(d["agreement"], d["locale"]) for d in docs}) != len(docs) or any({d["agreement"] for d in docs if d["locale"] == locale} != AGREEMENTS for locale in {d["locale"] for d in docs}):
        raise HTTPException(422, "Each published language needs all four agreements.")
    fingerprint = hashlib.sha256(json.dumps({"routing_version": routing_version, "documents": docs},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    await db.execute(text("SELECT pg_advisory_xact_lock(61306132)"))
    current = await db.get(OpsSetting, "contributor_terms_" + routing_version)
    history = (await db.execute(select(OpsSetting).where(
        OpsSetting.key.startswith("contributor_terms_audit_")))).scalars().all()
    for row in history:
        published = json.loads(row.value)
        if published["routing_version"] != routing_version:
            continue
        if published["payload_sha256"] == fingerprint:
            # A lost-response retry preserves the original approver and time.
            # Replaying an older bundle cannot roll back a newer publication.
            return {"published": True, "publication_id": published["id"],
                    "current": bool(current and json.loads(current.value) == published["documents"])}
        for prior in published["documents"]:
            for doc in docs:
                if all(prior[key] == doc[key] for key in ("agreement", "locale", "version")) and any(
                        prior[key] != doc[key] for key in TermsDocument.model_fields):
                    raise HTTPException(409, "A published document version is immutable; use a new version for changed contents or object references.")
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
    publication_id = str(uuid4())
    approved_at = datetime.now(timezone.utc).isoformat()
    for doc in docs:
        doc.update(approved_by=operator.email, approved_by_user_id=operator.id,
                   published_at=approved_at, publication_id=publication_id)
    # The current pointer may advance, but the original founder approval and
    # version/hash/object evidence are insert-only and remain independently auditable.
    db.add(OpsSetting(key="contributor_terms_audit_" + publication_id, value=json.dumps({
        "id": publication_id, "routing_version": routing_version, "payload_sha256": fingerprint,
        "approved_by": operator.email, "approved_by_user_id": operator.id,
        "approved_at": approved_at, "documents": docs,
    })))
    if current:
        current.value = json.dumps(docs)
    else:
        db.add(OpsSetting(key="contributor_terms_" + routing_version, value=json.dumps(docs)))
    await db.commit()
    return {"published": True, "publication_id": publication_id, "current": True}

@router.post("/consents/export")
async def export_consents(_: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    from app.models import ContributorDeletion
    await deletion_lock(db)
    receipts = (await db.execute(select(ContributorConsent).where(
        ContributorConsent.subject.not_in(select(ContributorDeletion.subject))))).scalars().all()
    if not receipts:
        return {"exported": 0}
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


class RetainedRecord(BaseModel):
    scope: str = Field(min_length=10, max_length=1000)
    reason: str = Field(min_length=10, max_length=1000)
    review_at: date


class DeletionFulfillmentIn(BaseModel):
    footage_cleanup: str = Field(min_length=20, max_length=4000)
    processor_cleanup: str = Field(min_length=20, max_length=4000)
    retained_records: list[RetainedRecord] = Field(min_length=1, max_length=30)


@router.get('/deletions')
async def deletion_queue(_: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    from app.models import ContributorDeletion
    rows = (await db.execute(select(ContributorDeletion).order_by(ContributorDeletion.requested_at))).scalars()
    return {'requests':[{'id':r.id,'subject':r.subject,'status':r.status,'requested_at':r.requested_at,
                         'provider_status':r.provider_status,'attempts':r.attempts,
                         'evidence':json.loads(r.evidence) if r.evidence else None} for r in rows]}


@router.post('/deletions/{request_id}/fulfill')
async def fulfill_deletion(request_id: str, body: DeletionFulfillmentIn,
                           operator: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    from app.core import contributor_deletion as deletion
    from app.models import ContributorDeletion, PayoutRecipient
    await deletion.lock(db)
    row = (await db.execute(select(ContributorDeletion).where(ContributorDeletion.id == request_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, 'deletion_request_not_found')
    if row.status == 'completed':
        return {'status':'completed', 'request_id':row.id}
    if any(len(v.strip()) < 20 for v in (body.footage_cleanup,body.processor_cleanup)) or any(
        len(v.scope.strip()) < 10 or len(v.reason.strip()) < 10 for v in body.retained_records):
        raise HTTPException(422, 'cleanup_and_retention_evidence_required')
    attempts = (await db.execute(select(ContributorRecipientAttempt).where(ContributorRecipientAttempt.subject == row.subject))).scalars().all()
    if any(a.status in ('submitting','needs_reconciliation') for a in attempts):
        raise HTTPException(409, 'resolve_provider_submissions_before_deletion')
    if row.evidence is None and any(v.review_at < datetime.now(timezone.utc).date() for v in body.retained_records):
        raise HTTPException(422, 'retention_review_date_must_not_be_past')
    evidence = body.model_dump(mode='json')
    if row.evidence and json.loads(row.evidence)['cleanup'] != evidence:
        raise HTTPException(409, 'deletion_evidence_already_recorded')
    if row.evidence is None:
        row.evidence = json.dumps({'cleanup':evidence, 'operator':operator.email,
                                   'recorded_at':datetime.now(timezone.utc).isoformat()})
    row.status = 'processing'
    # Commit intent before contacting Cognito. Reacquire the same lock and reload:
    # a second worker may finish during the commit boundary.
    await db.commit()
    await deletion.lock(db)
    await db.refresh(row)
    if row.status == 'completed':
        return {'status':'completed', 'request_id':row.id}
    row.attempts += 1
    try:
        await asyncio.to_thread(deletion.delete_cognito_user, row.subject)
    except Exception:
        row.provider_status = 'retry_required'
        db.add(OpsSetting(key='contrib_delete_attempt_'+str(uuid4()), value=json.dumps({
            'request_id':row.id, 'operator':operator.email, 'at':datetime.now(timezone.utc).isoformat(),
            'result':'retry_required'})))
        await db.commit()
        raise HTTPException(503, 'identity_deletion_retry_required') from None
    account = await db.get(ContributorAccount, row.subject)
    if account:
        wearer = await db.get(Wearer, account.wearer_id)
        wearer.name, wearer.contact, wearer.workplace, wearer.location, wearer.note = 'Deleted contributor','','','',''
        wearer.is_active = False
        linked = await db.get(PayoutRecipient, account.wearer_id)
        if linked:
            await db.delete(linked)
        for attempt in attempts:
            attempt.summary = '{}'
            attempt.recipient_id = None
            attempt.status = 'deleted'
    row.provider_status, row.status, row.completed_at = 'deleted','completed',datetime.now(timezone.utc)
    db.add(OpsSetting(key='contrib_delete_attempt_'+str(uuid4()), value=json.dumps({
        'request_id':row.id, 'operator':operator.email, 'at':row.completed_at.isoformat(), 'result':'completed'})))
    await db.commit()
    return {'status':'completed', 'request_id':row.id}
