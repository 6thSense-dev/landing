"""Pydantic v2 models for the admin leads CRM (/api/admin/leads)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _stripped(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class AdminLeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    organization: str
    message: str
    followed_up: bool
    followed_up_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadStats(BaseModel):
    total: int
    followed_up: int
    pending: int


class AdminLeadsResponse(BaseModel):
    ok: bool = True
    leads: list[AdminLeadOut]
    stats: LeadStats


class AdminLeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr = Field(max_length=320)
    organization: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    followed_up: bool = False

    @field_validator("name", "organization", "message", mode="before")
    @classmethod
    def _trim(cls, v: object) -> object:
        return _stripped(v)

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v


class AdminLeadUpdate(BaseModel):
    """Partial update — every field optional. Omitted fields are left as-is."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = Field(default=None, max_length=320)
    organization: str | None = Field(default=None, min_length=1, max_length=200)
    message: str | None = Field(default=None, min_length=1, max_length=5000)
    followed_up: bool | None = None

    @field_validator("name", "organization", "message", mode="before")
    @classmethod
    def _trim(cls, v: object) -> object:
        return _stripped(v)

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v
