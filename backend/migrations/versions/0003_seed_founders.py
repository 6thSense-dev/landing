"""seed founder accounts from env

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-23
"""
from __future__ import annotations

import logging
import os

from alembic import op
import sqlalchemy as sa

from app.core.passwords import hash_password


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.seed_founders")


def upgrade() -> None:
    bind = op.get_bind()
    for i in range(1, 5):
        email = os.environ.get(f"FOUNDER_{i}_EMAIL")
        name = os.environ.get(f"FOUNDER_{i}_NAME")
        pw = os.environ.get(f"FOUNDER_{i}_PASSWORD")
        if not (email and name and pw):
            log.warning("FOUNDER_%d_* env not fully set; skipping", i)
            continue
        if len(pw) < 12:
            log.warning("FOUNDER_%d_PASSWORD shorter than 12 chars; skipping", i)
            continue
        pwh = hash_password(pw)
        bind.execute(
            sa.text(
                "INSERT INTO users (email, name, role, password_hash) "
                "VALUES (:email, :name, 'founder', :pwh) "
                "ON CONFLICT (email) DO NOTHING"
            ),
            {"email": email.lower().strip(), "name": name.strip(), "pwh": pwh},
        )


def downgrade() -> None:
    # Seeding is data-only; downgrade is a no-op so we don't blow away
    # accounts created in the meantime by the CLI.
    pass
