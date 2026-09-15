"""Clean-time estimates must not create payments or count a source twice."""
import copy
import pytest
from sqlalchemy import select
from app.core.ops_clean import estimate_krw, validate_manifest
from app.models import Wearer, OpsCamera, CleanRun
from tests.test_ops_routes import app, _sid, _client, _episode, ORIGIN


def manifest(run='factory-test'):
    return {'schema':'6thsense-clean-qc/1','run_id':run,'device_id':'ABC123',
        'source_seconds':100,'retained_seconds':60,'rejected_seconds':40,
        'recordings':[{'recording':'ego_20260901_120000_ABC123','source_seconds':100,
            'sources':[{'bucket':'6thsense-raw','key':'sessions/site/ABC123/ego_20260901_120000_ABC123/video.mp4','version_id':'source-v1','sha256':'a'*64}],
            'intervals':[{'start_s':0,'end_s':60,'disposition':'keep'},{'start_s':60,'end_s':100,'disposition':'reject'}]}],
        'outputs':[{'key':f'clean/{run}/joined.mp4','version_id':'output-v1','sha256':'b'*64,'bytes':100}]}


def test_estimate_is_hourly_and_rounds_once():
    assert estimate_krw(3600,11000)==11000
    assert estimate_krw(1800,11000)==5500
    assert estimate_krw(60,11000)==183
    assert estimate_krw(60,None) is None
    assert estimate_krw(60,0)==0
    validate_manifest(manifest())


@pytest.mark.parametrize('fault',['gap','overlap','nan','totals','duplicate','unversioned','outside','missing'])
def test_bad_evidence_is_rejected(fault):
    doc=manifest(); rec=doc['recordings'][0]
    if fault=='gap':rec['intervals'][1]['start_s']=61
    if fault=='overlap':rec['intervals'][1]['start_s']=59
    if fault=='nan':doc['source_seconds']=float('nan')
    if fault=='totals':doc['retained_seconds']=70
    if fault=='duplicate':doc['recordings'].append(copy.deepcopy(rec))
    if fault=='unversioned':rec['sources'][0].pop('version_id')
    if fault=='outside':doc['outputs'][0]['key']='other/joined.mp4'
    if fault=='missing':doc['outputs']=[]
    with pytest.raises(ValueError):validate_manifest(doc)


@pytest.mark.asyncio
async def test_clean_requires_ops(app,db_session):
    sid=await _sid(db_session,'guest')
    async with _client(app) as c:
        assert (await c.get('/api/ops/clean/state',cookies={'sid':sid})).status_code==403
        assert (await c.post('/api/ops/clean/scan',cookies={'sid':sid},headers={'Origin':ORIGIN})).status_code==403


@pytest.mark.asyncio
async def test_camera_assignment_preserves_existing_ownership_and_payments(app,db_session):
    sid=await _sid(db_session,'ops')
    first=Wearer(name='Contributor One',workplace='Printing workshop',rate_krw_hour=11000)
    other=Wearer(name='Other');db_session.add_all([first,other]);await db_session.commit()
    for name,kw in [('free',{}),('assigned',{'wearer_id':other.id}),('paid',{'paid':True})]:
        row=await _episode(db_session,name,**kw);row.device_id='ABC123'
    await db_session.commit()
    async with _client(app) as c:
        res=await c.post('/api/ops/clean/cameras',json={'device_id':'EGO-ABC123','wearer_id':first.id,'assign_unassigned_recordings':True},cookies={'sid':sid},headers={'Origin':ORIGIN})
        assert res.status_code==200,res.text
        rows={e['recording']:e for e in (await c.get('/api/ops/state',cookies={'sid':sid})).json()['episodes']}
    assert rows['free']['wearer_id']==first.id
    assert rows['assigned']['wearer_id']==other.id
    assert rows['paid']['wearer_id'] is None and rows['paid']['paid']


@pytest.mark.asyncio
async def test_import_is_unpaid_idempotent_and_rate_is_snapshotted(app,db_session,monkeypatch):
    from app.api.routes import ops_clean
    from tests.test_ops_artifacts import multimodal_manifest
    sid=await _sid(db_session,'ops')
    wearer=Wearer(name='Contributor One',rate_krw_hour=11000);db_session.add(wearer);await db_session.commit()
    db_session.add(OpsCamera(device_id='ABC123',wearer_id=wearer.id));await db_session.commit()
    doc=multimodal_manifest();monkeypatch.setattr(ops_clean,'committed_results',lambda:[(doc,'qc-results/factory-test/result.json','v1','a'*64)])
    await _episode(db_session,doc['recordings'][0]['recording'],wearer_id=wearer.id)
    async with _client(app) as c:
        async def scan():return await c.post('/api/ops/clean/scan',cookies={'sid':sid},headers={'Origin':ORIGIN})
        first=await scan();assert first.status_code==200,first.text
        assert first.json()['imported']==1
        run=first.json()['runs'][0];assert run['estimated_krw']==183 and run['paid'] is False
        wearer.rate_krw_hour=22000;await db_session.commit()
        again=await scan();assert again.json()['imported']==0
        assert again.json()['runs'][0]['rate_krw_hour']==11000
        doc=manifest('factory-rerun')
        assert (await scan()).status_code==409
    assert len((await db_session.execute(select(CleanRun))).scalars().all())==1


@pytest.mark.asyncio
async def test_unassigned_camera_cannot_create_earnings(app,db_session,monkeypatch):
    from app.api.routes import ops_clean
    sid=await _sid(db_session,'ops')
    monkeypatch.setattr(ops_clean,'committed_results',lambda:[(manifest(),'qc-results/factory-test/result.json','v1','a'*64)])
    async with _client(app) as c:
        res=await c.post('/api/ops/clean/scan',cookies={'sid':sid},headers={'Origin':ORIGIN})
        assert res.status_code==409
    assert not (await db_session.execute(select(CleanRun))).scalars().all()

@pytest.mark.parametrize('tamper',[None,'digest','size','metadata','marker','mixed'])
def test_import_checks_committed_marker_and_output(tamper,monkeypatch):
    import hashlib,json,io
    from app.core import ops_clean
    doc=manifest();body=json.dumps(doc).encode();digest=hashlib.sha256(body).hexdigest()
    marker={'manifest':{'key':'qc-results/factory-test/result.json','version_id':'v1','sha256':digest}}
    if tamper=='digest':marker['manifest']['sha256']='c'*64
    if tamper=='marker':marker['manifest']['key']='qc-results/different/result.json'
    class S3:
        def get_paginator(self,name):return self
        def paginate(self,**kwargs):return [{'Contents':[{'Key':'qc-results/factory-test/_SUCCESS.json'}]+([{'Key':'qc-results/broken/_SUCCESS.json'}] if tamper=='mixed' else [])}]
        def get_object(self,**kwargs):
            if 'broken' in kwargs['Key']:return {'Body':io.BytesIO(b'not json'),'ContentLength':8,'VersionId':'v1'}
            b=json.dumps(marker).encode() if kwargs['Key'].endswith('_SUCCESS.json') else body
            return {'Body':io.BytesIO(b),'ContentLength':len(b),'VersionId':'v1'}
        def head_object(self,**kwargs):
            assert kwargs['VersionId']=='output-v1'
            return {'ContentLength':101 if tamper=='size' else 100,'Metadata':{'sha256':'c'*64 if tamper=='metadata' else 'b'*64}}
    monkeypatch.setattr(ops_clean,'_client',lambda cfg:S3())
    if tamper=='mixed':
        results=ops_clean.committed_results();assert len(results)==1 and len(results.errors)==1
    elif tamper:
        results=ops_clean.committed_results();assert not results and len(results.errors)==1
    else:assert ops_clean.committed_results()[0][3]==digest


def test_duplicate_content_and_nonfinite_recording_time_are_rejected():
    doc=manifest();rec=copy.deepcopy(doc['recordings'][0]);rec['recording']='ego_20260901_130000_ABC123';rec['sources'][0]['key']=rec['sources'][0]['key'].replace('120000','130000');doc['recordings'].append(rec)
    doc.update(source_seconds=200,retained_seconds=120,rejected_seconds=80)
    with pytest.raises(ValueError,match='Duplicate source'):validate_manifest(doc)
    doc=manifest();doc['recordings'][0]['source_seconds']=float('nan')
    with pytest.raises(ValueError):validate_manifest(doc)

@pytest.mark.asyncio
async def test_already_paid_raw_is_not_reimported_as_unpaid(app,db_session,monkeypatch):
    from app.api.routes import ops_clean
    sid=await _sid(db_session,'ops')
    await _episode(db_session,'ego_20260901_120000_ABC123',paid=True)
    monkeypatch.setattr(ops_clean,'committed_results',lambda:[(manifest(),'qc-results/factory-test/result.json','v1','a'*64)])
    async with _client(app) as c:
        res=await c.post('/api/ops/clean/scan',cookies={'sid':sid},headers={'Origin':ORIGIN})
        assert res.status_code==409 and 'already paid' in res.json()['detail']


def test_recording_label_is_bound_to_source_path_and_camera():
    doc=manifest();doc['recordings'][0]['recording']='ego_20260901_130000_ABC123'
    with pytest.raises(ValueError,match='does not belong'):validate_manifest(doc)
    doc=manifest();doc['device_id']='FFFFFF'
    with pytest.raises(ValueError,match='source camera'):validate_manifest(doc)


@pytest.mark.asyncio
async def test_camera_backfill_accepts_historical_id_formats(app,db_session):
    sid=await _sid(db_session,'ops');w=Wearer(name='Contributor');db_session.add(w);await db_session.commit()
    for i,device in enumerate(['abc123','ego-ABC123',' EGO-abc123 ','']):
        e=await _episode(db_session,f'ego_20260901_12000{i}_ABC123');e.device_id=device
    await db_session.commit()
    async with _client(app) as c:
        response=await c.post('/api/ops/clean/cameras',json={'device_id':'ABC123','wearer_id':w.id,'assign_unassigned_recordings':True},cookies={'sid':sid},headers={'Origin':ORIGIN})
        assert response.status_code==200
        rows=(await c.get('/api/ops/state',cookies={'sid':sid})).json()['episodes']
    assert len(rows)==4 and all(e['wearer_id']==w.id for e in rows)
