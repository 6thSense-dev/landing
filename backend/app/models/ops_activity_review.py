"""Append-only human declarations; no QC, approval or payment side effects."""
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.lead import Base

class ActivityReview(Base):
    __tablename__ = 'ops_activity_reviews'
    __table_args__ = (UniqueConstraint('run_id', 'task_id', 'revision', name='uq_activity_review_revision'),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), ForeignKey('ops_clean_runs.run_id'), nullable=False)
    task_id: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    criteria_version: Mapped[str] = mapped_column(String(80), nullable=False)
    criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
    intervals_json: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), nullable=False)
    reviewer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False)
    criteria_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

class ActivityCriteria(Base):
    __tablename__ = 'ops_activity_criteria'
    task_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(80), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
