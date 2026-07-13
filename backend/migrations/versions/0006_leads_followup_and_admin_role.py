"""add lead follow-up tracking and the admin role

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08

Two additions for the internal leads CRM:
  * leads.followed_up (bool) + leads.followed_up_at (ts) — the admin marks a
    lead as followed up from the CRM; the timestamp records when.
  * users.role gains 'admin' — the role that owns the leads CRM. Reachable
    through the same Partner Login page as the other roles.

DDL is idempotent (IF [NOT] EXISTS) so it is safe against a DB built from the
ORM metadata (the test harness) as well as one migrated 0001 -> 0005.
"""
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Lead follow-up tracking.
    op.execute(
        "ALTER TABLE leads "
        "ADD COLUMN IF NOT EXISTS followed_up BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS followed_up_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS leads_followed_up_idx ON leads (followed_up)"
    )

    # users.role gains 'admin'.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('admin', 'founder', 'customer', 'investor'))"
    )


def downgrade() -> None:
    # Fold any admin accounts back to founder so the stricter check can re-apply.
    op.execute("UPDATE users SET role = 'founder' WHERE role = 'admin'")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('founder', 'customer', 'investor'))"
    )

    op.execute("DROP INDEX IF EXISTS leads_followed_up_idx")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS followed_up_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS followed_up")
