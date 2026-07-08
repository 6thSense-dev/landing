"""collapse leads to a single contact form: drop kind/product, re-key on email

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08

The site now has one intake — the Contact Us form at the bottom of the home
page. `kind` (preorder|waitlist|contact) and `product` (hand|nerve|skin) no
longer mean anything, so they're dropped. Uniqueness returns to `email` alone,
and `message` becomes required.

"Optimize the rows": the old (email, kind) uniqueness allowed several rows per
address, so we first collapse to one row per email (keeping the most recently
updated) and backfill any empty message before enforcing NOT NULL — no lead is
lost.

DDL is written idempotently (IF [NOT] EXISTS) so it is safe against a DB built
directly from the ORM metadata (the test harness) as well as one migrated
0001 -> 0004.
"""
from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


_LEGACY_MSG = "(legacy signup — no message)"


def upgrade() -> None:
    # 1. Collapse to one row per email: delete any row that is older than
    #    another row sharing its email (ordered by updated_at, then id).
    op.execute(
        """
        DELETE FROM leads a
        USING leads b
        WHERE a.email = b.email
          AND (a.updated_at, a.id) < (b.updated_at, b.id)
        """
    )

    # 2. Backfill: a contact needs a message. Old waitlist/preorder rows have
    #    none, so give them a clear sentinel rather than dropping the lead.
    op.execute(
        f"""
        UPDATE leads
        SET message = '{_LEGACY_MSG}'
        WHERE message IS NULL OR btrim(message) = ''
        """
    )

    # 3. Drop the kind/product machinery.
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_kind_check")
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_product_check")
    op.execute("DROP INDEX IF EXISTS leads_email_kind_key")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS kind")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS product")

    # 4. message is now required.
    op.execute("ALTER TABLE leads ALTER COLUMN message SET NOT NULL")

    # 5. Re-key uniqueness on email alone.
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_email_key")
    op.execute("ALTER TABLE leads ADD CONSTRAINT leads_email_key UNIQUE (email)")


def downgrade() -> None:
    # Reverse to the 0004 shape: kind/product columns back, message nullable,
    # uniqueness on (email, kind).
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_email_key")

    op.execute(
        "ALTER TABLE leads "
        "ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'contact'"
    )
    op.execute("ALTER TABLE leads ALTER COLUMN kind DROP DEFAULT")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS product VARCHAR(20)")

    op.execute("ALTER TABLE leads ALTER COLUMN message DROP NOT NULL")

    op.execute(
        "ALTER TABLE leads ADD CONSTRAINT leads_kind_check "
        "CHECK (kind IN ('preorder', 'waitlist', 'contact'))"
    )
    op.execute(
        "ALTER TABLE leads ADD CONSTRAINT leads_product_check "
        "CHECK (product IS NULL OR product IN ('hand', 'nerve', 'skin'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS leads_email_kind_key "
        "ON leads (email, kind)"
    )
