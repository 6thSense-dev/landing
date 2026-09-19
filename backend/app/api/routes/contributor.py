"""Authenticated mobile pilot. All totals come from the existing Ops ledgers."""
import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import re
import os
import secrets
from fastapi import Header
from typing import Literal
from app.core import contributor_deletion
from app.models import ContributorDeletion, ContributorDeletionReceipt, ProcessingJob
from uuid import uuid4
from app.core.ops_s3 import _client as s3_client, get_settings as s3_settings
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError
from app.core.contributor_auth import contributor_identity, REGIONS
from app.core.db import get_session
from app.core.ops_ledger import footage_ledger
from app.models import ContributorAccount, ContributorConsent, ContributorCameraClaim, ContributorRecipientAttempt, Episode, Wearer, OpsCamera, OpsSetting, Payout, PayoutRecipient

router = APIRouter(prefix="/api/contributor", tags=["contributor"])
RECORDS_BUCKET = "6thsense-contributor-records"
AGREEMENTS = {"participation", "privacy", "collection", "international_transfer"}
RECEIPT_RETRIES_PER_DAY = 20

def now():
    return datetime.now(timezone.utc)

async def account_for(identity, db):
    await contributor_deletion.ensure_active(db, identity["subject"])
    account = await db.get(ContributorAccount, identity["subject"])
    if not account:
        raise HTTPException(409, "enrollment_required")
    wearer = await db.get(Wearer, account.wearer_id)
    if not wearer or not wearer.is_active or account.routing_version != identity["region"]["routing_version"]:
        raise HTTPException(403, "enrollment_inactive")
    return account

async def terms_for(region, db):
    row = await db.get(OpsSetting, "contributor_terms_" + region["routing_version"])
    try:
        docs = json.loads(row.value) if row else []
    except (ValueError, TypeError):
        return []
    if not isinstance(docs, list) or any(not isinstance(d, dict) for d in docs):
        return []
    complete = []
    for locale in ("en", "ko"):
        localized = [d for d in docs if d.get("locale") == locale]
        if (len(localized) == len(AGREEMENTS)
                and all(isinstance(d.get("agreement"), str) for d in localized)
                and {d.get("agreement") for d in localized} == AGREEMENTS
                and all(all(isinstance(d.get(k), str) and d[k] for k in
                            ("version", "sha256", "key", "object_version")) for d in localized)):
            complete.extend(localized)
    return complete

async def has_consent(account, region, db, locale=None, verified_phone=None):
    from app.api.routes.form_contracts import has_form_consent
    form_consent = await has_form_consent(account, db, verified_phone=verified_phone)
    if form_consent is not None:
        return form_consent
    terms = await terms_for(region, db)
    if locale is not None:
        terms = [d for d in terms if d["locale"] == locale]
    required = {(d["agreement"], d["version"], d["sha256"], d["locale"]) for d in terms}
    if not required:
        return False
    receipts = (await db.execute(select(ContributorConsent).where(ContributorConsent.subject == account.subject))).scalars().all()
    return any({(d["agreement"], d["version"], d["sha256"], d["locale"]) for d in json.loads(c.snapshot)["documents"]}.issubset(required) and {d["agreement"] for d in json.loads(c.snapshot)["documents"]} == AGREEMENTS for c in receipts)

@router.get("/configuration")
async def configuration():
    import os
    return {"identity": {"region": os.getenv("CONTRIBUTOR_COGNITO_REGION", "us-west-2"), "clientId": os.getenv("CONTRIBUTOR_COGNITO_CLIENT", "")}, "signup": os.getenv("CONTRIBUTOR_SIGNUP_MODE", "closed"), "upload": "operator_sd_card", "payment": "operator_approved", "threshold_seconds": 14400, "threshold_comparison": "at_least", "calculation_schedule": "Sunday 23:59", "calculation_timezone": "Asia/Seoul"}

class EnrollmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)

@router.post("/enrollment")
async def enrollment(body: EnrollmentIn, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    await contributor_deletion.ensure_active(db, identity["subject"])
    if not body.name.strip():
        raise HTTPException(422, "name_required")
    await db.execute(text("SELECT pg_advisory_xact_lock(61306132)"))
    account = await db.get(ContributorAccount, identity["subject"])
    if not account:
        region = identity["region"]
        wearer = Wearer(name=body.name.strip(), contact="", location=region["region"], rate_krw_hour=region["hourly_rate_minor"] if region["currency"] == "KRW" else None, note="Verified mobile contributor; camera assignment requires operator confirmation.")
        db.add(wearer)
        await db.flush()
        account = ContributorAccount(subject=identity["subject"], wearer_id=wearer.id, routing_version=region["routing_version"])
        db.add(account)
        await db.commit()
    return {"enrolled": True}

@router.get("/terms")
async def terms(locale: str = "en", identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    if locale not in ("en", "ko"):
        raise HTTPException(422, "unsupported_locale")
    docs = [d for d in await terms_for(identity["region"], db) if d["locale"] == locale]
    if {d["agreement"] for d in docs} != AGREEMENTS:
        return {"status": "not_published", "documents": []}
    def urls():
        s3 = s3_client(s3_settings())
        # Founder identity belongs to the private approval audit, not the phone.
        return [{**{k: d[k] for k in ("agreement", "version", "sha256", "locale")}, "url": s3.generate_presigned_url("get_object", Params={"Bucket": RECORDS_BUCKET, "Key": d["key"], "VersionId": d["object_version"]}, ExpiresIn=900)} for d in docs]
    return {"status": "published", "documents": await asyncio.to_thread(urls)}

class ConsentIn(BaseModel):
    locale: str = Field(pattern="^(en|ko)$")
    documents: dict[str, str]
    versions: dict[str, str]

@router.post("/consent")
async def consent(body: ConsentIn, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    account = await account_for(identity, db)
    await db.execute(text("SELECT pg_advisory_xact_lock(61306132)"))
    docs = [d for d in await terms_for(identity["region"], db) if d["locale"] == body.locale]
    if (set(body.documents) != AGREEMENTS or set(body.versions) != AGREEMENTS
            or {d["agreement"]: d["sha256"] for d in docs} != body.documents
            or {d["agreement"]: d["version"] for d in docs} != body.versions):
        raise HTTPException(409, "terms_changed_or_unavailable")
    if not await has_consent(account, identity["region"], db, locale=body.locale, verified_phone=identity.get("verified_phone")):
        receipt_id = str(uuid4())
        snapshot = {"id": receipt_id, "subject": account.subject, "wearer_id": account.wearer_id, "routing_version": account.routing_version, "accepted_at": now().isoformat(), "locale": body.locale, "documents": docs}
        db.add(ContributorConsent(id=receipt_id, subject=account.subject, snapshot=json.dumps(snapshot)))
        await db.commit()
    return {"accepted": True}

class ClaimIn(BaseModel):
    device_id: str = Field(min_length=6, max_length=16)

@router.post("/cameras")
async def claim_camera(body: ClaimIn, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    account = await account_for(identity, db)
    if not await has_consent(account, identity["region"], db, verified_phone=identity.get("verified_phone")):
        raise HTTPException(409, "consent_required")
    device = body.device_id.strip().upper().removeprefix("EGO-")
    if not re.fullmatch("[A-F0-9]{6}", device):
        raise HTTPException(422, "unsupported_camera")
    await db.execute(text("SELECT pg_advisory_xact_lock(61306130)"))
    camera = await db.get(OpsCamera, device)
    if camera and camera.wearer_id not in (None, account.wearer_id):
        raise HTTPException(409, "camera_assignment_conflict")
    existing = (await db.execute(select(ContributorCameraClaim).where(ContributorCameraClaim.subject == account.subject, ContributorCameraClaim.device_id == device, ContributorCameraClaim.status.in_(["pending", "approved"]), ContributorCameraClaim.ended_at.is_(None)))).scalars().first()
    if not existing:
        existing = ContributorCameraClaim(id=str(uuid4()), subject=account.subject, device_id=device, status="pending")
        db.add(existing)
        await db.commit()
    return {"id": existing.id, "device_id": device, "status": existing.status}

@router.get("/dashboard")
async def dashboard(identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    account = await account_for(identity, db)
    wearer = await db.get(Wearer, account.wearer_id)
    raw = (await db.execute(select(Episode).where(Episode.wearer_id == account.wearer_id, Episode.deleted_at.is_(None)).order_by(Episode.first_seen_at.desc()))).scalars().all()
    rows = [r for r in await footage_ledger(db) if r["wearer_id"] == account.wearer_id and not r.get("counterparty")]
    approved = [r for r in rows if r["review_status"] == "reviewed"]
    by_recording = {r["recording"]: r for r in rows}
    claims = (await db.execute(select(ContributorCameraClaim).where(ContributorCameraClaim.subject == account.subject).order_by(ContributorCameraClaim.created_at.desc()))).scalars().all()
    payouts = (await db.execute(select(Payout).where(Payout.wearer_id == account.wearer_id).order_by(Payout.approved_at.desc()))).scalars().all()
    attempts = (await db.execute(select(ContributorRecipientAttempt).where(ContributorRecipientAttempt.subject == account.subject, ContributorRecipientAttempt.status != "retry_allowed").order_by(ContributorRecipientAttempt.created_at.desc()))).scalars().all()
    linked = await db.get(PayoutRecipient, account.wearer_id)
    bank = next((a for a in attempts if linked and a.recipient_id == linked.wise_recipient_id), attempts[0] if attempts else None)
    return {"name": wearer.name, "country": identity["region"]["country"], "consent_current": await has_consent(account, identity["region"], db, verified_phone=identity.get("verified_phone")), "rate": wearer.rate_krw_hour, "currency": identity["region"]["currency"], "recorded_seconds": sum(e.duration_s or 0 for e in raw), "unknown_duration_count": sum(not e.duration_s for e in raw), "approved_seconds": sum(r["retained_seconds"] for r in approved), "cameras": [{"id": c.id, "device_id": c.device_id, "status": "ended" if c.ended_at else c.status} for c in claims], "recordings": [{"recording": e.recording, "duration_seconds": e.duration_s or None, "uploaded_at": e.uploaded_at, "approved_seconds": by_recording[e.recording]["retained_seconds"] if e.recording in by_recording and by_recording[e.recording]["review_status"] == "reviewed" else None, "review_status": by_recording[e.recording]["review_status"] if e.recording in by_recording else "awaiting_qc"} for e in raw], "payouts": [{"id": p.id, "amount": p.amount_krw, "currency": "KRW", "status": p.status, "scheduled_for": p.scheduled_for} for p in payouts], "bank": {**json.loads(bank.summary), "status": "ready" if linked and bank.recipient_id == linked.wise_recipient_id else bank.status} if bank else None, "updated_at": now().isoformat()}

class BankIn(BaseModel):
    values: dict[str, str] = Field(default_factory=dict, max_length=20)
    operation_id: str | None = Field(default=None, pattern="^[0-9a-f-]{36}$")
    owns_account: bool = False
    shares_details: bool = False

    @staticmethod
    def clean(values):
        if any(len(k) > 40 or len(v) > 255 for k, v in values.items()):
            raise HTTPException(422, "invalid_bank_fields")
        return {k: v.strip().upper() if k == "ifscCode" else v.strip() for k, v in values.items()}

async def bank_status(account, db):
    linked = await db.get(PayoutRecipient, account.wearer_id)
    attempts = (await db.execute(select(ContributorRecipientAttempt).where(
        ContributorRecipientAttempt.subject == account.subject,
        ContributorRecipientAttempt.status != "retry_allowed",
    ).order_by(ContributorRecipientAttempt.created_at.desc()))).scalars().all()
    attempt = next((a for a in attempts if linked and a.recipient_id == linked.wise_recipient_id), attempts[0] if attempts else None)
    if linked:
        matching = attempt and attempt.recipient_id == linked.wise_recipient_id
        summary = json.loads(attempt.summary) if matching else {"accountHolderName": linked.verified_name}
        status = "ready"
    elif attempt:
        summary, status = json.loads(attempt.summary), attempt.status
    else:
        return None
    return {**{k: summary[k] for k in ("accountHolderName", "bankLabel", "maskedAccount", "currency", "submissionId", "submittedAt") if k in summary}, "status": status}


async def bank_account(identity, db):
    # Bank registration must not wait for the global footage scanner. Lock only
    # this wearer: account deletion updates this same row before it commits.
    await db.execute(text("SET LOCAL lock_timeout = '2s'"))
    account = await db.get(ContributorAccount, identity["subject"])
    if not account:
        raise HTTPException(409, "enrollment_required")
    try:
        wearer = (await db.execute(select(Wearer).where(
            Wearer.id == account.wearer_id).with_for_update())).scalar_one_or_none()
    except DBAPIError:
        await db.rollback()
        raise HTTPException(503, "payment_sheet_unavailable") from None
    if await db.get(ContributorDeletion, identity["subject"]):
        raise HTTPException(403, "account_deletion_pending")
    if not wearer or not wearer.is_active or account.routing_version != identity["region"]["routing_version"]:
        raise HTTPException(403, "enrollment_inactive")
    if not await has_consent(account, identity["region"], db, verified_phone=identity.get("verified_phone")):
        raise HTTPException(409, "consent_required")
    return account, wearer


async def remember_sheet_receipt(account, receipt, db, consent=None):
    existing = await db.get(ContributorRecipientAttempt, receipt["submissionId"])
    if existing and existing.subject != account.subject:
        raise HTTPException(409, "operation_conflict")
    if not existing:
        summary = {**receipt, "country": "KR", "currency": "KRW"}
        if consent:
            summary["payment_consent"] = consent
        db.add(ContributorRecipientAttempt(id=receipt["submissionId"], subject=account.subject,
            summary=json.dumps(summary, ensure_ascii=False), status="sheet_saved"))
        await db.commit()
    return receipt


@router.get("/bank/setup")
async def bank_setup(identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    account, _ = await bank_account(identity, db)
    from app.core.payment_notice import public_notice
    from app.core.payment_sheet import PaymentSheetClient, PaymentSheetError
    country = identity["region"]["country"]
    bank = await bank_status(account, db)
    if country == "KR" and bank is None:
        try:
            bank = await asyncio.to_thread(PaymentSheetClient().lookup, account.wearer_id)
        except PaymentSheetError:
            raise HTTPException(503, "payment_sheet_unavailable") from None
        if bank:
            await remember_sheet_receipt(account, bank, db)
    return {"country": country, "bank": bank,
            "notice": public_notice() if country == "KR" else None}


class WebBankIn(BankIn):
    notice_version: str = Field(max_length=80)
    notice_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    locale: Literal["en", "ko"]
    collects_details: bool = False
    international_transfer: bool = False

    def receipt(self, identity):
        from app.core.payment_notice import VERSION, DIGEST, REQUIRED_CHOICES, public_notice
        if identity["region"]["country"] != "KR":
            raise HTTPException(409, "payout_region_unavailable")
        if self.notice_version != VERSION or self.notice_sha256 != DIGEST:
            raise HTTPException(409, "payment_notice_changed")
        choices = {k: getattr(self, k) for k in REQUIRED_CHOICES}
        if not all(choices.values()):
            raise HTTPException(422, "bank_confirmation_required")
        return {"notice": public_notice(), "locale": self.locale,
                "accepted_at": now().isoformat(), "choices": choices}


@router.post("/bank/web/requirements")
async def web_bank_requirements(body: WebBankIn, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    body.receipt(identity)
    await bank_account(identity, db)
    from app.core.payment_sheet import requirements
    return requirements()


@router.post("/bank/web")
async def web_save_bank(body: WebBankIn, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    consent = body.receipt(identity)
    account, wearer = await bank_account(identity, db)
    from app.core.payment_sheet import PaymentSheetClient, PaymentSheetError, clean_values
    from uuid import UUID
    try:
        UUID(body.operation_id or "")
    except ValueError:
        raise HTTPException(422, "bank_confirmation_required") from None
    existing = await bank_status(account, db)
    if existing:
        return existing
    operation = await db.get(ContributorRecipientAttempt, body.operation_id)
    if operation:
        raise HTTPException(409, "operation_conflict")
    values, issues = clean_values(body.values)
    if issues:
        raise HTTPException(422, {"code": "invalid_bank_fields", "fields": issues})
    try:
        receipt = await asyncio.to_thread(PaymentSheetClient().submit, account.wearer_id,
            wearer.name, body.operation_id, values, consent)
    except PaymentSheetError:
        # The Sheet may have saved before a response was lost. No success is
        # claimed; lookup and retries recover its one row per contributor.
        raise HTTPException(503, "payment_sheet_unavailable") from None
    return await remember_sheet_receipt(account, receipt, db, consent)


@router.post("/bank/requirements")
async def bank_requirements(body: BankIn, identity=Depends(contributor_identity)):
    raise HTTPException(410, "use_website_bank_registration")


@router.post("/bank")
async def save_bank(body: BankIn, identity=Depends(contributor_identity)):
    # Older mobile builds cannot supply consent for spreadsheet storage.
    raise HTTPException(410, "use_website_bank_registration")


def deletion_status(row):
    return {'status': row.status if row else 'none',
            'request_id': row.id if row else None,
            'requested_at': row.requested_at if row else None,
            'expected_completion': os.getenv('CONTRIBUTOR_DELETION_EXPECTED_COMPLETION') or None}


@router.get('/account-deletion/receipt')
async def deletion_receipt(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_session)):
    token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not re.fullmatch('[a-f0-9]{64}', token):
        raise HTTPException(404, 'receipt_not_found')
    digest = hashlib.sha256(token.encode()).hexdigest()
    # The original hash remains valid, including receipts issued before 0018.
    row = (await db.execute(select(ContributorDeletion).where(ContributorDeletion.receipt_hash == digest))).scalar_one_or_none()
    if row is None:
        receipt = await db.get(ContributorDeletionReceipt, digest)
        if receipt is not None:
            row = await db.get(ContributorDeletion, receipt.subject)
    if not row:
        raise HTTPException(404, 'receipt_not_found')
    return deletion_status(row)


@router.get('/account-deletion')
async def get_deletion(identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    return deletion_status(await db.get(ContributorDeletion, identity['subject']))


class DeletionIn(BaseModel):
    confirmed: Literal[True]


@router.post('/account-deletion')
async def request_deletion(body: DeletionIn, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    await contributor_deletion.lock(db)
    subject = identity['subject']
    row = await db.get(ContributorDeletion, subject)
    issued_at = now()
    if row is not None:
        # The shared DB lock makes issuance limits hold across workers and IPs.
        # Only minting is limited: existing receipts and status stay available.
        recent = (await db.execute(select(ContributorDeletionReceipt.created_at).where(
            ContributorDeletionReceipt.subject == subject,
            ContributorDeletionReceipt.created_at > issued_at - timedelta(days=1),
        ).order_by(ContributorDeletionReceipt.created_at.desc()).limit(RECEIPT_RETRIES_PER_DAY))).scalars().all()
        if len(recent) >= RECEIPT_RETRIES_PER_DAY:
            retry_after = max(1, math.ceil((recent[-1] + timedelta(days=1) - issued_at).total_seconds()))
            raise HTTPException(429, 'deletion_receipt_retry_limited', headers={'Retry-After': str(retry_after)})
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    if row is None:
        row = ContributorDeletion(subject=subject, id=str(uuid4()), receipt_hash=digest, status='requested')
        db.add(row)
    else:
        # Responses can arrive out of order. Store only a hash of each new
        # bearer; neither another request nor fulfillment revokes older ones.
        db.add(ContributorDeletionReceipt(subject=subject, receipt_hash=digest, created_at=issued_at))
    account = await db.get(ContributorAccount, subject)
    if account:
        wearer = await db.get(Wearer, account.wearer_id)
        wearer.is_active = False
        for claim in (await db.execute(select(ContributorCameraClaim).where(ContributorCameraClaim.subject == subject, ContributorCameraClaim.ended_at.is_(None)))).scalars():
            claim.ended_at = now()
        for camera in (await db.execute(select(OpsCamera).where(OpsCamera.wearer_id == account.wearer_id))).scalars():
            camera.wearer_id = None
        recordings = select(Episode.recording).where(Episode.wearer_id == account.wearer_id)
        for job in (await db.execute(select(ProcessingJob).where(ProcessingJob.recording.in_(recordings)))).scalars():
            job.state, job.reason = 'blocked', 'Contributor account deletion requested.'
            job.lease_token = job.lease_until = None
    await db.commit()
    return {**deletion_status(row), 'receipt_token': token}


@router.get('/notice')
async def public_notice(routing_version: str, locale: str = 'en', db: AsyncSession = Depends(get_session)):
    if locale not in ('en','ko'):
        raise HTTPException(422, 'unsupported_locale')
    region = next((r for r in REGIONS if r['routing_version'] == routing_version), None)
    if region is None:
        return {'status':'not_published','documents':[]}
    docs = [d for d in await terms_for(region, db) if d['locale'] == locale]
    if {d['agreement'] for d in docs} != AGREEMENTS:
        return {'status':'not_published','documents':[]}
    # Only a founder-published immutable bundle may be exposed before signup.
    for doc in docs:
        publication = doc.get('publication_id')
        audit = await db.get(OpsSetting, 'contributor_terms_audit_' + publication) if isinstance(publication,str) else None
        try:
            proof = json.loads(audit.value) if audit else {}
            if proof.get('routing_version') != routing_version or doc not in proof.get('documents',[]):
                return {'status':'not_published','documents':[]}
        except (ValueError,TypeError):
            return {'status':'not_published','documents':[]}
    return await terms(locale=locale, identity={'region':region}, db=db)
