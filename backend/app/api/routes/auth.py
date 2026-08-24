"""POST /api/auth/login | POST /api/auth/logout | GET /api/auth/me"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_deps import COOKIE_NAME, GUEST_SESSION_TTL, current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.limiter import current_login_rate_limit, limiter, login_rate_limit_key, mark_guest_login
from app.core.passwords import DUMMY_HASH, verify_password
from app.core.sessions import hash_session_token, mint_session_token
from app.models import Session as SessionRow, User
from app.models.user import GUEST_EMAIL, GUEST_ROLE
from app.schemas import LoginRequest, LoginResponse, UserOut
from app.schemas.auth import normalise_identifier


router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(days=14)

#: Bare usernames that resolve to an account. Exactly one entry, on purpose.
#:
#: The product committed to `guest` / <password> on the login page, and
#: `guest` is not an email address. Rather than add a nullable
#: `users.username` column plus a unique index plus a second lookup path in
#: the hot login route for ONE account, the alias is written out here where it
#: can be read, grepped and reviewed in a single line.
#:
#: If a second entry ever needs to be added: don't. That is the point at which
#: a real `users.username` column (unique, indexed, validated on create-user)
#: is the correct move, and this constant should be deleted in the same commit.
RESERVED_USERNAMES: dict[str, str] = {"guest": GUEST_EMAIL}  # guest@6thsense.dev


def _email_domain(identifier: object) -> str:
    """Domain of a login identifier, for the structured failure log.

    Never returns the identifier itself: the log line must stay PII-free and
    must not become a place to inject arbitrary user input. A bare username
    has no domain, so it is reported as the literal "username" — which is
    still useful, because it distinguishes "someone tried the demo login"
    from "someone tried an address we don't have".
    """
    if not isinstance(identifier, str):
        return "unknown"
    if "@" not in identifier:
        return "username" if identifier else "unknown"
    domain = identifier.rsplit("@", 1)[-1]
    return domain or "unknown"


def resolve_identifier(identifier: str) -> str | None:
    """Map a validated login identifier to the email that keys `users`.

    Returns None when a bare username is not one of RESERVED_USERNAMES, i.e.
    when it cannot address an account at all. We deliberately do NOT fall back
    to looking the raw word up as an email: `app.cli create-user` does not
    validate the address format, so a row whose `email` happened to be a bare
    word would otherwise become reachable by username — accidental username
    authentication is exactly what this map exists to avoid.
    """
    if "@" in identifier:
        return identifier
    return RESERVED_USERNAMES.get(identifier)


async def _classify_login_bucket(request: Request) -> None:
    """Pick the rate-limit bucket before slowapi runs.

    FastAPI resolves route `dependencies` before it calls the endpoint, and
    slowapi's check happens inside the endpoint wrapper — so this runs first
    and `login_rate_limit_key` can see the result. `request.json()` is the
    body FastAPI has already read and cached; it is not a second read of the
    stream.

    Matching is on the submitted identifier, not on a database lookup: a
    lookup here would hand an unauthenticated caller a free query on every
    request, and would have to happen before the throttle it is meant to
    inform. The worst an attacker gets from claiming to be `guest` is the
    guest bucket, which only ever tries the guest password.
    """
    try:
        body = await request.json()
    except Exception:  # malformed body — FastAPI will 422 it before we care
        return
    if not isinstance(body, dict):
        return
    identifier = normalise_identifier(body.get("identifier")) or normalise_identifier(
        body.get("email")
    )
    # Same resolution the route will do, so the bucket and the account can
    # never drift apart: both `guest` and `guest@6thsense.dev` land here.
    if identifier and resolve_identifier(identifier) == GUEST_EMAIL:
        mark_guest_login(request)


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(_classify_login_bucket)],
)
@limiter.limit(current_login_rate_limit, key_func=login_rate_limit_key)
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    identifier = payload.identifier or ""
    email = resolve_identifier(identifier)
    user = None
    if email is not None:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        # Constant-time decoy verify so we don't leak whether the email exists.
        verify_password(payload.password, DUMMY_HASH)
        logger.info(
            "auth_login_failed",
            extra={"email_domain": _email_domain(identifier), "reason": "unknown_or_inactive"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not verify_password(payload.password, user.password_hash):
        logger.info(
            "auth_login_failed",
            extra={"email_domain": _email_domain(identifier), "reason": "bad_password"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    raw = mint_session_token()
    now = datetime.now(timezone.utc)
    # 14 days for a real user; hours for the shared guest credential, and
    # absolute rather than sliding (see app.core.auth_deps.current_user).
    ttl = GUEST_SESSION_TTL if user.role == GUEST_ROLE else SESSION_TTL
    expires_at = now + ttl
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
        max_age=int(ttl.total_seconds()),
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
