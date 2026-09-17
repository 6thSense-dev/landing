"""Authenticated Form sync and phone-verified account activation. Never passwords."""
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.contributor_auth import contributor_identity, cognito_user
from app.core import contributor_deletion
from app.core.db import get_session
from app.core.limiter import limiter
from app.models import ContributorAccount, Wearer
from app.models.form_contract import FormContract


def private(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'


router = APIRouter(prefix='/api/form-contracts', tags=['contributor'], dependencies=[Depends(private)])


def config():
    try:
        data = json.loads(os.getenv('CONTRIBUTOR_FORM_BUNDLE', '{}'))
        if (os.getenv('CONTRIBUTOR_FORM_ENABLED') != 'true'
                or not isinstance(data, dict)
                or not all(data.get(k) for k in ('form_id', 'version', 'terms_sha256', 'effective_at', 'url'))
                or data.get('rate_krw_hour') != 11000
                or not re.fullmatch('[0-9a-f]{64}', data['terms_sha256'])):
            raise ValueError()
        effective = datetime.fromisoformat(data['effective_at'])
        if not effective.tzinfo or not re.fullmatch(r'https://docs\.google\.com/forms/d/e/[A-Za-z0-9_-]+/viewform', data['url']):
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503, 'contract_setup_pending') from None


def phone_digest(phone):
    key = os.getenv('CONTRIBUTOR_FORM_PHONE_KEY', '')
    if len(key) < 32:
        raise HTTPException(503, 'contract_setup_pending')
    return hmac.new(key.encode(), phone.encode(), hashlib.sha256).hexdigest()


def valid_row(row, bundle):
    return (row.state == 'signed' and row.form_id == bundle['form_id']
            and row.version == bundle['version'] and row.terms_sha256 == bundle['terms_sha256'])


async def has_form_consent(account, db):
    if os.getenv('CONTRIBUTOR_FORM_ENABLED') != 'true':
        return None
    bundle = config()
    rows = list((await db.execute(select(FormContract).where(FormContract.subject == account.subject))).scalars())
    return any(valid_row(row, bundle) for row in rows) if rows else None


class Submission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    response_id: str = Field(min_length=5, max_length=512)
    form_id: str = Field(min_length=10, max_length=128)
    version: str = Field(min_length=1, max_length=80)
    terms_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    receipt_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    phone: str = Field(pattern=r'^\+8210[0-9]{8}$')
    name: str = Field(min_length=1, max_length=200)
    signature: str = Field(min_length=1, max_length=200)
    signed_at: datetime
    accepted: dict[str, StrictBool]
    # Staff-controlled registry field, not an answer participants can choose.
    wearer_id: int | None = Field(default=None, gt=0)
    state: str = Field(default='signed', pattern='^(signed|withdrawn)$')


@router.get('/configuration')
async def configuration():
    b = config()
    return {'url': b['url'], 'version': b['version'], 'rate_krw_hour': 11000}


@router.post('/sync')
@limiter.limit('120/minute')
async def sync(request: Request, db: AsyncSession = Depends(get_session)):
    bundle = config()
    body = await request.body()
    secret = os.getenv('CONTRIBUTOR_FORM_SYNC_SECRET', '')
    stamp, signature = request.headers.get('x-form-timestamp', ''), request.headers.get('x-form-signature', '')
    if len(secret) < 32:
        raise HTTPException(503, 'contract_setup_pending')
    if not stamp.isascii() or not stamp.isdigit() or len(stamp) > 12 or abs(time.time() - int(stamp)) > 300:
        raise HTTPException(401, 'invalid_form_authentication')
    expected = hmac.new(secret.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    if not re.fullmatch('[0-9a-f]{64}', signature) or not hmac.compare_digest(expected, signature):
        raise HTTPException(401, 'invalid_form_authentication')
    try:
        item = Submission.model_validate_json(body)
    except ValidationError:
        # No raw body or Pydantic input echo, especially if someone sent a password.
        raise HTTPException(422, 'invalid_form_submission') from None
    required = {'participation', 'collection', 'privacy', 'international_transfer', 'adult'}
    if (item.form_id != bundle['form_id'] or item.version != bundle['version']
            or item.terms_sha256 != bundle['terms_sha256']
            or set(item.accepted) != required or not all(item.accepted.values())
            or not item.name.strip()
            or item.name.strip() != item.signature.strip()
            or not item.signed_at.tzinfo
            or item.signed_at < datetime.fromisoformat(bundle['effective_at'])
            or item.signed_at.timestamp() > time.time() + 60):
        raise HTTPException(409, 'contract_evidence_mismatch')
    await contributor_deletion.lock(db)
    identity = hashlib.sha256((item.form_id + ':' + item.response_id).encode()).hexdigest()
    evidence = item.model_dump(mode='json', exclude={'phone', 'wearer_id', 'state'})
    encoded = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
    digest = phone_digest(item.phone)
    row = await db.get(FormContract, identity)
    if row:
        if row.source_json != encoded or row.phone_digest != digest:
            raise HTTPException(409, 'immutable_contract_conflict')
        if row.state == 'withdrawn' and item.state != 'withdrawn':
            raise HTTPException(409, 'withdrawn_contract_cannot_be_reactivated')
        if item.wearer_id is not None and row.wearer_id not in (None, item.wearer_id):
            raise HTTPException(409, 'contract_identity_conflict')
        row.state = item.state
        if row.wearer_id is None:
            row.wearer_id = item.wearer_id
    else:
        row = FormContract(id=identity, response_id=item.response_id, form_id=item.form_id,
            version=item.version, terms_sha256=item.terms_sha256, receipt_sha256=item.receipt_sha256,
            phone_digest=digest, name=item.name.strip(), signed_at=item.signed_at,
            wearer_id=item.wearer_id, state=item.state, source_json=encoded)
        db.add(row)
    if row.wearer_id is not None:
        wearer = await db.get(Wearer, row.wearer_id)
        if not wearer or not wearer.is_active:
            raise HTTPException(409, 'existing_contributor_unavailable')
    await db.commit()
    return {'recorded': True, 'contract_id': identity, 'linked': bool(row.subject), 'state': row.state}


@router.post('/activate')
@limiter.limit('10/minute')
async def activate(request: Request, identity=Depends(contributor_identity), db: AsyncSession = Depends(get_session)):
    bundle = config()
    if identity['region']['routing_version'] != 'kr-2026-v1':
        raise HTTPException(403, 'contract_region_mismatch')
    await contributor_deletion.lock(db)
    await contributor_deletion.ensure_active(db, identity['subject'])
    # Read the verified provider attributes; never trust a browser-supplied phone.
    token = request.headers['authorization'][7:]
    try:
        user = await asyncio.to_thread(cognito_user, token)
        attrs = {a['Name']: a['Value'] for a in user['UserAttributes']}
        if attrs.get('sub') != identity['subject'] or attrs.get('phone_number_verified') != 'true':
            raise ValueError()
        digest = phone_digest(attrs['phone_number'])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, 'verified_account_required') from None
    matches = list((await db.execute(select(FormContract).where(FormContract.phone_digest == digest))).scalars())
    eligible = [row for row in matches if valid_row(row, bundle)]
    if len(eligible) != 1:
        raise HTTPException(409, 'contract_not_found' if not eligible else 'contract_identity_review_required')
    row = eligible[0]
    if row.subject not in (None, identity['subject']):
        raise HTTPException(409, 'contract_identity_review_required')
    account = await db.get(ContributorAccount, identity['subject'])
    if account:
        if row.wearer_id is not None and row.wearer_id != account.wearer_id:
            raise HTTPException(409, 'contract_identity_review_required')
        wearer = await db.get(Wearer, account.wearer_id)
        if not wearer or not wearer.is_active or account.routing_version != 'kr-2026-v1':
            raise HTTPException(403, 'enrollment_inactive')
    else:
        wearer = await db.get(Wearer, row.wearer_id) if row.wearer_id is not None else None
        if wearer:
            linked = (await db.execute(select(ContributorAccount).where(ContributorAccount.wearer_id == wearer.id))).scalar_one_or_none()
            if linked or not wearer.is_active:
                raise HTTPException(409, 'contract_identity_review_required')
        elif row.wearer_id is not None:
            raise HTTPException(409, 'contract_identity_review_required')
        else:
            # A same-name legacy record needs explicit staff linking, never an automatic merge.
            existing = (await db.execute(select(Wearer.id).where(Wearer.name == row.name).limit(1))).scalar_one_or_none()
            if existing:
                raise HTTPException(409, 'contract_identity_review_required')
            wearer = Wearer(name=row.name, contact='', location='South Korea', rate_krw_hour=11000,
                note='Signed Google Form contract; physical camera assignment pending.')
            db.add(wearer)
            await db.flush()
        account = ContributorAccount(subject=identity['subject'], wearer_id=wearer.id, routing_version='kr-2026-v1')
        db.add(account)
        await db.flush()
    row.subject, row.wearer_id = account.subject, account.wearer_id
    await db.commit()
    return {'activated': True, 'contract_id': row.id, 'name': row.name}
