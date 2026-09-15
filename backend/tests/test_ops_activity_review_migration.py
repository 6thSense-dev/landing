"""Exercise additive migration on isolated testcontainer, never production."""
import os
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from tests.test_migrations import _alembic

@pytest.mark.asyncio
async def test_0016_roundtrip(postgres_container):
    result=_alembic('upgrade','0015');assert result.returncode==0,result.stderr
    result=_alembic('upgrade','0016');assert result.returncode==0,result.stderr
    engine=create_async_engine(os.environ['DATABASE_URL'])
    async with engine.connect() as conn:
        tables=(await conn.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars().all()
        assert 'ops_activity_reviews' in tables and 'ops_activity_criteria' in tables
        constraints=(await conn.exec_driver_sql("SELECT conname FROM pg_constraint WHERE conrelid='ops_activity_reviews'::regclass")).scalars().all()
        assert 'uq_activity_review_revision' in constraints
    await engine.dispose()
    result=_alembic('downgrade','0015');assert result.returncode==0,result.stderr
    engine=create_async_engine(os.environ['DATABASE_URL'])
    async with engine.connect() as conn:
        tables=(await conn.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars().all()
        assert 'ops_activity_reviews' not in tables and 'ops_clean_runs' in tables
    await engine.dispose()
    result=_alembic('downgrade','base');assert result.returncode==0,result.stderr


@pytest.mark.asyncio
async def test_0016_preserves_existing_workflow_rows_and_can_store_reviews(postgres_container):
    import json
    from datetime import datetime, timezone
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.models import ActivityReview, Episode, FootageReview, Payout, PayoutItem, User
    from app.models.ops_activity_review import ActivityCriteria
    from tests.test_ops_rounding import seed_run

    result = _alembic('upgrade', '0015')
    assert result.returncode == 0, result.stderr
    engine = create_async_engine(os.environ['DATABASE_URL'])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    tables = ('ops_episodes', 'ops_clean_runs', 'ops_footage_reviews', 'ops_payouts',
              'ops_payout_items', 'ops_payout_recipients', 'ops_cameras', 'ops_wearers')

    async def snapshot():
        async with engine.connect() as conn:
            return {table: sorted(json.dumps(row, sort_keys=True) for row in
                (await conn.execute(text(f'SELECT row_to_json(t) FROM {table} t'))).scalars()) for table in tables}

    try:
        async with Session() as db:
            person, run, recs = await seed_run(db)
            db.add(Episode(recording='historical-paid-raw', wearer_id=person.id, paid=True,
                           amount_krw=123, paid_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
            db.add(FootageReview(run_id=run.run_id, recording=recs[0]['recording'], manifest_sha256=run.manifest_sha256,
                                decision='reviewed', reviewer='fixture-reviewer', collection_date='2026-09-01', note='Historical evidence'))
            db.add(Payout(id='migration-reserved', wearer_id=person.id, amount_krw=44184, accepted_seconds=14460,
                          approved_by='fixture-reviewer', scheduled_for=datetime(2026, 9, 4, tzinfo=timezone.utc),
                          recipient_id='321', source_currency='USD', wise_profile_id='123', wise_environment='sandbox', recipient_hash='hash'))
            await db.flush()
            db.add(PayoutItem(run_id=run.run_id, recording=recs[0]['recording'], payout_id='migration-reserved',
                              manifest_sha256=run.manifest_sha256, accepted_seconds=14460, rate_krw_hour=11000, collection_date='2026-09-01'))
            user = User(email='migration-reviewer@example.test', name='Synthetic reviewer', role='ops', password_hash='fixture-only')
            db.add(user); await db.commit()
            run_id, reviewer_id = run.run_id, user.id
        before = await snapshot()
        result = _alembic('upgrade', 'head')
        assert result.returncode == 0, result.stderr
        assert await snapshot() == before
        async with Session() as db:
            db.add(ActivityCriteria(task_id='fixture', version='v1', text='Synthetic criteria', sha256='b' * 64))
            db.add(ActivityReview(run_id=run_id, task_id='fixture', revision=1, manifest_sha256='a' * 64,
                                 criteria_version='v1', criteria_text='Synthetic criteria', criteria_sha256='b' * 64,
                                 intervals_json='[]', sources_json='[]', reviewer_id=reviewer_id,
                                 reviewer_email='migration-reviewer@example.test'))
            await db.commit()
            assert (await db.execute(select(ActivityReview))).scalar_one().reviewed_at is not None
        result = _alembic('downgrade', '0015')
        assert result.returncode == 0, result.stderr
        assert await snapshot() == before
    finally:
        await engine.dispose()
        result = _alembic('downgrade', 'base')
        assert result.returncode == 0, result.stderr
