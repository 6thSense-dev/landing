"""Real Postgres/API isolation and financial retry tests; no external writes."""
import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy import select
from fastapi import HTTPException
from app.core.contributor_auth import contributor_identity, token_claims, REGIONS
from app.core.contributor_attribution import owner_at_capture, end_mobile_assignment
from app.core.contributor_wise import parse_requirements, recipient_body
from app.models import ContributorAccount, ContributorConsent, ContributorCameraClaim, ContributorRecipientAttempt, Wearer, Episode, OpsSetting, OpsCamera
from tests.test_ops_routes import app, _client, _sid, ORIGIN
SUBJECT='11111111-1111-1111-1111-111111111111'
OTHER='22222222-2222-2222-2222-222222222222'
REGION=REGIONS[0]
def identity(app, subject=SUBJECT):
    app.dependency_overrides[contributor_identity]=lambda:{'subject':subject,'region':REGION}
def documents():
    return [{'agreement':k,'version':'v1','sha256':str(i)*64,'locale':'en','key':'terms/korea/'+k+'/v1/en.pdf','object_version':'v1'} for i,k in enumerate(['participation','privacy','collection','international_transfer'],1)]
async def setup(db,subject=SUBJECT):
    w=Wearer(name='Test person',rate_krw_hour=11000);db.add(w);await db.flush()
    a=ContributorAccount(subject=subject,wearer_id=w.id,routing_version=REGION['routing_version']);db.add(a);await db.commit();return a
async def accept(db):
    db.add(OpsSetting(key='contributor_terms_kr-2026-v1',value=json.dumps(documents())))
    db.add(ContributorConsent(id=str(uuid4()),subject=SUBJECT,snapshot=json.dumps({'documents':documents()})));await db.commit()

async def test_mobile_and_staff_auth_are_separate(app,db_session):
    sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        assert (await c.get('/api/contributor/dashboard',cookies={'sid':sid})).status_code==401
        identity(app)
        assert (await c.get('/api/ops/contributors',headers={'Authorization':'Bearer token'})).status_code==401

async def test_idempotent_enrollment_and_own_dashboard(app,db_session):
    identity(app)
    async with _client(app) as c:
        for _ in range(2):assert (await c.post('/api/contributor/enrollment',json={'name':'New person'})).status_code==200
        accounts=(await db_session.execute(select(ContributorAccount))).scalars().all();assert len(accounts)==1
        other=await setup(db_session,OTHER)
        db_session.add_all([Episode(recording='mine',session='s',device_id='ABC123',wearer_id=accounts[0].wearer_id,duration_s=61),Episode(recording='secret_other',session='s',device_id='ABC124',wearer_id=other.wearer_id,duration_s=999)])
        await db_session.commit();r=await c.get('/api/contributor/dashboard');assert r.status_code==200,r.text
        d=r.json();assert d['recorded_seconds']==61 and d['approved_seconds']==0
        assert d['recordings'][0]['approved_seconds'] is None and 'secret_other' not in r.text
        assert not d['consent_current'] and d['payouts']==[]

async def test_consent_missing_stale_and_retries(app,db_session):
    await setup(db_session);identity(app)
    async with _client(app) as c:
        assert (await c.get('/api/contributor/terms')).json()=={'status':'not_published','documents':[]}
        assert (await c.post('/api/contributor/cameras',json={'device_id':'ABC123'})).status_code==409
        assert (await c.post('/api/contributor/bank/requirements',json={'values':{}})).status_code==410
        assert (await c.post('/api/contributor/consent',json={'locale':'en','documents':{},'versions':{}})).status_code==409
        db_session.add(OpsSetting(key='contributor_terms_kr-2026-v1',value=json.dumps(documents())));await db_session.commit()
        body={'locale':'en','documents':{d['agreement']:d['sha256'] for d in documents()},'versions':{d['agreement']:d['version'] for d in documents()}}
        for _ in range(2):assert (await c.post('/api/contributor/consent',json=body)).status_code==200
        assert len((await db_session.execute(select(ContributorConsent))).scalars().all())==1
        r=await c.post('/api/contributor/cameras',json={'device_id':'ego-abc123'});assert r.json()['status']=='pending'
        assert await db_session.get(OpsCamera,'ABC123') is None
        row=await db_session.get(OpsSetting,'contributor_terms_kr-2026-v1');doc=documents();doc[0]['sha256']='a'*64;row.value=json.dumps(doc);await db_session.commit()
        assert not (await c.get('/api/contributor/dashboard')).json()['consent_current']
        assert (await c.post('/api/contributor/consent',json=body)).status_code==409

async def test_camera_supervision_and_capture_intervals(app,db_session):
    a=await setup(db_session);await accept(db_session);identity(app);sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        claim=(await c.post('/api/contributor/cameras',json={'device_id':'ABC123'})).json()
        url='/api/ops/contributors/cameras/'+claim['id']+'/approve'
        assert (await c.post(url,json={'physically_verified':True})).status_code==403
        r=await c.post(url,json={'physically_verified':True},cookies={'sid':sid},headers={'Origin':ORIGIN});assert r.status_code==200,r.text
        start=datetime.fromisoformat(r.json()['effective_at'])
        f={'device_id':'EGO-ABC123','started_at':start+timedelta(seconds=1),'duration_s':60,'complete':True,'clock_source':'ntp'}
        assert await owner_at_capture(db_session,f)==a.wearer_id
        assert await owner_at_capture(db_session,{**f,'started_at':start-timedelta(hours=1)}) is None
        for source in ('unknown','rtc','synced'):
            assert await owner_at_capture(db_session,{**f,'clock_source':source}) is None
        await end_mobile_assignment(db_session,'ABC123',999);await db_session.flush()
        assert await owner_at_capture(db_session,f) is None

def test_token_limits_pool_client_and_kind(monkeypatch):
    monkeypatch.setenv('CONTRIBUTOR_COGNITO_POOL','us-west-2_test');monkeypatch.setenv('CONTRIBUTOR_COGNITO_CLIENT','client')
    claims={'sub':SUBJECT,'iss':'https://cognito-idp.us-west-2.amazonaws.com/us-west-2_test','client_id':'client','token_use':'access'}
    def token(c):return 'header.'+base64.urlsafe_b64encode(json.dumps(c).encode()).decode().rstrip('=')+'.signature'
    assert token_claims(token(claims))['sub']==SUBJECT
    for k,v in [('iss','evil'),('client_id','staff'),('token_use','id')]:
        with pytest.raises(HTTPException):token_claims(token({**claims,k:v}))

async def test_aws_verification_is_authoritative(monkeypatch):
    import app.core.contributor_auth as m
    monkeypatch.setattr(m,'token_claims',lambda _:{'sub':SUBJECT})
    monkeypatch.setattr(m,'cognito_user',lambda _:(_ for _ in ()).throw(RuntimeError('secret-token')))
    with pytest.raises(HTTPException) as exc:await contributor_identity('Bearer plausible')
    assert exc.value.status_code==401 and 'secret' not in exc.value.detail

async def test_legacy_bank_registration_requires_website_without_wise(app,db_session,monkeypatch):
    await setup(db_session);await accept(db_session);identity(app)
    from app.core import contributor_wise as m
    def forbidden(): raise AssertionError('Legacy endpoint must not create Wise recipients')
    monkeypatch.setattr(m,'RecipientClient',forbidden)
    async with _client(app) as c:
        for endpoint in ('','/requirements'):
            result=await c.post('/api/contributor/bank'+endpoint,json={'values':{}})
            assert result.status_code==410
            assert result.json()['detail']=='use_website_bank_registration'
        assert not (await db_session.execute(select(ContributorRecipientAttempt))).scalars().all()

def test_recipient_shape_and_unsupported_field():
    r=recipient_body('IN',{'accountNumber':'001234567','email':'test@example.invalid','accountHolderName':'Test Person'},'123')
    assert r['details']['email']=='test@example.invalid' and r['details']['accountNumber']=='001234567'
    assert r['currency']=='INR' and r['type']=='indian' and r['profile']==123
    with pytest.raises(ValueError):recipient_body('IN',{'bucket':'evil'},'123')
    with pytest.raises(ValueError):parse_requirements([{'type':'indian','fields':[{'key':'unknown','type':'text','required':True}]}],'IN')


def test_provider_acceptance_is_not_operator_ownership_confirmation():
    from app.core.wise import recipient_confirmation_required
    assert recipient_confirmation_required({"confirmations":{"outcomes":[{"requiresCustomerAcceptance":True}]}})
    assert not recipient_confirmation_required({"confirmations":{"outcomes":[{"requiresCustomerAcceptance":False}]}})
    assert not recipient_confirmation_required({})
