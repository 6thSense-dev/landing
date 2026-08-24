"""FastAPI dependencies for cookie-session auth + role gating."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.sessions import hash_session_token
from app.models import Session as SessionRow, User
from app.models.user import GUEST_ROLE


COOKIE_NAME = "sid"

#: How long a shared-guest session lives, measured from when it was created
#: and never extended. Every other role keeps the 14-day sliding window.
#:
#: WHY GUEST IS DIFFERENT
#:   The sliding window renews on every request, so a tab left open renews
#:   forever. That is fine for a personal credential and wrong for one that is
#:   handed out in sales emails: the realistic failure mode is a laptop left
#:   open in a prospect's office, and "until they close the laptop, plus two
#:   weeks" is not a window we want on a credential we do not control. Eight
#:   hours is one working day: long enough that nobody is re-logging-in during
#:   an evaluation, short enough that an abandoned session is gone by morning.
GUEST_SESSION_TTL = timedelta(hours=8)


class _ClearCookieUnauthorized(HTTPException):
    """Raised when the session is invalid/expired. The exception handler in
    app.main translates this to a 401 response with the sid cookie cleared.
    A dedicated subclass is needed because FastAPI drops Response mutations
    made inside a dependency when an HTTPException propagates."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )


async def current_user(
    request: Request,
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
        raise _ClearCookieUnauthorized()
    sess_row, user = row
    now = datetime.now(timezone.utc)
    is_guest = user.role == GUEST_ROLE
    expired = sess_row.expires_at < now
    if is_guest and sess_row.created_at is not None:
        # Belt to the braces of expires_at: the cap is enforced against the
        # row's own creation time, so a guest session cannot outlive it even
        # if something else widened expires_at.
        expired = expired or (sess_row.created_at + GUEST_SESSION_TTL) <= now
    if expired or not user.is_active:
        await session.execute(
            SessionRow.__table__.delete().where(SessionRow.id == sess_row.id)
        )
        await session.commit()
        raise _ClearCookieUnauthorized()
    # Sliding expiry: bump last_used_at, extend expires_at to at least now + 14d.
    #
    # Guest is the exception, and it is the whole point of the short TTL: a
    # sliding window on a SHARED credential never closes, so giving guest an
    # 8-hour TTL and then renewing it on every poll would buy nothing. A guest
    # session expires an absolute GUEST_SESSION_TTL after login and is not
    # extended by use. Every other role's behaviour is unchanged.
    new_expiry = sess_row.expires_at if is_guest else max(
        sess_row.expires_at, now + timedelta(days=14)
    )
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
