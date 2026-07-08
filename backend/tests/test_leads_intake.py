"""Integration tests for POST /api/leads — the single Contact Us intake.

Covers: honeypot drop, invalid email (422), required message (422), upsert on
email (one row per address, values refreshed), email case-insensitivity, and
Slack notification behaviour (fired after commit, failure-isolated).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    # Raise the limit well above what any single test needs and reset the bucket
    # store so these functional tests never trip the rate limiter.
    monkeypatch.setenv("SENSEPROBE_RATE_LIMIT", "1000/minute")
    from app.core.limiter import limiter

    limiter.reset()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _payload(**over):
    base = {
        "name": "Ada",
        "email": "ada@x.com",
        "organization": "Acme",
        "message": "I'd like to talk about tactile skin.",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Happy path.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_contact_accepted_and_persisted(client, db_session):
    res = await client.post("/api/leads", json=_payload())
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "created": True}
    row = (
        await db_session.execute(
            text("SELECT name, organization, message FROM leads WHERE email='ada@x.com'")
        )
    ).one()
    assert row == ("Ada", "Acme", "I'd like to talk about tactile skin.")


# --------------------------------------------------------------------------- #
# Honeypot: filled -> silent 200, no DB write, no Slack.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_honeypot_drops_silently(client, db_session, monkeypatch):
    calls = []

    import app.api.routes.leads as leads_mod

    def _spy(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(leads_mod, "notify_new_lead", _spy)

    res = await client.post("/api/leads", json=_payload(website="http://spam.example"))
    assert res.status_code == 200
    assert res.json() == {"ok": True, "created": False}
    count = (await db_session.execute(text("SELECT COUNT(*) FROM leads"))).scalar_one()
    assert count == 0
    assert calls == []  # no Slack notification scheduled


# --------------------------------------------------------------------------- #
# Validation: 422s.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invalid_email_422(client, db_session):
    res = await client.post("/api/leads", json=_payload(email="not-an-email"))
    assert res.status_code == 422, res.text
    count = (await db_session.execute(text("SELECT COUNT(*) FROM leads"))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_missing_message_422(client, db_session):
    body = _payload()
    del body["message"]
    res = await client.post("/api/leads", json=body)
    assert res.status_code == 422, res.text
    count = (await db_session.execute(text("SELECT COUNT(*) FROM leads"))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_blank_message_is_rejected_422(client):
    res = await client.post("/api/leads", json=_payload(message="   "))
    assert res.status_code == 422, res.text


# --------------------------------------------------------------------------- #
# Upsert on email: same email -> one row, refreshed values.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_same_email_upserts(client, db_session):
    r1 = await client.post("/api/leads", json=_payload(message="first"))
    assert r1.json() == {"ok": True, "created": True}
    r2 = await client.post(
        "/api/leads", json=_payload(organization="NewCo", message="second")
    )
    assert r2.json() == {"ok": True, "created": False}
    rows = (
        await db_session.execute(
            text("SELECT organization, message FROM leads WHERE email='ada@x.com'")
        )
    ).all()
    assert rows == [("NewCo", "second")]  # single row, refreshed


@pytest.mark.asyncio
async def test_email_case_insensitive(client, db_session):
    await client.post("/api/leads", json=_payload(email="ada@x.com"))
    await client.post("/api/leads", json=_payload(email="ADA@x.com"))
    count = (await db_session.execute(text("SELECT COUNT(*) FROM leads"))).scalar_one()
    assert count == 1  # normalised email collapses to one row


# --------------------------------------------------------------------------- #
# Slack: fired after commit; a Slack outage does NOT fail the request and the
# row is still committed.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_slack_notification_scheduled_on_success(client, db_session, monkeypatch):
    calls = []
    import app.api.routes.leads as leads_mod

    def _spy(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(leads_mod, "notify_new_lead", _spy)

    res = await client.post("/api/leads", json=_payload())
    assert res.status_code == 200
    assert len(calls) == 1
    assert calls[0]["email"] == "ada@x.com"
    assert calls[0]["is_new"] is True


@pytest.mark.asyncio
async def test_slack_failure_isolated_row_still_committed(
    client, db_session, monkeypatch
):
    # Simulate Slack being completely down at the HTTP layer, exercising the
    # REAL notifier (with its try/except) rather than bypassing it. A webhook is
    # configured so the notifier actually attempts the call, which then fails.
    import app.core.slack as slack_mod

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/down")

    def _explode(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(slack_mod.urllib.request, "urlopen", _explode)

    res = await client.post("/api/leads", json=_payload())
    # Request still succeeds ...
    assert res.status_code == 200
    assert res.json() == {"ok": True, "created": True}
    # ... and the row is committed to the DB despite Slack being down.
    count = (await db_session.execute(text("SELECT COUNT(*) FROM leads"))).scalar_one()
    assert count == 1


def test_notify_new_lead_swallows_errors(monkeypatch):
    """The notifier itself must never raise, even if the HTTP call blows up."""
    import app.core.slack as slack_mod

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")

    def _explode(*a, **k):
        raise OSError("network unreachable")

    monkeypatch.setattr(slack_mod.urllib.request, "urlopen", _explode)

    # Must not raise.
    slack_mod.notify_new_lead(
        name="Ada",
        organization="Acme",
        email="ada@x.com",
        message="hi",
        is_new=True,
    )


def test_notify_new_lead_noop_without_webhook(monkeypatch):
    import app.core.slack as slack_mod

    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    called = []
    monkeypatch.setattr(
        slack_mod.urllib.request,
        "urlopen",
        lambda *a, **k: called.append(1),
    )
    slack_mod.notify_new_lead(
        name="Ada",
        organization="Acme",
        email="ada@x.com",
        message="hi",
        is_new=True,
    )
    assert called == []  # never attempts an HTTP call when unconfigured
