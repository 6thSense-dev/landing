"""create users and sessions tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="users_email_key"),
        sa.CheckConstraint(
            "role IN ('founder', 'customer', 'investor')",
            name="users_role_check",
        ),
    )
    op.create_index("users_role_idx", "users", ["role"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.UniqueConstraint("token_hash", name="sessions_token_hash_key"),
    )
    op.create_index("sessions_user_id_idx", "sessions", ["user_id"])
    op.create_index("sessions_expires_at_idx", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("sessions_expires_at_idx", table_name="sessions")
    op.drop_index("sessions_user_id_idx", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("users_role_idx", table_name="users")
    op.drop_table("users")
