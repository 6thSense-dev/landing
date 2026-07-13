"""Admin leads CRM — /api/admin/leads.

Every route requires an authenticated user with the `admin` role. Provides the
list + stats the CRM renders, full CRUD, a one-call follow-up toggle (via
PATCH), and a CSV export of the current view.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_deps import require_role
from app.core.db import get_session
from app.models import Lead
from app.schemas.admin import (
    AdminLeadCreate,
    AdminLeadOut,
    AdminLeadsResponse,
    AdminLeadUpdate,
    LeadStats,
)


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)
logger = logging.getLogger(__name__)

# Filter values the CRM's segmented control sends.
_STATUS_ALL = "all"
_STATUS_PENDING = "pending"
_STATUS_FOLLOWED_UP = "followed_up"


def _apply_filters(stmt, *, status_filter: str, q: str | None):
    if status_filter == _STATUS_PENDING:
        stmt = stmt.where(Lead.followed_up.is_(False))
    elif status_filter == _STATUS_FOLLOWED_UP:
        stmt = stmt.where(Lead.followed_up.is_(True))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.name.ilike(like),
                Lead.email.ilike(like),
                Lead.organization.ilike(like),
                Lead.message.ilike(like),
            )
        )
    return stmt


async def _stats(session: AsyncSession) -> LeadStats:
    total = (await session.execute(select(func.count(Lead.id)))).scalar_one()
    followed = (
        await session.execute(
            select(func.count(Lead.id)).where(Lead.followed_up.is_(True))
        )
    ).scalar_one()
    return LeadStats(total=total, followed_up=followed, pending=total - followed)


@router.get("/leads", response_model=AdminLeadsResponse)
async def list_leads(
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(default=None, max_length=200),
    status_filter: str = Query(default=_STATUS_ALL, alias="status"),
) -> AdminLeadsResponse:
    stmt = _apply_filters(select(Lead), status_filter=status_filter, q=q)
    # Pending first, then newest — the work queue reads top-to-bottom.
    stmt = stmt.order_by(Lead.followed_up.asc(), Lead.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return AdminLeadsResponse(
        leads=[AdminLeadOut.model_validate(r) for r in rows],
        stats=await _stats(session),
    )


@router.post("/leads", response_model=AdminLeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: AdminLeadCreate,
    session: AsyncSession = Depends(get_session),
) -> AdminLeadOut:
    exists = (
        await session.execute(select(Lead.id).where(Lead.email == payload.email))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A lead with that email already exists.",
        )
    now = datetime.now(timezone.utc)
    lead = Lead(
        name=payload.name,
        email=payload.email,
        organization=payload.organization,
        message=payload.message,
        followed_up=payload.followed_up,
        followed_up_at=now if payload.followed_up else None,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    logger.info("admin_lead_created", extra={"lead_id": int(lead.id)})
    return AdminLeadOut.model_validate(lead)


async def _get_or_404(session: AsyncSession, lead_id: int) -> Lead:
    lead = (
        await session.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found."
        )
    return lead


@router.patch("/leads/{lead_id}", response_model=AdminLeadOut)
async def update_lead(
    lead_id: int,
    payload: AdminLeadUpdate,
    session: AsyncSession = Depends(get_session),
) -> AdminLeadOut:
    lead = await _get_or_404(session, lead_id)
    data = payload.model_dump(exclude_unset=True)

    if "email" in data and data["email"] != lead.email:
        clash = (
            await session.execute(
                select(Lead.id).where(
                    Lead.email == data["email"], Lead.id != lead_id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another lead already uses that email.",
            )

    if "followed_up" in data and data["followed_up"] != lead.followed_up:
        # Stamp / clear the follow-up time as the flag flips.
        lead.followed_up_at = (
            datetime.now(timezone.utc) if data["followed_up"] else None
        )

    for field, value in data.items():
        setattr(lead, field, value)

    await session.commit()
    await session.refresh(lead)
    logger.info("admin_lead_updated", extra={"lead_id": int(lead.id)})
    return AdminLeadOut.model_validate(lead)


@router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    lead = await _get_or_404(session, lead_id)
    await session.delete(lead)
    await session.commit()
    logger.info("admin_lead_deleted", extra={"lead_id": lead_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/leads.csv")
async def export_leads_csv(
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(default=None, max_length=200),
    status_filter: str = Query(default=_STATUS_ALL, alias="status"),
) -> Response:
    stmt = _apply_filters(select(Lead), status_filter=status_filter, q=q)
    stmt = stmt.order_by(Lead.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "name",
            "email",
            "organization",
            "message",
            "followed_up",
            "followed_up_at",
            "created_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.name,
                r.email,
                r.organization,
                r.message,
                "yes" if r.followed_up else "no",
                r.followed_up_at.isoformat() if r.followed_up_at else "",
                r.created_at.isoformat() if r.created_at else "",
            ]
        )

    today = datetime.now(timezone.utc).date().isoformat()
    filename = f"6thsense-leads-{today}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
