"""Mobile identities are separate from staff users. No camera or bank claim grants authority."""
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.lead import Base

class ContributorAccount(Base):
    __tablename__ = "contributor_accounts"
    subject: Mapped[str] = mapped_column(String(64), primary_key=True)
    wearer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ops_wearers.id"), unique=True)
    routing_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ContributorConsent(Base):
    __tablename__ = "contributor_consents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject: Mapped[str] = mapped_column(ForeignKey("contributor_accounts.subject"), index=True)
    snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ContributorCameraClaim(Base):
    __tablename__ = "contributor_camera_claims"
    __table_args__ = (Index("contributor_camera_active_unique", "device_id", unique=True, postgresql_where=text("status = 'approved' AND ended_at IS NULL")),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject: Mapped[str] = mapped_column(ForeignKey("contributor_accounts.subject"), index=True)
    device_id: Mapped[str] = mapped_column(String(6), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    operator: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ContributorRecipientAttempt(Base):
    __tablename__ = "contributor_recipient_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject: Mapped[str] = mapped_column(ForeignKey("contributor_accounts.subject"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="submitting")
    recipient_id: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
