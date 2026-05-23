"""POST /api/auth/login | POST /api/auth/logout | GET /api/auth/me"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_deps import COOKIE_NAME, current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.limiter import current_login_rate_limit, limiter
from app.core.passwords import DUMMY_HASH, verify_password
from app.core.sessions import hash_session_token, mint_session_token
from app.models import Session as SessionRow, User
from app.schemas import LoginRequest, LoginResponse, UserOut


router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(days=14)


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1] if "@" in email else "unknown"


@router.post("/login", response_model=LoginResponse)
@limiter.limit(current_login_rate_limit)
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    result = await session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        # Constant-time decoy verify so we don't leak whether the email exists.
        verify_password(payload.password, DUMMY_HASH)
        logger.info(
            "auth_login_failed",
            extra={"email_domain": _email_domain(payload.email), "reason": "unknown_or_inactive"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not verify_password(payload.password, user.password_hash):
        logger.info(
            "auth_login_failed",
            extra={"email_domain": _email_domain(payload.email), "reason": "bad_password"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    raw = mint_session_token()
    now = datetime.now(timezone.utc)
    expires_at = now + SESSION_TTL
    ua = request.headers.get("user-agent")
    xff = request.headers.get("x-forwarded-for")
    ip = xff.split(",")[-1].strip() if xff else (request.client.host if request.client else None)
    await session.execute(
        SessionRow.__table__.insert().values(
            user_id=user.id,
            token_hash=hash_session_token(raw),
            expires_at=expires_at,
            user_agent=ua[:500] if ua else None,
            ip=ip[:64] if ip else None,
        )
    )
    await session.commit()

    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    logger.info(
        "auth_login_ok",
        extra={"user_id": int(user.id), "email_domain": _email_domain(user.email)},
    )
    return LoginResponse(
        ok=True,
        user=UserOut(id=user.id, email=user.email, name=user.name, role=user.role),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await session.execute(
            SessionRow.__table__.delete().where(
                SessionRow.token_hash == hash_session_token(token)
            )
        )
        await session.commit()
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp
