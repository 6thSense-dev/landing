"""Seed migration reads FOUNDER_n_* env and upserts users."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import User


_BACKEND_DIR = Path(__file__).resolve().parents[1]  # backend/


def _alembic(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env=full_env,
        capture_output=True,
        text=True,
    )


def _run_alembic(env: dict) -> subprocess.CompletedProcess:
    return _alembic(["upgrade", "head"], env)


@pytest_asyncio.fixture(autouse=True)
async def _reset_to_pre_seed(postgres_container):
    """Build the real revision 0002 schema, rather than stamping current tables.

    The URL comes exclusively from our disposable testcontainer. Recreating
    its public schema isolates seed tests from earlier migration/model tests.
    """
    url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url

    async def reset_schema():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()

    try:
        await reset_schema()
        result = _alembic(["upgrade", "0002"], {"DATABASE_URL": url})
        assert result.returncode == 0, result.stderr
        yield
    finally:
        try:
            await reset_schema()
        finally:
            if previous_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_url


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
