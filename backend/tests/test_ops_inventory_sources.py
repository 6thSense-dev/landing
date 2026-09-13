import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.core import ops_inventory as inv
from app.core import ops_inventory_sources as sources
from app.api.routes import ops
from app.core.auth_deps import current_user

SOURCE = {'id':'company-raw','label':'Company raw','bucket':'fixture-company-raw','prefix':'sessions/','expected_owner':'537124957922'}

@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.delenv('OPS_INVENTORY_SOURCES',raising=False)
    monkeypatch.setenv('OPS_S3_BUCKET','fixture-operations')


def test_registry_configured_two_accounts_and_default(monkeypatch):
    monkeypatch.setenv('OPS_INVENTORY_SOURCES',json.dumps([SOURCE,{**SOURCE,'id':'production-raw','bucket':'fixture-production-raw','expected_owner':'194680606079'}]))
    monkeypatch.setattr(inv,'_inventory_client',lambda _:pytest.fail('registry must not create AWS client'))
    rows=sources.source_registry()['sources']
    assert len(rows)==3
    assert rows[0]==dict(id='operations',label='Operations raw',bucket='fixture-operations',prefix='',expected_owner=None)
    assert rows[1]['expected_owner']=='537124957922' and rows[2]['expected_owner']=='194680606079'

@pytest.mark.parametrize('raw',['null','{}','not-json',json.dumps([SOURCE]*11),json.dumps([{**SOURCE,'id':'operations'}]),json.dumps([SOURCE,SOURCE]),json.dumps([{**SOURCE,'secret':'SECRET'}])])
def test_malformed_config_sanitized(monkeypatch,raw):
    monkeypatch.setenv('OPS_INVENTORY_SOURCES',raw)
    with pytest.raises(sources.InvalidInventorySources,match='Recording source configuration is invalid'):
        sources.inventory_sources()

@pytest.mark.parametrize('field,value',[('expected_owner',None),('expected_owner','123'),('expected_owner',537124957922),('prefix','sessions'),('prefix','../'),('prefix','sessions/./'),('prefix','sessions/\\/'),('prefix','nul\x00/'),('bucket','127.0.0.1'),('bucket','bad..bucket'),('bucket','BadBucket'),('id','../'),('label','')])
def test_invalid_source_rejected(monkeypatch,field,value):
    monkeypatch.setenv('OPS_INVENTORY_SOURCES',json.dumps([{**SOURCE,field:value}]))
    with pytest.raises(sources.InvalidInventorySources):sources.inventory_sources()

class Client:
    def __init__(self,denied=False):self.calls=[];self.denied=denied
    def list_objects_v2(self,**kwargs):
        self.calls.append(kwargs)
        if self.denied:raise RuntimeError('SECRET PROVIDER ERROR')
        return {'IsTruncated':False,'Contents':[{'Key':'sessions/new-layout/movie.mp4','Size':20}]}
    def close(self):pass

@pytest.mark.parametrize('denied',[False,True])
def test_expected_owner_and_scope_applied(monkeypatch,denied):
    monkeypatch.setenv('OPS_INVENTORY_SOURCES',json.dumps([SOURCE]))
    client=Client(denied)
    monkeypatch.setattr(inv,'_inventory_client',lambda _:client)
    result=inv.inventory_coverage('company-raw')
    assert client.calls==[dict(Bucket=SOURCE['bucket'],Prefix='sessions/',ExpectedBucketOwner=SOURCE['expected_owner'],MaxKeys=1000)]
    assert result['source_id']=='company-raw' and result['scope_prefix']=='sessions/'
    assert result['expected_owner']==SOURCE['expected_owner']
    assert result['listing_complete'] is not denied
    if denied:
        assert result['objects_observed']==0 and result['stop_reason']=='read_error'
        assert 'unknown' in result['limitations'][0]
        assert 'SECRET' not in json.dumps(result)

@pytest.mark.asyncio
async def test_routes_fail_before_aws_and_auth(monkeypatch):
    app=FastAPI();app.include_router(ops.router)
    monkeypatch.setattr(inv,'_inventory_client',lambda _:pytest.fail('must not access AWS'))
    app.dependency_overrides[current_user]=lambda:SimpleNamespace(role='admin')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as c:
        assert (await c.get('/api/ops/inventory-sources')).status_code==200
        assert (await c.get('/api/ops/inventory-coverage?source_id=unlisted')).status_code==404
        monkeypatch.setenv('OPS_INVENTORY_SOURCES','SECRET')
        for path in ['/api/ops/inventory-sources','/api/ops/inventory-coverage']:
            response=await c.get(path)
            assert response.status_code==503 and 'SECRET' not in response.text
        app.dependency_overrides[current_user]=lambda:SimpleNamespace(role='guest')
        assert (await c.get('/api/ops/inventory-sources')).status_code==403


def test_default_does_not_invent_owner(monkeypatch):
    client=Client()
    monkeypatch.setattr(inv,'_inventory_client',lambda _:client)
    result=inv.inventory_coverage()
    assert result['expected_owner'] is None and result['source_id']=='operations'
    assert 'ExpectedBucketOwner' not in client.calls[0]


def test_deep_config_is_sanitized(monkeypatch):
    monkeypatch.setenv('OPS_INVENTORY_SOURCES','['*2000+']'*2000)
    with pytest.raises(sources.InvalidInventorySources):sources.inventory_sources()


def test_out_of_scope_provider_row_cannot_be_reported(monkeypatch):
    monkeypatch.setenv('OPS_INVENTORY_SOURCES',json.dumps([{**SOURCE,'prefix':'different/'}]))
    monkeypatch.setattr(inv,'_inventory_client',lambda _:Client())
    result=inv.inventory_coverage('company-raw')
    assert result['objects_observed']==0
    assert result['stop_reason']=='read_error'
    assert result['listing_complete'] is False


@pytest.mark.parametrize('complete',[True,False])
def test_nested_source_prefix_does_not_claim_parent_metadata_missing(monkeypatch,complete):
    recording='sessions/site/ego_20260903_120000_ABCD'
    scope=recording+'/chunks/'
    monkeypatch.setenv('OPS_INVENTORY_SOURCES',json.dumps([{**SOURCE,'prefix':scope}]))
    class NestedClient(Client):
        def list_objects_v2(self,**kwargs):
            return {'Contents':[{'Key':scope+'001.mp4','Size':3}], 'IsTruncated':not complete}
    monkeypatch.setattr(inv,'_inventory_client',lambda _:NestedClient())
    result=inv.inventory_coverage('company-raw')
    assert result['listing_complete'] is complete
    assert result['recordings_missing_metadata']==0
    assert result['recordings_metadata_outside_scope']==1
    assert result['metadata_scope_complete'] is False
    assert result['examples']['missing_metadata_prefixes']==[]
    assert result['examples']['outside_scope_prefixes']==[recording]
    assert result['scope_prefix']==scope
    assert 'unknown, not missing' in ' '.join(result['limitations'])


@pytest.mark.parametrize('complete',[True,False])
def test_recording_root_scope_can_observe_expected_metadata(complete):
    recording='sessions/site/ego_20260903_120000_ABCD'
    result=inv.build_coverage([{'Key':recording+'/chunks/001.mp4','Size':3}],
        bucket='fixture',listing_complete=complete,scope_prefix=recording+'/')
    assert result['recordings_missing_metadata']==1
    assert result['recordings_metadata_outside_scope']==0
    assert result['metadata_scope_complete'] is True
    assert result['examples']['missing_metadata_prefixes']==[recording]
    if not complete:
        assert 'not yet observed' in ' '.join(result['limitations'])
