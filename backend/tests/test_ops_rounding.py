"""Splitting a run across payment weeks must not change its total earnings."""
import itertools
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.ops_clean import estimate_krw
from app.core.ops_ledger import allocate_recording_amounts, footage_ledger, price
from app.models import CleanRun, FootageReview, Payout, PayoutItem, PayoutRecipient, Wearer
from tests.test_ops_routes import app, _client, _sid, ORIGIN


def recordings(seconds):
    return [
        {"recording": f"ego_20260901_12000{i}_ABC123", "source_seconds": value,
         "intervals": [{"start_s": 0, "end_s": value, "disposition": "keep"}] if value else []}
        for i, value in enumerate(seconds)
    ]


@pytest.mark.parametrize("seconds,total,rate", [
    ([60, 60], 120, 11000),
    ([60, 60, 60], 180, 11000),
    ([0, 1, 2, 7.3], 10.3, 11000),
    ([50.245, 50.245], 100.51, 3600),  # Stored total crosses the rounding boundary.
    ([60, 60], 120, 0),
])
def test_all_subsets_and_input_orders_preserve_the_immutable_run_estimate(seconds, total, rate):
    recs = recordings(seconds)
    allocation = allocate_recording_amounts(recs, total, rate)
    target = estimate_krw(total, rate)
    assert sum(allocation.values()) == target
    for order in itertools.permutations(recs):
        assert allocate_recording_amounts(order, total, rate) == allocation
    for size in range(len(recs) + 1):
        for selected in itertools.combinations(allocation, size):
            first = [{"allocated_krw": amount} for name, amount in allocation.items() if name in selected]
            rest = [{"allocated_krw": amount} for name, amount in allocation.items() if name not in selected]
            assert price(first) + price(rest) == target
    if seconds == [60, 60] and rate == 11000:
        assert list(allocation.values()) == [184, 183]
    if total == 100.51:
        assert target == 101 and sum(seconds) == 100.49


def test_unconfigured_rates_and_empty_footage_do_not_invent_money():
    recs = recordings([0, 0])
    assert list(allocate_recording_amounts(recs, 0, 11000).values()) == [0, 0]
    assert list(allocate_recording_amounts(recs, 0, None).values()) == [None, None]
    assert list(allocate_recording_amounts(recs, 1, 11000).values()) == [None, None]
    assert price([]) == 0
    assert price([{"allocated_krw": None}]) is None


async def seed_run(db):
    person = Wearer(name="Rounding contributor", rate_krw_hour=11000)
    db.add(person)
    await db.flush()
    recs = recordings([14460, 14460])
    doc = {"schema": "6thsense-clean-qc/1", "recordings": recs, "source_seconds": 28920}
    run = CleanRun(
        run_id="rounding-run", device_id="ABC123", wearer_id=person.id,
        manifest_key="rounding-result", manifest_version="v1", manifest_sha256="a" * 64,
        manifest_json=json.dumps(doc), retained_seconds=28920, rejected_seconds=0,
        rate_krw_hour=11000,
    )
    recipient = PayoutRecipient(
        wearer_id=person.id, wise_recipient_id="321", verified_name=person.name,
        updated_by="test", wise_profile_id="123", wise_environment="sandbox", recipient_hash="hash",
    )
    db.add_all([run, recipient])
    await db.commit()
    return person, run, recs


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
async def test_separate_approvals_in_either_order_preserve_run_total_and_rate_snapshot(
    app, db_session, monkeypatch, order
):
    monkeypatch.setenv("WISE_PROFILE_ID", "123")
    monkeypatch.setenv("WISE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WISE_SOURCE_CURRENCY", "USD")
    sid = await _sid(db_session, "ops")
    person, run, recs = await seed_run(db_session)
    expected = allocate_recording_amounts(recs, run.retained_seconds, run.rate_krw_hour)
    first_snapshot = None
    async with _client(app) as client:
        for index in order:
            response = await client.post("/api/ops/payments/review", cookies={"sid": sid},
                headers={"Origin": ORIGIN}, json={
                    "run_id": run.run_id, "recording": recs[index]["recording"],
                    "manifest_sha256": run.manifest_sha256, "decision": "reviewed",
                    "collection_date": "2026-09-01", "watched_all": True,
                })
            assert response.status_code == 200, response.text
            state = (await client.get("/api/ops/payments/state", cookies={"sid": sid})).json()
            contributor = state["contributors"][0]
            assert contributor["eligible_krw"] == expected[recs[index]["recording"]]
            response = await client.post("/api/ops/payments/approve", cookies={"sid": sid},
                headers={"Origin": ORIGIN}, json={
                    "wearer_id": person.id, "entries": contributor["eligible_entries"],
                    "expected_amount_krw": contributor["eligible_krw"],
                    "expected_recipient_revision": contributor["recipient"]["revision"],
                    "approve_payment": True,
                })
            assert response.status_code == 200, response.text
            payouts = response.json()["payouts"]
            if first_snapshot is None:
                first_snapshot = payouts[0]
                # Editing the contributor's future rate must not reprice this run.
                person.rate_krw_hour = 22000
                await db_session.commit()
            else:
                assert next(p for p in payouts if p["id"] == first_snapshot["id"]) == first_snapshot
    payouts = (await db_session.execute(select(Payout))).scalars().all()
    assert len(payouts) == 2
    assert sum(p.amount_krw for p in payouts) == estimate_krw(28920, 11000) == 88367
    assert sorted(p.amount_krw for p in payouts) == [44183, 44184]
    items = (await db_session.execute(select(PayoutItem))).scalars().all()
    assert len(items) == 2 and all(item.rate_krw_hour == 11000 for item in items)


@pytest.mark.asyncio
async def test_pre_fix_reservation_is_preserved_and_remaining_run_requires_reconciliation(db_session):
    from app.api.routes.ops_payments import eligible
    from app.core.ops_ledger import friday
    person, run, recs = await seed_run(db_session)
    previous = Payout(
        id="historical-partial", wearer_id=person.id, amount_krw=44183,
        accepted_seconds=14460, approved_by="old-operator", scheduled_for=datetime.now(timezone.utc),
        recipient_id="321", source_currency="USD", wise_profile_id="123",
        wise_environment="sandbox", recipient_hash="hash", status="approved",
    )
    db_session.add(previous)
    await db_session.flush()
    db_session.add(PayoutItem(run_id=run.run_id, recording=recs[0]["recording"], payout_id=previous.id,
        manifest_sha256=run.manifest_sha256, accepted_seconds=14460, rate_krw_hour=11000,
        collection_date="2026-09-01"))
    db_session.add(FootageReview(run_id=run.run_id, recording=recs[1]["recording"],
        manifest_sha256=run.manifest_sha256, decision="reviewed", reviewer="operator",
        collection_date="2026-09-01"))
    await db_session.commit()
    rows = await footage_ledger(db_session)
    assert all(row["allocation_needs_reconciliation"] for row in rows)
    pending = next(row for row in rows if not row["payout_id"])
    assert pending["payment_status"] == "needs_reconciliation"
    assert eligible(rows, friday(datetime.now(timezone.utc)), "accumulated")[0] == []
    await db_session.refresh(previous)
    assert previous.amount_krw == 44183 and previous.status == "approved"
    assert previous.accepted_seconds == 14460 and previous.recipient_id == "321"
