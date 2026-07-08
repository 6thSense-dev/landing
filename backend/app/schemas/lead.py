"""Pydantic v2 request / response models for /api/leads.

A single Contact Us submission: the contactor's details (name, email,
organization) plus the message they want to send. All are required.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


def _stripped(value: str) -> str:
    if not isinstance(value, str):
        return value
    return value.strip()


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr = Field(max_length=320)
    organization: str = Field(min_length=1, max_length=200)
    # Required free-text body — this is a contact form. Blank after trim -> 422.
    message: str = Field(min_length=1, max_length=5000)
    # Honeypot: a field no real user sees or fills. When present/non-empty the
    # request is silently dropped (200, no write, no Slack).
    website: str | None = Field(default=None, max_length=500)

    @field_validator("name", "organization", "message", mode="before")
    @classmethod
    def _trim(cls, v: str) -> str:
        return _stripped(v)

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, v: str) -> str:
        if not isinstance(v, str):
            return v
        return v.strip().lower()


class LeadResponse(BaseModel):
    ok: bool = True
    created: bool
