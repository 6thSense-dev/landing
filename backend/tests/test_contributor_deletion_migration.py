"""Run separately on a disposable *_test database (no application fixture)."""
import os
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.test_migrations import _alembic

async def test_deletion_migration_preserves_unenrolled_requests(postgres_container):
    assert _alembic('upgrade','head').returncode == 0
    engine=create_async_engine(os.environ['DATABASE_URL'])
    try:
        async with engine.begin() as connection:
            await connection.execute(text("INSERT INTO contributor_deletions(subject,id,status,receipt_hash,provider_status,attempts) VALUES ('unenrolled','request','requested','hash','pending',0)"))
        result=_alembic('downgrade','0016')
        assert result.returncode != 0 and 'retention-aware' in result.stderr
        async with engine.begin() as connection:
            assert (await connection.execute(text("SELECT count(*) FROM contributor_deletions"))).scalar()==1
            await connection.execute(text("DELETE FROM contributor_deletions"))
        assert _alembic('downgrade','base').returncode == 0
    finally:
        await engine.dispose()
