"""ops: board settings (the payment rate)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-07

The operations board prices payment per approved episode, and until now the
rate lived only in the laptop tool's JSON file. A rate held in an operator's
browser would let two operators stamp two different amounts onto the same
shift, so it goes in Postgres beside the episodes it prices.

Keyed kv rather than a one-row table with a column per setting: the next
setting should be an INSERT, not another migration.

Guarded by an inspector for the same reason 0009 and 0010 are:
tests/test_seed_migration builds its schema from ORM metadata and then replays
the migrations.
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    if "ops_settings" not in _insp().get_table_names():
        op.create_table(
            "ops_settings",
            sa.Column("key", sa.String(60), primary_key=True),
            sa.Column("value", sa.Text, nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
        )

    # Seeded at 0 rather than left absent so the board reads a rate rather than
    # a missing row, and DO NOTHING so a re-run cannot reset a rate somebody set.
    op.get_bind().execute(
        sa.text("INSERT INTO ops_settings (key, value) VALUES ('rate_krw', '0') "
                "ON CONFLICT (key) DO NOTHING"))


def downgrade() -> None:
    if "ops_settings" in _insp().get_table_names():
        op.drop_table("ops_settings")
