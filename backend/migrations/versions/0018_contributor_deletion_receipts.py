"""Preserve every issued deletion receipt across retries and identity removal."""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    # Original 0017 receipt hashes are intentionally left untouched.
    op.create_table('contributor_deletion_receipts',
        sa.Column('receipt_hash', sa.String(64), primary_key=True),
        sa.Column('subject', sa.String(64), sa.ForeignKey('contributor_deletions.subject'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_contributor_deletion_receipts_subject', 'contributor_deletion_receipts', ['subject'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM contributor_deletion_receipts)')).scalar():
        raise RuntimeError('Issued deletion receipts must remain usable; retain migration 0018.')
    op.drop_index('ix_contributor_deletion_receipts_subject', table_name='contributor_deletion_receipts')
    op.drop_table('contributor_deletion_receipts')
