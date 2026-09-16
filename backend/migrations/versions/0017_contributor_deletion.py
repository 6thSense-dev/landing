"""Deletion requests exist independently of enrollment and survive identity removal."""
from alembic import op
import sqlalchemy as sa
revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('contributor_deletions',
        sa.Column('subject',sa.String(64),primary_key=True),
        sa.Column('id',sa.String(36),unique=True,nullable=False),
        sa.Column('status',sa.String(24),nullable=False),
        sa.Column('receipt_hash',sa.String(64),unique=True,nullable=False),
        sa.Column('requested_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('completed_at',sa.DateTime(timezone=True)),
        sa.Column('evidence',sa.Text()),
        sa.Column('provider_status',sa.String(24),nullable=False),
        sa.Column('attempts',sa.Integer(),nullable=False))

def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM contributor_deletions)')).scalar():
        raise RuntimeError('Deletion requests require retention-aware migration.')
    op.drop_table('contributor_deletions')
