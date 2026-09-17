"""Add the Google Form contract mirror without changing existing receipts."""
from alembic import op
import sqlalchemy as sa

revision = '0020'
down_revision = '0019'
branch_labels = depends_on = None

def upgrade():
    op.create_table('contributor_form_contracts',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('response_id', sa.String(512), unique=True, nullable=False),
        sa.Column('form_id', sa.String(128), nullable=False),
        sa.Column('version', sa.String(80), nullable=False),
        sa.Column('terms_sha256', sa.String(64), nullable=False),
        sa.Column('receipt_sha256', sa.String(64), nullable=False),
        sa.Column('phone_digest', sa.String(64), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('subject', sa.String(64), sa.ForeignKey('contributor_accounts.subject')),
        sa.Column('wearer_id', sa.BigInteger(), sa.ForeignKey('ops_wearers.id')),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('source_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_contributor_form_contracts_phone_digest', 'contributor_form_contracts', ['phone_digest'])
    op.create_index('ix_contributor_form_contracts_subject', 'contributor_form_contracts', ['subject'])

def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM contributor_form_contracts)')).scalar():
        raise RuntimeError('Contract evidence exists; destructive downgrade refused.')
    op.drop_table('contributor_form_contracts')
