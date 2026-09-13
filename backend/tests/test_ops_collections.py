"""A combined video is a viewing convenience, never another payable run."""
import copy
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.core.ops_collections import COLLECTIONS_KEY, validate_collection, collection_playback
from app.models import CleanRun, Wearer
from tests.test_ops_routes import app, _sid, _client


def evidence():
    runs = [SimpleNamespace(run_id=f'batch-{i}', manifest_sha256=str(i)*64, wearer_id=1,
        retained_seconds=60, manifest_json=json.dumps({'outputs': [{'role':'recording_preview','recording':f'ego_2026090{i}_120000_ABC123'}]})) for i in (1,2)]
    doc = {'schema':'6thsense-clean-collection/1','collection_id':'joined-test','wearer_id':1,'payable':False,
        'label':'Two batches','retained_seconds':120,'full_decode_passed':True,
        'source_runs':[{'run_id':r.run_id,'manifest_sha256':r.manifest_sha256} for r in runs],
        'recordings':[{'recording':f'ego_2026090{i}_120000_ABC123'} for i in (1,2)],
        'output':{'key':'clean/collections/joined-test/joined-preview.mp4','version_id':'v1','bytes':100,'sha256':'a'*64}}
    return doc,runs


@pytest.mark.parametrize('fault',['changed_manifest','owner','missing_run','duplicate_run','time','nan','key','version','hash','unchecked','payable','duplicate_recording','order','missing_label','object_label','boolean_bytes'])
def test_collection_cannot_drift_from_original_ledger(fault):
    doc,runs=evidence()
    if fault=='changed_manifest':runs[0].manifest_sha256='f'*64
    if fault=='owner':runs[0].wearer_id=2
    if fault=='missing_run':runs.pop()
    if fault=='duplicate_run':doc['source_runs'][1]=copy.deepcopy(doc['source_runs'][0])
    if fault=='time':doc['retained_seconds']=180
    if fault=='nan':doc['retained_seconds']=float('nan')
    if fault=='key':doc['output']['key']='clean/collections/other/joined-preview.mp4'
    if fault=='version':doc['output']['version_id']='null'
    if fault=='hash':doc['output']['sha256']='invalid'
    if fault=='unchecked':doc['full_decode_passed']=False
    if fault=='payable':doc['payable']=True
    if fault=='duplicate_recording':doc['recordings'][1]=copy.deepcopy(doc['recordings'][0])
    if fault=='order':doc['recordings'].reverse()
    if fault=='missing_label':doc.pop('label')
    if fault=='object_label':doc['label']={}
    if fault=='boolean_bytes':doc['output']['bytes']=True
    with pytest.raises(ValueError):validate_collection(doc,runs)


def test_collection_signs_only_matching_pinned_output(monkeypatch):
    from app.core import ops_collections
    doc,runs=evidence();validate_collection(doc,runs);calls=[]
    class S3:
        def head_object(self,**args):
            calls.append(args);return {'ContentLength':100,'Metadata':{'sha256':'a'*64}}
        def generate_presigned_url(self,method,**args):
            assert args['Params']==calls[0];return 'https://example.test/verified-output'
    monkeypatch.setattr(ops_collections,'_client',lambda _:S3())
    doc['output']['label']={}
    assert collection_playback(doc)[0]['url']=='https://example.test/verified-output'
    assert collection_playback(doc)[0]['label']==doc['label']
    doc['output']['bytes']=101
    with pytest.raises(ValueError):collection_playback(doc)


@pytest.mark.asyncio
async def test_collection_routes_preserve_earnings_and_reject_stale_sources(app,db_session,monkeypatch):
    from app.api.routes.ops import _put_setting
    from app.api.routes import ops_clean
    from tests.test_ops_clean import manifest
    sid=await _sid(db_session,'ops');w=Wearer(name='Contributor',rate_krw_hour=11000);db_session.add(w);await db_session.commit()
    doc,rows=evidence();doc['wearer_id']=w.id
    for i,row in enumerate(rows,1):
        m=manifest(row.run_id);m['outputs'][0].update(role='recording_preview',recording=f'ego_2026090{i}_120000_ABC123')
        db_session.add(CleanRun(run_id=row.run_id,device_id='ABC123',wearer_id=w.id,manifest_key='qc-results/'+row.run_id+'/result.json',manifest_version='v1',manifest_sha256=row.manifest_sha256,manifest_json=json.dumps(m),retained_seconds=60,rejected_seconds=40,rate_krw_hour=11000))
    await db_session.commit()
    async with _client(app) as c:
        before=(await c.get('/api/ops/clean/state',cookies={'sid':sid})).json()
        await _put_setting(db_session,COLLECTIONS_KEY,json.dumps([doc]));await db_session.commit()
        monkeypatch.setattr(ops_clean,'collection_playback',lambda d:[{'url':'https://example.test/joined'}])
        after=(await c.get('/api/ops/clean/state',cookies={'sid':sid})).json()
        assert after['runs']==before['runs'] and len(after['collections'])==1
        assert sum(r['estimated_krw'] for r in after['runs'])==366 and all(not r['paid'] for r in after['runs'])
        assert (await c.get('/api/ops/clean/collections/joined-test/files',cookies={'sid':sid})).status_code==200
        invalid=[]
        for label in [None, {}]:
            bad=copy.deepcopy(doc);bad['label']=label;invalid.append(bad)
        huge=copy.deepcopy(doc);huge['retained_seconds']=10**400;invalid.append(huge)
        await _put_setting(db_session,COLLECTIONS_KEY,json.dumps(invalid+[doc]));await db_session.commit()
        mixed=(await c.get('/api/ops/clean/state',cookies={'sid':sid})).json()
        assert mixed['runs']==before['runs'] and mixed['collections']==after['collections']
        assert mixed['collection_errors']==3
        assert (await c.get('/api/ops/clean/collections/joined-test/files',cookies={'sid':sid})).status_code==200
        await _put_setting(db_session,COLLECTIONS_KEY,json.dumps([doc]));await db_session.commit()
        source=await db_session.get(CleanRun,'batch-1');source.manifest_sha256='f'*64;await db_session.commit()
        state=(await c.get('/api/ops/clean/state',cookies={'sid':sid})).json()
        assert not state['collections'] and state['collection_errors']==1
        assert (await c.get('/api/ops/clean/collections/joined-test/files',cookies={'sid':sid})).status_code==404
        assert len((await db_session.execute(select(CleanRun))).scalars().all())==2


@pytest.mark.asyncio
@pytest.mark.parametrize('config',['not json', '{}', '[null]'])
async def test_malformed_collection_config_does_not_break_clean_state(app,db_session,config):
    from app.api.routes.ops import _put_setting
    sid=await _sid(db_session,'ops')
    await _put_setting(db_session,COLLECTIONS_KEY,config);await db_session.commit()
    async with _client(app) as c:
        response=await c.get('/api/ops/clean/state',cookies={'sid':sid})
        assert response.status_code==200 and response.json()['collection_errors']==1
        assert response.json()['collections']==[]


@pytest.mark.asyncio
async def test_combined_video_requires_ops(app,db_session):
    sid=await _sid(db_session,'guest')
    async with _client(app) as c:
        assert (await c.get('/api/ops/clean/collections/joined-test/files')).status_code==401
        assert (await c.get('/api/ops/clean/collections/joined-test/files',cookies={'sid':sid})).status_code==403
