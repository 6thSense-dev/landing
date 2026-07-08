"""Round-trip the Alembic migrations against a fresh Postgres."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine


def _alembic(*args, env=None):
    cwd = Path(__file__).resolve().parents[1]  # backend/
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_migration_upgrade_then_downgrade(postgres_container):
    # `postgres_container` fixture sets DATABASE_URL.
    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr


@pytest.mark.asyncio
async def test_migration_0002_creates_users_and_sessions(postgres_container):
    """After alembic upgrade head, the users and sessions tables exist."""
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        tables = (
            await conn.exec_driver_sql(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
        ).fetchall()
    await engine.dispose()
    table_names = [r[0] for r in tables]
    assert "users" in table_names
    assert "sessions" in table_names


@pytest.mark.asyncio
async def test_migration_0005_collapses_leads_to_contact(postgres_container):
    """After upgrade head: leads has no kind/product, message is NOT NULL, and
    uniqueness is back on email alone (no composite (email, kind) index)."""
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        cols = (
            await conn.exec_driver_sql(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name='leads'"
            )
        ).fetchall()
        col_map = {name: nullable for name, nullable in cols}

        # email-only unique constraint present.
        email_uc = (
            await conn.exec_driver_sql(
                "SELECT conname FROM pg_constraint WHERE conname='leads_email_key'"
            )
        ).fetchall()

        # Old composite (email, kind) index is gone.
        kind_idx = (
            await conn.exec_driver_sql(
                "SELECT indexname FROM pg_indexes "
                "WHERE indexname='leads_email_kind_key'"
            )
        ).fetchall()
    await engine.dispose()

    assert "kind" not in col_map
    assert "product" not in col_map
    assert col_map.get("message") == "NO"       # NOT NULL
    assert len(email_uc) == 1                    # email-only unique restored
    assert kind_idx == []


@pytest.mark.asyncio
async def test_migration_0004_downgrade_restores_email_unique(postgres_container):
    """Downgrading 0004 drops the new columns and restores email uniqueness."""
    assert _alembic("upgrade", "head").returncode == 0
    down = _alembic("downgrade", "0003")
    assert down.returncode == 0, down.stderr

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        cols = (
            await conn.exec_driver_sql(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='leads'"
            )
        ).fetchall()
        col_names = {c[0] for c in cols}
        email_uc = (
            await conn.exec_driver_sql(
                "SELECT conname FROM pg_constraint WHERE conname='leads_email_key'"
            )
        ).fetchall()
        kind_idx = (
            await conn.exec_driver_sql(
                "SELECT indexname FROM pg_indexes "
                "WHERE indexname='leads_email_kind_key'"
            )
        ).fetchall()
    await engine.dispose()

    assert "kind" not in col_names
    assert "product" not in col_names
    assert "message" not in col_names
    assert len(email_uc) == 1          # email-only unique restored
    assert kind_idx == []              # composite index removed

    # Clean up: fully tear the schema down so we don't leave a `leads` table
    # missing its new columns for later tests (whose create_all no-ops on an
    # existing table).
    assert _alembic("downgrade", "base").returncode == 0
