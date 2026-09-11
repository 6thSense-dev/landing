"""Real Postgres checks for privileged identity provisioning, without live access."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli_intake_admin import EMAIL, provision
from app.core.passwords import hash_password, verify_password
from app.models import Session as SessionRow, User


@pytest.fixture
def provision_db(db_session, monkeypatch):
    # Same database, separate committed transactions like the actual CLI.
    monkeypatch.setattr("app.cli_intake_admin.get_sessionmaker", lambda: async_sessionmaker(db_session.bind, expire_on_commit=False))
    return db_session


@pytest.mark.asyncio
async def test_create_and_idempotence(provision_db):
    db = provision_db
    with pytest.raises(ValueError, match="does not exist"):
        await provision()
    with pytest.raises(ValueError, match="12"):
        await provision(new_password="short")
    await provision(new_password="test-only-long-password")
    user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one()
    assert user.role == "admin" and user.is_active
    assert verify_password("test-only-long-password", user.password_hash)
    assert "already admin" in await provision()
    with pytest.raises(ValueError, match="preserved"):
        await provision(new_password="test-only-replacement")


@pytest.mark.asyncio
async def test_promotion_preserves_password_revokes_only_target_sessions(provision_db):
    db = provision_db
    original = hash_password("test-only-long-password")
    ronak = User(email=EMAIL, name="Ronak", role="founder", password_hash=original)
    guest = User(email="guest@6thsense.dev", name="Guest", role="guest", password_hash=original)
    db.add_all([ronak, guest])
    await db.flush()
    db.add_all([SessionRow(user_id=u.id, token_hash=str(u.id).zfill(64), expires_at=datetime.now(timezone.utc)+timedelta(days=1)) for u in (ronak, guest)])
    await db.commit()
    await provision()
    await db.refresh(ronak)
    await db.refresh(guest)
    assert ronak.role == "admin" and ronak.password_hash == original
    assert guest.role == "guest"
    assert (await db.execute(select(SessionRow.user_id))).scalars().all() == [guest.id]


@pytest.mark.asyncio
async def test_inactive_and_ambiguous_identity_refused(provision_db):
    db = provision_db
    user = User(email=EMAIL, name="Ronak", role="founder", is_active=False, password_hash="unchanged")
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="inactive"):
        await provision()
    user.is_active = True
    db.add(User(email=EMAIL.upper(), name="Other", role="customer", password_hash="unchanged"))
    await db.commit()
    with pytest.raises(ValueError, match="case variants"):
        await provision()
    await db.refresh(user)
    assert user.role == "founder"


@pytest.mark.asyncio
async def test_single_mixed_case_identity_refused(provision_db):
    db = provision_db
    user = User(email=EMAIL.upper(), name="Ronak", role="founder", password_hash="unchanged")
    db.add(user)
    await db.commit()
    with pytest.raises(ValueError, match="canonical lowercase"):
        await provision()
    await db.refresh(user)
    assert user.role == "founder" and user.password_hash == "unchanged"


@pytest.mark.asyncio
async def test_concurrent_provision_creates_once(provision_db):
    import asyncio
    results = await asyncio.gather(
        provision(new_password="test-only-long-password"),
        provision(new_password="test-only-long-password"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, str) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert len((await provision_db.execute(select(User))).scalars().all()) == 1
