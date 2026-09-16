import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import select, func
from app.core import ops_payment_calculation as calculation
from app.models import OpsSetting, Payout, PayoutItem, Wearer

DUE = datetime(2026, 9, 20, 14, 59, tzinfo=timezone.utc)


def enable(monkeypatch):
    monkeypatch.setenv('OPS_PAYMENT_CALCULATION_ENABLED', 'true')
    monkeypatch.setenv('OPS_PAYMENT_CALCULATION_START_AT', DUE.isoformat())


def test_activation_cutoff_and_catchup(monkeypatch):
    monkeypatch.delenv('OPS_PAYMENT_CALCULATION_ENABLED', raising=False)
    assert calculation.due_calculation(DUE) is None
    enable(monkeypatch)
    assert calculation.due_calculation(DUE - timedelta(microseconds=1)) is None
    assert calculation.due_calculation(DUE) == DUE
    assert calculation.due_calculation(DUE + timedelta(days=2)) == DUE
    assert calculation.due_calculation(DUE + timedelta(days=8)) == DUE + timedelta(days=7)
    monkeypatch.setenv('OPS_PAYMENT_CALCULATION_START_AT', '2026-09-20T23:59:00')
    with pytest.raises(ValueError): calculation.due_calculation(DUE)


def test_exact_four_hours_of_fractional_recordings_is_eligible():
    from app.api.routes.ops_payments import eligible
    durations = [764.66, 1168.72, 1190.29, 286.32, 661.51, 182.55,
                 369.42, 183.17, 990.65, 8602.71]
    rows = [dict(legacy_paid=False, payout_id=None, retained_seconds=s,
                 review_status='reviewed', collection_date='2026-09-20',
                 rate_krw_hour=11000, allocated_krw=1) for s in durations]
    ready, seconds = eligible(rows, DUE, 'accumulated')
    assert seconds == 14400 and ready == rows
    rows[-1]['retained_seconds'] = 8602.70
    ready, seconds = eligible(rows, DUE, 'accumulated')
    assert seconds == 14399.99 and ready == []


@pytest.mark.asyncio
async def test_weekly_import_deduplicates_and_only_calculates(db_session, monkeypatch):
    enable(monkeypatch)
    active = Wearer(name='Active contributor', rate_krw_hour=11000)
    inactive = Wearer(name='Inactive contributor', is_active=False)
    db_session.add_all([active, inactive])
    await db_session.commit()
    base = dict(run_id='run', recording='accepted', manifest_sha256='a'*64,
                wearer_id=active.id, retained_seconds=14400, allocated_krw=44000,
                legacy_paid=False, payout_id=None, review_status='reviewed',
                collection_date='2026-09-20', rate_krw_hour=11000,
                reviewed_at=DUE.isoformat())
    rows = [base]
    for i, change in enumerate([
        {'legacy_paid': True}, {'payout_id': 'reserved'}, {'review_status': 'needs_review'},
        {'counterparty': {'business': 'separate'}}, {'collection_date': None},
        {'collection_date': '2026-09-21'}, {'wearer_id': inactive.id},
        {'reviewed_at': (DUE + timedelta(seconds=1)).isoformat()},
    ]):
        rows.append({**base, 'recording': f'excluded-{i}', **change})
    async def ledger(_): return rows
    monkeypatch.setattr(calculation, 'footage_ledger', ledger)
    from app.api.routes import ops_clean
    scans = []
    async def scan(*args, **kwargs):
        scans.append(1)
        await asyncio.sleep(0.05)
        return {'imported': 1, 'scan_errors': [{'run_id':'invalid'}]}
    monkeypatch.setattr(ops_clean, 'scan', scan)
    results = await asyncio.gather(calculation.tick(DUE), calculation.tick(DUE))
    assert sorted(results) == [False, True]
    assert scans == [1]
    assert await calculation.tick(DUE + timedelta(minutes=1)) is False
    saved = await db_session.get(OpsSetting, calculation.calculation_key(DUE))
    doc = json.loads(saved.value)
    assert doc['mode'] == 'calculation_only' and doc['operator_approval_required']
    assert doc['scan_error_count'] == 1
    assert doc['contributors'] == [{'wearer_id':active.id, 'qualifying_seconds':14400,
        'eligible_krw':44000, 'entries':[{k:base[k] for k in ('run_id','recording','manifest_sha256','retained_seconds','allocated_krw')}]}]
    for model in (Payout, PayoutItem):
        assert (await db_session.execute(select(func.count()).select_from(model))).scalar() == 0
    # A new Sunday is a distinct calculation. Reserved data is excluded again;
    # retries of the old date never mutate the already-persisted snapshot.
    rows[0] = {**base, 'payout_id': 'reserved-later'}
    assert await calculation.tick(DUE + timedelta(days=7)) is True
    await db_session.refresh(saved)
    assert json.loads(saved.value) == doc


@pytest.mark.asyncio
async def test_failed_import_retries_without_marking_week_complete(db_session, monkeypatch):
    enable(monkeypatch)
    from app.api.routes import ops_clean
    async def failed(*args, **kwargs): raise RuntimeError('temporary import failure')
    monkeypatch.setattr(ops_clean, 'scan', failed)
    with pytest.raises(RuntimeError): await calculation.tick(DUE)
    assert await db_session.get(OpsSetting, calculation.calculation_key(DUE)) is None
    async def okay(*args, **kwargs): return {'imported': 0, 'scan_errors': []}
    monkeypatch.setattr(ops_clean, 'scan', okay)
    assert await calculation.tick(DUE + timedelta(minutes=1)) is True
