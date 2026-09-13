"""Exercise additive migration on isolated testcontainer, never production."""
import os
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from tests.test_migrations import _alembic

@pytest.mark.asyncio
async def test_0014_roundtrip(postgres_container):
    result=_alembic('upgrade','0013');assert result.returncode==0,result.stderr
    result=_alembic('upgrade','0014');assert result.returncode==0,result.stderr
    engine=create_async_engine(os.environ['DATABASE_URL'])
    async with engine.connect() as conn:
        tables=(await conn.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars().all()
        assert 'ops_activity_reviews' in tables and 'ops_activity_criteria' in tables
        constraints=(await conn.exec_driver_sql("SELECT conname FROM pg_constraint WHERE conrelid='ops_activity_reviews'::regclass")).scalars().all()
        assert 'uq_activity_review_revision' in constraints
    await engine.dispose()
    result=_alembic('downgrade','0013');assert result.returncode==0,result.stderr
    engine=create_async_engine(os.environ['DATABASE_URL'])
    async with engine.connect() as conn:
        tables=(await conn.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars().all()
        assert 'ops_activity_reviews' not in tables and 'ops_clean_runs' in tables
    await engine.dispose()
    result=_alembic('downgrade','base');assert result.returncode==0,result.stderr
