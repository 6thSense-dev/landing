import copy
import json

import pytest
from sqlalchemy import select
from app.core.ops_external_payments import record_external_payment, external_payment_history
from app.core.ops_ledger import footage_ledger, price
from app.models import CleanRun, Wearer, OpsSetting, Payout, PayoutItem
from tests.test_ops_clean import manifest


async def fixture(db):
    person=Wearer(name="Payment test",rate_krw_hour=11000);db.add(person);await db.flush()
    doc=manifest();run=CleanRun(run_id=doc['run_id'],device_id='ABC123',wearer_id=person.id,
        manifest_key='qc-results/factory-test/result.json',manifest_version='v1',manifest_sha256='a'*64,
        manifest_json=json.dumps(doc),retained_seconds=60,rejected_seconds=40,rate_krw_hour=11000)
    db.add(run);await db.commit()
    ref=dict(bucket='6thsense-contributor-records',key='payment-receipts/test/evidence.json',version_id='v1',sha256='c'*64)
    event=dict(schema='6thsense-external-payment/1',transfer_id='123456',wearer_id=person.id,
        payment_basis='operator_reported_paid',provider_delivery_status='unverified',reported_at='2026-09-15T08:00:00+00:00',
        earnings_krw=183,incentive_krw=20000,total_krw=20183,document=ref,audit_receipt=ref,recording_count=1,
        runs=[dict(run_id=run.run_id,manifest_sha256='a'*64,amount_krw=183,recordings=1,retained_seconds=60)])
    return run,event


@pytest.mark.asyncio
async def test_external_report_clears_only_exact_earnings_and_keeps_incentive_separate(db_session):
    run,event=await fixture(db_session)
    before=(run.manifest_json,run.manifest_sha256,run.retained_seconds,run.rate_krw_hour)
    assert (await record_external_payment(db_session,event))['recorded'] is False
    assert not run.paid and not (await db_session.execute(select(OpsSetting))).scalars().all()
    await record_external_payment(db_session,event,publish=True);await db_session.commit()
    assert run.paid and run.amount_krw==183
    assert before==(run.manifest_json,run.manifest_sha256,run.retained_seconds,run.rate_krw_hour)
    assert (await record_external_payment(db_session,event,publish=True))['idempotent']
    history=await external_payment_history(db_session)
    assert len(history)==1 and history[0]['amount_krw']==20183 and history[0]['incentive_krw']==20000
    assert history[0]['provider_status']=='unverified' and 'document' not in history[0]
    entries=await footage_ledger(db_session)
    assert price([e for e in entries if not e['legacy_paid'] and not e['payout_id']])==0
    assert not (await db_session.execute(select(Payout))).scalars().all()
    assert not (await db_session.execute(select(PayoutItem))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize('fault',['owner','manifest','amount','duplicate','paid','settlement_claim','unversioned','transfer_alias'])
async def test_external_import_rejects_changed_or_ambiguous_evidence(db_session,fault):
    run,event=await fixture(db_session)
    if fault=='owner':event['wearer_id']+=1
    if fault=='manifest':event['runs'][0]['manifest_sha256']='b'*64
    if fault=='amount':event['earnings_krw']+=1;event['total_krw']+=1
    if fault=='duplicate':event['runs'].append(copy.deepcopy(event['runs'][0]))
    if fault=='paid':run.paid=True;await db_session.commit()
    if fault=='settlement_claim':event['provider_delivery_status']='confirmed'
    if fault=='unversioned':event['document']['version_id']='null'
    if fault=='transfer_alias':event['transfer_id']='0123456'
    with pytest.raises(ValueError):await record_external_payment(db_session,event,publish=True)
    assert not (await db_session.execute(select(OpsSetting))).scalars().all()
