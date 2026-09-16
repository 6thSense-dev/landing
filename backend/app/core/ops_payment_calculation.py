"""Weekly clean import and calculation only; never reserve, transfer, or fund money."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import os

from sqlalchemy import select, text
from app.core.db import get_engine, get_sessionmaker
from app.core.ops_ledger import KOREA, PAYMENT_THRESHOLD_SECONDS, calculation_week, footage_ledger, last_sunday, price, retained_duration
from app.models import Wearer

logger = logging.getLogger(__name__)


def due_calculation(now):
    if os.getenv("OPS_PAYMENT_CALCULATION_ENABLED") != "true":
        return None
    start = datetime.fromisoformat(os.environ["OPS_PAYMENT_CALCULATION_START_AT"].replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("Calculation start must include a timezone")
    local = start.astimezone(KOREA)
    if (local.weekday(), local.hour, local.minute, local.second, local.microsecond) != (6, 23, 59, 0, 0):
        raise ValueError("Calculation start must be Sunday 23:59 Asia/Seoul")
    due = last_sunday(now)
    return due if due >= start else None


def calculation_key(due):
    return "payment_calculation_" + due.astimezone(KOREA).date().isoformat()


async def save_calculation(db, due, calculated_at, scan_result):
    from app.api.routes.ops import _setting, _put_setting
    from app.api.routes.ops_payments import eligible
    from app.core.contributor_deletion import lock as deletion_lock
    await deletion_lock(db)
    await db.execute(text("SELECT pg_advisory_xact_lock(61306131)"))
    key = calculation_key(due)
    if await _setting(db, key):
        return False
    rows = await footage_ledger(db)
    active = (await db.execute(select(Wearer).where(Wearer.is_active.is_(True)))).scalars().all()
    groups = []
    for person in active:
        # A late scan/restart may calculate later; post-cutoff reviews wait for
        # the following weekly snapshot. Existing approvals remain immutable.
        own = [r for r in rows if r["wearer_id"] == person.id and r.get("reviewed_at")
               and datetime.fromisoformat(r["reviewed_at"]) <= due]
        ready, seconds = eligible(own, due, "accumulated")
        if not seconds:
            continue
        groups.append({
            "wearer_id": person.id, "qualifying_seconds": seconds,
            "eligible_krw": price(ready),
            "entries": [{**{k: r[k] for k in ("run_id", "recording", "manifest_sha256", "retained_seconds", "allocated_krw")},
                         "retained_seconds_exact": str(retained_duration(r))} for r in ready],
        })
    result = {
        "scheduled_for": due.isoformat(), "calculated_at": calculated_at.isoformat(),
        "timezone": "Asia/Seoul", "collection_week": calculation_week(due),
        "threshold_seconds": PAYMENT_THRESHOLD_SECONDS, "threshold_rule": "at_least",
        "mode": "calculation_only", "operator_approval_required": True,
        "imported_runs": scan_result.get("imported", 0),
        "scan_error_count": len(scan_result.get("scan_errors", [])),
        "contributors": sorted(groups, key=lambda g: g["wearer_id"]),
    }
    payload = json.dumps(result, separators=(",", ":"))
    await _put_setting(db, key, payload)
    await _put_setting(db, "payment_calculation_latest", payload)
    await db.commit()
    return True


async def tick(now=None):
    now = now or datetime.now(timezone.utc)
    due = due_calculation(now)
    if due is None:
        return False
    # Share the scanner's replica election. A lost connection releases the lock;
    # the durable weekly key makes a restart after commit harmless.
    async with get_engine().connect() as connection:
        won = (await connection.execute(text("SELECT pg_try_advisory_lock(61306133)"))).scalar()
        if not won:
            return False
        try:
            from app.api.routes.ops import _setting
            from app.api.routes.ops_clean import scan
            async with get_sessionmaker()() as db:
                if await _setting(db, calculation_key(due)):
                    return False
                result = await scan(None, db, skip_invalid=True)
                if any(e.get("retryable") or e.get("error") == "ClientError" for e in result.get("scan_errors", [])):
                    raise RuntimeError("Clean storage reads remain unresolved; weekly calculation will retry")
                # Exceptions leave the weekly key absent, allowing retry. Invalid
                # individual imports are counted and never converted into pay.
                return await save_calculation(db, due, now, result)
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(61306133)"))


async def run():
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("weekly_payment_calculation_failed")
        await asyncio.sleep(30)
