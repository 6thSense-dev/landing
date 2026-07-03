"""SQLAlchemy ORM model for the `leads` table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Uniqueness is on (email, kind) — see Index below — not on email alone,
    # so one person can hold one row per kind (e.g. a preorder AND a contact).
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    organization: Mapped[str] = mapped_column(String(200), nullable=False)
    # kind: preorder | waitlist | contact
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # product: hand | nerve | skin | NULL (NULL for a general contact)
    product: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # message: optional free-text; required for contact (enforced at the API)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
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
            "leads_email_kind_key",
            "email",
            "kind",
            unique=True,
        ),
        Index(
            "leads_created_at_idx",
            "created_at",
            postgresql_using="btree",
            postgresql_ops={"created_at": "DESC"},
        ),
        CheckConstraint(
            "kind IN ('preorder', 'waitlist', 'contact')",
            name="leads_kind_check",
        ),
        CheckConstraint(
            "product IS NULL OR product IN ('hand', 'nerve', 'skin')",
            name="leads_product_check",
        ),
    )
