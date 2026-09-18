"""Authenticated payment setup, consent receipts and provider-write isolation."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import contributor_wise
from app.core.payment_notice import public_notice
from app.models import ContributorRecipientAttempt, PayoutRecipient
from tests.test_contributor_mobile import setup, accept, identity, SUBJECT, OTHER
from tests.test_ops_routes import app, _client


def body(**overrides):
    notice = public_notice()
    return {
        "values": {"accountHolderName": "Test Recipient", "accountNumber": "001234567890",
                   "dateOfBirth": "1990-01-02", "email": "private@example.invalid"},
        "operation_id": str(uuid4()), "locale": "ko",
        "notice_version": notice["version"], "notice_sha256": notice["sha256"],
        "collects_details": True, "shares_details": True,
        "international_transfer": True, "owns_account": True, **overrides,
    }


@pytest.fixture
def provider(monkeypatch):
    class Fake:
        creations = []
        checks = []
        fail = False

        def requirements(self, country, values):
            self.checks.append(values)
            return {"country": "KR", "currency": "KRW", "fields": [
                {"key": key, "required": True, "minLength": 2, "maxLength": 255}
                for key in body()["values"]]}

        def create(self, country, values):
            self.creations.append(values)
            if self.fail:
                raise OSError("private-provider-response")
            return {"id": 7654321}

    fake = Fake()
    monkeypatch.setattr(contributor_wise, "RecipientClient", lambda: fake)
    return fake


async def test_setup_needs_auth_and_contract_but_not_camera(app, db_session):
    async with _client(app) as client:
        unauth = await client.get("/api/contributor/bank/setup")
        assert unauth.status_code == 401
        assert unauth.headers["cache-control"] == "private, no-store"
        await setup(db_session)
        identity(app)
        assert (await client.get("/api/contributor/bank/setup")).status_code == 409
        await accept(db_session)
        await setup(db_session, OTHER)
        db_session.add(ContributorRecipientAttempt(id=str(uuid4()), subject=OTHER,
            summary=json.dumps({"accountHolderName": "Other private name", "maskedAccount": "•••• 9999"}), status="needs_review"))
        await db_session.commit()
        response = await client.get("/api/contributor/bank/setup")
        assert response.status_code == 200
        assert response.json()["bank"] is None
        assert response.json()["notice"] == public_notice()
        assert "Other private" not in response.text


async def test_web_requires_each_consent_and_exact_notice_before_provider(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    async with _client(app) as client:
        for endpoint in ("/web/requirements", "/web"):
            for key in ("collects_details", "shares_details", "international_transfer", "owns_account"):
                response = await client.post("/api/contributor/bank" + endpoint, json=body(**{key: False}))
                assert response.status_code == 422
            for override in ({"notice_version": "stale"}, {"notice_sha256": "0" * 64}):
                assert (await client.post("/api/contributor/bank" + endpoint, json=body(**override))).status_code == 409
        assert provider.checks == provider.creations == []


async def test_masked_submission_records_notice_and_never_repeats_create(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    payload = body()
    async with _client(app) as client:
        for _ in range(2):
            response = await client.post("/api/contributor/bank/web", json=payload)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "needs_review"
        assert len(provider.creations) == 1
        attempt = (await db_session.execute(select(ContributorRecipientAttempt))).scalar_one()
        summary = json.loads(attempt.summary)
        assert summary["maskedAccount"] == "•••• 7890"
        for secret in ("001234567890", "1990-01-02", "private@example.invalid"):
            assert secret not in attempt.summary
        receipt = summary["payment_consent"]
        assert receipt["notice"] == public_notice()
        assert receipt["locale"] == "ko" and receipt["accepted_at"]
        assert all(receipt["choices"].values())
        response = await client.get("/api/contributor/bank/setup")
        assert response.json()["bank"]["maskedAccount"] == "•••• 7890"
        assert "payment_consent" not in response.json()["bank"]


async def test_unknown_outcome_remains_held_after_new_operation_id(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    provider.fail = True
    async with _client(app) as client:
        for _ in range(2):
            response = await client.post("/api/contributor/bank/web", json=body())
            assert response.json()["status"] == "needs_reconciliation"
            assert "private-provider" not in response.text
        assert len(provider.creations) == 1
        assert (await client.get("/api/contributor/bank/setup")).json()["bank"]["status"] == "needs_reconciliation"


async def test_manually_linked_recipient_is_ready_without_new_creation(app, db_session, provider):
    account = await setup(db_session); await accept(db_session); identity(app)
    db_session.add(PayoutRecipient(wearer_id=account.wearer_id, wise_recipient_id="12345",
        recipient_hash="a" * 64, wise_profile_id="1", wise_environment="production",
        verified_name="Test Recipient", updated_by="ops@example.invalid"))
    await db_session.commit()
    async with _client(app) as client:
        response = await client.get("/api/contributor/bank/setup")
        assert response.json()["bank"]["status"] == "ready"
        assert (await client.post("/api/contributor/bank/web", json=body())).json()["status"] == "ready"
        assert provider.creations == provider.checks == []


async def test_invalid_fields_do_not_create_attempt_or_echo_details(app, db_session, provider):
    await setup(db_session); await accept(db_session); identity(app)
    async with _client(app) as client:
        response = await client.post("/api/contributor/bank/web", json=body(values={"accountNumber": "1"}))
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_bank_fields"
        assert not provider.creations
        assert not (await db_session.execute(select(ContributorRecipientAttempt))).scalars().all()
        response = await client.post("/api/contributor/bank/web", content="x" * 9000)
        assert response.status_code == 413 and response.headers["cache-control"] == "private, no-store"
