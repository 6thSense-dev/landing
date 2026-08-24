"""SQLAlchemy ORM model for the `users` table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.lead import Base


#: Every value `users.role` may take, in the order the CHECK constraint states
#: them. Kept in lockstep with migration 0007_add_guest_role.py and
#: app.cli.VALID_ROLES.
ROLES: tuple[str, ...] = ("admin", "founder", "customer", "investor", "guest")

#: The shared, read-only demo role handed to prospects. It carries no database
#: privilege of its own -- every restriction is enforced in the application
#: layer (see app/api/routes/auth.py, app/core/auth_deps.py and the catalog
#: routes). The role only makes the row insertable and greppable.
GUEST_ROLE = "guest"

#: Where migration 0007's downgrade parks a guest row so the narrower 0006-era
#: CHECK can re-apply: role folded to this value AND is_active=false, in one
#: statement block. That exact pair is 0007's artefact and nothing else -- a real
#: customer row is active -- which is what lets `app.cli seed-guest` recognise it
#: and restore the demo account after a rollback instead of demanding the row be
#: deleted by hand. Keep in lockstep with 0007_add_guest_role.DOWNGRADE_FOLD_ROLE.
GUEST_DOWNGRADE_FOLD_ROLE = "customer"

#: The single account allowed to hold GUEST_ROLE via `app.cli seed-guest`.
#: The login form also accepts the bare username `guest`, which resolves here
#: through app.api.routes.auth.RESERVED_USERNAMES.
GUEST_EMAIL = "guest@6thsense.dev"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            # Keep in lockstep with ROLES above and migration 0007. The test
            # suite builds its schema from this metadata (create_all), not from
            # the migrations, so a role missing here fails only under test.
            "role IN ('admin', 'founder', 'customer', 'investor', 'guest')",
            name="users_role_check",
        ),
        Index("users_role_idx", "role"),
    )
