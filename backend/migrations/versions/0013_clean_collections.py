"""Clean collections, camera assignments and contributor workplace/rate."""
from alembic import op
import sqlalchemy as sa
revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('ops_wearers')}
    for column in [sa.Column('workplace', sa.String(200), nullable=False, server_default=''),
                   sa.Column('location', sa.String(200), nullable=False, server_default=''),
                   sa.Column('rate_krw_hour', sa.Integer(), nullable=True)]:
        if column.name not in columns:
            op.add_column('ops_wearers', column)
    tables = set(sa.inspect(bind).get_table_names())
    if 'ops_cameras' not in tables:
        op.create_table('ops_cameras',
            sa.Column('device_id', sa.String(32), primary_key=True),
            sa.Column('wearer_id', sa.BigInteger(), sa.ForeignKey('ops_wearers.id')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    if 'ops_clean_runs' not in tables:
        op.create_table('ops_clean_runs',
            sa.Column('run_id', sa.String(120), primary_key=True),
            sa.Column('device_id', sa.String(32), nullable=False),
            sa.Column('wearer_id', sa.BigInteger(), sa.ForeignKey('ops_wearers.id')),
            sa.Column('manifest_key', sa.Text(), nullable=False),
            sa.Column('manifest_version', sa.Text(), nullable=False),
            sa.Column('manifest_sha256', sa.String(64), nullable=False),
            sa.Column('manifest_json', sa.Text(), nullable=False),
            sa.Column('retained_seconds', sa.Float(), nullable=False),
            sa.Column('rejected_seconds', sa.Float(), nullable=False),
            sa.Column('rate_krw_hour', sa.Integer()),
            sa.Column('paid', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('paid_at', sa.DateTime(timezone=True)),
            sa.Column('amount_krw', sa.Integer()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    op.drop_table('ops_clean_runs')
    op.drop_table('ops_cameras')
    for name in ('rate_krw_hour', 'location', 'workplace'):
        op.drop_column('ops_wearers', name)
