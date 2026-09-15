import copy
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.core.ops_activity_review import source_recordings, summarize
from app.models import CleanRun
from app.models.ops_activity_review import ActivityReview
from tests.test_ops_routes import app, _sid, _client, ORIGIN
from tests.test_ops_clean import manifest

R = 'ego_20260901_120000_ABC123'
PATH = '/api/ops/clean/runs/review-fixture/activity-review'

def span(start, end, judgment='accepted'):
    return dict(recording=R, start_ns=str(start), end_ns=str(end), judgment=judgment, reason='Explicit fixture criterion')

def payload(**changes):
    return dict(task_id='manipulation', expected_revision=0, manifest_sha256='c'*64,
                criteria_version='v1', criteria_text='Review coherent manipulation; exclude waiting.',
                intervals=[span(0, 10)], **changes)

async def setup(db):
    run = CleanRun(run_id='review-fixture',device_id='ABC123',manifest_key='fixture.json',manifest_version='v1',manifest_sha256='c'*64,
        manifest_json=json.dumps(manifest('review-fixture')),retained_seconds=60,rejected_seconds=40,rate_krw_hour=100,paid=True,amount_krw=50)
    db.add(run);await db.commit()
    return run


def test_exact_ns_and_overlap_union_conflict():
    doc=manifest();doc['recordings'][0]['source_seconds']=0.000000003
    records=source_recordings(SimpleNamespace(manifest_json=json.dumps(doc)))
    assert records[0]['source_duration_ns']=='3'
    result=summarize(records,[span(0,2),span(1,3)])
    assert result[0]['accepted_ns']=='3' and result[0]['unknown_ns']=='0'
    for rows in [[span(0,4)],[span(0,2),span(1,3,'excluded')],[span(0,2),span(1,3,'unknown')]]:
        with pytest.raises(ValueError):summarize(records,rows)
    assert summarize(records,[span(0,1),span(1,2,'excluded')])[0]['unknown_ns']=='1'

@pytest.mark.asyncio
async def test_append_snapshots_conflict_tasks_and_history(app,db_session):
    run=await setup(db_session);sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        headers={'Origin':ORIGIN};cookies={'sid':sid}
        empty=await c.get(PATH+'?task_id=manipulation',cookies=cookies)
        assert empty.status_code==200,empty.text
        assert empty.headers['cache-control']=='no-store'
        assert empty.json()['recordings'][0]['accepted_ns'] is None
        assert empty.json()['revision']==0
        response=await c.post(PATH,json=payload(),headers=headers,cookies=cookies)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['recordings'][0]['accepted_ns']=='10'
        assert result['review']['reviewer_email']=='ops@ops.test'
        assert result['unique_usable_ns'] is None
        assert (await c.post(PATH,json=payload(),headers=headers,cookies=cookies)).status_code==409
        body=payload();body['expected_revision']=1;body['intervals']=[]
        assert (await c.post(PATH,json=body,headers=headers,cookies=cookies)).status_code==200
        hist=await c.get(PATH+'?task_id=manipulation&revision=1',cookies=cookies)
        assert hist.json()['recordings'][0]['accepted_ns']=='10'
        assert hist.json()['latest_revision']==2
        other=payload();other['task_id']='segmentation'
        assert (await c.post(PATH,json=other,headers=headers,cookies=cookies)).status_code==200
        altered=payload();altered['expected_revision']=2;altered['criteria_text']='Different criteria'
        assert (await c.post(PATH,json=altered,headers=headers,cookies=cookies)).status_code==409
        stale=payload();stale['expected_revision']=2;stale['manifest_sha256']='d'*64
        assert (await c.post(PATH,json=stale,headers=headers,cookies=cookies)).status_code==409
    await db_session.refresh(run)
    assert (run.retained_seconds,run.rejected_seconds,run.rate_krw_hour,run.paid,run.amount_krw)==(60,40,100,True,50)
    rows=(await db_session.execute(select(ActivityReview))).scalars().all()
    assert len(rows)==3 and json.loads(rows[0].sources_json)[0]['sources'][0]['version_id']=='source-v1'

@pytest.mark.asyncio
async def test_auth_csrf_spoof_and_body_bound(app,db_session):
    await setup(db_session)
    async with _client(app) as c:
        assert (await c.get(PATH+'?task_id=x')).status_code==401
        guest=await _sid(db_session,'guest')
        assert (await c.get(PATH+'?task_id=x',cookies={'sid':guest})).status_code==403
        sid=await _sid(db_session,'admin');cookies={'sid':sid}
        assert (await c.post(PATH,json=payload(),cookies=cookies)).status_code==403
        body=payload();body['reviewer_email']='spoof@example.test'
        assert (await c.post(PATH,json=body,cookies=cookies,headers={'Origin':ORIGIN})).status_code==422
        assert (await c.post(PATH,content=b'x'*262145,cookies=cookies,headers={'Origin':ORIGIN})).status_code==413

@pytest.mark.asyncio
async def test_manifest_change_history_uses_immutable_source_snapshot(app,db_session):
    run=await setup(db_session);sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        assert (await c.post(PATH,json=payload(),cookies={'sid':sid},headers={'Origin':ORIGIN})).status_code==200
        run.manifest_sha256='d'*64
        doc=manifest();doc['recordings'][0]['source_seconds']=200
        run.manifest_json=json.dumps(doc);await db_session.commit()
        assert (await c.get(PATH+'?task_id=manipulation',cookies={'sid':sid})).status_code==409
        hist=await c.get(PATH+'?task_id=manipulation&revision=1',cookies={'sid':sid})
        assert hist.json()['recordings'][0]['source_duration_ns']=='100000000000'
        assert hist.json()['review']['manifest_sha256']=='c'*64
        assert hist.json()['manifest_sha256']=='c'*64
        assert hist.json()['current_manifest_sha256']=='d'*64
        body=payload();body['manifest_sha256']='d'*64;body['expected_revision']=1
        assert (await c.post(PATH,json=body,cookies={'sid':sid},headers={'Origin':ORIGIN})).status_code==409
        run.manifest_json='corrupt';await db_session.commit()
        hist=await c.get(PATH+'?task_id=manipulation&revision=1',cookies={'sid':sid})
        assert hist.status_code==200

@pytest.mark.parametrize('bad', ['-1','1.5','01',1,True,'1'*25])
def test_nanosecond_contract_is_strict(bad):
    from pydantic import ValidationError
    from app.api.routes.ops_activity_review import ReviewInput
    body=payload();body['intervals'][0]['start_ns']=bad
    with pytest.raises(ValidationError):ReviewInput.model_validate(body)

@pytest.mark.parametrize('seconds',['0.0000000001','1.00000000000000000000000000001','NaN','-1'])
def test_no_rounding_of_source_duration(seconds):
    with pytest.raises(ValueError):
        source_recordings(SimpleNamespace(manifest_json='{"recordings":[{"recording":"r","source_seconds":'+seconds+'}]}'))

@pytest.mark.asyncio
async def test_concurrent_revisions_one_wins(app,db_session):
    import asyncio
    await setup(db_session);sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        results=await asyncio.gather(*[c.post(PATH,json=payload(),cookies={'sid':sid},headers={'Origin':ORIGIN}) for _ in range(2)])
    assert sorted(r.status_code for r in results)==[200,409]
    assert len((await db_session.execute(select(ActivityReview))).scalars().all())==1

@pytest.mark.asyncio
async def test_criteria_version_conflict_across_runs(app,db_session):
    original=await setup(db_session)
    second=CleanRun(run_id='second',device_id='ABC123',manifest_key='other',manifest_version='v1',manifest_sha256='c'*64,
        manifest_json=original.manifest_json,retained_seconds=60,rejected_seconds=40)
    db_session.add(second);await db_session.commit();sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        assert (await c.post(PATH,json=payload(),cookies={'sid':sid},headers={'Origin':ORIGIN})).status_code==200
        body=payload();body['criteria_text']='Different across run'
        result=await c.post(PATH.replace('review-fixture','second'),json=body,cookies={'sid':sid},headers={'Origin':ORIGIN})
        assert result.status_code==409,result.text

@pytest.mark.parametrize('doc',[[],{'recordings':[None]},{'recordings':{}},{'recordings':[{'recording':'r','source_seconds':1,'sources':{}}]}, {'recordings':[{'recording':'r','source_seconds':1,'sources':[{'bucket':'x'}]}]}])
def test_legacy_source_shape_is_rejected(doc):
    with pytest.raises((ValueError,KeyError)):
        source_recordings(SimpleNamespace(manifest_json=json.dumps(doc)))

@pytest.mark.asyncio
async def test_bad_current_manifest_returns_sanitized_409(app,db_session):
    run=await setup(db_session);run.manifest_json='["SECRET"]';await db_session.commit()
    sid=await _sid(db_session,'ops')
    async with _client(app) as c:
        response=await c.get(PATH+'?task_id=test',cookies={'sid':sid})
        assert response.status_code==409 and 'SECRET' not in response.text
