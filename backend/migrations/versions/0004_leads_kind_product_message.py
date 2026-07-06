"""add kind/product/message to leads; re-key uniqueness on (email, kind)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-03

DDL is written idempotently (IF [NOT] EXISTS) so it is safe to run against a
DB whose `leads` table was created directly from the ORM metadata (as the test
harness does) as well as against a real DB migrated 0001 -> 0003.
"""
from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns. `kind` classifies the submission (preorder|waitlist|contact);
    # `product` scopes it to a product line where relevant (hand|nerve|skin,
    # NULL for a general enquiry); `message` is the optional free-text body
    # (required for contact submissions, enforced at the API layer).
    #
    # `kind` gets a temporary server_default of 'contact' so the ALTER can
    # backfill any pre-existing rows without a NULL violation; the default is
    # then dropped so the application must always supply an explicit kind.
    op.execute(
        "ALTER TABLE leads "
        "ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'contact'"
    )
    op.execute("ALTER TABLE leads ALTER COLUMN kind DROP DEFAULT")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS product VARCHAR(20)")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS message TEXT")

    op.execute(
        "ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_kind_check"
    )
    op.execute(
        "ALTER TABLE leads ADD CONSTRAINT leads_kind_check "
        "CHECK (kind IN ('preorder', 'waitlist', 'contact'))"
    )
    op.execute(
        "ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_product_check"
    )
    op.execute(
        "ALTER TABLE leads ADD CONSTRAINT leads_product_check "
        "CHECK (product IS NULL OR product IN ('hand', 'nerve', 'skin'))"
    )

    # Re-key uniqueness: one row per (email, kind) instead of per email, so a
    # single person can hold e.g. a preorder AND a contact row.
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_email_key")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS leads_email_kind_key "
        "ON leads (email, kind)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS leads_email_kind_key")
    op.execute(
        "ALTER TABLE leads ADD CONSTRAINT leads_email_key UNIQUE (email)"
    )
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_product_check")
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_kind_check")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS message")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS product")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS kind")
