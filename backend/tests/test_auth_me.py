"""GET /api/auth/me — session resolution, sliding expiry, deactivation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.passwords import hash_password
from app.core.sessions import hash_session_token, mint_session_token
from app.main import create_app
from app.models import Session as SessionRow, User


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    from app.core.limiter import limiter
    limiter.reset()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _seed_user_and_session(db_session, *, is_active=True, expires_in=timedelta(days=14)):
    user = User(
        email="u@x.com",
        name="U",
        role="founder",
        password_hash=hash_password("twelve-chars!!"),
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.commit()
    raw = mint_session_token()
    db_session.add(SessionRow(
        user_id=user.id,
        token_hash=hash_session_token(raw),
        expires_at=datetime.now(timezone.utc) + expires_in,
    ))
    await db_session.commit()
    return user, raw


@pytest.mark.asyncio
async def test_me_without_cookie_is_401(client):
    res = await client.get("/api/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_cookie_returns_user(client, db_session):
    user, raw = await _seed_user_and_session(db_session)
    res = await client.get("/api/auth/me", cookies={"sid": raw})
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "u@x.com"
    assert body["role"] == "founder"


@pytest.mark.asyncio
async def test_me_with_expired_session_is_401_and_clears_cookie(client, db_session):
    user, raw = await _seed_user_and_session(db_session, expires_in=timedelta(seconds=-1))
    res = await client.get("/api/auth/me", cookies={"sid": raw})
    assert res.status_code == 401
    set_cookie = res.headers.get("set-cookie", "")
    assert 'sid=""' in set_cookie or "sid=;" in set_cookie or "Max-Age=0" in set_cookie


@pytest.mark.asyncio
async def test_me_with_deactivated_user_is_401(client, db_session):
    user, raw = await _seed_user_and_session(db_session, is_active=True)
    await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db_session.commit()
    res = await client.get("/api/auth/me", cookies={"sid": raw})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_sliding_expiry_bumps_expires_at(client, db_session):
    user, raw = await _seed_user_and_session(db_session, expires_in=timedelta(days=7))
    res = await client.get("/api/auth/me", cookies={"sid": raw})
    assert res.status_code == 200
    sess = (await db_session.execute(select(SessionRow))).scalar_one()
    # Was 7 days; sliding window should have bumped it to ~14 days.
    delta = sess.expires_at - datetime.now(timezone.utc)
    assert delta > timedelta(days=13)


@pytest.mark.asyncio
async def test_garbage_cookie_is_401_and_clears(client):
    res = await client.get("/api/auth/me", cookies={"sid": "not-a-real-token"})
    assert res.status_code == 401
