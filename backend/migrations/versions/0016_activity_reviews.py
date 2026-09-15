"""Append-only task review snapshots, separate from QC and financial records."""
from alembic import op
import sqlalchemy as sa
revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('ops_activity_criteria',
        sa.Column('task_id', sa.String(80), primary_key=True),
        sa.Column('version', sa.String(80), primary_key=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False))
    op.create_table('ops_activity_reviews',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('run_id', sa.String(120), sa.ForeignKey('ops_clean_runs.run_id'), nullable=False),
        sa.Column('task_id', sa.String(80), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('manifest_sha256', sa.String(64), nullable=False),
        sa.Column('criteria_version', sa.String(80), nullable=False),
        sa.Column('criteria_text', sa.Text(), nullable=False),
        sa.Column('intervals_json', sa.Text(), nullable=False),
        sa.Column('sources_json', sa.Text(), nullable=False),
        sa.Column('criteria_sha256', sa.String(64), nullable=False),
        sa.Column('reviewer_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reviewer_email', sa.String(320), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('run_id', 'task_id', 'revision', name='uq_activity_review_revision'))

def downgrade():
    op.drop_table('ops_activity_reviews')
    op.drop_table('ops_activity_criteria')
