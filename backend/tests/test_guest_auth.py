"""The shared read-only demo account: login, session cap, throttling, seeding.

`guest` / <password> is one credential handed to every prospect. The real value
lives in the password manager and is passed to `seed-guest` through the
`CATALOG_GUEST_PASSWORD` environment variable; it is never written down here. The tests
here pin the four things that make that safe: it is the only bare username
that resolves, its session is absolutely capped rather than sliding, its login
throttle is separate from (and cannot loosen) the one protecting real
accounts, and it can be revoked in one command.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.auth import RESERVED_USERNAMES
from app.cli import GUEST_MIN_PASSWORD_LEN, MIN_PASSWORD_LEN, seed_guest
from app.core.auth_deps import GUEST_SESSION_TTL
from app.core.passwords import hash_password, verify_password
from app.core.sessions import hash_session_token, mint_session_token
from app.main import create_app
from app.models import Base, Session as SessionRow, User
from app.models.user import (
    GUEST_DOWNGRADE_FOLD_ROLE,
    GUEST_EMAIL,
    GUEST_ROLE,
    ROLES,
)
from tests.test_migrations import _alembic


GUEST_PASSWORD = "pytest-guest-pw"  # fixture only — never a real credential
#: The shortest value `seed-guest` accepts, and the one `create-user` must still
#: refuse. Obviously fake by construction: a working credential must never be a
#: literal in this repository, which is public.
GUEST_SHORT_PASSWORD = "x" * GUEST_MIN_PASSWORD_LEN
HDRS = {"Origin": "https://app.example"}


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    from app.core.limiter import limiter
    limiter.reset()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest_asyncio.fixture
async def guest(db_session):
    user = User(
        email=GUEST_EMAIL,
        name="Guest (shared demo)",
        role=GUEST_ROLE,
        password_hash=hash_password(GUEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def founder(db_session):
    user = User(
        email="alex@example.com",
        name="Alex",
        role="founder",
        password_hash=hash_password("twelve-chars!!"),
    )
    db_session.add(user)
    await db_session.commit()
    return user


# --------------------------------------------------------------------------- #
# The role exists                                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_guest_role_is_insertable(db_session):
    db_session.add(User(email="g@x.com", name="G", role=GUEST_ROLE, password_hash="h"))
    await db_session.flush()
    assert (await db_session.execute(select(User))).scalar_one().role == "guest"


@pytest.mark.asyncio
async def test_every_declared_role_is_insertable(db_session):
    """ROLES, the CheckConstraint and migration 0007 must not drift apart."""
    for i, role in enumerate(ROLES):
        db_session.add(User(email=f"r{i}@x.com", name=role, role=role, password_hash="h"))
    await db_session.flush()
    rows = (await db_session.execute(select(User.role))).scalars().all()
    assert set(rows) == set(ROLES)


@pytest.mark.asyncio
async def test_role_check_still_rejects_unknown_roles(db_session):
    db_session.add(User(email="bad@x.com", name="X", role="superuser", password_hash="h"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# --------------------------------------------------------------------------- #
# Login                                                                        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_guest_username_logs_in_and_me_reports_the_role(client, guest):
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user"]["role"] == "guest"
    assert body["user"]["email"] == GUEST_EMAIL

    sid = res.cookies.get("sid")
    assert sid
    me = await client.get("/api/auth/me", cookies={"sid": sid})
    assert me.status_code == 200
    assert me.json()["role"] == "guest"


@pytest.mark.asyncio
async def test_guest_username_is_case_and_space_insensitive(client, guest):
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "  GUEST  ", "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_guest_full_email_also_logs_in(client, guest):
    res = await client.post(
        "/api/auth/login",
        json={"identifier": GUEST_EMAIL, "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_guest_password_does_not_work_for_another_account(client, guest, founder):
    for identifier in ("alex@example.com", "alex", "admin", "nobody@example.com"):
        res = await client.post(
            "/api/auth/login",
            json={"identifier": identifier, "password": GUEST_PASSWORD},
            headers=HDRS,
        )
        assert res.status_code == 401, f"{identifier} -> {res.status_code}"


@pytest.mark.asyncio
async def test_wrong_guest_password_is_401(client, guest):
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "password": "guest667"},
        headers=HDRS,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_guest_username_without_an_account_is_401_not_500(client):
    """Before `seed-guest` has ever run, `guest` resolves to an address with no
    row behind it. That is an ordinary failed login, not an error."""
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert res.status_code == 401


# --------------------------------------------------------------------------- #
# Session lifetime                                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_guest_login_caps_the_session_at_eight_hours(client, guest, db_session):
    before = datetime.now(timezone.utc)
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert res.status_code == 200
    row = (await db_session.execute(select(SessionRow))).scalar_one()
    assert row.expires_at - before <= GUEST_SESSION_TTL + timedelta(seconds=30)
    assert row.expires_at - before > GUEST_SESSION_TTL - timedelta(minutes=1)
    # The cookie agrees with the row.
    assert f"Max-Age={int(GUEST_SESSION_TTL.total_seconds())}" in res.headers["set-cookie"]


@pytest.mark.asyncio
async def test_real_user_login_still_gets_fourteen_days(client, founder, db_session):
    res = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 200
    row = (await db_session.execute(select(SessionRow))).scalar_one()
    assert row.expires_at - datetime.now(timezone.utc) > timedelta(days=13)


async def _seed_guest_session(db_session, *, created_ago=timedelta(0), expires_in=timedelta(hours=8)):
    user = (await db_session.execute(select(User).where(User.email == GUEST_EMAIL))).scalar_one()
    raw = mint_session_token()
    now = datetime.now(timezone.utc)
    db_session.add(SessionRow(
        user_id=user.id,
        token_hash=hash_session_token(raw),
        expires_at=now + expires_in,
        created_at=now - created_ago,
    ))
    await db_session.commit()
    return raw


@pytest.mark.asyncio
async def test_guest_session_does_not_slide(client, guest, db_session):
    """A sliding window on a shared credential never closes, so guest is the
    one role whose expiry is not extended by use."""
    raw = await _seed_guest_session(db_session, expires_in=timedelta(hours=1))
    original = (await db_session.execute(select(SessionRow))).scalar_one().expires_at

    res = await client.get("/api/auth/me", cookies={"sid": raw})
    assert res.status_code == 200

    db_session.expire_all()
    row = (await db_session.execute(select(SessionRow))).scalar_one()
    assert row.expires_at == original
    assert row.last_used_at is not None  # still tracked, just not extended


@pytest.mark.asyncio
async def test_guest_session_past_the_absolute_cap_is_401(client, guest, db_session):
    """Even with a generous expires_at, a guest session older than the cap is
    dead — the cap is measured from created_at, not from whatever wrote
    expires_at."""
    raw = await _seed_guest_session(
        db_session,
        created_ago=GUEST_SESSION_TTL + timedelta(minutes=1),
        expires_in=timedelta(days=14),
    )
    res = await client.get("/api/auth/me", cookies={"sid": raw})
    assert res.status_code == 401
    db_session.expire_all()
    assert (await db_session.execute(select(SessionRow))).scalars().all() == []


@pytest.mark.asyncio
async def test_guest_session_inside_the_cap_still_works(client, guest, db_session):
    raw = await _seed_guest_session(
        db_session,
        created_ago=GUEST_SESSION_TTL - timedelta(minutes=5),
        expires_in=timedelta(minutes=5),
    )
    res = await client.get("/api/auth/me", cookies={"sid": raw})
    assert res.status_code == 200


# --------------------------------------------------------------------------- #
# Rate limiting                                                                #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_guest_gets_its_own_looser_bucket(client, guest, founder, monkeypatch):
    """A NATed office sharing the demo credential must not be locked out by
    the strict per-IP limit that protects real accounts."""
    monkeypatch.setenv("SENSEPROBE_LOGIN_RATE_LIMIT", "1/minute")
    monkeypatch.setenv("SENSEPROBE_GUEST_LOGIN_RATE_LIMIT", "10/minute")
    from app.core.limiter import limiter
    limiter.reset()

    # Burn the real-account bucket for this IP.
    first = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "wrong-password"},
        headers=HDRS,
    )
    second = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "wrong-password"},
        headers=HDRS,
    )
    assert first.status_code == 401
    assert second.status_code == 429

    # The guest bucket is untouched by that, and is looser.
    for i in range(4):
        res = await client.post(
            "/api/auth/login",
            json={"identifier": "guest", "password": GUEST_PASSWORD},
            headers=HDRS,
        )
        assert res.status_code == 200, f"guest attempt {i}: {res.status_code}"


@pytest.mark.asyncio
async def test_guest_bucket_is_still_bounded(client, guest, monkeypatch):
    """Looser is not unlimited — Argon2 is 64 MiB a call and must not become a
    free CPU amplifier just because the identifier says `guest`."""
    monkeypatch.setenv("SENSEPROBE_LOGIN_RATE_LIMIT", "100/minute")
    monkeypatch.setenv("SENSEPROBE_GUEST_LOGIN_RATE_LIMIT", "2/minute")
    from app.core.limiter import limiter
    limiter.reset()

    codes = []
    for _ in range(3):
        res = await client.post(
            "/api/auth/login",
            json={"identifier": "guest", "password": "wrong"},
            headers=HDRS,
        )
        codes.append(res.status_code)
    assert codes == [401, 401, 429]


@pytest.mark.asyncio
async def test_guest_traffic_does_not_burn_the_real_account_bucket(client, guest, founder, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_LOGIN_RATE_LIMIT", "2/minute")
    monkeypatch.setenv("SENSEPROBE_GUEST_LOGIN_RATE_LIMIT", "20/minute")
    from app.core.limiter import limiter
    limiter.reset()

    for _ in range(5):
        res = await client.post(
            "/api/auth/login",
            json={"identifier": "guest", "password": GUEST_PASSWORD},
            headers=HDRS,
        )
        assert res.status_code == 200

    res = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 200, "guest logins must not consume the real bucket"


def test_guest_login_rate_limit_default_and_override(monkeypatch):
    from app.core import limiter as limiter_module

    monkeypatch.delenv(limiter_module.GUEST_LOGIN_RATE_LIMIT_ENV, raising=False)
    assert limiter_module.guest_login_rate_limit() == "60/minute"
    monkeypatch.setenv(limiter_module.GUEST_LOGIN_RATE_LIMIT_ENV, "5/hour")
    assert limiter_module.guest_login_rate_limit() == "5/hour"


def test_limit_provider_picks_the_bucket_from_the_key(monkeypatch):
    from app.core import limiter as limiter_module

    monkeypatch.setenv("SENSEPROBE_LOGIN_RATE_LIMIT", "10/minute")
    monkeypatch.setenv(limiter_module.GUEST_LOGIN_RATE_LIMIT_ENV, "77/minute")
    assert limiter_module.current_login_rate_limit("1.2.3.4") == "10/minute"
    assert limiter_module.current_login_rate_limit(
        f"{limiter_module.GUEST_LOGIN_KEY_PREFIX}1.2.3.4"
    ) == "77/minute"


# --------------------------------------------------------------------------- #
# seed-guest                                                                   #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def fresh_db(postgres_container):
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    import app.core.db as _db
    _db._engine = None
    _db._sessionmaker = None
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def test_the_short_guest_password_is_a_scoped_exception():
    """The global rule is untouched; only seed-guest relaxes it, and only
    down to GUEST_MIN_PASSWORD_LEN."""
    assert MIN_PASSWORD_LEN == 12
    assert GUEST_MIN_PASSWORD_LEN < MIN_PASSWORD_LEN
    assert len(GUEST_PASSWORD) >= GUEST_MIN_PASSWORD_LEN


@pytest.mark.asyncio
async def test_seed_guest_accepts_the_shortest_allowed_password(fresh_db):
    """The carve-out is real: a password below MIN_PASSWORD_LEN but at
    GUEST_MIN_PASSWORD_LEN is accepted. Exercised with an obviously-fake value —
    no real credential is ever written down in this repo."""
    assert len(GUEST_SHORT_PASSWORD) < MIN_PASSWORD_LEN
    await seed_guest(password=GUEST_SHORT_PASSWORD)
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.email == GUEST_EMAIL))).scalar_one()
    assert verify_password(GUEST_SHORT_PASSWORD, row.password_hash)


@pytest.mark.asyncio
async def test_seed_guest_creates_the_account(fresh_db):
    msg = await seed_guest(password=GUEST_PASSWORD)
    assert "created" in msg
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.email == GUEST_EMAIL))).scalar_one()
    assert row.role == GUEST_ROLE
    assert row.is_active is True
    assert verify_password(GUEST_PASSWORD, row.password_hash)


@pytest.mark.asyncio
async def test_seed_guest_refuses_a_non_guest_email(fresh_db):
    with pytest.raises(ValueError, match="refusing to run against"):
        await seed_guest(email="alex@example.com", password="a-very-long-password")


@pytest.mark.asyncio
async def test_seed_guest_refuses_a_too_short_password(fresh_db):
    with pytest.raises(ValueError, match=str(GUEST_MIN_PASSWORD_LEN)):
        await seed_guest(password="g6")


@pytest.mark.asyncio
async def test_seed_guest_rotation_kills_live_sessions(fresh_db):
    await seed_guest(password=GUEST_PASSWORD)
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.email == GUEST_EMAIL))).scalar_one()
        s.add(SessionRow(
            user_id=user.id,
            token_hash=hash_session_token(mint_session_token()),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
        ))
        await s.commit()

    msg = await seed_guest(password="rotated-demo-pw")
    assert "1 live session(s) invalidated" in msg
    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.email == GUEST_EMAIL))).scalar_one()
        assert verify_password("rotated-demo-pw", row.password_hash)
        assert (await s.execute(select(SessionRow))).scalars().all() == []


@pytest.mark.asyncio
async def test_seed_guest_refuses_to_overwrite_a_non_guest_row(fresh_db):
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        s.add(User(email=GUEST_EMAIL, name="Real", role="founder", password_hash="h"))
        await s.commit()
    with pytest.raises(ValueError, match="role='founder'"):
        await seed_guest(password=GUEST_PASSWORD)


@pytest.mark.asyncio
async def test_seed_guest_refuses_an_active_row_in_the_fold_role(fresh_db):
    """A live customer at the demo address is still off limits.

    The rollback escape hatch keys on role AND is_active together; only the pair
    is 0007's artefact. This is the half that must keep refusing.
    """
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        s.add(User(
            email=GUEST_EMAIL,
            name="Real",
            role=GUEST_DOWNGRADE_FOLD_ROLE,
            password_hash="h",
            is_active=True,
        ))
        await s.commit()
    with pytest.raises(ValueError, match=f"role='{GUEST_DOWNGRADE_FOLD_ROLE}'"):
        await seed_guest(password=GUEST_PASSWORD)


@pytest.mark.asyncio
async def test_seed_guest_restores_a_0007_downgrade_artefact(fresh_db):
    """`alembic downgrade -1; alembic upgrade head; seed-guest` has to work.

    0007's downgrade deliberately keeps the row rather than deleting it, folding
    it to GUEST_DOWNGRADE_FOLD_ROLE and deactivating it. The migration's own
    docstring promises re-running seed-guest restores the demo; before this it
    did not -- it hit the non-guest-row guard and stranded the account.
    """
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        s.add(User(
            email=GUEST_EMAIL,
            name="Guest",
            role=GUEST_DOWNGRADE_FOLD_ROLE,   # exactly what downgrade() leaves
            password_hash="h",
            is_active=False,
        ))
        await s.commit()

    msg = await seed_guest(password=GUEST_PASSWORD)
    assert "restored from a 0007 downgrade" in msg

    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.email == GUEST_EMAIL))).scalar_one()
        assert user.role == "guest"
        assert user.is_active is True
        assert verify_password(GUEST_PASSWORD, user.password_hash)


@pytest.mark.asyncio
async def test_seed_guest_deactivate_needs_no_password(fresh_db):
    await seed_guest(password=GUEST_PASSWORD)
    msg = await seed_guest(deactivate=True)
    assert "DISABLED" in msg
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.email == GUEST_EMAIL))).scalar_one()
    assert row.is_active is False


@pytest.mark.asyncio
async def test_deactivate_blocks_login_and_kills_live_sessions(client, guest, db_session):
    live = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert live.status_code == 200
    sid = live.cookies.get("sid")

    msg = await seed_guest(deactivate=True)
    assert "1 live session(s) killed" in msg

    blocked = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert blocked.status_code == 401
    assert (await client.get("/api/auth/me", cookies={"sid": sid})).status_code == 401


@pytest.mark.asyncio
async def test_reactivating_after_deactivate(client, guest, db_session):
    await seed_guest(deactivate=True)
    await seed_guest(password=GUEST_PASSWORD)
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "password": GUEST_PASSWORD},
        headers=HDRS,
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_create_user_still_enforces_twelve_chars_for_the_guest_role(fresh_db):
    from app.cli import create_user

    with pytest.raises(ValueError, match="12"):
        await create_user(
            email="p@x.com", name="P", role="guest", password=GUEST_SHORT_PASSWORD
        )


# --------------------------------------------------------------------------- #
# Migration 0007                                                               #
# --------------------------------------------------------------------------- #

async def _role_check_def(engine) -> str:
    async with engine.begin() as conn:
        rows = (
            await conn.exec_driver_sql(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'users_role_check'"
            )
        ).fetchall()
    return rows[0][0] if rows else ""


@pytest.mark.asyncio
async def test_migration_0007_adds_then_removes_guest_from_the_check(postgres_container):
    assert _alembic("upgrade", "head").returncode == 0
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        assert "'guest'" in await _role_check_def(engine)

        down = _alembic("downgrade", "0006")
        assert down.returncode == 0, down.stderr
        assert "'guest'" not in await _role_check_def(engine)
    finally:
        await engine.dispose()
    assert _alembic("downgrade", "base").returncode == 0


@pytest.mark.asyncio
async def test_migration_0007_downgrade_deactivates_rather_than_promoting(postgres_container):
    """Folding a guest row straight to 'customer' would silently promote a
    published credential. The downgrade must revoke it first."""
    assert _alembic("upgrade", "head").returncode == 0
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO users (email, name, role, password_hash) "
                f"VALUES ('{GUEST_EMAIL}', 'Guest', 'guest', 'h')"
            )
            await conn.exec_driver_sql(
                "INSERT INTO sessions (user_id, token_hash, expires_at) "
                "SELECT id, 'deadbeef', now() + interval '8 hours' FROM users "
                "WHERE role = 'guest'"
            )

        down = _alembic("downgrade", "0006")
        assert down.returncode == 0, down.stderr

        async with engine.begin() as conn:
            row = (
                await conn.exec_driver_sql(
                    "SELECT role, is_active FROM users WHERE email = "
                    f"'{GUEST_EMAIL}'"
                )
            ).fetchone()
            sessions = (
                await conn.exec_driver_sql("SELECT count(*) FROM sessions")
            ).scalar_one()
        assert row is not None, "the row must survive: a downgrade must not delete data"
        assert row[0] == "customer"
        assert row[1] is False, "a demoted guest must not be able to authenticate"
        assert sessions == 0, "live guest cookies must not survive the role change"
    finally:
        await engine.dispose()
    assert _alembic("downgrade", "base").returncode == 0


# --------------------------------------------------------------------------- #
# Wiring                                                                       #
# --------------------------------------------------------------------------- #

def test_the_guest_identity_is_stated_in_exactly_one_place():
    assert GUEST_EMAIL == "guest@6thsense.dev"
    assert RESERVED_USERNAMES["guest"] == GUEST_EMAIL
    assert GUEST_ROLE in ROLES
