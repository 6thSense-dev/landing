"""SQLAlchemy ORM model for the `leads` table.

One table, one purpose: the site's single Contact Us form (bottom of the home
page). Each submission is a contactor's details plus the message they want to
send. Uniqueness is on `email` — a repeat submission from the same address
upserts the existing row rather than creating a duplicate.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # One row per email; a repeat submission upserts (see the /api/leads route).
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    organization: Mapped[str] = mapped_column(String(200), nullable=False)
    # The free-text body of the enquiry. Required — this is a contact form.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Admin follow-up tracking (set from the leads CRM, not the public form).
    followed_up: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    followed_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "leads_created_at_idx",
            "created_at",
            postgresql_using="btree",
            postgresql_ops={"created_at": "DESC"},
        ),
        # Speeds up the CRM's "pending follow-up" filter.
        Index("leads_followed_up_idx", "followed_up"),
    )
