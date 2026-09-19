"""Founder publication authority, immutable approval history, and exact consent."""
import asyncio
import hashlib
import io
import json
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routes.contributor import AGREEMENTS
from app.api.routes.ops import _put_setting
from app.core import ops_s3
from app.models import ContributorConsent, Episode, OpsSetting, User
from tests.test_contributor_mobile import SUBJECT, identity, setup
from tests.test_ops_routes import ORIGIN, _client, _sid, app

ROUTING = "kr-2026-v1"
URL = "/api/ops/contributors/terms/" + ROUTING
CURRENT = "contributor_terms_" + ROUTING
FOUNDER_CONFIG = "CONTRIBUTOR_TERMS_FOUNDER_EMAILS"


def bundle(version="v1", locales=("en",)):
    return {"approved_for_publication": True, "documents": [
        {"agreement": agreement, "locale": locale, "version": version,
         "key": f"terms/korea/{agreement}/{version}/{locale}.pdf",
         "object_version": f"object-{version}-{locale}",
         "sha256": hashlib.sha256(f"{agreement}/{version}/{locale}".encode()).hexdigest()}
        for locale in locales for agreement in sorted(AGREEMENTS)
    ]}


def consent_body(docs, locale="en"):
    localized = [d for d in docs if d["locale"] == locale]
    return {"locale": locale,
            "documents": {d["agreement"]: d["sha256"] for d in localized},
            "versions": {d["agreement"]: d["version"] for d in localized}}


@pytest.fixture
def s3(monkeypatch):
    class Fake:
        calls = []

        def get_object(self, **kwargs):
            self.calls.append(kwargs)
            _, _, agreement, version, filename = kwargs["Key"].split("/")
            return {"Body": io.BytesIO(f"{agreement}/{version}/{filename[:-4]}".encode())}

        def generate_presigned_url(self, operation, **kwargs):
            return "https://private.example.test/" + kwargs["Params"]["Key"]

    fake = Fake()
    monkeypatch.setattr(ops_s3, "_client", lambda _: fake)
    # contributor.py binds its read-only URL signer at import time.
    monkeypatch.setattr("app.api.routes.contributor.s3_client", lambda _: fake)
    return fake


async def post(client, sid, body=None):
    return await client.post(URL, json=body or bundle(), cookies={"sid": sid},
                             headers={"Origin": ORIGIN})


async def audits(db):
    rows = (await db.execute(select(OpsSetting).where(
        OpsSetting.key.startswith("contributor_terms_audit_")))).scalars().all()
    return {row.key: row.value for row in rows}


@pytest.mark.parametrize("role", ["ops", "admin", "founder"])
@pytest.mark.parametrize("configuration", ["", "someone-else@example.test"])
async def test_roles_cannot_publish_without_explicit_founder_identity(
        app, db_session, monkeypatch, s3, role, configuration):
    monkeypatch.setenv(FOUNDER_CONFIG, configuration)
    sid = await _sid(db_session, role)
    async with _client(app) as client:
        response = await post(client, sid, {**bundle(), "approved_by": "someone-else@example.test"})
    assert response.status_code == 403
    assert not s3.calls
    assert await db_session.get(OpsSetting, CURRENT) is None
    assert await audits(db_session) == {}


@pytest.mark.parametrize("role", ["customer", "investor", "guest"])
async def test_allowlist_never_grants_staff_access(app, db_session, monkeypatch, s3, role):
    monkeypatch.setenv(FOUNDER_CONFIG, role + "@ops.test")
    sid = await _sid(db_session, role)
    async with _client(app) as client:
        assert (await post(client, sid)).status_code == 403
    assert not s3.calls


async def test_founder_requires_active_session_and_csrf(app, db_session, monkeypatch, s3):
    monkeypatch.setenv(FOUNDER_CONFIG, "founder@ops.test")
    sid = await _sid(db_session, "founder")
    async with _client(app) as client:
        assert (await post(client, "invalid")).status_code == 401
        for origin in ({}, {"Origin": "https://untrusted.example"}):
            response = await client.post(URL, json=bundle(), cookies={"sid": sid}, headers=origin)
            assert response.status_code == 403
        user = (await db_session.execute(select(User))).scalar_one()
        user.is_active = False
        await db_session.commit()
        assert (await post(client, sid)).status_code == 401
    assert not s3.calls


async def test_publication_records_founder_and_exact_versions_once(app, db_session, monkeypatch, s3):
    monkeypatch.setenv(FOUNDER_CONFIG, " FOUNDER@OPS.TEST , admin@ops.test ")
    founder = await _sid(db_session, "founder")
    other_founder = await _sid(db_session, "admin")
    body = bundle(locales=("en", "ko"))
    async with _client(app) as client:
        response = await post(client, founder, body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["current"] is True
        before = await audits(db_session)
        assert len(before) == 1
        audit = json.loads(next(iter(before.values())))
        original_user = (await db_session.execute(select(User).where(User.role == "founder"))).scalar_one()
        assert audit["approved_by"] == original_user.email
        assert audit["approved_by_user_id"] == original_user.id
        assert datetime.fromisoformat(audit["approved_at"]).tzinfo is not None
        assert audit["id"] == result["publication_id"] and audit["routing_version"] == ROUTING
        for actual, expected in zip(audit["documents"], sorted(body["documents"], key=lambda d: (d["agreement"], d["locale"]))):
            assert all(actual[k] == v for k, v in expected.items())
            assert actual["approved_by"] == original_user.email
            assert actual["published_at"] == audit["approved_at"]
        retry = await post(client, other_founder, {**body, "documents": list(reversed(body["documents"]))})
        assert retry.json() == result
        assert await audits(db_session) == before
        assert len(s3.calls) == 8


async def test_replaying_prior_bundle_cannot_roll_back_new_publication(app, db_session, monkeypatch, s3):
    monkeypatch.setenv(FOUNDER_CONFIG, "founder@ops.test")
    sid = await _sid(db_session, "founder")
    async with _client(app) as client:
        old = (await post(client, sid)).json()
        current = (await post(client, sid, bundle("v2"))).json()
        replay = await post(client, sid)
        assert replay.json() == {**old, "current": False}
    db_session.expire_all()
    docs = json.loads((await db_session.get(OpsSetting, CURRENT)).value)
    assert {d["publication_id"] for d in docs} == {current["publication_id"]}
    assert len(await audits(db_session)) == 2
    assert len(s3.calls) == 8


@pytest.mark.parametrize("field,value", [("sha256", "a" * 64), ("object_version", "changed-object"), ("key", "terms/korea/collection/v1/other.pdf")])
async def test_published_document_versions_cannot_be_rebound(app, db_session, monkeypatch, s3, field, value):
    monkeypatch.setenv(FOUNDER_CONFIG, "founder@ops.test")
    sid = await _sid(db_session, "founder")
    async with _client(app) as client:
        assert (await post(client, sid)).status_code == 200
        before = await audits(db_session)
        changed = bundle()
        changed["documents"][0][field] = value
        assert (await post(client, sid, changed)).status_code == 409
    assert await audits(db_session) == before
    assert len(s3.calls) == 4


async def test_concurrent_publication_retries_have_one_audit(app, db_session, monkeypatch, s3):
    monkeypatch.setenv(FOUNDER_CONFIG, "founder@ops.test")
    sid = await _sid(db_session, "founder")
    async with _client(app) as client:
        first, second = await asyncio.gather(post(client, sid), post(client, sid))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(await audits(db_session)) == 1
    assert len(s3.calls) == 4


@pytest.mark.parametrize("failure", ["three_documents", "partial_language", "unapproved", "hash", "unversioned"])
async def test_incomplete_or_unverified_terms_never_publish(app, db_session, monkeypatch, s3, failure):
    monkeypatch.setenv(FOUNDER_CONFIG, "founder@ops.test")
    sid = await _sid(db_session, "founder")
    body = bundle()
    if failure == "three_documents":
        body["documents"] = [d for d in body["documents"] if d["agreement"] != "international_transfer"]
    elif failure == "partial_language":
        body["documents"][0]["locale"] = "ko"
    elif failure == "unapproved":
        body["approved_for_publication"] = False
    elif failure == "hash":
        body["documents"][0]["sha256"] = "0" * 64
    else:
        body["documents"][0]["object_version"] = "null"
    async with _client(app) as client:
        response = await post(client, sid, body)
    assert response.status_code == 422
    assert await db_session.get(OpsSetting, CURRENT) is None
    assert await audits(db_session) == {}


@pytest.mark.parametrize("key", [CURRENT, "contributor_terms_audit_" + str(uuid4()), " CONTRIBUTOR_TERMS_new"])
async def test_generic_setting_writer_cannot_publish_or_rewrite_audits(db_session, key):
    with pytest.raises(PermissionError, match="founder publication"):
        await _put_setting(db_session, key, "forged")
    await _put_setting(db_session, "last_scan", "normal scan")
    await db_session.commit()
    assert await db_session.get(OpsSetting, key) is None
    assert (await db_session.get(OpsSetting, "last_scan")).value == "normal scan"


async def test_ops_import_cannot_write_terms_or_forge_founder_audit(app, db_session, monkeypatch, s3):
    monkeypatch.setenv(FOUNDER_CONFIG, "founder@ops.test")
    founder = await _sid(db_session, "founder")
    ops = await _sid(db_session, "ops")
    async with _client(app) as client:
        assert (await post(client, founder)).status_code == 200
        before = await audits(db_session)
        current_before = (await db_session.get(OpsSetting, CURRENT)).value
        forged = {CURRENT: "forged", next(iter(before)): "forged"}
        response = await client.post("/api/ops/import", json={
            "episodes": {"legitimate_import": {"duration_s": 60, "settings": forged}},
            "settings": forged, "ops_settings": forged, **forged,
        }, cookies={"sid": ops}, headers={"Origin": ORIGIN})
        assert response.status_code == 200, response.text
        assert (await post(client, ops)).status_code == 403
    db_session.expire_all()
    assert (await db_session.get(OpsSetting, CURRENT)).value == current_before
    assert await audits(db_session) == before
    assert (await db_session.execute(select(Episode).where(
        Episode.recording == "legitimate_import"))).scalar_one().duration_s == 60
    assert len(s3.calls) == 4


@pytest.mark.parametrize("stored", ["old_three", "malformed", "duplicate"])
async def test_old_or_incomplete_bundles_fail_closed_everywhere(app, db_session, stored):
    await setup(db_session)
    identity(app)
    docs = bundle()["documents"]
    old = [d for d in docs if d["agreement"] != "international_transfer"]
    value = json.dumps(old if stored == "old_three" else docs + docs[:1]) if stored != "malformed" else "broken-json"
    db_session.add(OpsSetting(key=CURRENT, value=value))
    db_session.add(ContributorConsent(id=str(uuid4()), subject=SUBJECT, snapshot=json.dumps({"documents": old})))
    await db_session.commit()
    sid = await _sid(db_session, "ops")
    async with _client(app) as client:
        assert (await client.get("/api/contributor/terms")).json() == {"status": "not_published", "documents": []}
        assert (await client.get("/api/contributor/dashboard")).json()["consent_current"] is False
        assert (await client.post("/api/contributor/consent", json=consent_body(old))).status_code == 409
        assert (await client.post("/api/contributor/cameras", json={"device_id": "ABC123"})).status_code == 409
        # This legacy Wise route was retired by the spreadsheet onboarding release.
        assert (await client.post("/api/contributor/bank/requirements", json={})).status_code == 410
        assert (await client.post("/api/contributor/bank", json={})).status_code == 410
        onboarding = (await client.get("/api/ops/state", cookies={"sid": sid})).json()["onboarding"]
    assert onboarding["terms_status"] == "terms_not_configured"
    assert set(onboarding["required_agreements"]) == AGREEMENTS


async def test_consent_requires_all_four_exact_versions_hashes_and_locale(app, db_session, monkeypatch, s3):
    monkeypatch.setenv(FOUNDER_CONFIG, "founder@ops.test")
    sid = await _sid(db_session, "founder")
    await setup(db_session)
    identity(app)
    body = bundle(locales=("en", "ko"))
    async with _client(app) as client:
        assert (await post(client, sid, body)).status_code == 200
        old = [d for d in body["documents"] if d["agreement"] != "international_transfer"]
        db_session.add(ContributorConsent(id=str(uuid4()), subject=SUBJECT, snapshot=json.dumps({"documents": old[:3]})))
        await db_session.commit()
        assert (await client.get("/api/contributor/dashboard")).json()["consent_current"] is False
        for bad in (consent_body(old), {**consent_body(body["documents"]), "locale": "ko"},
                    {**consent_body(body["documents"]), "versions": {k: "wrong" for k in AGREEMENTS}},
                    {**consent_body(body["documents"]), "documents": {k: "0" * 64 for k in AGREEMENTS}}):
            assert (await client.post("/api/contributor/consent", json=bad)).status_code == 409
        missing_versions = consent_body(body["documents"])
        missing_versions.pop("versions")
        assert (await client.post("/api/contributor/consent", json=missing_versions)).status_code == 422
        before = None
        for locale in ("en", "en", "ko"):
            docs = (await client.get("/api/contributor/terms", params={"locale": locale})).json()["documents"]
            assert {d["agreement"] for d in docs} == AGREEMENTS
            assert all(set(d) == {"agreement", "version", "sha256", "locale", "url"} for d in docs)
            assert (await client.post("/api/contributor/consent", json=consent_body(docs, locale))).status_code == 200
            receipts = (await db_session.execute(select(ContributorConsent))).scalars().all()
            if before is None:
                before = {r.id: r.snapshot for r in receipts}
            else:
                assert all(next(r.snapshot for r in receipts if r.id == key) == value for key, value in before.items())
        assert (await client.get("/api/contributor/dashboard")).json()["consent_current"] is True
    assert len(receipts) == 3  # Original incomplete receipt plus one immutable receipt per language.
    accepted = [json.loads(r.snapshot) for r in receipts if "accepted_at" in json.loads(r.snapshot)]
    assert {r["locale"] for r in accepted} == {"en", "ko"}
    for receipt in accepted:
        assert receipt["subject"] == SUBJECT and receipt["routing_version"] == ROUTING
        assert len(receipt["documents"]) == 4
        assert {d["agreement"] for d in receipt["documents"]} == AGREEMENTS
        assert {d["locale"] for d in receipt["documents"]} == {receipt["locale"]}
        assert all(d["version"] == "v1" and d["sha256"] and d["publication_id"] for d in receipt["documents"])


async def test_same_bytes_new_version_still_requires_exact_displayed_version(app, db_session):
    await setup(db_session)
    identity(app)
    displayed = bundle()["documents"]
    newer = [{**d, "version": "v2"} for d in displayed]
    db_session.add(OpsSetting(key=CURRENT, value=json.dumps(newer)))
    await db_session.commit()
    async with _client(app) as client:
        assert (await client.post("/api/contributor/consent", json=consent_body(displayed))).status_code == 409
        assert (await client.post("/api/contributor/consent", json=consent_body(newer))).status_code == 200
