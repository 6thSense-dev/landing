"""Workspace is a personal, GET-only projection; never changes an account role."""
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from app.core.auth_deps import current_user
from app.core.db import get_session
from app.core.catalog_store import reset_store
import app.core.catalog_store as catalog_store
from app.main import create_app
from app.api.routes import ops

PATHS = ["/catalog/guest", "/catalog/guest/clips/clip-one", "/ops/state", "/ops/episodes/a/files"]


def configured(monkeypatch, email="ronak@6thsense.dev", role="admin", active=True):
    monkeypatch.setenv("CATALOG_SOURCE", "local")
    monkeypatch.setenv("CATALOG_LOCAL_DIR", str(Path(__file__).parent / "fixtures/catalog/bundle"))
    monkeypatch.setenv("CATALOG_LOCAL_SIGNING_KEY", "offline-test-workspace")
    # Keep real local signing deterministic when comparison requests straddle
    # a wall-clock second; monotonic cache behavior remains real.
    monkeypatch.setattr(catalog_store, "time", SimpleNamespace(time=lambda: 1900000000, monotonic=time.monotonic))
    reset_store()
    app = create_app()
    user = SimpleNamespace(id=3, email=email, role=role, is_active=active, name="Test owner")
    async def identity(): return user
    async def db(): yield None
    app.dependency_overrides[current_user] = identity
    app.dependency_overrides[get_session] = db
    return app, user


@pytest.mark.asyncio
@pytest.mark.parametrize("email,role,active", [
    ("other@6thsense.dev", "admin", True), ("ronak@6thsense.dev", "guest", True),
    ("ronak@6thsense.dev", "ops", True), ("ronak@6thsense.dev", "founder", True),
    ("ronak@6thsense.dev", "customer", True), ("ronak@6thsense.dev", "investor", True),
    ("ronak@6thsense.dev", "admin", False), ("Ronak@6thsense.dev", "admin", True),
])
async def test_only_exact_active_owner(monkeypatch, email, role, active):
    app, user = configured(monkeypatch, email, role, active)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/workspace/capability")).json() == {"enabled": False}
        for path in PATHS:
            r = await c.get("/api/workspace" + path, headers={"X-User-Email":"ronak@6thsense.dev", "X-Role":"admin"})
            assert r.status_code == 403
        assert (await c.get("/api/auth/me")).json()["workspace_enabled"] is False


@pytest.mark.asyncio
async def test_anonymous_cannot_reach_preview():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for path in ["/capability", *PATHS]:
            assert (await c.get("/api/workspace" + path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["guest", "investor", "customer", "founder", "admin"])
async def test_exact_existing_role_redaction_and_scoped_details(monkeypatch, role):
    app, user = configured(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        preview = await c.get(f"/api/workspace/catalog/{role}")
        detail = await c.get(f"/api/workspace/catalog/{role}/clips/clip-one")
        assert preview.status_code == detail.status_code == 200
        assert "no-store" in preview.headers["cache-control"]
        assert user.role == "admin" and user.email == "ronak@6thsense.dev"
        assert (await c.get("/api/auth/me")).json()["workspace_enabled"] is True
        # Compare with real production endpoints for the same role, including
        # every withheld pointer, after removing only role-scope URL/expiry.
        user.role = role
        actual = await c.get("/api/catalog")
        actual_detail = await c.get("/api/catalog/clips/clip-one")
        def normal(doc):
            if isinstance(doc, dict): return {k: normal(v) for k,v in doc.items() if k != "expires_at"}
            if isinstance(doc, list): return [normal(v) for v in doc]
            if isinstance(doc, str):
                return doc.replace(f"/api/workspace/catalog/{role}", "/api/catalog")
            return doc
        assert normal(preview.json()) == normal(actual.json())
        assert normal(detail.json()) == normal(actual_detail.json())
        for clip in preview.json()["clips"]:
            if clip.get("detail"):
                assert f"/api/workspace/catalog/{role}/clips/" in clip["detail"]


@pytest.mark.asyncio
async def test_no_preview_writes_or_generic_proxy(monkeypatch):
    app, user = configured(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/workspace/catalog/ops")).status_code == 404
        assert (await c.get("/api/workspace/catalog/guest/clips/unpublished")).status_code == 404
        for path in [*PATHS, "/ops/scan", "/ops/pay-bulk", "/ops/episodes/a/delete", "/ops/rate", "/admin/leads"]:
            for method in ["POST", "PUT", "PATCH", "DELETE"]:
                r = await c.request(method, "/api/workspace" + path, json={}, headers={"Origin":"http://localhost:5173"})
                assert r.status_code in (404,405)
        assert user.role == "admin"


@pytest.mark.asyncio
async def test_ops_preview_uses_existing_get_handlers(monkeypatch):
    app, user = configured(monkeypatch)
    calls=[]
    async def state(owner, db):
        calls.append(("state", owner.id)); return {"episodes": [{"recording":"one", "minutes":2}],"rate_krw":0}
    async def files(recording, owner, db):
        calls.append(("files", owner.id, recording)); return {"ok":True,"files":[]}
    monkeypatch.setattr(ops, "get_state", state)
    monkeypatch.setattr(ops, "list_episode_files", files)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r=await c.get("/api/workspace/ops/state")
        assert r.json()["episodes"][0]["recording"] == "one"
        assert "no-store" in r.headers["cache-control"]
        assert (await c.get("/api/workspace/ops/episodes/one/files")).json()["ok"] is True
    assert calls == [("state",3),("files",3,"one")]
