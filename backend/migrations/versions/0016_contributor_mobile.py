"""Durable mobile accounts, consent, supervised assignments and recipient submissions."""
from alembic import op
import sqlalchemy as sa
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("contributor_accounts", sa.Column("subject", sa.String(64), primary_key=True), sa.Column("wearer_id", sa.BigInteger(), sa.ForeignKey("ops_wearers.id"), nullable=False, unique=True), sa.Column("routing_version", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("contributor_consents", sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject", sa.String(64), sa.ForeignKey("contributor_accounts.subject"), nullable=False, index=True), sa.Column("snapshot", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("contributor_camera_claims", sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject", sa.String(64), sa.ForeignKey("contributor_accounts.subject"), nullable=False, index=True), sa.Column("device_id", sa.String(6), nullable=False, index=True), sa.Column("status", sa.String(24), nullable=False), sa.Column("operator", sa.String(200)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("effective_at", sa.DateTime(timezone=True)), sa.Column("ended_at", sa.DateTime(timezone=True)))
    op.create_index("contributor_camera_active_unique", "contributor_camera_claims", ["device_id"], unique=True, postgresql_where=sa.text("status = 'approved' AND ended_at IS NULL"))
    op.create_table("contributor_recipient_attempts", sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject", sa.String(64), sa.ForeignKey("contributor_accounts.subject"), nullable=False, index=True), sa.Column("status", sa.String(32), nullable=False), sa.Column("recipient_id", sa.String(64)), sa.Column("summary", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

def downgrade():
    # An application rollback must not erase identities or consent/payment audit.
    # Empty test/new installations can be reversed; populated ones need an
    # explicit retention-aware migration reviewed against the real records.
    names = ("contributor_recipient_attempts", "contributor_camera_claims", "contributor_consents", "contributor_accounts")
    connection = op.get_bind()
    if any(connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM " + name + " LIMIT 1)")).scalar() for name in names):
        raise RuntimeError("Contributor audit records require an explicit retention-aware migration.")
    for name in names:
        op.drop_table(name)
