"""Integration tests for the admin leads CRM (/api/admin/leads).

Auth model reused from test_role_guard: seed a user + session row directly and
pass the sid cookie. State-changing routes also require an allowed Origin
header (the OriginCheckMiddleware), so those requests send one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.core.sessions import hash_session_token, mint_session_token
from app.main import create_app
from app.models import Lead, Session as SessionRow, User


ORIGIN = "https://app.example"
ORIGIN_HEADER = {"Origin": ORIGIN}


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", ORIGIN)
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    monkeypatch.setenv("SENSEPROBE_RATE_LIMIT", "1000/minute")
    from app.core.limiter import limiter

    limiter.reset()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _seed_user_session(db_session, role: str) -> str:
    user = User(
        email=f"{role}@x.com",
        name=role.title(),
        role=role,
        password_hash=hash_password("twelve-chars!!"),
    )
    db_session.add(user)
    await db_session.commit()
    raw = mint_session_token()
    db_session.add(
        SessionRow(
            user_id=user.id,
            token_hash=hash_session_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
    )
    await db_session.commit()
    return raw


async def _seed_lead(db_session, *, email, name="Ada", org="Acme", msg="hi", followed_up=False):
    lead = Lead(
        name=name,
        email=email,
        organization=org,
        message=msg,
        followed_up=followed_up,
        followed_up_at=datetime.now(timezone.utc) if followed_up else None,
    )
    db_session.add(lead)
    await db_session.commit()
    return lead


# --------------------------------------------------------------------------- #
# Auth gating.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_requires_authentication(client):
    res = await client.get("/api/admin/leads")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_non_admin_forbidden(client, db_session):
    raw = await _seed_user_session(db_session, "founder")
    res = await client.get("/api/admin/leads", cookies={"sid": raw})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    res = await client.get("/api/admin/leads", cookies={"sid": raw})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["leads"] == []
    assert body["stats"] == {"total": 0, "followed_up": 0, "pending": 0}


# --------------------------------------------------------------------------- #
# List + stats + ordering + filters + search.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_list_stats_and_pending_first(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    await _seed_lead(db_session, email="done@x.com", followed_up=True)
    await _seed_lead(db_session, email="pending@x.com", followed_up=False)

    res = await client.get("/api/admin/leads", cookies={"sid": raw})
    body = res.json()
    assert body["stats"] == {"total": 2, "followed_up": 1, "pending": 1}
    # Pending sorts before followed-up.
    assert body["leads"][0]["email"] == "pending@x.com"
    assert body["leads"][0]["followed_up"] is False


@pytest.mark.asyncio
async def test_filter_pending_and_followed_up(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    await _seed_lead(db_session, email="done@x.com", followed_up=True)
    await _seed_lead(db_session, email="pending@x.com", followed_up=False)

    pending = (await client.get("/api/admin/leads?status=pending", cookies={"sid": raw})).json()
    assert [l["email"] for l in pending["leads"]] == ["pending@x.com"]

    done = (await client.get("/api/admin/leads?status=followed_up", cookies={"sid": raw})).json()
    assert [l["email"] for l in done["leads"]] == ["done@x.com"]


@pytest.mark.asyncio
async def test_search_matches_org_and_message(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    await _seed_lead(db_session, email="a@x.com", org="Robotics Co", msg="grippers")
    await _seed_lead(db_session, email="b@x.com", org="Other", msg="skin please")

    res = (await client.get("/api/admin/leads?q=robotics", cookies={"sid": raw})).json()
    assert [l["email"] for l in res["leads"]] == ["a@x.com"]
    res2 = (await client.get("/api/admin/leads?q=skin", cookies={"sid": raw})).json()
    assert [l["email"] for l in res2["leads"]] == ["b@x.com"]


# --------------------------------------------------------------------------- #
# Create.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_lead(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    res = await client.post(
        "/api/admin/leads",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"name": "Grace", "email": "GRACE@x.com", "organization": "Navy", "message": "hello"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["email"] == "grace@x.com"  # normalised
    assert body["followed_up"] is False
    assert body["followed_up_at"] is None


@pytest.mark.asyncio
async def test_create_followed_up_stamps_timestamp(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    res = await client.post(
        "/api/admin/leads",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"name": "G", "email": "g@x.com", "organization": "N", "message": "hi", "followed_up": True},
    )
    assert res.status_code == 201, res.text
    assert res.json()["followed_up_at"] is not None


@pytest.mark.asyncio
async def test_create_duplicate_email_409(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    await _seed_lead(db_session, email="dup@x.com")
    res = await client.post(
        "/api/admin/leads",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"name": "X", "email": "dup@x.com", "organization": "Y", "message": "z"},
    )
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_create_missing_message_422(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    res = await client.post(
        "/api/admin/leads",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"name": "X", "email": "x@x.com", "organization": "Y"},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_create_without_origin_is_403(client, db_session):
    """CSRF: state-changing admin request with no allowed Origin is blocked."""
    raw = await _seed_user_session(db_session, "admin")
    res = await client.post(
        "/api/admin/leads",
        cookies={"sid": raw},
        json={"name": "X", "email": "x@x.com", "organization": "Y", "message": "z"},
    )
    assert res.status_code == 403, res.text


# --------------------------------------------------------------------------- #
# Update / follow-up toggle.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_update_fields(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    lead = await _seed_lead(db_session, email="e@x.com", name="Old")
    res = await client.patch(
        f"/api/admin/leads/{lead.id}",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"name": "New Name"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_toggle_followed_up_sets_then_clears_timestamp(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    lead = await _seed_lead(db_session, email="t@x.com", followed_up=False)

    on = await client.patch(
        f"/api/admin/leads/{lead.id}",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"followed_up": True},
    )
    assert on.json()["followed_up"] is True
    assert on.json()["followed_up_at"] is not None

    off = await client.patch(
        f"/api/admin/leads/{lead.id}",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"followed_up": False},
    )
    assert off.json()["followed_up"] is False
    assert off.json()["followed_up_at"] is None


@pytest.mark.asyncio
async def test_update_missing_404(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    res = await client.patch(
        "/api/admin/leads/999999",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"name": "Nope"},
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_update_email_conflict_409(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    await _seed_lead(db_session, email="taken@x.com")
    mine = await _seed_lead(db_session, email="mine@x.com")
    res = await client.patch(
        f"/api/admin/leads/{mine.id}",
        cookies={"sid": raw},
        headers=ORIGIN_HEADER,
        json={"email": "taken@x.com"},
    )
    assert res.status_code == 409, res.text


# --------------------------------------------------------------------------- #
# Delete.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_delete_lead(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    lead = await _seed_lead(db_session, email="del@x.com")
    res = await client.delete(
        f"/api/admin/leads/{lead.id}", cookies={"sid": raw}, headers=ORIGIN_HEADER
    )
    assert res.status_code == 204
    count = (await db_session.execute(text("SELECT COUNT(*) FROM leads"))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_delete_missing_404(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    res = await client.delete(
        "/api/admin/leads/999999", cookies={"sid": raw}, headers=ORIGIN_HEADER
    )
    assert res.status_code == 404


# --------------------------------------------------------------------------- #
# CSV export.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_csv_export(client, db_session):
    raw = await _seed_user_session(db_session, "admin")
    await _seed_lead(db_session, email="csv@x.com", name="Csv Person", msg="export me")
    res = await client.get("/api/admin/leads.csv", cookies={"sid": raw})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers.get("content-disposition", "")
    text_body = res.text
    assert "name,email,organization,message,followed_up,followed_up_at,created_at" in text_body
    assert "csv@x.com" in text_body
    assert "export me" in text_body
