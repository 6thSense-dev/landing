"""/api/ops/*: role gate, CSRF prefix, the approve-before-pay guard, and the
two kinds of delete."""

from __future__ import annotations

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
