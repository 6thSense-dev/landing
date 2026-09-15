"""Freeze source ownership from supervised capture-time intervals, never the uploader."""
from datetime import datetime, timezone, timedelta
import re
from sqlalchemy import select
from app.models import ContributorAccount, ContributorCameraClaim

async def end_mobile_assignment(db, device, next_wearer_id):
    active = (await db.execute(select(ContributorCameraClaim).where(ContributorCameraClaim.device_id == device, ContributorCameraClaim.status == "approved", ContributorCameraClaim.ended_at.is_(None)))).scalars().all()
    for claim in active:
        account = await db.get(ContributorAccount, claim.subject)
        if account.wearer_id != next_wearer_id:
            claim.ended_at = datetime.now(timezone.utc)

async def owner_at_capture(db, facts):
    device = facts.get("device_id", "").strip().upper().removeprefix("EGO-")
    started = facts.get("started_at")
    # Unknown clocks and recordings spanning a handover need operator review.
    if not re.fullmatch("[A-F0-9]{6}", device) or not started or not started.tzinfo or facts.get("clock_source") != "ntp" or not facts.get("complete") or not facts.get("duration_s"):
        return None
    ended = started + timedelta(seconds=facts["duration_s"])
    if ended > datetime.now(timezone.utc) + timedelta(minutes=5):
        return None
    claims = (await db.execute(select(ContributorCameraClaim).where(ContributorCameraClaim.device_id == device, ContributorCameraClaim.status == "approved", ContributorCameraClaim.effective_at <= started))).scalars().all()
    matches = [c for c in claims if c.ended_at is None or c.ended_at >= ended]
    if len(matches) != 1:
        return None
    account = await db.get(ContributorAccount, matches[0].subject)
    return account.wearer_id
