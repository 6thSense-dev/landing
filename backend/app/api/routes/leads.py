"""POST /api/leads — idempotent UPSERT keyed on (email, kind).

Accepts three kinds of submission (preorder | waitlist | contact), optionally
scoped to a product (hand | nerve | skin). A honeypot field silently drops
bots. On success a Slack notification is fired via a BackgroundTask *after* the
DB commit, wrapped so it can never fail the request.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.limiter import current_rate_limit, limiter
from app.core.slack import notify_new_lead
from app.schemas import (
    KINDS_REQUIRING_MESSAGE,
    VALID_KINDS,
    VALID_PRODUCTS,
    LeadCreate,
    LeadResponse,
)


router = APIRouter(prefix="/api", tags=["leads"])
logger = logging.getLogger(__name__)


# Upsert keyed on (email, kind): a person can hold one row per kind. On a
# repeat submission of the same (email, kind) we refresh the mutable fields.
_UPSERT_SQL = text(
    """
    INSERT INTO leads (name, email, organization, kind, product, message)
    VALUES (:name, :email, :organization, :kind, :product, :message)
    ON CONFLICT (email, kind) DO UPDATE SET
        name         = EXCLUDED.name,
        organization = EXCLUDED.organization,
        product      = EXCLUDED.product,
        message      = EXCLUDED.message,
        updated_at   = now()
    RETURNING id, (xmax = 0) AS inserted
    """
)


def _validate_domain(payload: LeadCreate) -> None:
    """Enforce enum + per-kind rules. Raises 422 on any violation."""
    if payload.kind not in VALID_KINDS:
        raise HTTPException(
            status_code=422,
            detail={"kind": f"Unknown kind. Expected one of {sorted(VALID_KINDS)}."},
        )
    if payload.product is not None and payload.product not in VALID_PRODUCTS:
        raise HTTPException(
            status_code=422,
            detail={
                "product": f"Unknown product. Expected one of {sorted(VALID_PRODUCTS)} or null."
            },
        )
    if payload.kind in KINDS_REQUIRING_MESSAGE and not payload.message:
        raise HTTPException(
            status_code=422,
            detail={"message": f"A message is required for kind '{payload.kind}'."},
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

    _validate_domain(payload)

    row = (
        await session.execute(
            _UPSERT_SQL,
            {
                "name": payload.name,
                "email": payload.email,
                "organization": payload.organization,
                "kind": payload.kind,
                "product": payload.product,
                "message": payload.message,
            },
        )
    ).one()
    lead_id, inserted = row
    await session.commit()
    logger.info(
        "lead_captured",
        extra={
            "lead_id": int(lead_id),
            "is_new": bool(inserted),
            "kind": payload.kind,
            "product": payload.product,
        },
    )

    # Fire Slack AFTER commit, in the background. notify_new_lead never raises,
    # so a Slack outage cannot affect this request's 200.
    background_tasks.add_task(
        notify_new_lead,
        kind=payload.kind,
        product=payload.product,
        name=payload.name,
        organization=payload.organization,
        email=payload.email,
        message=payload.message,
        is_new=bool(inserted),
    )

    return LeadResponse(ok=True, created=bool(inserted))
