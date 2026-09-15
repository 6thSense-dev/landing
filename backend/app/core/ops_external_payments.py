"""Audited external payment bookkeeping; this module never calls a payment API."""
import json
import re
from datetime import datetime

from sqlalchemy import select, text
from app.core.ops_clean import estimate_krw
from app.models import CleanRun, OpsSetting, Payout, PayoutItem

PREFIX = "external_payment:wise:"


async def record_external_payment(db, event, *, publish=False):
    """Privileged maintenance entry point, not exposed as an HTTP endpoint.

    The operator attests payment; a funding-instructions PDF does not establish
    provider settlement. Preserve those two facts separately in the audit event.
    Entire, exact Clean runs are marked paid for bookkeeping; rates/time/QC stay frozen.
    """
    if event.get("schema") != "6thsense-external-payment/1" or not re.fullmatch(r"[1-9][0-9]{0,19}", event.get("transfer_id", "")):
        raise ValueError("Invalid external payment identity")
    if event.get("payment_basis") != "operator_reported_paid" or event.get("provider_delivery_status") != "unverified":
        raise ValueError("This import records an operator report, not confirmed provider delivery")
    for field in ("earnings_krw", "incentive_krw", "total_krw"):
        if type(event.get(field)) is not int or event[field] < 0:
            raise ValueError("Payment amounts must be nonnegative whole won")
    if event["earnings_krw"] <= 0 or event["earnings_krw"] + event["incentive_krw"] != event["total_krw"]:
        raise ValueError("Earnings and incentive must match the actual total")
    reported_at = datetime.fromisoformat(event["reported_at"])
    if reported_at.tzinfo is None:
        raise ValueError("Payment report time must include its timezone")
    for ref in (event.get("document", {}), event.get("audit_receipt", {})):
        if ref.get("bucket") != "6thsense-contributor-records" or not ref.get("key", "").startswith("payment-receipts/") or ref.get("version_id") in (None, "", "null") or not re.fullmatch(r"[a-f0-9]{64}", ref.get("sha256", "")):
            raise ValueError("Pinned private payment evidence is required")
    key = PREFIX + event["transfer_id"]
    await db.execute(text("SELECT pg_advisory_xact_lock(61306130)"))
    await db.execute(text("SELECT pg_advisory_xact_lock(61306131)"))
    existing = await db.get(OpsSetting, key)
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
    if existing:
        if existing.value != encoded:
            raise ValueError("External transfer is already recorded with different evidence")
        return {"recorded":True, "idempotent":True}
    if (await db.execute(select(Payout.id).where(Payout.transfer_id == event["transfer_id"]))).first():
        raise ValueError("This Wise transfer is already in the payout ledger")
    expected = {r["run_id"]: r for r in event.get("runs", [])}
    if not expected or len(expected) != len(event["runs"]):
        raise ValueError("Exact distinct Clean runs are required")
    runs = (await db.execute(select(CleanRun).where(CleanRun.run_id.in_(expected)).with_for_update())).scalars().all()
    if len(runs) != len(expected):
        raise ValueError("A paid Clean run is missing")
    if (await db.execute(select(PayoutItem).where(PayoutItem.run_id.in_(expected)))).first():
        raise ValueError("Footage already has a payment reservation")
    total = count = 0
    for run in runs:
        ref = expected[run.run_id]
        if run.paid or run.wearer_id != event["wearer_id"] or run.manifest_sha256 != ref["manifest_sha256"]:
            raise ValueError("Clean ownership, payment status or QC changed")
        amount = estimate_krw(run.retained_seconds, run.rate_krw_hour)
        recordings = len(json.loads(run.manifest_json)["recordings"])
        if amount is None or amount != ref["amount_krw"] or recordings != ref["recordings"] or run.retained_seconds != ref["retained_seconds"]:
            raise ValueError("Clean earnings or recording coverage changed")
        total += amount
        count += recordings
    if total != event["earnings_krw"] or count != event["recording_count"]:
        raise ValueError("Payment does not match the selected footage")
    if publish:
        for run in runs:
            run.paid = True
            run.paid_at = reported_at
            # An incentive is not additional footage time or a higher hourly rate.
            run.amount_krw = expected[run.run_id]["amount_krw"]
        db.add(OpsSetting(key=key, value=encoded))
        await db.flush()
    return {"recorded":publish, "idempotent":False, "recordings":count,
            "earnings_krw":total, "incentive_krw":event["incentive_krw"], "total_krw":event["total_krw"]}


async def external_payment_history(db):
    """Expose the bookkeeping breakdown, never the bank details or document URL."""
    rows = (await db.execute(select(OpsSetting).where(OpsSetting.key.startswith(PREFIX)))).scalars().all()
    result = []
    for row in rows:
        event = json.loads(row.value)
        if event.get("schema") != "6thsense-external-payment/1":
            continue
        result.append(dict(id=row.key,wearer_id=event["wearer_id"],amount_krw=event["total_krw"],
                           earnings_krw=event["earnings_krw"],incentive_krw=event["incentive_krw"],
                           accepted_seconds=sum(r["retained_seconds"] for r in event["runs"]),
                           status="paid (operator reported)",approved_by="Operator report",
                           approved_at=event["reported_at"],scheduled_for=event["reported_at"],
                           transfer_id=event["transfer_id"],provider_status=event["provider_delivery_status"],
                           error="",external=True))
    return result
