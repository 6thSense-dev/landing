"""Staff-confirmed camera handovers may wait for a verified signed account.

Approval evidence is immutable. Separate consumption prevents an old approval
from recreating a claim after a camera has been returned or reassigned.
"""
from datetime import datetime, timezone
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, text
from app.models import ContributorCameraClaim, OpsCamera, OpsSetting


def approval_key(identifier):
    return 'form_pre_' + identifier


def phone_key(digest):
    # OpsSetting keys have a 60-character limit; compare the full digest below.
    return 'form_pre_phone_' + digest[:40]


def consumption_key(identifier):
    return 'form_pre_use_' + identifier


async def for_phone(db, digest):
    index = await db.get(OpsSetting, phone_key(digest))
    if not index:
        return None
    row = await db.get(OpsSetting, approval_key(json.loads(index.value)))
    evidence = json.loads(row.value) if row else {}
    if evidence.get('phone_digest') != digest:
        raise HTTPException(409, 'contract_identity_review_required')
    return evidence


async def consume(db, evidence, account, signed_at):
    if not evidence:
        return
    await db.execute(text('SELECT pg_advisory_xact_lock(61306130)'))
    used = await db.get(OpsSetting, consumption_key(evidence['id']))
    if used:
        if json.loads(used.value)['subject'] != account.subject:
            raise HTTPException(409, 'contract_identity_review_required')
        return  # Never recreate or reactivate the consumed claim.
    current = datetime.now(timezone.utc)
    if current > datetime.fromisoformat(evidence['expires_at']):
        raise HTTPException(409, 'camera_preapproval_expired')
    camera = await db.get(OpsCamera, evidence['device_id'])
    if (account.wearer_id != evidence['wearer_id'] or not camera
            or camera.wearer_id != account.wearer_id
            or camera.updated_at != datetime.fromisoformat(evidence['camera_updated_at'])):
        raise HTTPException(409, 'camera_preapproval_changed')
    active = (await db.execute(select(ContributorCameraClaim.id).where(
        ContributorCameraClaim.device_id == evidence['device_id'],
        ContributorCameraClaim.status == 'approved', ContributorCameraClaim.ended_at.is_(None)
    ))).scalars().all()
    if active:
        raise HTTPException(409, 'camera_preapproval_changed')
    claim = ContributorCameraClaim(id=str(uuid4()), subject=account.subject,
        device_id=evidence['device_id'], status='approved', operator=evidence['operator'],
        effective_at=max(datetime.fromisoformat(evidence['approved_at']), signed_at))
    db.add(claim)
    db.add(OpsSetting(key=consumption_key(evidence['id']), value=json.dumps({
        'subject': account.subject, 'claim_id': claim.id, 'consumed_at': current.isoformat()})))
