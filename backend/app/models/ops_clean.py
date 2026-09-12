"""Versioned clean collections and explicit camera-to-person assignments."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.lead import Base


class OpsCamera(Base):
    __tablename__ = 'ops_cameras'
    device_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    wearer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('ops_wearers.id'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CleanRun(Base):
    __tablename__ = 'ops_clean_runs'
    run_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(32), nullable=False)
    wearer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('ops_wearers.id'))
    manifest_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_version: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    retained_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    rejected_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    rate_krw_hour: Mapped[int | None] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount_krw: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
