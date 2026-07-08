import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_RATE_LIMIT", "3/minute")
    from app.core.limiter import limiter
    # Reset the in-process bucket store so this test starts clean even if
    # earlier tests touched the limiter on overlapping IPs.
    limiter.reset()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"X-Forwarded-For": "1.1.1.1"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_429_after_limit(client):
    body = {"name": "A", "email": "a@x.com", "organization": "Acme", "message": "hi"}
    for i in range(3):
        body["email"] = f"a{i}@x.com"
        res = await client.post("/api/leads", json=body)
        assert res.status_code == 200, res.text
    body["email"] = "z@x.com"
    res = await client.post("/api/leads", json=body)
    assert res.status_code == 429
    assert res.json() == {
        "ok": False,
        "error": "Too many requests. Please slow down.",
    }
