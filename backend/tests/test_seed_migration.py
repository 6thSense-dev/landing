"""Seed migration reads FOUNDER_n_* env and upserts users."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User


def _alembic(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd="backend",
        env=full_env,
        capture_output=True,
        text=True,
    )


def _run_alembic(env: dict) -> subprocess.CompletedProcess:
    return _alembic(["upgrade", "head"], env)


@pytest_asyncio.fixture(autouse=True)
async def _reset_to_pre_seed(postgres_container):
    """Bookend each seed test: set up a clean 0002 state before, clean up after.

    Before:
    - Create all tables (idempotent).
    - Stamp alembic_version to 0002 so `alembic upgrade head` will run 0003.
    - Truncate sessions + users so prior seeded data doesn't interfere.

    After:
    - Truncate sessions + users to avoid polluting later tests (e.g., test_session_model)
      that insert the same emails.
    - Stamp alembic_version back to 0002 so subsequent suites see a consistent state.
    """
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        await conn.execute(text("DELETE FROM alembic_version"))
        await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0002')"))
        await conn.execute(text("TRUNCATE sessions, users RESTART IDENTITY CASCADE"))
    await engine.dispose()
    yield
    # Teardown: clean up seeded data and reset version marker.
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        # Tables may or may not exist (migration may have run); drop_all only what ORM knows.
        await conn.run_sync(Base.metadata.create_all)  # ensure tables exist before truncate
        await conn.execute(text("TRUNCATE sessions, users RESTART IDENTITY CASCADE"))
        await conn.execute(text("DELETE FROM alembic_version"))
        await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0002')"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_seeds_founders_from_env(postgres_container):
    env = os.environ.copy()
    env["FOUNDER_1_EMAIL"] = "a@x.com"
    env["FOUNDER_1_NAME"] = "Alice"
    env["FOUNDER_1_PASSWORD"] = "twelve-chars!!"
    env["FOUNDER_2_EMAIL"] = "b@x.com"
    env["FOUNDER_2_NAME"] = "Bob"
    env["FOUNDER_2_PASSWORD"] = "twelve-chars!!"
    # 3 and 4 deliberately missing.

    result = _run_alembic(env)
    assert result.returncode == 0, result.stderr

    engine = create_async_engine(os.environ["DATABASE_URL"])
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        rows = (await s.execute(select(User).where(User.email.in_(["a@x.com", "b@x.com"])))).scalars().all()
    await engine.dispose()
    emails = [r.email for r in rows]
    assert "a@x.com" in emails
    assert "b@x.com" in emails
    assert all(r.role == "founder" for r in rows)


@pytest.mark.asyncio
async def test_too_short_password_is_skipped(postgres_container):
    env = os.environ.copy()
    env["FOUNDER_1_EMAIL"] = "short@x.com"
    env["FOUNDER_1_NAME"] = "Short"
    env["FOUNDER_1_PASSWORD"] = "tooshort"
    result = _run_alembic(env)
    assert result.returncode == 0

    engine = create_async_engine(os.environ["DATABASE_URL"])
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        rows = (await s.execute(select(User).where(User.email == "short@x.com"))).scalars().all()
    await engine.dispose()
    assert rows == []


@pytest.mark.asyncio
async def test_idempotent_rerun_does_not_duplicate(postgres_container):
    env = os.environ.copy()
    env["FOUNDER_1_EMAIL"] = "id@x.com"
    env["FOUNDER_1_NAME"] = "Id"
    env["FOUNDER_1_PASSWORD"] = "twelve-chars!!"
    # First upgrade applies 0003 and inserts the user.
    result1 = _run_alembic(env)
    assert result1.returncode == 0, result1.stderr
    # Second upgrade is already at head — no duplicate should appear.
    result2 = _run_alembic(env)
    assert result2.returncode == 0, result2.stderr

    engine = create_async_engine(os.environ["DATABASE_URL"])
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        rows = (await s.execute(select(User).where(User.email == "id@x.com"))).scalars().all()
    await engine.dispose()
    assert len(rows) == 1
