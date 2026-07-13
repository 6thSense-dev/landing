"""app.cli: create-user + reset-password."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cli import create_user, reset_password
from app.core.passwords import hash_password, verify_password
from app.core.sessions import hash_session_token, mint_session_token
from app.models import Base, Session as SessionRow, User


@pytest_asyncio.fixture
async def fresh_db(postgres_container):
    import os
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    # Reset the in-process sessionmaker singleton so the CLI's get_sessionmaker()
    # connects on the current event loop.
    import app.core.db as _db
    _db._engine = None
    _db._sessionmaker = None
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_inserts(fresh_db):
    await create_user(email="new@x.com", name="New", role="customer", password="twelve-chars!!")
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.email == "new@x.com"))).scalar_one()
    assert row.role == "customer"
    assert verify_password("twelve-chars!!", row.password_hash)


@pytest.mark.asyncio
async def test_create_user_rejects_short_password(fresh_db):
    with pytest.raises(ValueError, match="12"):
        await create_user(email="x@x.com", name="X", role="customer", password="short")


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate(fresh_db):
    await create_user(email="dup@x.com", name="A", role="customer", password="twelve-chars!!")
    with pytest.raises(ValueError, match="exists"):
        await create_user(email="dup@x.com", name="B", role="founder", password="twelve-chars!!")


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_role(fresh_db):
    with pytest.raises(ValueError, match="role"):
        await create_user(
            email="a@x.com",
            name="A",
            role="operator",
            password="twelve-chars!!",
        )


@pytest.mark.asyncio
async def test_reset_password_updates_hash_and_kills_sessions(fresh_db):
    await create_user(email="r@x.com", name="R", role="founder", password="twelve-chars!!")
    SessionLocal = async_sessionmaker(fresh_db, expire_on_commit=False)
    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.email == "r@x.com"))).scalar_one()
        raw = mint_session_token()
        s.add(SessionRow(
            user_id=user.id,
            token_hash=hash_session_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        ))
        await s.commit()

    await reset_password(email="r@x.com", new_password="brand-new-pw-12")

    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.email == "r@x.com"))).scalar_one()
        assert verify_password("brand-new-pw-12", row.password_hash)
        assert not verify_password("twelve-chars!!", row.password_hash)
        remaining = (await s.execute(select(SessionRow).where(SessionRow.user_id == row.id))).scalars().all()
        assert remaining == []
