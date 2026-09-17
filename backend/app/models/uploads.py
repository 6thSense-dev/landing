"""Durable upload receipts. Upload identity never grants footage/payment approval."""
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.lead import Base


class UploadBatch(Base):
    __tablename__ = 'upload_batches'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[str] = mapped_column(ForeignKey('contributor_accounts.subject'), nullable=False, index=True)
    wearer_id: Mapped[int] = mapped_column(ForeignKey('ops_wearers.id'), nullable=False)
    recording: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadFile(Base):
    __tablename__ = 'upload_files'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey('upload_batches.id'), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    modified_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    upload_id: Mapped[str | None] = mapped_column(Text)
    version_id: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(String(200))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('batch_id', 'path'),)


class UploadPart(Base):
    __tablename__ = 'upload_parts'
    file_id: Mapped[str] = mapped_column(ForeignKey('upload_files.id'), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    checksum: Mapped[str] = mapped_column(String(44), nullable=False)
    etag: Mapped[str | None] = mapped_column(String(200))
