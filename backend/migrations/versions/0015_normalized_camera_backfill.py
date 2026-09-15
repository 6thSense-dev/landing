"""Backfill confirmed camera owners after normalizing historical ID spelling."""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    # 0014 is already deployed. Correct its missed case/whitespace variants
    # without changing explicit owners, paid sources, or any Clean/payments row.
    op.execute("""
        UPDATE ops_episodes AS e
        SET wearer_id = c.wearer_id
        FROM ops_cameras AS c
        WHERE e.wearer_id IS NULL AND e.paid = false
          AND c.wearer_id IS NOT NULL
          AND c.device_id IN ('16A4A5', '16A2B6', '4A636A', '1696C8')
          AND regexp_replace(upper(btrim(e.device_id)), '^EGO-', '') = c.device_id
    """)


def downgrade():
    # Historical attribution is never removed as part of a code rollback.
    pass
