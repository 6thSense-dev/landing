"""Authenticated contributor accounts and resumable, checksummed episode uploads."""
from alembic import op
import sqlalchemy as sa

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('upload_batches',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('subject', sa.String(64), sa.ForeignKey('contributor_accounts.subject'), nullable=False),
        sa.Column('wearer_id', sa.BigInteger, sa.ForeignKey('ops_wearers.id'), nullable=False),
        sa.Column('recording', sa.String(200), unique=True, nullable=False),
        sa.Column('manifest_hash', sa.String(64), nullable=False),
        sa.Column('total_bytes', sa.BigInteger, nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_upload_batches_subject', 'upload_batches', ['subject'])
    op.create_table('upload_files',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('batch_id', sa.String(32), sa.ForeignKey('upload_batches.id'), nullable=False),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('size', sa.BigInteger, nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('modified_ms', sa.BigInteger, nullable=False),
        sa.Column('upload_id', sa.Text), sa.Column('version_id', sa.Text),
        sa.Column('etag', sa.String(200)), sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('batch_id', 'path'))
    op.create_index('ix_upload_files_batch_id', 'upload_files', ['batch_id'])
    op.create_table('upload_parts',
        sa.Column('file_id', sa.String(32), sa.ForeignKey('upload_files.id'), primary_key=True),
        sa.Column('number', sa.Integer, primary_key=True),
        sa.Column('checksum', sa.String(44), nullable=False), sa.Column('etag', sa.String(200)))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM upload_batches)')).scalar():
        raise RuntimeError('Preserve upload attribution receipts; migration 0019 is in use.')
    for table in ('upload_parts', 'upload_files', 'upload_batches'):
        op.drop_table(table)
