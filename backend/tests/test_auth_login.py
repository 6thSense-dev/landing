"""POST /api/auth/login — happy paths + 401s + cookie + rate limit."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.passwords import hash_password
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


@pytest_asyncio.fixture
async def alex(db_session):
    user = User(
        email="alex@example.com",
        name="Alex",
        role="founder",
        password_hash=hash_password("twelve-chars!!"),
    )
    db_session.add(user)
    await db_session.commit()
    return user


HDRS = {"Origin": "https://app.example"}


@pytest.mark.asyncio
async def test_happy_path_sets_cookie_and_returns_user(client, alex):
    res = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["user"]["email"] == "alex@example.com"
    assert body["user"]["role"] == "founder"
    set_cookie = res.headers.get("set-cookie", "")
    assert "sid=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()


@pytest.mark.asyncio
async def test_email_is_case_insensitive(client, alex):
    res = await client.post(
        "/api/auth/login",
        json={"email": "ALEX@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_wrong_password_is_401(client, alex):
    res = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "wrong-password!"},
        headers=HDRS,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_unknown_email_is_401(client):
    res = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_inactive_user_is_401(client, db_session):
    db_session.add(User(
        email="off@example.com",
        name="Off",
        role="founder",
        password_hash=hash_password("twelve-chars!!"),
        is_active=False,
    ))
    await db_session.commit()
    res = await client.post(
        "/api/auth/login",
        json={"email": "off@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_login_persists_session_row(client, alex, db_session):
    res = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 200
    rows = (await db_session.execute(select(SessionRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == alex.id


@pytest.mark.asyncio
async def test_login_rate_limited(client, alex, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_LOGIN_RATE_LIMIT", "3/minute")
    from app.core.limiter import limiter
    limiter.reset()
    for _ in range(3):
        await client.post(
            "/api/auth/login",
            json={"email": "alex@example.com", "password": "wrong"},
            headers=HDRS,
        )
    res = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "wrong"},
        headers=HDRS,
    )
    assert res.status_code == 429
