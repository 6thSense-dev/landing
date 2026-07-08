"""POST /api/leads — idempotent UPSERT keyed on email.

The site's single Contact Us form. A honeypot field silently drops bots. On
success a Slack notification is fired via a BackgroundTask *after* the DB
commit, wrapped so it can never fail the request.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.limiter import current_rate_limit, limiter
from app.core.slack import notify_new_lead
from app.schemas import LeadCreate, LeadResponse


router = APIRouter(prefix="/api", tags=["leads"])
logger = logging.getLogger(__name__)


# Upsert keyed on email: one row per address. A repeat submission from the same
# email refreshes the mutable fields rather than creating a duplicate.
_UPSERT_SQL = text(
    """
    INSERT INTO leads (name, email, organization, message)
    VALUES (:name, :email, :organization, :message)
    ON CONFLICT (email) DO UPDATE SET
        name         = EXCLUDED.name,
        organization = EXCLUDED.organization,
        message      = EXCLUDED.message,
        updated_at   = now()
    RETURNING id, (xmax = 0) AS inserted
    """
)


@router.post("/leads", response_model=LeadResponse)
@limiter.limit(current_rate_limit)
async def create_lead(
    request: Request,
    payload: LeadCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> LeadResponse:
    # Honeypot: if the hidden field is filled, silently accept and drop. No DB
    # write, no Slack, no leak that it was rejected.
    if payload.website:
        logger.info("lead_honeypot_drop")
        return LeadResponse(ok=True, created=False)

    row = (
        await session.execute(
            _UPSERT_SQL,
            {
                "name": payload.name,
                "email": payload.email,
                "organization": payload.organization,
                "message": payload.message,
            },
        )
    ).one()
    lead_id, inserted = row
    await session.commit()
    logger.info(
        "lead_captured",
        extra={"lead_id": int(lead_id), "is_new": bool(inserted)},
    )

    # Fire Slack AFTER commit, in the background. notify_new_lead never raises,
    # so a Slack outage cannot affect this request's 200.
    background_tasks.add_task(
        notify_new_lead,
        name=payload.name,
        organization=payload.organization,
        email=payload.email,
        message=payload.message,
        is_new=bool(inserted),
    )

    return LeadResponse(ok=True, created=bool(inserted))
