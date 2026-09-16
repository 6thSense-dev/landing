"""Exercise real upgrade preservation and a rollback that must not revoke receipts."""
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.test_migrations import _alembic


async def test_receipt_migration_preserves_legacy_hash_and_blocks_destructive_rollback(postgres_container):
    assert _alembic('upgrade', '0017').returncode == 0
    engine = create_async_engine(os.environ['DATABASE_URL'])
    try:
        async with engine.begin() as connection:
            await connection.execute(text("INSERT INTO contributor_deletions(subject,id,status,receipt_hash,provider_status,attempts) VALUES ('legacy','request','requested','original-hash','pending',0)"))
        assert _alembic('upgrade', '0018').returncode == 0
        async with engine.begin() as connection:
            assert (await connection.execute(text("SELECT receipt_hash FROM contributor_deletions WHERE subject='legacy'"))).scalar() == 'original-hash'
            await connection.execute(text("INSERT INTO contributor_deletion_receipts(subject,receipt_hash) VALUES ('legacy','retry-hash')"))
        result = _alembic('downgrade', '0017')
        assert result.returncode != 0 and 'Issued deletion receipts must remain usable' in result.stderr
        async with engine.begin() as connection:
            assert (await connection.execute(text("SELECT count(*) FROM contributor_deletion_receipts"))).scalar() == 1
            await connection.execute(text("DELETE FROM contributor_deletion_receipts"))
            await connection.execute(text("DELETE FROM contributor_deletions"))
        assert _alembic('downgrade', 'base').returncode == 0
    finally:
        await engine.dispose()
