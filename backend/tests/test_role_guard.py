"""require_role: founder allowed, others 403."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.core.auth_deps import require_role
from app.core.passwords import hash_password
from app.core.sessions import hash_session_token, mint_session_token
from app.main import create_app
from app.models import Session as SessionRow, User


@pytest_asyncio.fixture
async def app_with_guarded_route(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    from app.core.limiter import limiter
    limiter.reset()
    app = create_app()

    @app.get("/api/portal/_test/founder-only")
    async def _f(user=Depends(require_role("founder"))):
        return {"ok": True, "role": user.role}

    return app


async def _seed(db_session, role: str) -> str:
    user = User(
        email=f"{role}@x.com",
        name=role.title(),
        role=role,
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
    return raw


@pytest.mark.asyncio
async def test_founder_allowed(app_with_guarded_route, db_session):
    raw = await _seed(db_session, "founder")
    async with AsyncClient(transport=ASGITransport(app=app_with_guarded_route), base_url="http://t") as c:
        res = await c.get("/api/portal/_test/founder-only", cookies={"sid": raw})
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_customer_forbidden(app_with_guarded_route, db_session):
    raw = await _seed(db_session, "customer")
    async with AsyncClient(transport=ASGITransport(app=app_with_guarded_route), base_url="http://t") as c:
        res = await c.get("/api/portal/_test/founder-only", cookies={"sid": raw})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_investor_forbidden(app_with_guarded_route, db_session):
    raw = await _seed(db_session, "investor")
    async with AsyncClient(transport=ASGITransport(app=app_with_guarded_route), base_url="http://t") as c:
        res = await c.get("/api/portal/_test/founder-only", cookies={"sid": raw})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_anon_is_401_not_403(app_with_guarded_route):
    async with AsyncClient(transport=ASGITransport(app=app_with_guarded_route), base_url="http://t") as c:
        res = await c.get("/api/portal/_test/founder-only")
    assert res.status_code == 401
