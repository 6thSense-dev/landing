"""The internal feature never trusts submitted identities or changes payments."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from httpx import ASGITransport, AsyncClient
from app.core.auth_deps import current_user
from app.main import create_app
from app.api.routes.intake_review import document, FIXTURE
from app.vendor.intake.workbench import project_activity

PREFIX = "/api/ops/intake-review"
ORIGIN = {"Origin": "http://localhost:5173"}


def configured(monkeypatch, email="ronak@6thsense.dev", role="admin", active=True, enabled=True):
    monkeypatch.setenv("INTAKE_REVIEW_ENABLED", "true" if enabled else "false")
    app = create_app()
    async def identity():
        return SimpleNamespace(id=123, email=email, role=role, is_active=active)
    app.dependency_overrides[current_user] = identity
    return app


def payload():
    view = project_activity(document()); c = view["candidates"][0]
    return dict(snapshot_sha256=view["snapshot_sha256"], candidate_id=c["id"], current_sha256=c["current_sha256"],
                bounds=[dict(span_id=s["span_id"], start_ns=s["interval_ns"][0], end_ns=s["interval_ns"][1]) for s in c["spans"]],
                reason="Synthetic reviewer trim", evidence_ids=["SYNTHETIC-review"])


@pytest.mark.asyncio
@pytest.mark.parametrize("email,role,active,enabled", [("ops@6thsense.dev","admin",True,True), ("guest@6thsense.dev","guest",True,True), ("ronak@6thsense.dev","ops",True,True), ("ronak@6thsense.dev","admin",False,True), ("ronak@6thsense.dev","admin",True,False)])
async def test_denied_every_private_endpoint(monkeypatch, email, role, active, enabled):
    app = configured(monkeypatch,email,role,active,enabled)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get(PREFIX+"/capability")).json() == {"enabled":False}
        for path in ("/activity","/preview"):
            r = await c.get(PREFIX+path, headers={"X-User-Email":"ronak@6thsense.dev"})
            assert r.status_code == 403
        assert (await c.post(PREFIX+"/proposal",json=payload(),headers=ORIGIN)).status_code == 403


@pytest.mark.asyncio
async def test_anonymous_denied(monkeypatch):
    monkeypatch.setenv("INTAKE_REVIEW_ENABLED", "true")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        for path in ("/capability","/activity","/preview"):
            assert (await c.get(PREFIX+path)).status_code == 401


@pytest.mark.asyncio
async def test_native_export_exact_time_and_immutable_source(monkeypatch):
    before = (FIXTURE/"cohort.json").read_bytes()
    app = configured(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get(PREFIX+"/capability")).json() == {"enabled":True}
        view = await c.get(PREFIX+"/activity")
        assert view.status_code == 200 and "no-store" in view.headers["cache-control"]
        preview = await c.get(PREFIX+"/preview")
        assert preview.status_code == 200 and preview.content == (FIXTURE/"preview.webm").read_bytes()
        p = payload(); p["bounds"][0]["start_ns"] = str(int(p["bounds"][0]["start_ns"])+1)
        result = await c.post(PREFIX+"/proposal",json=p,headers=ORIGIN)
        assert result.status_code == 200, result.text
        artifact = result.json()
        assert str(artifact["source_input"]["proposed"]["spans"][0]["interval_ns"][0]) == p["bounds"][0]["start_ns"]
        assert artifact["correction_receipt"]["reviewer_id"] == "ronak@6thsense.dev"
        assert artifact["collector_credit"] == "unchanged"
        assert "attachment" in result.headers["content-disposition"]
        assert (FIXTURE/"cohort.json").read_bytes() == before


@pytest.mark.asyncio
async def test_refuses_spoofing_stale_bounds_csrf_and_unbounded(monkeypatch):
    app = configured(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for mode in ("spoof", "stale", "outside", "rounded"):
            p = payload()
            if mode == "spoof": p["reviewer_id"] = "other"
            if mode == "stale": p["snapshot_sha256"] = "0"*64
            if mode == "outside": p["bounds"][0]["start_ns"] = "0"
            if mode == "rounded": p["bounds"][0]["start_ns"] = 9007199254741092
            assert (await c.post(PREFIX+"/proposal",json=p,headers=ORIGIN)).status_code == 409
        assert (await c.post(PREFIX+"/proposal",json=payload())).status_code == 403
        assert (await c.post(PREFIX+"/proposal",json=payload(),headers={"Origin":"https://evil.test"})).status_code == 403
        assert (await c.post(PREFIX+"/proposal",content="x"*65537,headers={**ORIGIN,"Content-Type":"application/json"})).status_code == 413
        assert (await c.post(PREFIX+"/proposal",content='{"a":1,"a":2}',headers={**ORIGIN,"Content-Type":"application/json"})).status_code == 409
        assert (await c.get(PREFIX+"/preview/../../core/config.py")).status_code == 404
        assert (await c.get(PREFIX+"/assets/cohort.json")).status_code == 404


@pytest.mark.asyncio
async def test_real_session_reads_persisted_identity_and_revocation(db_session, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.models import User, Session
    from app.core.sessions import hash_session_token
    monkeypatch.setenv("INTAKE_REVIEW_ENABLED", "true")
    user = User(email="ronak@6thsense.dev", name="Synthetic Ronak", role="admin", password_hash="not-used", is_active=True)
    db_session.add(user)
    await db_session.flush()
    db_session.add(Session(user_id=user.id, token_hash=hash_session_token("synthetic-session"), expires_at=datetime.now(timezone.utc)+timedelta(hours=1)))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test", cookies={"sid":"synthetic-session"}) as c:
        assert (await c.get(PREFIX+"/activity")).status_code == 200
        user.email = "ops@6thsense.dev"
        await db_session.commit()
        assert (await c.get(PREFIX+"/activity",headers={"X-User-Email":"ronak@6thsense.dev"})).status_code == 403
        user.email = "ronak@6thsense.dev"; user.role = "ops"
        await db_session.commit()
        assert (await c.get(PREFIX+"/preview")).status_code == 403
        user.role = "admin"; user.is_active = False
        await db_session.commit()
        assert (await c.get(PREFIX+"/activity")).status_code == 401
