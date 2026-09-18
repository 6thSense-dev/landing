"""Minimal mirror of signed Google Form records; Google retains source evidence."""
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.lead import Base


class FormContract(Base):
    __tablename__ = 'contributor_form_contracts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    response_id: Mapped[str] = mapped_column(String(512), unique=True)
    form_id: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(80))
    terms_sha256: Mapped[str] = mapped_column(String(64))
    receipt_sha256: Mapped[str] = mapped_column(String(64))
    phone_digest: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subject: Mapped[str | None] = mapped_column(ForeignKey('contributor_accounts.subject'), index=True)
    wearer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('ops_wearers.id'))
    state: Mapped[str] = mapped_column(String(24), default='signed')
    source_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
