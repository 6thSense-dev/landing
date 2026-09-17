"""Immutable signed evidence and verified identity preserve payment histories."""
import hashlib
import hmac
import json
import time
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.api.routes import form_contracts as m
from app.models import ContributorAccount, ContributorDeletion, Wearer
from app.models.form_contract import FormContract
from tests.test_ops_routes import app, _client
from tests.test_contributor_mobile import identity, setup, accept, SUBJECT, OTHER

PHONE = '+821012345678'
SECRET = 'test-only-secret-never-deploy-' * 2
BUNDLE = {'form_id':'test-form-id-123', 'version':'v1', 'terms_sha256':'a'*64,
          'effective_at':'2026-01-01T00:00:00+00:00', 'rate_krw_hour':11000,
          'url':'https://docs.google.com/forms/d/e/test-form/viewform'}

def provider(subject=SUBJECT, phone=PHONE, verified='true'):
    return {'UserAttributes':[{'Name':k,'Value':v} for k,v in {
        'sub':subject,'phone_number':phone,'phone_number_verified':verified}.items()]}

@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setenv('CONTRIBUTOR_FORM_ENABLED','true')
    monkeypatch.setenv('CONTRIBUTOR_FORM_BUNDLE',json.dumps(BUNDLE))
    monkeypatch.setenv('CONTRIBUTOR_FORM_SYNC_SECRET',SECRET)
    monkeypatch.setenv('CONTRIBUTOR_FORM_PHONE_KEY','phone-digest-test-key-'*3)
    monkeypatch.setattr(m,'cognito_user',lambda _:provider())

def evidence(**kw):
    return {'response_id':'response-one','form_id':BUNDLE['form_id'],'version':'v1',
        'terms_sha256':'a'*64,'receipt_sha256':'b'*64,'phone':PHONE,
        'name':'New contractor','signature':'New contractor','signed_at':'2026-01-02T00:00:00+00:00',
        'accepted':{key:True for key in ('participation','collection','privacy','international_transfer','adult')},**kw}

async def send(c,data=None,stamp=None,secret=SECRET):
    body=json.dumps(data or evidence());stamp=stamp or str(int(time.time()))
    sig=hmac.new(secret.encode(),(stamp+'.'+body).encode(),hashlib.sha256).hexdigest()
    return await c.post('/api/form-contracts/sync',content=body,headers={
        'Content-Type':'application/json','X-Form-Timestamp':stamp,'X-Form-Signature':sig})

async def activate(c):
    return await c.post('/api/form-contracts/activate',headers={'Authorization':'Bearer test-access'})

async def test_configuration_authentication_and_body_cap(app,monkeypatch):
    async with _client(app) as c:
        r=await c.get('/api/form-contracts/configuration')
        assert r.json()['rate_krw_hour']==11000 and r.headers['cache-control']=='no-store'
        assert (await send(c,secret='wrong')).status_code==401
        assert (await send(c,stamp=str(int(time.time())-301))).status_code==401
        assert (await send(c,stamp='1'*5000)).status_code==401
        assert (await activate(c)).status_code==401
        assert (await c.post('/api/form-contracts/sync',content='x'*8193)).status_code==413
        for bad in [{**BUNDLE,'effective_at':'bad'},[],{**BUNDLE,'url':'https://evil.invalid'}]:
            monkeypatch.setenv('CONTRIBUTOR_FORM_BUNDLE',json.dumps(bad))
            assert (await c.get('/api/form-contracts/configuration')).status_code==503

@pytest.mark.parametrize('changes,code',[
    ({'password':'must-never-echo'},422),({'version':'application-only'},409),
    ({'signature':'Someone else'},409),({'name':' ','signature':' '},409),
    ({'signed_at':'2025-01-01T00:00:00+00:00'},409),({'signed_at':'2026-01-01T00:00:00'},409),
    ({'phone':'+12025550123'},422),({'accepted':{'participation':True}},409),
    ({'accepted':{**evidence()['accepted'],'adult':'true'}},422)])
async def test_invalid_evidence(app,changes,code):
    async with _client(app) as c:
        r=await send(c,evidence(**changes));assert r.status_code==code,r.text
        assert 'must-never-echo' not in r.text and PHONE not in r.text

async def test_idempotent_activation_and_withdrawal(app,db_session):
    identity(app)
    async with _client(app) as c:
        first=await send(c);assert first.status_code==200,first.text
        assert (await send(c)).json()==first.json()
        assert not list((await db_session.execute(select(ContributorAccount))).scalars())
        for _ in range(2):
            r=await activate(c);assert r.status_code==200,r.text
        rows=list((await db_session.execute(select(FormContract))).scalars())
        assert len(rows)==1 and PHONE not in rows[0].source_json
        account=await db_session.get(ContributorAccount,SUBJECT)
        wearer=await db_session.get(Wearer,account.wearer_id)
        assert wearer.rate_krw_hour==11000 and await m.has_form_consent(account,db_session)
        assert (await send(c)).json()['linked']
        assert (await send(c,evidence(name='Altered',signature='Altered'))).status_code==409
        await accept(db_session)
        assert (await send(c,evidence(state='withdrawn'))).status_code==200
        await db_session.refresh(rows[0])
        from app.api.routes.contributor import has_consent
        assert not await has_consent(account,{},db_session)
        assert (await send(c)).json()['detail']=='withdrawn_contract_cannot_be_reactivated'

async def test_existing_account_keeps_rate_and_history(app,db_session):
    account=await setup(db_session);wearer=await db_session.get(Wearer,account.wearer_id)
    wearer.rate_krw_hour=15000;await db_session.commit();identity(app)
    async with _client(app) as c:
        await send(c);assert (await activate(c)).status_code==200
    await db_session.refresh(wearer)
    assert wearer.rate_krw_hour==15000 and len(list((await db_session.execute(select(Wearer))).scalars()))==1

async def test_duplicate_phone_or_other_subject_requires_review(app,monkeypatch):
    identity(app)
    async with _client(app) as c:
        await send(c);assert (await activate(c)).status_code==200
        identity(app,OTHER);monkeypatch.setattr(m,'cognito_user',lambda _:provider(OTHER))
        assert (await activate(c)).status_code==409
        identity(app);monkeypatch.setattr(m,'cognito_user',lambda _:provider())
        await send(c,evidence(response_id='another-response'))
        assert (await activate(c)).json()['detail']=='contract_identity_review_required'

async def test_legacy_name_needs_staff_link_and_deletion_remains_blocked(app,db_session):
    wearer=Wearer(name='New contractor',rate_krw_hour=11000);db_session.add(wearer)
    await db_session.commit();identity(app)
    async with _client(app) as c:
        await send(c)
        assert (await activate(c)).json()['detail']=='contract_identity_review_required'
        assert (await send(c,evidence(wearer_id=wearer.id))).status_code==200
        assert (await activate(c)).status_code==200
        account=await db_session.get(ContributorAccount,SUBJECT);assert account.wearer_id==wearer.id
        db_session.add(ContributorDeletion(subject=SUBJECT,id=str(uuid4()),receipt_hash='c'*64));await db_session.commit()
        assert (await activate(c)).json()['detail']=='account_deletion_pending'

@pytest.mark.parametrize('phone,verified,code',[(PHONE,'false',401),('+821099998888','true',409)])
async def test_provider_phone_overrides_browser_input(app,monkeypatch,phone,verified,code):
    identity(app);monkeypatch.setattr(m,'cognito_user',lambda _:provider(phone=phone,verified=verified))
    async with _client(app) as c:
        await send(c)
        r=await c.post('/api/form-contracts/activate',json={'phone':PHONE},headers={'Authorization':'Bearer test-access'})
        assert r.status_code==code

async def test_korean_contract_cannot_link_another_routing_region(app):
    from app.core.contributor_auth import contributor_identity
    app.dependency_overrides[contributor_identity]=lambda:{'subject':SUBJECT,'region':{'routing_version':'in-2026-v1'}}
    async with _client(app) as c:
        await send(c)
        assert (await activate(c)).json()['detail']=='contract_region_mismatch'
