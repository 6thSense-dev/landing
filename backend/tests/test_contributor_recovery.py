"""Recipient recovery is audited, retry-safe, and separate from payout approval."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import ContributorRecipientAttempt, OpsSetting, PayoutRecipient
from tests.test_contributor_mobile import SUBJECT, accept, identity, setup
from tests.test_ops_routes import app, _client, _sid, ORIGIN


async def held_attempt(db, *, status="needs_reconciliation", recipient_id=None, age_minutes=10):
    account = await setup(db)
    attempt = ContributorRecipientAttempt(
        id=str(uuid4()), subject=SUBJECT, status=status, recipient_id=recipient_id,
        summary=json.dumps({"country": "KR", "currency": "KRW", "maskedAccount": "•••• 7890"}),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )
    db.add(attempt)
    await db.commit()
    return account, attempt


@pytest.fixture
def provider(monkeypatch):
    from app.core import wise
    monkeypatch.setenv("WISE_PROFILE_ID", "123")
    monkeypatch.setenv("WISE_ENVIRONMENT", "sandbox")
    calls = []
    result = {
        "id": 456, "active": True, "profileId": 123, "currency": "KRW", "hash": "recipient-hash",
        "details": {"accountNumber": "001234567890", "email": "private@example.invalid"},
    }

    class FakeWise:
        def recipient(self, recipient_id):
            calls.append(recipient_id)
            return result

    monkeypatch.setattr(wise, "WiseClient", FakeWise)
    return result, calls


def found(**changes):
    return {"resolution": "found", "recipient_id": 456, "verified_owner": True,
            "note": "Confirmed ownership with contributor and Wise.", **changes}


def not_created(**changes):
    return {"resolution": "not_created", "confirmed_not_created": True,
            "note": "Wise confirmed this submission created no recipient.", **changes}


def path(attempt):
    return f"/api/ops/contributors/recipients/{attempt.id}/resolve"


async def post(client, attempt, sid, body):
    return await client.post(path(attempt), json=body, cookies={"sid": sid}, headers={"Origin": ORIGIN})


async def audit_for(db, attempt):
    return await db.get(OpsSetting, "contributor_bank_audit_" + attempt.id)


async def test_recovery_requires_staff_session_and_csrf(app, db_session, provider):
    _, attempt = await held_attempt(db_session)
    sid = await _sid(db_session, "ops")
    identity(app)
    async with _client(app) as client:
        response = await client.post(path(attempt), json=found(), headers={"Origin": ORIGIN, "Authorization": "Bearer mobile-token"})
        assert response.status_code == 401
        response = await client.post(path(attempt), json=found(), cookies={"sid": sid})
        assert response.status_code == 403
    assert provider[1] == []
    assert await audit_for(db_session, attempt) is None


async def test_found_recipient_is_audited_once_without_approving_payout(app, db_session, provider):
    account, attempt = await held_attempt(db_session)
    sid = await _sid(db_session, "ops")
    async with _client(app) as client:
        response = await post(client, attempt, sid, found())
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "needs_review"
        await db_session.refresh(attempt)
        assert attempt.recipient_id == "456"
        assert await db_session.get(PayoutRecipient, account.wearer_id) is None
        audit = await audit_for(db_session, attempt)
        original = audit.value
        evidence = json.loads(original)
        assert evidence["operator"] == "ops@ops.test"
        assert evidence["previous_status"] == "needs_reconciliation"
        assert evidence["wise_profile_id"] == "123" and evidence["wise_environment"] == "sandbox"
        assert evidence["verified_owner"] and evidence["resolved_at"]
        assert "001234567890" not in original and "private@example.invalid" not in original
        assert "note" not in response.json()
        assert (await post(client, attempt, sid, found(note="Do not overwrite the original evidence."))).status_code == 200
        assert (await post(client, attempt, sid, not_created())).status_code == 409
        assert (await post(client, attempt, sid, found(recipient_id=457))).status_code == 409
        await db_session.refresh(audit)
        assert audit.value == original and provider[1] == [456]
        identity(app)
        dashboard = await client.get("/api/contributor/dashboard")
        assert dashboard.json()["bank"]["status"] == "needs_review"
        assert "Confirmed ownership" not in dashboard.text
        # The existing payment screen must still explicitly verify and link it.
        linked = await client.post("/api/ops/payments/recipient", json={"wearer_id": account.wearer_id,
            "recipient_id": 456, "confirm_recipient": True}, cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert linked.status_code == 200, linked.text
        assert (await client.get("/api/contributor/dashboard")).json()["bank"]["status"] == "ready"


@pytest.mark.parametrize("field,value", [("active", False), ("profileId", 999), ("currency", "USD"), ("id", 457), ("hash", "")])
async def test_found_recipient_must_match_provider_account(app, db_session, provider, field, value):
    _, attempt = await held_attempt(db_session)
    sid = await _sid(db_session, "ops")
    provider[0][field] = value
    async with _client(app) as client:
        response = await post(client, attempt, sid, found())
        assert response.status_code == 409, response.text
    await db_session.refresh(attempt)
    assert attempt.status == "needs_reconciliation" and attempt.recipient_id is None
    assert await audit_for(db_session, attempt) is None


async def test_recovery_requires_explicit_evidence_and_sanitizes_provider_failure(app, db_session, provider, monkeypatch):
    _, attempt = await held_attempt(db_session)
    sid = await _sid(db_session, "ops")
    async with _client(app) as client:
        for body in [found(verified_owner=False), found(note="          "), found(recipient_id=None),
                     not_created(confirmed_not_created=False), not_created(recipient_id=456)]:
            assert (await post(client, attempt, sid, body)).status_code == 422
        assert provider[1] == []
        from app.core import wise
        class BrokenWise:
            def recipient(self, _):
                raise RuntimeError("private-bank-and-provider-token")
        monkeypatch.setattr(wise, "WiseClient", BrokenWise)
        response = await post(client, attempt, sid, found())
        assert response.status_code == 503
        assert "private-bank" not in response.text
    assert await audit_for(db_session, attempt) is None


async def test_confirmed_no_create_allows_one_new_submission(app, db_session, provider, monkeypatch):
    _, attempt = await held_attempt(db_session)
    await accept(db_session)
    identity(app)
    sid = await _sid(db_session, "ops")
    from app.core import contributor_wise
    creates = []
    class FakeRecipient:
        def requirements(self, country, values):
            return {"country": "KR", "currency": "KRW", "fields": [
                {"key": key, "required": True, "minLength": None, "maxLength": None}
                for key in ["accountHolderName", "accountNumber"]]}
        def create(self, country, values):
            creates.append(country)
            return {"id": 456}
    monkeypatch.setattr(contributor_wise, "RecipientClient", FakeRecipient)
    body = {"operation_id": str(uuid4()), "owns_account": True, "shares_details": True,
            "values": {"accountHolderName": "Test Person", "accountNumber": "001234567890"}}
    async with _client(app) as client:
        response = await post(client, attempt, sid, not_created())
        assert response.status_code == 200 and response.json()["status"] == "retry_allowed"
        assert (await client.get("/api/contributor/dashboard")).json()["bank"] is None
        assert (await client.post("/api/contributor/bank", json={**body, "operation_id": attempt.id})).status_code == 409
        for _ in range(2):
            response = await client.post("/api/contributor/bank", json=body)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "needs_review"
        assert (await post(client, attempt, sid, not_created())).status_code == 200
    assert creates == ["KR"] and provider[1] == []
    rows = (await db_session.execute(select(ContributorRecipientAttempt))).scalars().all()
    assert len(rows) == 2
    assert json.loads((await audit_for(db_session, attempt)).value)["confirmed_not_created"]


@pytest.mark.parametrize("age_minutes,expected", [(0, 409), (6, 200)])
async def test_only_stale_inflight_attempts_can_be_reconciled(app, db_session, provider, age_minutes, expected):
    _, attempt = await held_attempt(db_session, status="submitting", age_minutes=age_minutes)
    sid = await _sid(db_session, "ops")
    async with _client(app) as client:
        response = await post(client, attempt, sid, not_created())
        assert response.status_code == expected, response.text
    assert (await audit_for(db_session, attempt) is not None) == (expected == 200)


async def test_known_created_recipient_cannot_be_freed_for_retry(app, db_session, provider):
    _, attempt = await held_attempt(db_session, status="needs_review", recipient_id="456")
    sid = await _sid(db_session, "ops")
    async with _client(app) as client:
        assert (await post(client, attempt, sid, not_created())).status_code == 409
        assert (await post(client, attempt, sid, found(recipient_id=457))).status_code == 409
    assert await audit_for(db_session, attempt) is None


async def test_conflicting_concurrent_resolutions_commit_only_one_audit(app, db_session, provider):
    _, attempt = await held_attempt(db_session)
    sid = await _sid(db_session, "ops")
    async with _client(app) as client:
        responses = await asyncio.gather(post(client, attempt, sid, found()), post(client, attempt, sid, not_created()))
        assert sorted(r.status_code for r in responses) == [200, 409]
    evidence = json.loads((await audit_for(db_session, attempt)).value)
    await db_session.refresh(attempt)
    assert (attempt.status, attempt.recipient_id) == (("needs_review", "456")
        if evidence["resolution"] == "found" else ("retry_allowed", None))
