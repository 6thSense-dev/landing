"""Deletion is durable before enrollment and completion requires actual provider success."""
import asyncio
import json
import pytest
from sqlalchemy import select
from tests.test_contributor_mobile import identity, setup, SUBJECT, REGION, documents
from tests.test_ops_routes import app, _client, _sid, ORIGIN
from app.models import ContributorAccount, Wearer, OpsSetting

PATH = '/api/contributor/account-deletion'

async def test_before_enrollment_idempotent_and_receipt_private(app, db_session):
    identity(app)
    async with _client(app) as c:
        assert (await c.get(PATH)).json()['status'] == 'none'
        assert (await c.post(PATH, json={'confirmed': False})).status_code == 422
        replies = await asyncio.gather(*(c.post(PATH, json={'confirmed': True}) for _ in range(2)))
        assert all(r.status_code == 200 for r in replies)
        assert len({r.json()['request_id'] for r in replies}) == 1
        r = (await c.post(PATH, json={'confirmed': True})).json()
        assert r['status'] == 'requested' and len(r['receipt_token']) == 64
        assert (await c.post('/api/contributor/enrollment', json={'name':'person'})).status_code == 403
        assert await db_session.get(ContributorAccount, SUBJECT) is None
        assert (await c.get(PATH + '/receipt', headers={'Authorization':'Bearer incorrect'})).status_code == 404
        assert (await c.get(PATH + '/receipt', headers={'Authorization':'Bearer '+r['receipt_token']})).json()['request_id'] == r['request_id']
        assert 'receipt_token' not in (await c.get(PATH)).json()
        # Every successful response must remain usable, not just the last one.
        for prior in [reply.json() for reply in replies] + [r]:
            status = await c.get(PATH + '/receipt', headers={'Authorization':'Bearer '+prior['receipt_token']})
            assert status.status_code == 200
            assert status.json()['request_id'] == r['request_id']


async def test_legacy_receipt_and_retry_hashes_remain_private(app, db_session):
    import hashlib
    from app.models import ContributorDeletion, ContributorDeletionReceipt
    legacy_token = 'a' * 64
    legacy_hash = hashlib.sha256(legacy_token.encode()).hexdigest()
    db_session.add(ContributorDeletion(subject=SUBJECT, id='legacy-request',
                                      receipt_hash=legacy_hash, status='requested'))
    await db_session.commit()
    identity(app)
    async with _client(app) as c:
        retry = (await c.post(PATH, json={'confirmed': True})).json()
        assert retry['request_id'] == 'legacy-request'
        for token in [legacy_token, retry['receipt_token']]:
            response = await c.get(PATH+'/receipt', headers={'Authorization': 'Bearer '+token})
            assert response.status_code == 200
            assert set(response.json()) == {'status', 'request_id', 'requested_at', 'expected_completion'}
        assert (await c.get(PATH+'/receipt', headers={'Authorization': 'Bearer '+'f'*64})).status_code == 404
    row = await db_session.get(ContributorDeletion, SUBJECT)
    await db_session.refresh(row)
    assert row.receipt_hash == legacy_hash
    saved = (await db_session.execute(select(ContributorDeletionReceipt))).scalar_one()
    assert saved.receipt_hash == hashlib.sha256(retry['receipt_token'].encode()).hexdigest()
    assert saved.receipt_hash != retry['receipt_token']


def evidence():
    return {'footage_cleanup': 'S3 versions and derived footage removed; evidence ticket A.',
            'processor_cleanup': 'Wise recipient and exported receipts reconciled; ticket B.',
            'retained_records': [{'scope':'consent and payment audit records', 'reason':'Documented legal accounting obligation', 'review_at':'2027-01-01'}]}

@pytest.mark.parametrize("enrolled", [True, False])
async def test_fulfillment_failure_retry_and_scrubbing(app, db_session, monkeypatch, enrolled):
    from app.core import contributor_deletion as deletion
    account = await setup(db_session) if enrolled else None
    if account:
        from app.models import ContributorRecipientAttempt, PayoutRecipient
        from uuid import uuid4
        db_session.add(ContributorRecipientAttempt(id=str(uuid4()),subject=SUBJECT,status='needs_review',recipient_id='123',summary=json.dumps({'accountHolderName':'Private Name','maskedAccount':'1234'})))
        db_session.add(PayoutRecipient(wearer_id=account.wearer_id,wise_recipient_id='123',verified_name='Private Name',updated_by='staff'))
        await db_session.commit()
    identity(app)
    sid = await _sid(db_session, 'ops')
    calls = []
    def failure(subject):
        calls.append(subject)
        raise RuntimeError('secret provider detail')
    monkeypatch.setattr(deletion, 'delete_cognito_user', failure)
    async with _client(app) as c:
        receipt = (await c.post(PATH, json={'confirmed':True})).json()
        retry_receipt = (await c.post(PATH, json={'confirmed':True})).json()
        url = '/api/ops/contributors/deletions/'+receipt['request_id']+'/fulfill'
        assert (await c.post(url, json=evidence())).status_code in (401,403)
        kwargs = {'cookies':{'sid':sid}, 'headers':{'Origin':ORIGIN}}
        assert (await c.post(url, json={}, **kwargs)).status_code == 422
        r = await c.post(url, json=evidence(), **kwargs)
        assert r.status_code == 503 and 'secret' not in r.text
        assert (await c.get(PATH)).json()['status'] == 'processing'
        monkeypatch.setattr(deletion, 'delete_cognito_user', lambda subject: calls.append(subject))
        replies = await asyncio.gather(*(c.post(url, json=evidence(), **kwargs) for _ in range(2)))
        assert all(r.status_code == 200 for r in replies)
        assert len(calls) == 2
        status = await c.get(PATH+'/receipt', headers={'Authorization':'Bearer '+receipt['receipt_token']})
        assert status.json()['status'] == 'completed'
        # Completion remains public only to the bearer after authentication ends.
        from app.core.contributor_auth import contributor_identity
        from fastapi import HTTPException
        def removed_identity():
            raise HTTPException(401, 'authentication_required')
        app.dependency_overrides[contributor_identity] = removed_identity
        assert (await c.get(PATH)).status_code == 401
        for saved in [receipt, retry_receipt]:
            status = await c.get(PATH+'/receipt', headers={'Authorization':'Bearer '+saved['receipt_token']})
            assert status.status_code == 200 and status.json()['status'] == 'completed'
    if account:
        await db_session.refresh(account)
        wearer = await db_session.get(Wearer, account.wearer_id)
        assert not wearer.is_active and wearer.name == 'Deleted contributor' and wearer.contact == ''
        assert await db_session.get(PayoutRecipient, account.wearer_id) is None
        bank=(await db_session.execute(select(ContributorRecipientAttempt))).scalar_one()
        assert bank.summary == '{}' and bank.recipient_id is None and bank.status == 'deleted'

async def test_notice_requires_publication_audit(app, db_session, monkeypatch):
    from app.api.routes import contributor
    class S3:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            assert Params['VersionId'] == 'v1'
            return 'https://example.invalid/final'
    monkeypatch.setattr(contributor, 's3_client', lambda _:S3())
    monkeypatch.setattr(contributor, 's3_settings', lambda:None)
    url='/api/contributor/notice?routing_version='+REGION['routing_version']+'&locale=en'
    async with _client(app) as c:
        assert (await c.get(url)).json()=={'status':'not_published','documents':[]}
        docs=documents()
        pointer=OpsSetting(key='contributor_terms_'+REGION['routing_version'], value=json.dumps(docs))
        db_session.add(pointer); await db_session.commit()
        assert (await c.get(url)).json()['status']=='not_published'
        for d in docs: d['publication_id']='published-id'
        pointer.value=json.dumps(docs)
        db_session.add(OpsSetting(key='contributor_terms_audit_published-id',value=json.dumps({'routing_version':REGION['routing_version'],'documents':docs})))
        await db_session.commit()
        r=await c.get(url)
        assert r.json()['status']=='published' and len(r.json()['documents'])==4
        assert 'key' not in r.json()['documents'][0]

async def test_pending_blocks_actions_and_operator_approvals(app, db_session):
    from app.models import ContributorCameraClaim, OpsCamera, Episode
    from tests.test_contributor_mobile import accept
    account=await setup(db_session)
    db_session.add(Episode(recording='assigned',session='s',device_id='ABC123',wearer_id=account.wearer_id))
    await db_session.commit()
    await accept(db_session)
    identity(app)
    sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        claim=(await c.post('/api/contributor/cameras',json={'device_id':'ABC123'})).json()
        kwargs={'cookies':{'sid':sid},'headers':{'Origin':ORIGIN}}
        url='/api/ops/contributors/cameras/'+claim['id']+'/approve'
        assert (await c.post(url,json={'physically_verified':True},**kwargs)).status_code==200
        assert (await c.post(PATH,json={'confirmed':True})).status_code==200
        for path,body in [('/enrollment',{'name':'new'}),('/cameras',{'device_id':'ABC124'}),('/bank',{}),('/bank/requirements',{})]:
            assert (await c.post('/api/contributor'+path,json=body)).status_code==403
        assert (await c.post(url,json={'physically_verified':True},**kwargs)).status_code in (403,409)
        assert (await c.post('/api/ops/payments/recipient',json={'wearer_id':account.wearer_id,'recipient_id':123,'confirm_recipient':True},**kwargs)).status_code==403
        assert (await c.post('/api/ops/episodes/assigned/assign',json={'wearer_id':None},**kwargs)).status_code==403
        assert (await c.post('/api/ops/wearers/'+str(account.wearer_id),json={'is_active':True},**kwargs)).status_code==403
        assert (await c.post('/api/ops/contributors/consents/export',**kwargs)).json()=={'exported':0}
    camera=await db_session.get(OpsCamera,'ABC123')
    assert camera.wearer_id is None
    assignment=await db_session.get(ContributorCameraClaim,claim['id'])
    assert assignment.ended_at is not None

async def test_enrollment_and_deletion_race_never_leaves_active_account(app, db_session):
    identity(app)
    async with _client(app) as c:
        replies=await asyncio.gather(c.post(PATH,json={'confirmed':True}),c.post('/api/contributor/enrollment',json={'name':'racer'}))
        assert replies[0].status_code==200
        assert replies[1].status_code in (200,403)
    account=await db_session.get(ContributorAccount,SUBJECT)
    if account:
        assert not (await db_session.get(Wearer,account.wearer_id)).is_active

async def test_unknown_bank_outcome_holds_deletion(app, db_session, monkeypatch):
    from app.core import contributor_deletion
    from app.models import ContributorRecipientAttempt
    from uuid import uuid4
    await setup(db_session)
    db_session.add(ContributorRecipientAttempt(id=str(uuid4()),subject=SUBJECT,status='needs_reconciliation',summary='{}'))
    await db_session.commit()
    identity(app); sid=await _sid(db_session,'ops')
    calls=[]
    monkeypatch.setattr(contributor_deletion,'delete_cognito_user',lambda subject:calls.append(subject))
    async with _client(app) as c:
        receipt=(await c.post(PATH,json={'confirmed':True})).json()
        r=await c.post('/api/ops/contributors/deletions/'+receipt['request_id']+'/fulfill',json=evidence(),cookies={'sid':sid},headers={'Origin':ORIGIN})
        assert r.status_code==409 and calls==[]
        assert (await c.get(PATH)).json()['status']=='requested'


def test_cognito_delete_is_idempotent_but_does_not_swallow_provider_failure(monkeypatch):
    from botocore.exceptions import ClientError
    from app.core import contributor_deletion as deletion
    monkeypatch.setenv('CONTRIBUTOR_COGNITO_POOL','test_pool')
    calls=[]
    class Cognito:
        def admin_delete_user(self,**kwargs):
            calls.append(kwargs)
            raise ClientError({'Error':{'Code':code}},'AdminDeleteUser')
    monkeypatch.setattr(deletion.boto3,'client',lambda *args,**kwargs:Cognito())
    code='UserNotFoundException'
    deletion.delete_cognito_user(SUBJECT)
    assert calls==[{'UserPoolId':'test_pool','Username':SUBJECT}]
    code='AccessDeniedException'
    with pytest.raises(ClientError):deletion.delete_cognito_user(SUBJECT)

async def test_deletion_holds_processing_even_previously_completed_jobs(app, db_session, monkeypatch):
    from app.models import Episode, ProcessingJob
    from app.core.ops_processing import reconcile
    account=await setup(db_session)
    db_session.add(Episode(recording='mine',session='session',device_id='ABC123',wearer_id=account.wearer_id))
    db_session.add(ProcessingJob(recording='mine',fingerprint='hash',input_json='{}',state='running',reason='worker',lease_token='old'))
    await db_session.commit()
    identity(app)
    async with _client(app) as c:
        assert (await c.post(PATH,json={'confirmed':True})).status_code==200
    sid=await _sid(db_session,'ops')
    monkeypatch.setenv('OPS_PROCESSOR_TOKEN','test-worker')
    async with _client(app) as c:
        assert (await c.post('/api/ops/processing/mine/retry',cookies={'sid':sid},headers={'Origin':ORIGIN})).status_code==403
        stale=await db_session.get(ProcessingJob,'mine')
        stale.state='retry'
        await db_session.commit()
        assert (await c.post('/api/ops/processing/claim',headers={'Authorization':'Bearer test-worker','Origin':ORIGIN})).json()=={'job':None}
    job=await db_session.get(ProcessingJob,'mine')
    await db_session.refresh(job)
    assert job.state=='blocked' and job.lease_token is None
    jobs=await reconcile(db_session,{'mine':{}},{},[])
    assert jobs['mine'].state=='blocked' and 'deletion' in jobs['mine'].reason

async def test_scan_cannot_restore_jobs_after_deletion_acceptance(app, db_session, monkeypatch):
    from types import SimpleNamespace
    from app.api.routes import ops
    from app.core import ops_processing
    from app.models import Episode, ProcessingJob
    account=await setup(db_session)
    db_session.add(Episode(recording='mine',session='s',device_id='ABC123',wearer_id=account.wearer_id))
    db_session.add(ProcessingJob(recording='mine',fingerprint='old',input_json='{}',state='queued',reason='ready'))
    await db_session.commit()
    identity(app); sid=await _sid(db_session,'ops')
    entered, release=asyncio.Event(),asyncio.Event()
    async def paused_reconcile(db,*args):
        job=await db.get(ProcessingJob,'mine')
        entered.set()
        await release.wait()
        job.state='queued'
    async def raw_context(db):return {},{},[]
    async def state(db):return {}
    monkeypatch.setattr(ops,'walk_bucket',lambda:{})
    monkeypatch.setattr(ops,'_raw_context',raw_context)
    monkeypatch.setattr(ops,'_state',state)
    monkeypatch.setattr(ops,'refresh_source_receipts',lambda *args:[])
    monkeypatch.setattr(ops,'raw_settings',lambda:SimpleNamespace(bucket='test'))
    monkeypatch.setattr(ops_processing,'reconcile',paused_reconcile)
    async with _client(app) as c:
        scan=asyncio.create_task(c.post('/api/ops/scan',cookies={'sid':sid},headers={'Origin':ORIGIN}))
        await asyncio.wait_for(entered.wait(),5)
        deletion=asyncio.create_task(c.post(PATH,json={'confirmed':True}))
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(deletion),.2)
        finally:
            release.set()
            replies=await asyncio.gather(scan,deletion)
        assert all(r.status_code==200 for r in replies)
    assert (await db_session.get(ProcessingJob,'mine')).state=='blocked'


async def test_retry_issuance_limit_preserves_receipts_and_recovers(app, db_session, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func
    from app.api.routes import contributor
    from app.models import ContributorDeletionReceipt
    issued_at = datetime(2026, 9, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(contributor, 'now', lambda: issued_at)
    identity(app)
    async with _client(app) as c:
        original = (await c.post(PATH, json={'confirmed': True})).json()
        tokens = [original['receipt_token']]
        # Fill all but one slot, then race two clients for the final slot.
        for _ in range(contributor.RECEIPT_RETRIES_PER_DAY - 1):
            response = await c.post(PATH, json={'confirmed': True})
            assert response.status_code == 200
            tokens.append(response.json()['receipt_token'])
        replies = await asyncio.gather(*(c.post(PATH, json={'confirmed': True}) for _ in range(2)))
        assert sorted(r.status_code for r in replies) == [200, 429]
        tokens.append(next(r for r in replies if r.status_code == 200).json()['receipt_token'])
        blocked = next(r for r in replies if r.status_code == 429)
        assert blocked.json() == {'detail': 'deletion_receipt_retry_limited'}
        assert blocked.headers['retry-after'] == '86400'
        assert (await db_session.execute(select(func.count()).select_from(ContributorDeletionReceipt))).scalar() == contributor.RECEIPT_RETRIES_PER_DAY
        assert (await c.get(PATH)).json()['request_id'] == original['request_id']
        for token in tokens:
            result = await c.get(PATH+'/receipt', headers={'Authorization':'Bearer '+token})
            assert result.status_code == 200 and result.json()['request_id'] == original['request_id']
        # Limits are per authenticated subject, not an IP-wide signup blocker.
        from app.core.contributor_auth import contributor_identity
        app.dependency_overrides[contributor_identity] = lambda: {'subject':'another-person','region':REGION}
        assert (await c.post(PATH, json={'confirmed': True})).status_code == 200
        identity(app)
        # A fresh process needs no in-memory limiter state; rolling-window expiry
        # permits recovery and never deletes or invalidates prior receipt rows.
        issued_at += timedelta(days=1)
        assert (await c.post(PATH, json={'confirmed': True})).status_code == 200
        assert (await db_session.execute(select(func.count()).select_from(ContributorDeletionReceipt))).scalar() == contributor.RECEIPT_RETRIES_PER_DAY + 1
