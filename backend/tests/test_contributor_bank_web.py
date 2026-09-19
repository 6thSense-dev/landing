"""Spreadsheet saves: auth, consent, recovery, masking and scanner isolation."""
import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import contributor_wise, payment_sheet
from app.core.payment_notice import public_notice
from app.models import ContributorRecipientAttempt, PayoutRecipient
from tests.test_contributor_mobile import setup, accept, identity, SUBJECT, OTHER
from tests.test_ops_routes import app, _client


def body(**overrides):
    notice = public_notice()
    return {"values": {"accountHolderName": "테스트", "bankName": "신한은행", "accountNumber": "001-234-567890"},
        "operation_id": str(uuid4()), "locale": "ko", "notice_version": notice["version"], "notice_sha256": notice["sha256"],
        "collects_details": True, "shares_details": True, "international_transfer": True, "owns_account": True, **overrides}


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    class Fake:
        rows = {}
        creations = []
        lost_response = False
        unavailable = False
        def lookup(self, wearer_id):
            if self.unavailable: raise payment_sheet.PaymentSheetError('payment_sheet_unavailable')
            return self.rows.get(wearer_id)
        def submit(self, wearer_id, name, operation, values, consent):
            if self.unavailable: raise payment_sheet.PaymentSheetError('payment_sheet_unavailable')
            if wearer_id not in self.rows:
                self.creations.append((wearer_id, values, consent))
                self.rows[wearer_id] = {"status": "sheet_saved", "submissionId": operation,
                    "accountHolderName": values['accountHolderName'], "bankLabel": values['bankName'],
                    "maskedAccount": '•••• '+values['accountNumber'][-4:], "submittedAt": "2026-09-19T10:00:00Z"}
            if self.lost_response: raise payment_sheet.PaymentSheetError('payment_sheet_unavailable')
            return self.rows[wearer_id]
    fake = Fake()
    monkeypatch.setattr(payment_sheet, 'PaymentSheetClient', lambda: fake)
    def no_wise(): raise AssertionError('Bank registration must never call Wise')
    monkeypatch.setattr(contributor_wise, 'RecipientClient', no_wise)
    return fake


async def test_setup_needs_auth_contract_and_isolates_contributors(app, db_session):
    async with _client(app) as client:
        assert (await client.get('/api/contributor/bank/setup')).status_code == 401
        await setup(db_session); identity(app)
        assert (await client.get('/api/contributor/bank/setup')).status_code == 409
        await accept(db_session); await setup(db_session, OTHER)
        db_session.add(ContributorRecipientAttempt(id=str(uuid4()),subject=OTHER,
            summary=json.dumps({'accountHolderName':'Other private name'}),status='sheet_saved'))
        await db_session.commit()
        response = await client.get('/api/contributor/bank/setup')
        assert response.status_code == 200 and response.json()['bank'] is None
        assert response.headers['cache-control'] == 'private, no-store'
        assert 'Other private' not in response.text


async def test_web_requires_each_consent_and_current_notice(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    async with _client(app) as client:
        for endpoint in ('/web/requirements', '/web'):
            for key in ('collects_details','shares_details','international_transfer','owns_account'):
                assert (await client.post('/api/contributor/bank'+endpoint,json=body(**{key:False}))).status_code == 422
            assert (await client.post('/api/contributor/bank'+endpoint,json=body(notice_version='old'))).status_code == 409
        response = await client.post('/api/contributor/bank/web/requirements',json=body())
        assert [f['key'] for f in response.json()['fields']] == ['accountHolderName','bankName','accountNumber']
        assert provider.creations == []


async def test_save_only_after_sheet_receipt_masks_database_and_deduplicates(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    async with _client(app) as client:
        for _ in range(2):
            result = await client.post('/api/contributor/bank/web',json=body())
            assert result.status_code == 200, result.text
            assert result.json()['status'] == 'sheet_saved'
        assert len(provider.creations) == 1
        assert provider.creations[0][1]['accountNumber'] == '001234567890'
        attempt = (await db_session.execute(select(ContributorRecipientAttempt))).scalar_one()
        assert attempt.recipient_id is None
        assert '001234567890' not in attempt.summary and '001-234' not in attempt.summary
        assert json.loads(attempt.summary)['payment_consent']['notice'] == public_notice()
        assert (await client.get('/api/contributor/bank/setup')).json()['bank']['maskedAccount'] == '•••• 7890'


async def test_lost_response_recovered_by_setup_without_duplicate(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    provider.lost_response = True
    async with _client(app) as client:
        response = await client.post('/api/contributor/bank/web',json=body())
        assert response.status_code == 503
        assert not (await db_session.execute(select(ContributorRecipientAttempt))).scalars().all()
        response = await client.get('/api/contributor/bank/setup')
        assert response.json()['bank']['status'] == 'sheet_saved'
        provider.lost_response = False
        assert (await client.post('/api/contributor/bank/web',json=body())).json()['status'] == 'sheet_saved'
        assert len(provider.creations) == 1


async def test_unavailable_sheet_never_reports_success(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    provider.unavailable = True
    async with _client(app) as client:
        assert (await client.get('/api/contributor/bank/setup')).status_code == 503
        assert (await client.post('/api/contributor/bank/web',json=body())).status_code == 503
        assert not (await db_session.execute(select(ContributorRecipientAttempt))).scalars().all()


async def test_global_scanner_locks_do_not_block_bank_registration(app, db_session):
    await setup(db_session); await accept(db_session); identity(app)
    engine = create_async_engine(str(db_session.bind.url))
    try:
        async with engine.connect() as scan:
            await scan.execute(text('SELECT pg_advisory_lock(61306133)'))
            await scan.execute(text('SELECT pg_advisory_lock(61306129)'))
            try:
                async with _client(app) as client:
                    result = await asyncio.wait_for(client.post('/api/contributor/bank/web',json=body()),timeout=3)
                    assert result.status_code == 200, result.text
            finally:
                await scan.execute(text('SELECT pg_advisory_unlock_all()'))
    finally: await engine.dispose()


async def test_existing_payment_link_unchanged(app, db_session, provider):
    account=await setup(db_session); await accept(db_session); identity(app)
    db_session.add(PayoutRecipient(wearer_id=account.wearer_id,wise_recipient_id='12345',recipient_hash='a'*64,
        wise_profile_id='1',wise_environment='production',verified_name='Test',updated_by='ops@example.invalid'))
    await db_session.commit()
    async with _client(app) as client:
        assert (await client.post('/api/contributor/bank/web',json=body())).json()['status'] == 'ready'
        assert provider.creations == []


async def test_invalid_fields_and_legacy_routes_never_write(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    async with _client(app) as client:
        response=await client.post('/api/contributor/bank/web',json=body(values={'accountNumber':'1'}))
        assert response.status_code==422 and response.json()['detail']['code']=='invalid_bank_fields'
        for endpoint in ('','/requirements'):
            assert (await client.post('/api/contributor/bank'+endpoint,json={'values':{}})).status_code==410
        assert provider.creations==[]

async def test_resolved_legacy_operation_id_cannot_hide_a_new_sheet_receipt(app, db_session, provider):
    await setup(db_session);await accept(db_session);identity(app)
    operation=str(uuid4())
    db_session.add(ContributorRecipientAttempt(id=operation,subject=SUBJECT,status='retry_allowed',summary='{}'))
    await db_session.commit()
    async with _client(app) as client:
        assert (await client.post('/api/contributor/bank/web',json=body(operation_id=operation))).status_code==409
        assert provider.creations==[]
        assert (await client.post('/api/contributor/bank/web',json=body())).json()['status']=='sheet_saved'
