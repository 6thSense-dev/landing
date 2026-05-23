"""Session model: FK cascade, token_hash unique, defaults."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.models import Session, User


def _expires():
    return datetime.now(timezone.utc) + timedelta(days=14)


@pytest.mark.asyncio
async def test_insert_session_with_user(db_session):
    user = User(email="a@x.com", name="A", role="founder", password_hash="h")
    db_session.add(user)
    await db_session.flush()
    session_row = Session(
        user_id=user.id,
        token_hash="0" * 64,
        expires_at=_expires(),
    )
    db_session.add(session_row)
    await db_session.flush()
    fetched = (await db_session.execute(select(Session))).scalar_one()
    assert fetched.user_id == user.id
    assert fetched.last_used_at is not None


@pytest.mark.asyncio
async def test_token_hash_unique(db_session):
    user = User(email="a@x.com", name="A", role="founder", password_hash="h")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Session(user_id=user.id, token_hash="abc", expires_at=_expires()))
    await db_session.flush()
    db_session.add(Session(user_id=user.id, token_hash="abc", expires_at=_expires()))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_deleting_user_cascades_to_sessions(db_session):
    user = User(email="a@x.com", name="A", role="founder", password_hash="h")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Session(user_id=user.id, token_hash="t1", expires_at=_expires()))
    await db_session.flush()
    await db_session.execute(delete(User).where(User.id == user.id))
    await db_session.flush()
    remaining = (await db_session.execute(select(Session))).scalars().all()
    assert remaining == []
