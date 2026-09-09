"""ops: when a take actually landed in the bucket

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-09

The board had no notion of upload time at all. It matters more than the
recording time for two questions the operator actually asks: "did this
collector upload the same day or hoard a fortnight of cards", and "has this
camera gone quiet". Neither is answerable from `started_at`, which is the
camera's own clock and is exactly the thing in doubt.

It is not in any metadata the camera writes -- it is S3's `LastModified`, an
independent clock, which is also what makes the clock-skew check possible.

Guarded by an inspector for the same reason 0009-0011 are:
tests/test_seed_migration builds its schema from ORM metadata and then replays
the migrations.
"""
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    cols = {c["name"] for c in _insp().get_columns("ops_episodes")}
    if "uploaded_at" not in cols:
        op.add_column("ops_episodes",
                      sa.Column("uploaded_at", sa.DateTime(timezone=True)))
    if "ops_episodes_uploaded_idx" not in {
            i["name"] for i in _insp().get_indexes("ops_episodes")}:
        op.create_index("ops_episodes_uploaded_idx", "ops_episodes", ["uploaded_at"])


def downgrade() -> None:
    if "uploaded_at" in {c["name"] for c in _insp().get_columns("ops_episodes")}:
        op.drop_column("ops_episodes", "uploaded_at")
