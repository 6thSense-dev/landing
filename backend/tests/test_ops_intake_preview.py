from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import pytest
from app.core.ops_intake_preview import digest,load_configured_preview,project_preview
FIXTURE=Path(__file__).parent/'fixtures/intake/synthetic.json'
NOW=datetime(2026,9,10,12,tzinfo=timezone.utc)
def fixture():return json.loads(FIXTURE.read_text())
def seal(doc):
    doc['document_sha256']=digest({k:v for k,v in doc.items() if k!='document_sha256'});return doc
def reseal_report(doc):
    report=doc['accounting_report'];report['report_sha256']=digest({k:v for k,v in report.items() if k!='report_sha256'})
    doc['accounting_report_sha256']=report['report_sha256']
    for rows in doc['judgments'].values():
        for row in rows:row['accounting_report_sha256']=report['report_sha256']
    return seal(doc)
def test_native_report_separate_judgments_immutable():
    doc=fixture();before=deepcopy(doc);report=project_preview(doc,now=NOW);row=report['rows'][0]
    assert doc==before
    assert (row['credit_minor'],row['settled_minor'],row['outstanding_minor'])==('100','40','60')
    assert [row['judgments'][k]['status'] for k in ('capture','annotation','dataset')]==['accepted','rejected','unknown']
    assert row['legacy_paid'] is True and row['correction_count']==1
    assert report['synthetic'] is True and report['authenticity']=='not_verified'
    assert 'imports' not in report and 'accounting' not in report
def test_huge_exact_amount_and_signed_observed_subset():
    doc=fixture();huge=2**100+123;row=doc['accounting_report']['reconciliation']['episodes'][0]
    row.update(obligation_minor=huge,outstanding_minor=None,settled_minor=None,observed_settled_minor=-15)
    result=project_preview(reseal_report(doc),now=NOW)['rows'][0]
    assert result['credit_minor']==str(huge) and result['observed_settled_minor']=='-15'
    assert result['settled_minor'] is None and f'"{huge}"' in json.dumps(result)
def test_source_conflict_hides_money():
    doc=fixture();doc['episode_bindings'][0]['source_sha256']='b'*64
    row=project_preview(seal(doc),now=NOW)['rows'][0]
    assert row['source_binding']=='conflict' and row['credit_minor'] is None
    assert row['legacy_amount_minor'] is None and row['legacy_paid'] is None and row['correction_count'] is None
    assert all(j['status']=='unknown' for j in row['judgments'].values())

@pytest.mark.parametrize('change', ['not_object','missing_field','extra_field','bool_amount','empty_evidence','wrong_episode','wrong_parent','duplicate_id'])
def test_malformed_correction_history_rejected(change):
    doc=fixture();corrections=doc['accounting_report']['reconciliation']['episodes'][0]['corrections']
    if change=='not_object':corrections[0]=None
    elif change=='missing_field':corrections[0].pop('legacy_paid')
    elif change=='extra_field':corrections[0]['note']='unsupported'
    elif change=='bool_amount':corrections[0]['legacy_amount_minor']=True
    elif change=='empty_evidence':corrections[0]['evidence_ids']=[]
    elif change=='wrong_episode':corrections[0]['episode_id']='other-episode'
    elif change=='wrong_parent':corrections[0]['supersedes_id']='other-parent'
    else:corrections.append(dict(corrections[0],supersedes_id=corrections[0]['id']))
    with pytest.raises(ValueError):project_preview(reseal_report(doc),now=NOW)
@pytest.mark.parametrize('field',['source_sha256','accounting_report_sha256'])
def test_annotation_binding_conflict_cannot_debit_credit(field):
    doc=fixture();doc['judgments']['annotation'][0][field]='b'*64
    row=project_preview(seal(doc),now=NOW)['rows'][0]
    assert row['credit_minor']=='100' and row['judgments']['annotation']['reason']=='judgment_binding_conflict'
@pytest.mark.parametrize('change',['missing','duplicate','no_evidence'])
def test_unsupported_judgments_unknown(change):
    doc=fixture();rows=doc['judgments']['capture']
    if change=='missing':rows.clear()
    elif change=='duplicate':rows.append(dict(rows[0],id='different',status='rejected'))
    else:rows[0]['evidence_ids']=[]
    assert project_preview(seal(doc),now=NOW)['rows'][0]['judgments']['capture']['status']=='unknown'
def test_stale_future_no_old_rows():
    assert project_preview(fixture(),now=datetime(2026,9,13,tzinfo=timezone.utc))['rows']==[]
    assert project_preview(fixture(),now=datetime(2026,9,9,tzinfo=timezone.utc))['reasons']==['snapshot_from_future']
@pytest.mark.parametrize('change',['report','import','money','binding_coverage','currency','synthetic'])
def test_malformed_report_rejected(change):
    doc=fixture()
    if change=='report':doc['accounting_report_sha256']='b'*64
    elif change=='import':doc['accounting_report']['imports'][0]['payload']['episodes'][0]['episode']['legacy_paid']=False;reseal_report(doc)
    elif change=='money':doc['accounting_report']['reconciliation']['episodes'][0]['obligation_minor']=True;reseal_report(doc)
    elif change=='binding_coverage':doc['episode_bindings']=[]
    elif change=='currency':doc['accounting_report']['reconciliation']['episodes'][0]['currency']='USD';reseal_report(doc)
    else:doc['synthetic']=False
    with pytest.raises(ValueError):project_preview(seal(doc),now=NOW)
def test_config_pin_duplicate_json_symlink_unknown(tmp_path,monkeypatch):
    monkeypatch.delenv('OPS_INTAKE_PREVIEW_PATH',raising=False);monkeypatch.delenv('OPS_INTAKE_PREVIEW_SHA256',raising=False)
    assert load_configured_preview(now=NOW)['reasons']==['snapshot_not_configured']
    assert load_configured_preview(path=str(FIXTURE),now=NOW)['reasons']==['snapshot_pin_not_configured']
    pin=hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert load_configured_preview(path=str(FIXTURE),expected_sha256=pin,now=NOW)['status']=='supplied_preview'
    assert load_configured_preview(path=str(FIXTURE),expected_sha256='b'*64,now=NOW)['rows']==[]
    path=tmp_path/'duplicate.json';path.write_text('{"schema":1,"schema":2}')
    assert load_configured_preview(path=path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),now=NOW)['rows']==[]
    alias=tmp_path/'alias';alias.symlink_to(FIXTURE.resolve())
    assert load_configured_preview(path=alias,expected_sha256=pin,now=NOW)['rows']==[]
