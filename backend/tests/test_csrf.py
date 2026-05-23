"""Origin-check middleware: POST under /api/auth/* requires allowed Origin."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://app.example")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_post_login_without_origin_is_403(client):
    res = await client.post(
        "/api/auth/login",
        json={"email": "a@x.com", "password": "12chars!!aaa"},
    )
    assert res.status_code == 403
    assert res.json() == {"ok": False, "error": "Forbidden."}


@pytest.mark.asyncio
async def test_post_login_with_disallowed_origin_is_403(client):
    res = await client.post(
        "/api/auth/login",
        json={"email": "a@x.com", "password": "12chars!!aaa"},
        headers={"Origin": "https://evil.example"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_post_login_with_allowed_origin_passes_csrf(client):
    res = await client.post(
        "/api/auth/login",
        json={"email": "a@x.com", "password": "12chars!!aaa"},
        headers={"Origin": "https://app.example"},
    )
    # The login route doesn't exist yet at this point (or the user doesn't);
    # we only assert CSRF didn't block, so status is NOT 403.
    assert res.status_code != 403


@pytest.mark.asyncio
async def test_get_health_unaffected_by_origin_check(client):
    res = await client.get("/health")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_post_leads_unaffected_by_origin_check(client):
    res = await client.post(
        "/api/leads",
        json={"name": "Ada", "email": "a@x.com", "organization": "Acme"},
    )
    # /api/leads is NOT in the CSRF guard list, so it should not be 403.
    assert res.status_code != 403
