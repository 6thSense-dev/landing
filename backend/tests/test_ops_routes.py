"""/api/ops/*: role gate, CSRF prefix, the approve-before-pay guard, and the
two kinds of delete."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.passwords import hash_password
from app.core.sessions import hash_session_token, mint_session_token
from app.main import create_app
from app.models import Episode, Session as SessionRow, User, Wearer


ORIGIN = "https://app.example"


@pytest_asyncio.fixture
async def app(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", ORIGIN)
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    from app.core.limiter import limiter
    limiter.reset()
    return create_app()


async def _sid(db_session, role: str) -> str:
    user = User(email=f"{role}@ops.test", name=role, role=role,
                password_hash=hash_password("twelve-chars!!"))
    db_session.add(user)
    await db_session.commit()
    raw = mint_session_token()
    db_session.add(SessionRow(user_id=user.id, token_hash=hash_session_token(raw),
                              expires_at=datetime.now(timezone.utc) + timedelta(days=14)))
    await db_session.commit()
    return raw


async def _episode(db_session, recording="ego_test_0001", **kw) -> Episode:
    e = Episode(recording=recording, session="s", device_id="ABC123", **kw)
    db_session.add(e)
    await db_session.commit()
    return e


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# --- who may reach it ---------------------------------------------------------

@pytest.mark.parametrize("role", ["ops", "founder", "admin"])
@pytest.mark.asyncio
async def test_ops_area_open_to_ops_founder_admin(app, db_session, role):
    sid = await _sid(db_session, role)
    async with _client(app) as c:
        assert (await c.get("/api/ops/state", cookies={"sid": sid})).status_code == 200


@pytest.mark.parametrize("role", ["customer", "investor", "guest"])
@pytest.mark.asyncio
async def test_ops_area_closed_to_everyone_else(app, db_session, role):
    sid = await _sid(db_session, role)
    async with _client(app) as c:
        assert (await c.get("/api/ops/state", cookies={"sid": sid})).status_code == 403


@pytest.mark.asyncio
async def test_ops_area_needs_a_session(app):
    async with _client(app) as c:
        assert (await c.get("/api/ops/state")).status_code == 401


@pytest.mark.asyncio
async def test_writes_are_behind_the_origin_check(app, db_session):
    """A hard delete purges objects from a bucket that denies re-upload. One
    cross-site form post from a logged-in ops session must not reach it."""
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    async with _client(app) as c:
        no_origin = await c.post("/api/ops/episodes/ego_test_0001/delete",
                                 json={"kind": "hard"}, cookies={"sid": sid})
        wrong = await c.post("/api/ops/episodes/ego_test_0001/delete",
                             json={"kind": "hard"}, cookies={"sid": sid},
                             headers={"Origin": "https://evil.example"})
    assert no_origin.status_code == 403
    assert wrong.status_code == 403


# --- approve / pay ------------------------------------------------------------

@pytest.mark.asyncio
async def test_pay_refuses_an_unapproved_episode(app, db_session):
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    async with _client(app) as c:
        res = await c.post("/api/ops/episodes/ego_test_0001/pay",
                           json={"value": True, "amount_krw": 10320},
                           cookies={"sid": sid}, headers={"Origin": ORIGIN})
    assert res.status_code == 409

    async with _client(app) as c:
        await c.post("/api/ops/episodes/ego_test_0001/approve", json={"value": True},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
        ok = await c.post("/api/ops/episodes/ego_test_0001/pay",
                          json={"value": True, "amount_krw": 10320},
                          cookies={"sid": sid}, headers={"Origin": ORIGIN})
    assert ok.status_code == 200
    row = next(e for e in ok.json()["episodes"] if e["recording"] == "ego_test_0001")
    assert row["paid"] is True and row["amount_krw"] == 10320


# --- assignment ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_stores_the_wearer_on_the_episode(app, db_session):
    """Stored on the episode, not resolved through a device date range -- so a
    camera handed over mid-shift splits, and settled history never moves."""
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    db_session.add(Wearer(name="Wearer One"))
    await db_session.commit()
    wid = (await db_session.execute(__import__("sqlalchemy").select(Wearer.id))).scalar_one()
    async with _client(app) as c:
        res = await c.post("/api/ops/episodes/ego_test_0001/assign",
                           json={"wearer_id": wid}, cookies={"sid": sid},
                           headers={"Origin": ORIGIN})
        bad = await c.post("/api/ops/episodes/ego_test_0001/assign",
                           json={"wearer_id": 999999}, cookies={"sid": sid},
                           headers={"Origin": ORIGIN})
    assert res.status_code == 200
    assert next(e for e in res.json()["episodes"]
                if e["recording"] == "ego_test_0001")["wearer_id"] == wid
    assert bad.status_code == 404


# --- delete -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soft_delete_keeps_the_row_and_restores(app, db_session):
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    async with _client(app) as c:
        d = await c.post("/api/ops/episodes/ego_test_0001/delete",
                         json={"kind": "soft", "reason": "duplicate"},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        row = next(e for e in d.json()["episodes"] if e["recording"] == "ego_test_0001")
        assert row["delete_kind"] == "soft" and row["deleted_at"]
        assert row["deleted_by"] == "ops@ops.test" and row["delete_reason"] == "duplicate"

        r = await c.post("/api/ops/episodes/ego_test_0001/restore",
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
    back = next(e for e in r.json()["episodes"] if e["recording"] == "ego_test_0001")
    assert back["deleted_at"] is None and back["delete_kind"] is None


@pytest.mark.asyncio
async def test_hard_delete_cannot_be_restored(app, db_session):
    """Clearing the flag would put a row back whose objects are gone from a
    bucket that refuses re-upload -- a ledger entry pointing at nothing."""
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    async with _client(app) as c:
        d = await c.post("/api/ops/episodes/ego_test_0001/delete",
                         json={"kind": "hard", "reason": "worthless"},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert d.json()["s3_purge"] == "not_implemented"
        r = await c.post("/api/ops/episodes/ego_test_0001/restore",
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_delete_kind_must_be_soft_or_hard(app, db_session):
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    async with _client(app) as c:
        res = await c.post("/api/ops/episodes/ego_test_0001/delete",
                           json={"kind": "purge"}, cookies={"sid": sid},
                           headers={"Origin": ORIGIN})
    assert res.status_code == 422


# --- import -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_merges_and_never_regenerates(app, db_session):
    """A re-import must not wipe decisions. The laptop ledger enforced this on
    itself and it is the one property this data cannot survive losing."""
    sid = await _sid(db_session, "ops")
    payload = {"episodes": {"ego_a": {"session": "s1", "device_id": "D1",
                                      "duration_s": 60, "bytes": 10},
                            "ego_b": {"session": "s1", "device_id": "D2"}},
               "payments": {"ego_a": {"paid": True, "amount": 0}}}
    async with _client(app) as c:
        first = await c.post("/api/ops/import", json=payload,
                             cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert first.json()["added"] == 2
        # A tick with amount 0 is carried VERBATIM -- inventing a rate here
        # would fabricate a payment record.
        a = next(e for e in first.json()["episodes"] if e["recording"] == "ego_a")
        assert a["paid"] is True and a["amount_krw"] == 0

        await c.post("/api/ops/episodes/ego_b/approve", json={"value": True},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
        again = await c.post("/api/ops/import", json=payload,
                             cookies={"sid": sid}, headers={"Origin": ORIGIN})
    assert again.json()["added"] == 0
    b = next(e for e in again.json()["episodes"] if e["recording"] == "ego_b")
    assert b["approved"] is True


# --- task labels --------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_names_are_case_insensitively_unique(app, db_session):
    """"Garment Folding" and "garment folding" are one activity and two labels.
    Splitting them is the exact failure the table exists to prevent, so the
    clash is refused at creation rather than cleaned up later."""
    sid = await _sid(db_session, "ops")
    async with _client(app) as c:
        first = await c.post("/api/ops/tasks",
                             json={"name": "Garment Folding", "category": "packing_and_folding"},
                             cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert first.status_code == 200
        dupe = await c.post("/api/ops/tasks",
                            json={"name": "garment folding", "category": "other"},
                            cookies={"sid": sid}, headers={"Origin": ORIGIN})
    assert dupe.status_code == 409
    assert "Garment Folding" in dupe.json()["detail"]


@pytest.mark.asyncio
async def test_label_an_episode_and_clear_it(app, db_session):
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    async with _client(app) as c:
        made = await c.post("/api/ops/tasks", json={"name": "Floor Sweeping",
                                                    "category": "cleaning_and_waste"},
                            cookies={"sid": sid}, headers={"Origin": ORIGIN})
        tid = made.json()["tasks"][0]["id"]
        on = await c.post("/api/ops/episodes/ego_test_0001/task", json={"task_id": tid},
                          cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert next(e for e in on.json()["episodes"]
                    if e["recording"] == "ego_test_0001")["task_id"] == tid
        assert on.json()["totals"]["unlabelled"] == 0

        bad = await c.post("/api/ops/episodes/ego_test_0001/task", json={"task_id": 999999},
                           cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert bad.status_code == 404

        off = await c.post("/api/ops/episodes/ego_test_0001/task", json={"task_id": None},
                           cookies={"sid": sid}, headers={"Origin": ORIGIN})
    assert next(e for e in off.json()["episodes"]
                if e["recording"] == "ego_test_0001")["task_id"] is None


@pytest.mark.asyncio
async def test_retiring_a_task_does_not_delete_its_episodes(app, db_session):
    """SET NULL, not CASCADE. Losing a label is a relabelling chore; losing the
    episodes that carried it is a loss."""
    import sqlalchemy as sa
    sid = await _sid(db_session, "ops")
    await _episode(db_session)
    async with _client(app) as c:
        made = await c.post("/api/ops/tasks", json={"name": "Tray Kitting",
                                                    "category": "pick_place_kitting"},
                            cookies={"sid": sid}, headers={"Origin": ORIGIN})
        tid = made.json()["tasks"][0]["id"]
        await c.post("/api/ops/episodes/ego_test_0001/task", json={"task_id": tid},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
    await db_session.execute(sa.text("DELETE FROM ops_tasks WHERE id = :i"), {"i": tid})
    await db_session.commit()
    async with _client(app) as c:
        after = await c.get("/api/ops/state", cookies={"sid": sid})
    row = next(e for e in after.json()["episodes"] if e["recording"] == "ego_test_0001")
    assert row["task_id"] is None          # label gone
    assert row["recording"] == "ego_test_0001"   # episode still here


# --- the rate and settling a batch --------------------------------------------

@pytest.mark.asyncio
async def test_rate_persists_and_prices_a_payment(app, db_session):
    """A payment with no explicit amount is stamped with the board's rate.

    The old default was 0, so a client that forgot the field recorded a payment
    of zero -- indistinguishable in the ledger from a shift that was not paid.
    """
    sid = await _sid(db_session, "ops")
    await _episode(db_session, "ego_rate_1", duration_s=600, approved=True)
    async with _client(app) as c:
        r = await c.post("/api/ops/rate", json={"rate_krw": 11000},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        assert r.json()["rate_krw"] == 11000

        r = await c.post("/api/ops/episodes/ego_rate_1/pay", json={"value": True},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        row = next(e for e in r.json()["episodes"] if e["recording"] == "ego_rate_1")
        assert row["paid"] is True and row["amount_krw"] == 11000

        # And the rate survives a reload rather than living in one browser.
        assert (await c.get("/api/ops/state",
                            cookies={"sid": sid})).json()["rate_krw"] == 11000


@pytest.mark.asyncio
async def test_bulk_pay_settles_the_batch_at_the_rate(app, db_session):
    sid = await _sid(db_session, "ops")
    for rec in ("ego_b1", "ego_b2"):
        await _episode(db_session, rec, duration_s=300, approved=True)
    async with _client(app) as c:
        await c.post("/api/ops/rate", json={"rate_krw": 9000},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
        r = await c.post("/api/ops/pay-bulk",
                         json={"recordings": ["ego_b1", "ego_b2", "ego_b1"]},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        assert r.json()["changed"] == 2                  # de-duplicated
        rows = {e["recording"]: e for e in r.json()["episodes"]}
        assert all(rows[k]["paid"] and rows[k]["amount_krw"] == 9000
                   for k in ("ego_b1", "ego_b2"))


@pytest.mark.asyncio
async def test_bulk_pay_is_all_or_nothing(app, db_session):
    """One unapproved row fails the batch. A partial run would leave the
    operator believing somebody was paid who was not."""
    sid = await _sid(db_session, "ops")
    await _episode(db_session, "ego_ok", duration_s=300, approved=True)
    await _episode(db_session, "ego_notyet", duration_s=300, approved=False)
    async with _client(app) as c:
        r = await c.post("/api/ops/pay-bulk",
                         json={"recordings": ["ego_ok", "ego_notyet"]},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 409
        assert "not approved" in r.json()["detail"]

        r = await c.post("/api/ops/pay-bulk", json={"recordings": ["ego_ok", "ego_ghost"]},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 404

        # Neither attempt paid the approved one.
        rows = {e["recording"]: e
                for e in (await c.get("/api/ops/state",
                                      cookies={"sid": sid})).json()["episodes"]}
        assert rows["ego_ok"]["paid"] is False


# --- the Users tab -------------------------------------------------------------

@pytest.mark.asyncio
async def test_wearer_details_round_trip_and_retire(app, db_session):
    """Contact and note are storable and editable, and retiring keeps the row."""
    sid = await _sid(db_session, "ops")
    async with _client(app) as c:
        r = await c.post("/api/ops/wearers",
                         json={"name": "김민준", "contact": "010-0000-0000",
                               "note": "파이가게 성수"},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        w = next(x for x in r.json()["wearers"] if x["name"] == "김민준")
        assert w["contact"] == "010-0000-0000" and w["note"] == "파이가게 성수"
        assert w["is_active"] is True

        r = await c.post(f"/api/ops/wearers/{w['id']}",
                         json={"contact": "010-1111-2222", "is_active": False},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        w2 = next(x for x in r.json()["wearers"] if x["id"] == w["id"])
        # The untouched field survives a one-field save.
        assert w2["contact"] == "010-1111-2222"
        assert w2["note"] == "파이가게 성수"
        assert w2["is_active"] is False


@pytest.mark.asyncio
async def test_retiring_a_wearer_keeps_their_episodes_attributed(app, db_session):
    """The reason there is no DELETE: a settled payment must keep its name."""
    sid = await _sid(db_session, "ops")
    w = Wearer(name="박지훈")
    db_session.add(w)
    await db_session.commit()
    await _episode(db_session, "ego_keepme", duration_s=600, approved=True,
                   paid=True, amount_krw=11000, wearer_id=w.id)
    async with _client(app) as c:
        r = await c.post(f"/api/ops/wearers/{w.id}", json={"is_active": False},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        row = next(e for e in r.json()["episodes"] if e["recording"] == "ego_keepme")
        assert row["wearer_id"] == w.id and row["paid"] is True


@pytest.mark.asyncio
async def test_updating_an_unknown_person_is_404(app, db_session):
    sid = await _sid(db_session, "ops")
    async with _client(app) as c:
        r = await c.post("/api/ops/wearers/999999", json={"name": "ghost"},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 404


# --- regressions found in the pre-deploy audit ---------------------------------

@pytest.mark.asyncio
async def test_a_rate_change_cannot_reprice_an_already_paid_episode(app, db_session):
    """Settling is a one-way stamp. Re-ticking after the rate moved must not
    rewrite what the ledger says somebody was paid."""
    sid = await _sid(db_session, "ops")
    await _episode(db_session, "ego_stamp", duration_s=600, approved=True)
    async with _client(app) as c:
        await c.post("/api/ops/rate", json={"rate_krw": 10320},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
        await c.post("/api/ops/episodes/ego_stamp/pay", json={"value": True},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
        await c.post("/api/ops/rate", json={"rate_krw": 11000},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
        # Tick it again at the new rate: the recorded amount must not move.
        r = await c.post("/api/ops/episodes/ego_stamp/pay", json={"value": True},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        row = next(e for e in r.json()["episodes"] if e["recording"] == "ego_stamp")
        assert row["amount_krw"] == 10320


@pytest.mark.asyncio
async def test_bulk_pay_refuses_deleted_episodes(app, db_session):
    sid = await _sid(db_session, "ops")
    await _episode(db_session, "ego_live", duration_s=300, approved=True)
    await _episode(db_session, "ego_dead", duration_s=300, approved=True)
    async with _client(app) as c:
        await c.post("/api/ops/episodes/ego_dead/delete",
                     json={"kind": "soft", "reason": "test clip"},
                     cookies={"sid": sid}, headers={"Origin": ORIGIN})
        r = await c.post("/api/ops/pay-bulk",
                         json={"recordings": ["ego_live", "ego_dead"]},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 409 and "deleted" in r.json()["detail"]
        rows = {e["recording"]: e
                for e in (await c.get("/api/ops/state", cookies={"sid": sid})).json()["episodes"]}
        assert rows["ego_live"]["paid"] is False


@pytest.mark.asyncio
async def test_a_negative_amount_is_rejected_not_clamped(app, db_session):
    sid = await _sid(db_session, "ops")
    await _episode(db_session, "ego_neg", duration_s=300, approved=True)
    async with _client(app) as c:
        r = await c.post("/api/ops/episodes/ego_neg/pay",
                         json={"value": True, "amount_krw": -5000},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_paying_with_no_rate_set_is_refused_not_booked_as_zero(app, db_session):
    """Migration 0011 seeds the rate at 0, so this is the state of every fresh
    deploy. A ₩0 settlement is indistinguishable from an unpaid one."""
    sid = await _sid(db_session, "ops")
    await _episode(db_session, "ego_norate", duration_s=600, approved=True)
    async with _client(app) as c:
        r = await c.post("/api/ops/episodes/ego_norate/pay", json={"value": True},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 409 and "rate" in r.json()["detail"].lower()

        r = await c.post("/api/ops/pay-bulk", json={"recordings": ["ego_norate"]},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 409

        # Deliberate zero is still allowed, but it has to be said out loud.
        r = await c.post("/api/ops/episodes/ego_norate/pay",
                         json={"value": True, "amount_krw": 0},
                         cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        row = next(e for e in r.json()["episodes"] if e["recording"] == "ego_norate")
        assert row["paid"] is True and row["amount_krw"] == 0


# --- scanning the bucket -------------------------------------------------------

def _obj(key, size=1000, when="2026-09-09T11:23:01+00:00"):
    from datetime import datetime
    return {"Key": key, "Size": size, "LastModified": datetime.fromisoformat(when)}


class _FakeS3:
    """Just enough S3 to drive a scan: a pager and a metadata GET."""

    def __init__(self, objects, meta=None, meta_raises=False):
        self._objects, self._meta, self._raises = objects, meta or {}, meta_raises

    def get_paginator(self, _name):
        objects = self._objects

        class _P:
            def paginate(self, **_kw):
                yield {"Contents": objects}
        return _P()

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 - boto3 casing
        if self._raises:
            raise RuntimeError("boom")
        import io
        return {"Body": io.BytesIO(json.dumps(self._meta.get(Key, {})).encode())}


@pytest.fixture
def fake_bucket(monkeypatch):
    """Point the scanner at an in-memory bucket."""
    def _install(objects, meta=None, meta_raises=False):
        import app.core.ops_scan as scan
        monkeypatch.setattr(scan, "_client", lambda cfg: _FakeS3(objects, meta, meta_raises))
        monkeypatch.setattr(scan, "get_settings", lambda: scan.OpsS3Settings(
            bucket="b", region="r", access_key_id="k", secret_access_key="s",
            presign_ttl=900) if hasattr(scan, "OpsS3Settings") else _Cfg())
    return _install


class _Cfg:
    bucket = "6thsense-raw"
    region = "us-west-2"


@pytest.mark.asyncio
async def test_scan_inserts_new_takes_with_upload_time(app, db_session, monkeypatch):
    import app.core.ops_scan as scan
    rec = "ego_20260909_103948_16A4A5"
    pre = f"sessions/2026-09-03_korea-datafarm/16A4A5/{rec}"
    monkeypatch.setattr(scan, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(scan, "_client", lambda cfg: _FakeS3(
        [_obj(f"{pre}/metadata.json", 900, "2026-09-09T11:20:00+00:00"),
         _obj(f"{pre}/video_live_0000.mp4", 45_000_000, "2026-09-09T11:23:01+00:00")],
        meta={f"{pre}/metadata.json": {
            "device_id": "16A4A5", "start_time": "2026-09-09T10:39:48+00:00",
            "duration_s": 1800, "frame_count": 54000, "dropped_frames": 0,
            "complete": True, "clock_source": "ntp", "fw": "1.7.0"}}))
    sid = await _sid(db_session, "ops")
    async with _client(app) as c:
        r = await c.post("/api/ops/scan", cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scan"]["added"] == 1 and body["scan"]["seen"] == 1
        e = next(x for x in body["episodes"] if x["recording"] == rec)
        # The LAST object decides when the take landed, not the first.
        assert e["uploaded_at"].startswith("2026-09-09T11:23:01")
        assert e["device_id"] == "16A4A5" and e["minutes"] == 30.0
        assert e["size_bytes"] == 45_000_900 and e["files"] == 2
        assert body["last_scan"]


@pytest.mark.asyncio
async def test_rescanning_never_disturbs_a_payment(app, db_session, monkeypatch):
    """The whole reason a re-scan is safe to press."""
    import app.core.ops_scan as scan
    rec = "ego_20260909_103948_16A4A5"
    pre = f"sessions/2026-09-03_korea-datafarm/16A4A5/{rec}"
    w = Wearer(name="김민준")
    db_session.add(w)
    await db_session.commit()
    db_session.add(Episode(recording=rec, session="2026-09-03_korea-datafarm",
                           device_id="16A4A5", duration_s=1800, approved=True,
                           paid=True, amount_krw=11000, wearer_id=w.id))
    await db_session.commit()
    monkeypatch.setattr(scan, "get_settings", lambda: _Cfg())
    # The bucket now reports a DIFFERENT recording camera and more bytes.
    monkeypatch.setattr(scan, "_client", lambda cfg: _FakeS3(
        [_obj(f"{pre}/metadata.json", 900),
         _obj(f"{pre}/video_live_0000.mp4", 90_000_000)],
        meta={f"{pre}/metadata.json": {"device_id": "DIFFERENT", "duration_s": 9999}}))
    sid = await _sid(db_session, "ops")
    async with _client(app) as c:
        r = await c.post("/api/ops/scan", cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        assert r.json()["scan"]["added"] == 0
        e = next(x for x in r.json()["episodes"] if x["recording"] == rec)
        assert e["paid"] is True and e["amount_krw"] == 11000
        assert e["approved"] is True and e["wearer_id"] == w.id
        # Growable facts refresh; identity does not move under a settled row.
        assert e["size_bytes"] == 90_000_900
        assert e["device_id"] == "16A4A5"


@pytest.mark.asyncio
async def test_scan_leaves_episodes_the_bucket_did_not_report(app, db_session, monkeypatch):
    """A take missing from a listing is a bad prefix or a flaky call, never a
    deletion -- the uploader keys cannot delete."""
    import app.core.ops_scan as scan
    await _episode(db_session, "ego_20260101_000000_AAAA", duration_s=60, approved=True)
    monkeypatch.setattr(scan, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(scan, "_client", lambda cfg: _FakeS3([]))
    sid = await _sid(db_session, "ops")
    async with _client(app) as c:
        r = await c.post("/api/ops/scan", cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200 and r.json()["scan"]["seen"] == 0
        assert len(r.json()["episodes"]) == 1


@pytest.mark.asyncio
async def test_scan_skips_probes_and_bookkeeping_and_survives_bad_metadata(
        app, db_session, monkeypatch):
    import app.core.ops_scan as scan
    rec = "ego_20260908_235819_1696C8"
    pre = f"sessions/2026-09-03_korea-datafarm/1696C8/{rec}"
    monkeypatch.setattr(scan, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(scan, "_client", lambda cfg: _FakeS3(
        [_obj(f"{pre}/metadata.json"),
         _obj("sessions/2026-09-03_korea-datafarm/.ego-s3-test/probe.txt"),
         _obj("sessions/2026-09-03_korea-datafarm/_machine/notes.json"),
         _obj("sessions/2026-09-03_korea-datafarm/loose-file.txt")],
        meta_raises=True))
    sid = await _sid(db_session, "ops")
    async with _client(app) as c:
        r = await c.post("/api/ops/scan", cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        # Only the real take; the probe, the bookkeeping dir and the loose file
        # are not episodes.
        assert r.json()["scan"]["seen"] == 1
        assert [e["recording"] for e in r.json()["episodes"]] == [rec]


@pytest.mark.asyncio
async def test_scan_needs_the_ops_role(app, db_session):
    sid = await _sid(db_session, "customer")
    async with _client(app) as c:
        r = await c.post("/api/ops/scan", cookies={"sid": sid}, headers={"Origin": ORIGIN})
        assert r.status_code == 403
