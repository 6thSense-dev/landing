"""Immutable review evidence, contributor payouts, and retryable processing jobs."""

from datetime import datetime
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models.lead import Base


class FootageReview(Base):
    __tablename__ = "ops_footage_reviews"
    run_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("ops_clean_runs.run_id"), primary_key=True
    )
    recording: Mapped[str] = mapped_column(String(200), primary_key=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(320), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    collection_date: Mapped[str | None] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Payout(Base):
    __tablename__ = "ops_payouts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    wearer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ops_wearers.id"), nullable=False
    )
    amount_krw: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="approved")
    approved_by: Mapped[str] = mapped_column(String(320), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recipient_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    wise_profile_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    wise_environment: Mapped[str] = mapped_column(
        String(16), nullable=False, default="sandbox"
    )
    recipient_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    quote_id: Mapped[str | None] = mapped_column(String(100))
    transfer_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_status: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PayoutItem(Base):
    __tablename__ = "ops_payout_items"
    run_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("ops_clean_runs.run_id"), primary_key=True
    )
    recording: Mapped[str] = mapped_column(String(200), primary_key=True)
    payout_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ops_payouts.id"), nullable=False, index=True
    )
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    rate_krw_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    collection_date: Mapped[str] = mapped_column(String(10), nullable=False)


class PayoutRecipient(Base):
    __tablename__ = "ops_payout_recipients"
    wearer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ops_wearers.id"), primary_key=True
    )
    wise_recipient_id: Mapped[str] = mapped_column(String(80), nullable=False)
    recipient_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    wise_profile_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    wise_environment: Mapped[str] = mapped_column(
        String(16), nullable=False, default="sandbox"
    )
    verified_name: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(320), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessingJob(Base):
    __tablename__ = "ops_processing_jobs"
    recording: Mapped[str] = mapped_column(String(200), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_run_id: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
