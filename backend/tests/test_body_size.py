import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client(postgres_container, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://app.example")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_oversize_body_rejected_with_413(client):
    payload = '{"name":"' + "a" * 5000 + '","email":"a@x.com","organization":"Acme"}'
    res = await client.post(
        "/api/leads",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 413
    assert res.json() == {"ok": False, "error": "Request too large."}


@pytest.mark.asyncio
async def test_oversize_body_does_not_touch_db(client, db_session):
    from sqlalchemy import text
    payload = '{"name":"' + "a" * 5000 + '","email":"a@x.com","organization":"Acme"}'
    await client.post("/api/leads", content=payload, headers={"Content-Type": "application/json"})
    rows = (await db_session.execute(text("SELECT COUNT(*) FROM leads"))).scalar_one()
    assert rows == 0


@pytest.mark.asyncio
async def test_login_endpoint_rejects_oversized_body(client):
    big = "x" * 8000
    res = await client.post(
        "/api/auth/login",
        json={"email": "a@x.com", "password": big},
        headers={"Origin": "https://app.example"},
    )
    # We don't have the auth route yet at this point in development, so the
    # body-size check should still kick in first. Expect 413, not 404.
    assert res.status_code == 413
