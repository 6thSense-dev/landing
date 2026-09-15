"""Shared pytest fixtures: a Postgres testcontainer + a per-test session."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.models import Base


def pytest_configure(config):
    """Set a stub DATABASE_URL so module-level `app = create_app()` doesn't
    raise at collection time.  The real URL is injected by the
    `postgres_container` session fixture before any test actually runs."""
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://stub:stub@localhost/stub")


@pytest.fixture(scope="session")
def postgres_container():
    external = os.getenv("TEST_DATABASE_URL")
    if external:
        from urllib.parse import urlparse
        if not urlparse(external).path.rsplit("/", 1)[-1].endswith("_test"):
            raise ValueError("TEST_DATABASE_URL must name an isolated *_test database")
        os.environ["DATABASE_URL"] = external
        yield None
        return
    with PostgresContainer("postgres:16-alpine") as pg:
        # Inject for any module that calls get_settings().
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = url
        yield pg


@pytest_asyncio.fixture(autouse=True)
async def _reset_db_singletons():
    """Reset the module-level engine/sessionmaker singletons in app.core.db
    before each async test so they are re-created on the current event loop.
    Without this, the second test sees connections attached to a closed loop."""
    import app.core.db as _db
    _db._engine = None
    _db._sessionmaker = None
    yield
    if _db._engine is not None:
        await _db._engine.dispose()
    _db._engine = None
    _db._sessionmaker = None


@pytest_asyncio.fixture
async def db_session(postgres_container) -> AsyncSession:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
