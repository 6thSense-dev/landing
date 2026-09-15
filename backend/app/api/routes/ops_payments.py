"""Payment approval reserves exact reviewed footage; future footage is never included."""

import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from app.api.routes.ops import require_ops
from app.core.db import get_session
from app.core.ops_external_payments import external_payment_history
from app.core.ops_ledger import (
    footage_ledger,
    friday,
    previous_week,
    price,
    KOREA,
)
from app.models import (
    CleanRun,
    FootageReview,
    Payout,
    PayoutItem,
    PayoutRecipient,
    Wearer,
)

router = APIRouter(prefix="/api/ops/payments", tags=["ops"])


def configuration():
    return {
        "timezone": "Asia/Seoul",
        "payday": "Friday 18:00",
        "threshold_seconds": 14400,
        "threshold_rule": "strictly_more_than",
        "threshold_basis": "accumulated",
        "wise_environment": os.getenv("WISE_ENVIRONMENT", "sandbox"),
        "source_currency": os.getenv("WISE_SOURCE_CURRENCY", "USD"),
        "wise_configured": bool(
            os.getenv("WISE_API_TOKEN")
            and os.getenv("WISE_PROFILE_ID")
            and os.getenv("WISE_SOURCE_CURRENCY", "USD")
        ),
        "automatic_funding_enabled": os.getenv("OPS_WISE_AUTO_FUND") == "true",
        "automatic_payouts_enabled": os.getenv("OPS_PAYOUT_AUTOMATION_ENABLED") == "true",
    }


def recipient_revision(recipient):
    """Fence approval against the exact recipient the operator reviewed."""
    identity = [
        recipient.wearer_id,
        recipient.wise_recipient_id,
        recipient.recipient_hash,
        recipient.wise_profile_id,
        recipient.wise_environment,
        recipient.verified_name,
    ]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def eligible(entries, due, basis):
    start, end = previous_week(due)
    ready = [
        e
        for e in entries
        if not e["legacy_paid"]
        and not e["payout_id"]
        and e["retained_seconds"] > 0
        and e["review_status"] == "reviewed"
        and e["collection_date"]
        and e["collection_date"] < end
        and e["rate_krw_hour"] is not None
        and e["allocated_krw"] is not None
        and not e.get("allocation_needs_reconciliation", False)
    ]
    qualifying = sum(
        e["retained_seconds"]
        for e in ready
        if basis == "accumulated" or start <= e["collection_date"] < end
    )
    return ready if qualifying > 14400 else [], qualifying


async def state(db):
    entries = await footage_ledger(db)
    due = friday(datetime.now(timezone.utc))
    cfg = configuration()
    recipients = {
        r.wearer_id: r for r in (await db.execute(select(PayoutRecipient))).scalars()
    }
    people = (await db.execute(select(Wearer).order_by(Wearer.name))).scalars().all()
    payouts = (
        (await db.execute(select(Payout).order_by(Payout.approved_at.desc())))
        .scalars()
        .all()
    )
    groups = []
    for p in people:
        rows = [e for e in entries if e["wearer_id"] == p.id]
        ready, qualifying = eligible(rows, due, cfg["threshold_basis"])
        recipient = recipients.get(p.id)
        groups.append(
            {
                "wearer_id": p.id,
                "name": p.name,
                "workplace": p.workplace,
                "is_active": p.is_active,
                "entries": rows,
                "due_krw": price(
                    [e for e in rows if not e["legacy_paid"] and not e["payout_id"]]
                ),
                "eligible_entries": [
                    {
                        "run_id": e["run_id"],
                        "recording": e["recording"],
                        "manifest_sha256": e["manifest_sha256"],
                    }
                    for e in ready
                ],
                "eligible_krw": price(ready),
                "qualifying_seconds": qualifying,
                "recipient": {
                    "id": recipient.wise_recipient_id,
                    "name": recipient.verified_name,
                    "revision": recipient_revision(recipient),
                }
                if recipient
                else None,
            }
        )
    return {
        "contributors": groups,
        "configuration": cfg,
        "scheduled_for": due.isoformat(),
        "collection_week": previous_week(due),
        "payouts": [
            {
                "id": p.id,
                "wearer_id": p.wearer_id,
                "amount_krw": p.amount_krw,
                "accepted_seconds": p.accepted_seconds,
                "status": p.status,
                "approved_by": p.approved_by,
                "approved_at": p.approved_at.isoformat(),
                "scheduled_for": p.scheduled_for.isoformat(),
                "transfer_id": p.transfer_id,
                "provider_status": p.provider_status,
                "error": p.error,
            }
            for p in payouts
        ] + await external_payment_history(db),
    }


@router.get("/state")
async def get_state(_=Depends(require_ops), db=Depends(get_session)):
    return await state(db)


class ReviewIn(BaseModel):
    run_id: str
    recording: str
    manifest_sha256: str
    decision: str
    collection_date: date | None = None
    note: str = Field(default="", max_length=2000)
    watched_all: bool = False


@router.post("/review")
async def review(body: ReviewIn, user=Depends(require_ops), db=Depends(get_session)):
    if body.decision not in ("reviewed", "needs_review", "withheld"):
        raise HTTPException(422, "Invalid review decision.")
    if body.decision == "reviewed" and not body.watched_all:
        raise HTTPException(
            422,
            "Confirm that all retained footage and flagged intervals were reviewed.",
        )
    if body.decision == "withheld" and not body.note.strip():
        raise HTTPException(
            422, "A reason is required when withholding footage from payment."
        )
    if body.collection_date and body.collection_date > datetime.now(KOREA).date():
        raise HTTPException(422, "Collection date cannot be in the future.")
    await db.execute(text("SELECT pg_advisory_xact_lock(61306131)"))
    run = await db.get(CleanRun, body.run_id)
    if not run or run.manifest_sha256 != body.manifest_sha256:
        raise HTTPException(409, "Footage changed. Reload before reviewing.")
    if body.recording not in {
        r["recording"] for r in json.loads(run.manifest_json)["recordings"]
    }:
        raise HTTPException(404, "Unknown recording.")
    if run.paid or await db.get(PayoutItem, (body.run_id, body.recording)):
        raise HTTPException(
            409, "This footage is reserved or paid; its review is locked."
        )
    record = await db.get(FootageReview, (body.run_id, body.recording))
    if record is None:
        record = FootageReview(run_id=body.run_id, recording=body.recording)
        db.add(record)
    record.manifest_sha256 = body.manifest_sha256
    record.decision = body.decision
    record.reviewer = user.email
    record.reviewed_at = datetime.now(timezone.utc)
    record.note = body.note.strip()
    record.collection_date = (
        body.collection_date.isoformat() if body.collection_date else None
    )
    await db.commit()
    return {"ok": True}


class EntryIn(BaseModel):
    run_id: str
    recording: str
    manifest_sha256: str


class ApproveIn(BaseModel):
    wearer_id: int
    entries: list[EntryIn] = Field(min_length=1, max_length=2000)
    expected_amount_krw: int = Field(gt=0)
    expected_recipient_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    approve_payment: bool = False


@router.post("/approve")
async def approve(body: ApproveIn, user=Depends(require_ops), db=Depends(get_session)):
    if not body.approve_payment:
        raise HTTPException(422, "Explicit payment approval is required.")
    await db.execute(text("SELECT pg_advisory_xact_lock(61306131)"))
    person = await db.get(Wearer, body.wearer_id)
    recipient = await db.get(PayoutRecipient, body.wearer_id)
    cfg = configuration()
    if not person or not person.is_active or not recipient:
        raise HTTPException(
            409, "An active contributor and verified Wise recipient are required."
        )
    if recipient_revision(recipient) != body.expected_recipient_revision:
        raise HTTPException(
            409, "Payment recipient changed. Reload and review the recipient before approving."
        )
    if recipient.wise_profile_id != os.getenv(
        "WISE_PROFILE_ID", ""
    ) or recipient.wise_environment != os.getenv("WISE_ENVIRONMENT", "sandbox"):
        raise HTTPException(
            409, "Verify the recipient in the currently configured Wise account."
        )
    if not cfg["source_currency"] or not recipient.recipient_hash:
        raise HTTPException(
            409, "Configure the Wise funding currency before approving payment."
        )
    due = friday(datetime.now(timezone.utc))
    rows = [e for e in await footage_ledger(db) if e["wearer_id"] == body.wearer_id]
    ready, _ = eligible(rows, due, cfg["threshold_basis"])
    requested = {(e.run_id, e.recording, e.manifest_sha256) for e in body.entries}
    actual = {(e["run_id"], e["recording"], e["manifest_sha256"]) for e in ready}
    if len(requested) != len(body.entries) or requested != actual:
        raise HTTPException(
            409, "Eligibility or review changed. Reload the payment breakdown."
        )
    amount = price(ready)
    if not amount or amount != body.expected_amount_krw:
        raise HTTPException(409, "Payment amount changed. Reload before approving.")
    payout = Payout(
        id=str(uuid.uuid4()),
        wearer_id=person.id,
        amount_krw=amount,
        accepted_seconds=sum(e["retained_seconds"] for e in ready),
        status="approved",
        approved_by=user.email,
        scheduled_for=due,
        recipient_id=recipient.wise_recipient_id,
        source_currency=cfg["source_currency"],
        wise_profile_id=recipient.wise_profile_id,
        wise_environment=recipient.wise_environment,
        recipient_hash=recipient.recipient_hash,
    )
    db.add(payout)
    await db.flush()
    for e in ready:
        db.add(
            PayoutItem(
                run_id=e["run_id"],
                recording=e["recording"],
                payout_id=payout.id,
                manifest_sha256=e["manifest_sha256"],
                accepted_seconds=e["retained_seconds"],
                rate_krw_hour=e["rate_krw_hour"],
                collection_date=e["collection_date"],
            )
        )
    await db.commit()
    return await state(db)


class RecipientIn(BaseModel):
    wearer_id: int
    recipient_id: int = Field(gt=0)
    confirm_recipient: bool = False


@router.post("/recipient")
async def recipient(
    body: RecipientIn, user=Depends(require_ops), db=Depends(get_session)
):
    from app.core.wise import WiseClient

    if not body.confirm_recipient:
        raise HTTPException(422, "Confirm the recipient belongs to this contributor.")
    person = await db.get(Wearer, body.wearer_id)
    if not person:
        raise HTTPException(404, "Unknown contributor.")
    import asyncio

    try:
        info = await asyncio.to_thread(WiseClient().recipient, body.recipient_id)
    except Exception:
        raise HTTPException(
            502,
            "Wise recipient verification failed. Check the connection and recipient ID.",
        )
    if (
        not info.get("active")
        or not info.get("hash")
        or info.get("currency") != "KRW"
        or str(info.get("profileId")) != os.getenv("WISE_PROFILE_ID")
    ):
        raise HTTPException(
            409, "Select a KRW recipient belonging to the configured Wise profile."
        )
    # Use the same transaction lock as approval so its recipient snapshot cannot
    # change between checking the displayed revision and reserving the footage.
    await db.execute(text("SELECT pg_advisory_xact_lock(61306131)"))
    row = await db.get(PayoutRecipient, person.id)
    if not row:
        row = PayoutRecipient(wearer_id=person.id)
        db.add(row)
    row.wise_recipient_id = str(body.recipient_id)
    row.verified_name = info.get("name", {}).get("fullName", "")
    row.updated_by = user.email
    row.recipient_hash = info["hash"]
    row.wise_profile_id = str(info["profileId"])
    row.wise_environment = os.getenv("WISE_ENVIRONMENT", "sandbox")
    await db.commit()
    return await state(db)
