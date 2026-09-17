"""Coverage of contract bridge failures and preserved contributor access."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api.routes import form_contracts as m
from app.api.routes.contributor import has_consent
from app.models import ContributorAccount, Wearer
from app.models.form_contract import FormContract
from tests.test_ops_routes import app, _client
from tests.test_contributor_mobile import identity, setup, accept, SUBJECT, OTHER, REGION
from tests.test_form_contracts import configuration, evidence, provider, send, activate, BUNDLE, PHONE


@pytest.mark.parametrize('result', [provider(subject=OTHER), {'UserAttributes': []}, None])
async def test_provider_identity_failure_never_links_contract(app, db_session, monkeypatch, result):
    identity(app)
    monkeypatch.setattr(m, 'cognito_user', lambda _: result)
    async with _client(app) as c:
        assert (await send(c)).status_code == 200
        response = await activate(c)
        assert response.status_code == 401
        assert response.json()['detail'] == 'verified_account_required'
    assert not list((await db_session.execute(select(ContributorAccount))).scalars())
    assert (await db_session.execute(select(FormContract))).scalar_one().subject is None


@pytest.mark.parametrize('existing', [False, True])
async def test_staff_link_to_missing_or_inactive_contributor_rolls_back(app, db_session, existing):
    wearer_id = 987654
    if existing:
        wearer = Wearer(name='Unavailable', is_active=False)
        db_session.add(wearer)
        await db_session.commit()
        wearer_id = wearer.id
    async with _client(app) as c:
        response = await send(c, evidence(wearer_id=wearer_id))
        assert response.status_code == 409
        assert response.json()['detail'] == 'existing_contributor_unavailable'
    assert not list((await db_session.execute(select(FormContract))).scalars())


async def test_staff_link_conflict_does_not_change_existing_account(app, db_session):
    account = await setup(db_session)
    other = await setup(db_session, OTHER)
    identity(app)
    async with _client(app) as c:
        assert (await send(c, evidence(wearer_id=other.wearer_id))).status_code == 200
        response = await activate(c)
        assert response.status_code == 409
        assert response.json()['detail'] == 'contract_identity_review_required'
    await db_session.refresh(account)
    assert account.wearer_id != other.wearer_id
    assert (await db_session.execute(select(FormContract))).scalar_one().subject is None


async def test_unlinked_legacy_consent_survives_new_form_rollout(app, db_session):
    account = await setup(db_session)
    await accept(db_session)
    assert await m.has_form_consent(account, db_session) is None
    assert await has_consent(account, REGION, db_session)


async def test_current_form_does_not_fall_back_to_legacy_after_version_change(app, db_session, monkeypatch):
    identity(app)
    async with _client(app) as c:
        await send(c)
        assert (await activate(c)).status_code == 200
    await accept(db_session)
    account = await db_session.get(ContributorAccount, SUBJECT)
    monkeypatch.setenv('CONTRIBUTOR_FORM_BUNDLE', json.dumps({**BUNDLE, 'version': 'v2'}))
    assert not await has_consent(account, REGION, db_session)


async def test_future_signed_at_and_chunked_body_are_rejected_without_echo(app):
    async with _client(app) as c:
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        assert (await send(c, evidence(signed_at=future))).status_code == 409
        async def chunks():
            yield b'private-submission-' + b'x' * 4000
            yield b'x' * 5000
        response = await c.post('/api/form-contracts/sync', content=chunks())
        assert response.status_code == 413
        assert 'private-submission' not in response.text


async def test_missing_phone_hash_key_fails_closed_before_contract_write(app, db_session, monkeypatch):
    monkeypatch.delenv('CONTRIBUTOR_FORM_PHONE_KEY')
    async with _client(app) as c:
        response = await send(c)
        assert response.status_code == 503
        assert PHONE not in response.text
    assert not list((await db_session.execute(select(FormContract))).scalars())


async def test_withdrawal_sync_succeeds_after_existing_wearer_is_deactivated(app, db_session):
    identity(app)
    async with _client(app) as c:
        assert (await send(c)).status_code == 200
        assert (await activate(c)).status_code == 200
        account = await db_session.get(ContributorAccount, SUBJECT)
        wearer = await db_session.get(Wearer, account.wearer_id)
        wearer.is_active = False
        await db_session.commit()
        response = await send(c, evidence(state='withdrawn'))
        assert response.status_code == 200, response.text
        assert response.json()['state'] == 'withdrawn'
        assert response.json()['linked']
        assert not await m.has_form_consent(account, db_session)
        assert (await send(c)).json()['detail'] == 'withdrawn_contract_cannot_be_reactivated'


async def test_verified_phone_withdrawal_blocks_legacy_uploads_before_form_activation(app, db_session, monkeypatch):
    from uuid import uuid4
    from app.core import contributor_auth as auth
    from app.models import ContributorCameraClaim, ContributorConsent
    from tests.test_contributor_mobile import documents

    monkeypatch.setenv('OPS_BROWSER_UPLOAD_ENABLED', 'true')
    await setup(db_session)
    await setup(db_session, OTHER)
    await accept(db_session)
    db_session.add(ContributorConsent(id=str(uuid4()), subject=OTHER,
        snapshot=json.dumps({'documents': documents()})))
    db_session.add(ContributorCameraClaim(id=str(uuid4()), subject=SUBJECT, device_id='ABC123',
        status='approved', effective_at=datetime.now(timezone.utc) - timedelta(days=1)))
    db_session.add(ContributorCameraClaim(id=str(uuid4()), subject=OTHER, device_id='ABC124',
        status='approved', effective_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await db_session.commit()
    verified = provider()
    verified['UserAttributes'].append({'Name': 'custom:routing_version', 'Value': REGION['routing_version']})
    token_subject = [SUBJECT]
    monkeypatch.setattr(auth, 'token_claims', lambda _: {'sub': token_subject[0]})
    monkeypatch.setattr(auth, 'cognito_user', lambda _: verified)
    headers = {'Authorization': 'Bearer verified-test-token'}
    async with _client(app) as c:
        assert (await c.get('/api/uploads/info', headers=headers)).status_code == 200
        assert (await send(c, evidence(state='withdrawn'))).status_code == 200
        row = (await db_session.execute(select(FormContract))).scalar_one()
        assert row.subject is None  # No browser activation has ever occurred.
        response = await c.get('/api/uploads/info', headers=headers)
        assert response.status_code == 403, response.text
        assert PHONE not in response.text
        assert (await activate(c)).json()['detail'] == 'contract_withdrawn'
        # Another verified account must not inherit this phone's withdrawal.
        token_subject[0] = OTHER
        for attribute in verified['UserAttributes']:
            if attribute['Name'] == 'phone_number':
                attribute['Value'] = '+821099998888'
            if attribute['Name'] == 'sub':
                attribute['Value'] = OTHER
        assert (await c.get('/api/uploads/info', headers=headers)).status_code == 200
