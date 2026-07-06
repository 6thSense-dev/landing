"""Integration tests for POST /api/leads."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    # Reset the shared limiter bucket so earlier test modules can't leave this
    # module's default IP already rate-limited.
    monkeypatch.setenv("SENSEPROBE_RATE_LIMIT", "1000/minute")
    from app.core.limiter import limiter

    limiter.reset()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_first_submission_returns_created_true(client, db_session):
    res = await client.post(
        "/api/leads",
        json={"name": "Ada", "email": "ada@x.com", "organization": "Acme"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "created": True}
    row = (await db_session.execute(text("SELECT name, email, organization FROM leads"))).one()
    assert row == ("Ada", "ada@x.com", "Acme")


@pytest.mark.asyncio
async def test_duplicate_email_upserts_and_returns_created_false(client, db_session):
    body = {"name": "Ada", "email": "ada@x.com", "organization": "Acme"}
    await client.post("/api/leads", json=body)
    res = await client.post(
        "/api/leads",
        json={"name": "Ada Lovelace", "email": "ADA@x.com", "organization": "Analytical"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "created": False}
    rows = (await db_session.execute(text("SELECT name, organization FROM leads"))).all()
    assert rows == [("Ada Lovelace", "Analytical")]  # one row, latest values


@pytest.mark.asyncio
async def test_invalid_email_returns_422_with_field_errors(client):
    res = await client.post(
        "/api/leads",
        json={"name": "Ada", "email": "not-an-email", "organization": "Acme"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["ok"] is False
    assert "email" in body["errors"]


@pytest.mark.asyncio
async def test_success_log_contains_no_pii(client, caplog):
    import logging
    caplog.set_level(logging.INFO)
    await client.post(
        "/api/leads",
        json={"name": "Ada", "email": "ada@x.com", "organization": "Acme"},
    )
    captured = " ".join(caplog.messages + [str(r.__dict__) for r in caplog.records])
    assert "ada@x.com" not in captured
    assert "Acme" not in captured
