"""POST /api/auth/logout — deletes session, clears cookie, idempotent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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


HDRS = {"Origin": "https://app.example"}


@pytest.mark.asyncio
async def test_logout_deletes_session_and_clears_cookie(client, db_session):
    user = User(
        email="u@x.com", name="U", role="founder",
        password_hash=hash_password("twelve-chars!!"),
    )
    db_session.add(user)
    await db_session.commit()
    raw = mint_session_token()
    db_session.add(SessionRow(
        user_id=user.id,
        token_hash=hash_session_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    ))
    await db_session.commit()

    res = await client.post("/api/auth/logout", cookies={"sid": raw}, headers=HDRS)
    assert res.status_code == 204
    rows = (await db_session.execute(select(SessionRow))).scalars().all()
    assert rows == []
    sc = res.headers.get("set-cookie", "")
    assert "sid=" in sc and ("Max-Age=0" in sc or 'sid=""' in sc)


@pytest.mark.asyncio
async def test_logout_without_cookie_is_204(client):
    res = await client.post("/api/auth/logout", headers=HDRS)
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_logout_twice_is_idempotent(client, db_session):
    user = User(
        email="u@x.com", name="U", role="founder",
        password_hash=hash_password("twelve-chars!!"),
    )
    db_session.add(user)
    await db_session.commit()
    raw = mint_session_token()
    db_session.add(SessionRow(
        user_id=user.id,
        token_hash=hash_session_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    ))
    await db_session.commit()
    res1 = await client.post("/api/auth/logout", cookies={"sid": raw}, headers=HDRS)
    res2 = await client.post("/api/auth/logout", cookies={"sid": raw}, headers=HDRS)
    assert res1.status_code == 204
    assert res2.status_code == 204
