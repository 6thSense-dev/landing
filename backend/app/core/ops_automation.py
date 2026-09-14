"""A single elected scanner and approved-payout reconciler across API replicas."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select, text
from app.core.db import get_engine, get_sessionmaker
from app.core.wise import WiseClient, WiseError
from app.models import Payout

logger = logging.getLogger(__name__)


async def advance_payout(db, p, client):
    if p.wise_profile_id != client.profile or p.wise_environment != client.environment:
        raise WiseError(
            "Wise profile/environment changed; payment remains reserved for reconciliation."
        )
    # Check identity again before creating a transfer. Never follow a changed recipient.
    if not p.transfer_id:
        recipient = await asyncio.to_thread(client.recipient, p.recipient_id)
        if (
            not recipient.get("active")
            or recipient.get("hash") != p.recipient_hash
            or str(recipient.get("profileId")) != p.wise_profile_id
            or recipient.get("currency") != "KRW"
        ):
            raise WiseError(
                "Recipient details changed; payment remains reserved for reconciliation."
            )
        if not p.quote_id:
            q = await asyncio.to_thread(client.quote, p)
            if q.get("targetCurrency") != "KRW" or Decimal(
                str(q.get("targetAmount", 0))
            ) != Decimal(p.amount_krw):
                raise WiseError("Wise quote does not match the approved KRW amount.")
            p.quote_id = q["id"]
            p.status = "quoted"
            await db.commit()
        # Persist quote and payout UUID before POST. Retrying after a lost response
        # reuses customerTransactionId; it cannot create a second logical transfer.
        t = await asyncio.to_thread(client.transfer, p)
        p.transfer_id = str(t["id"])
        p.status = "processing"
        await db.commit()
    t = await asyncio.to_thread(client.status, p)
    provider = t.get("status", "unknown")
    if (
        str(t.get("targetAccount")) != p.recipient_id
        or t.get("targetCurrency") != "KRW"
        or Decimal(str(t.get("targetValue", 0))) != Decimal(p.amount_krw)
    ):
        raise WiseError(
            "Transfer identity or amount differs from the approved payment."
        )
    p.provider_status = provider
    if provider in ("outgoing_payment_sent", "funds_converted", "processing"):
        p.status = "sent" if provider == "outgoing_payment_sent" else "processing"
    elif provider in ("cancelled", "funds_refunded", "bounced_back"):
        p.status = "needs_attention"
        p.error = "Wise transfer was cancelled, refunded or returned. Reconcile before issuing another payment."
    elif provider == "incoming_payment_waiting":
        if os.getenv("OPS_WISE_AUTO_FUND") == "true":
            # Funding is an instruction to Wise, not proof of receipt by the contributor.
            p.status = "funding"
            await db.commit()
            result = await asyncio.to_thread(client.fund, p)
            if result.get("status") != "COMPLETED":
                raise WiseError("Wise funding was not completed.")
            p.status = "processing"
        else:
            p.status = "awaiting_funding"
    else:
        p.status = "processing"
    await db.commit()


async def payout_tick():
    if not os.getenv("WISE_API_TOKEN") or not os.getenv("WISE_PROFILE_ID"):
        return
    client = WiseClient()
    async with get_sessionmaker()() as db:
        now = datetime.now(timezone.utc)
        payouts = (
            (
                await db.execute(
                    select(Payout).where(
                        Payout.scheduled_for <= now,
                        Payout.status.in_(
                            [
                                "approved",
                                "quoted",
                                "processing",
                                "funding",
                                "awaiting_funding",
                                "sent",
                            ]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for p in payouts:
            try:
                p.error = ""
                await advance_payout(db, p, client)
            except WiseError as e:
                p.error = str(e)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("payout_reconciliation_failed")


async def tick():
    # Session advisory lock survives transaction commits and is released even if
    # either scan fails. Separate connection prevents returning a locked pool entry.
    async with get_engine().connect() as lock:
        won = (
            await lock.execute(text("SELECT pg_try_advisory_lock(61306133)"))
        ).scalar()
        if not won:
            return
        try:
            from app.api.routes.ops import scan_bucket, _put_setting
            from app.api.routes.ops_clean import scan

            async with get_sessionmaker()() as db:
                try:
                    await scan(
                        None, db, skip_invalid=True
                    )  # verified committed results only
                except Exception:
                    await db.rollback()
                    logger.exception("automatic_clean_import_failed")
                try:
                    await scan_bucket(None, db)
                    await _put_setting(
                        db,
                        "automation_last_success",
                        datetime.now(timezone.utc).isoformat(),
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception("automatic_raw_scan_failed")
            await payout_tick()
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(61306133)"))


async def run():
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ops_automation_tick_failed")
        await asyncio.sleep(300)
