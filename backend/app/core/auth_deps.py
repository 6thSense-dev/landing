"""FastAPI dependencies for cookie-session auth + role gating."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.sessions import hash_session_token
from app.models import Session as SessionRow, User


COOKIE_NAME = "sid"


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def current_user(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    token_hash = hash_session_token(token)
    row = (
        await session.execute(
            select(SessionRow, User)
            .join(User, User.id == SessionRow.user_id)
            .where(SessionRow.token_hash == token_hash)
        )
    ).one_or_none()
    if row is None:
        _clear_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    sess_row, user = row
    now = datetime.now(timezone.utc)
    if sess_row.expires_at < now or not user.is_active:
        await session.execute(
            SessionRow.__table__.delete().where(SessionRow.id == sess_row.id)
        )
        await session.commit()
        _clear_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    # Sliding expiry: bump last_used_at, extend expires_at to at least now + 14d.
    new_expiry = max(sess_row.expires_at, now + timedelta(days=14))
    await session.execute(
        update(SessionRow)
        .where(SessionRow.id == sess_row.id)
        .values(last_used_at=now, expires_at=new_expiry)
    )
    await session.commit()
    request.state.user = user
    return user


def require_role(role: str):
    async def _dep(user: User = Depends(current_user)) -> User:
        if user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden.",
            )
        return user

    return _dep
