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
