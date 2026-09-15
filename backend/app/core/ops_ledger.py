"""Contributor time derived from versioned clean intervals, never raw metadata clocks."""

import json
from collections import defaultdict
from datetime import timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.core.ops_artifacts import artifact_status
from app.core.ops_clean import estimate_krw
from app.models import (
    CleanRun,
    Episode,
    FootageReview,
    OpsCamera,
    Payout,
    PayoutItem,
    Wearer,
)

KOREA = ZoneInfo("Asia/Seoul")


def friday(now):
    local = now.astimezone(KOREA)
    due = local.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(
        days=(4 - local.weekday()) % 7
    )
    if due <= local:
        due += timedelta(days=7)
    return due.astimezone(timezone.utc)


def previous_week(due):
    local = due.astimezone(KOREA).date()
    end = local - timedelta(days=local.weekday())
    return (end - timedelta(days=7)).isoformat(), end.isoformat()


def allocate_recording_amounts(recordings, retained_seconds, rate_krw_hour):
    """Allocate the immutable run estimate once, before selecting a payout subset.

    Largest remainders distribute whole won by retained-time weights. Recording
    identity breaks ties, so review order, payout dates and input order cannot
    move rounding between recordings. The run's stored total remains authoritative
    even when a historical manifest's interval sum differs within QC tolerance.
    """
    weights = {
        rec["recording"]: sum(
            (Decimal(str(i["end_s"])) - Decimal(str(i["start_s"]))
             for i in rec.get("intervals", []) if i["disposition"] == "keep"),
            Decimal(0),
        )
        for rec in recordings
    }
    if rate_krw_hour is None:
        return {name: None for name in weights}
    amount = estimate_krw(retained_seconds, rate_krw_hour)
    total_weight = sum(weights.values(), Decimal(0))
    if not total_weight:
        # There is no payable footage to weight. Do not invent a recipient for
        # a nonzero legacy estimate whose accepted intervals are missing.
        return {name: None if amount else 0 for name in weights}
    shares = {name: Decimal(amount) * weight / total_weight for name, weight in weights.items()}
    allocated = {name: int(share) for name, share in shares.items()}
    remainder = amount - sum(allocated.values())
    for name in sorted(shares, key=lambda name: (-(shares[name] - allocated[name]), name))[:remainder]:
        allocated[name] += 1
    return allocated


def price(entries):
    amounts = [e["allocated_krw"] for e in entries]
    return None if any(amount is None for amount in amounts) else sum(amounts)


async def footage_ledger(db):
    runs = (
        (await db.execute(select(CleanRun).order_by(CleanRun.created_at)))
        .scalars()
        .all()
    )
    episodes = {e.recording: e for e in (await db.execute(select(Episode))).scalars()}
    reviews = {
        (r.run_id, r.recording): r
        for r in (await db.execute(select(FootageReview))).scalars()
    }
    items = {
        (r.run_id, r.recording): r
        for r in (await db.execute(select(PayoutItem))).scalars()
    }
    payouts = {p.id: p for p in (await db.execute(select(Payout))).scalars()}
    rows = []
    for run in runs:
        doc = json.loads(run.manifest_json)
        amounts = allocate_recording_amounts(doc["recordings"], run.retained_seconds, run.rate_krw_hour)
        for rec in doc["recordings"]:
            key = (run.run_id, rec["recording"])
            e = episodes.get(rec["recording"])
            review = reviews.get(key)
            item = items.get(key)
            valid = review and review.manifest_sha256 == run.manifest_sha256
            keep = sum(
                i["end_s"] - i["start_s"]
                for i in rec.get("intervals", [])
                if i["disposition"] == "keep"
            )
            reasons = defaultdict(float)
            for i in rec.get("intervals", []):
                if i["disposition"] == "reject":
                    reasons[str(i.get("reason") or "Excluded by QC")] += (
                        i["end_s"] - i["start_s"]
                    )
            collected = (
                review.collection_date
                if valid and review.collection_date
                else (
                    e.started_at.astimezone(KOREA).date().isoformat()
                    if e and e.started_at and e.clock_source == "ntp"
                    else None
                )
            )
            payout = payouts.get(item.payout_id) if item else None
            rows.append(
                {
                    "run_id": run.run_id,
                    "recording": rec["recording"],
                    "manifest_sha256": run.manifest_sha256,
                    "artifact_status": artifact_status(doc),
                    "wearer_id": run.wearer_id,
                    "device_id": run.device_id,
                    "source_seconds": rec.get("source_seconds", 0),
                    "retained_seconds": keep,
                    "rejected_seconds": rec.get("source_seconds", 0) - keep,
                    "rejection_reasons": dict(reasons),
                    "collection_date": collected,
                    "date_basis": "Operator-confirmed"
                    if valid and review.collection_date
                    else "Camera NTP"
                    if collected
                    else "Needs date confirmation",
                    "uploaded_at": e.uploaded_at.isoformat()
                    if e and e.uploaded_at
                    else None,
                    "review_status": review.decision if valid else "needs_review",
                    "reviewer": review.reviewer if valid else None,
                    "review_note": review.note if valid else "",
                    "reviewed_at": review.reviewed_at.isoformat() if valid else None,
                    "rate_krw_hour": run.rate_krw_hour,
                    "allocated_krw": amounts[rec["recording"]],
                    "legacy_paid": run.paid,
                    "payout_id": item.payout_id if item else None,
                    "payment_status": payout.status
                    if payout
                    else "paid"
                    if run.paid
                    else "unapproved",
                    "review_intervals": [
                        i
                        for i in doc.get("review_intervals", [])
                        if i.get("recording") == rec["recording"]
                    ],
                }
            )
    # Older reservations may have been rounded as partial-run subtotals. Their
    # committed amount is authoritative; hold the remainder for reconciliation
    # instead of changing a reservation or silently carrying its discrepancy.
    reserved = defaultdict(list)
    for row in rows:
        if row["payout_id"]:
            reserved[row["payout_id"]].append(row)
    held_runs = {
        row["run_id"]
        for payout_id, entries in reserved.items()
        if price(entries) != payouts[payout_id].amount_krw
        for row in entries
    }
    for row in rows:
        row["allocation_needs_reconciliation"] = row["run_id"] in held_runs
        if row["allocation_needs_reconciliation"] and not row["payout_id"] and not row["legacy_paid"]:
            row["payment_status"] = "needs_reconciliation"
    return rows


async def contributor_summary(db, entries=None):
    entries = entries if entries is not None else await footage_ledger(db)
    people = (await db.execute(select(Wearer).order_by(Wearer.name))).scalars().all()
    cameras = (await db.execute(select(OpsCamera))).scalars().all()
    eps = (await db.execute(select(Episode))).scalars().all()
    result = []
    for p in people:
        clean = [r for r in entries if r["wearer_id"] == p.id]
        raw = [e for e in eps if e.wearer_id == p.id and not e.deleted_at]
        dates = sorted(r["collection_date"] for r in clean if r["collection_date"])
        uploads = sorted(e.uploaded_at.isoformat() for e in raw if e.uploaded_at)
        result.append(
            {
                "wearer_id": p.id,
                "devices": sorted(c.device_id for c in cameras if c.wearer_id == p.id),
                "episodes": len(raw),
                "clean_recordings": len(clean),
                "source_seconds": sum(r["source_seconds"] for r in clean),
                "retained_seconds": sum(r["retained_seconds"] for r in clean),
                "rejected_seconds": sum(r["rejected_seconds"] for r in clean),
                "unpaid_seconds": sum(
                    r["retained_seconds"]
                    for r in clean
                    if r["payment_status"] != "paid"
                ),
                "reviewed_seconds": sum(
                    r["retained_seconds"]
                    for r in clean
                    if r["review_status"] == "reviewed"
                ),
                "pending_recordings": sum(
                    e.recording not in {r["recording"] for r in clean} for e in raw
                ),
                "first_collection_date": dates[0] if dates else None,
                "last_collection_date": dates[-1] if dates else None,
                "dates_unconfirmed": sum(not r["collection_date"] for r in clean),
                "last_upload": uploads[-1] if uploads else None,
            }
        )
    return result
