"""Pydantic v2 request / response models for /api/leads."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

# Allowed enum-like values. Kept here (not as Pydantic Enums) so the route can
# validate them and return 422 explicitly, rather than the global 400 handler.
VALID_KINDS: frozenset[str] = frozenset({"preorder", "waitlist", "contact"})
VALID_PRODUCTS: frozenset[str] = frozenset({"hand", "nerve", "skin"})
# Kinds that require a non-empty free-text message.
KINDS_REQUIRING_MESSAGE: frozenset[str] = frozenset({"contact"})


def _stripped(value: str) -> str:
    if not isinstance(value, str):
        return value
    return value.strip()


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr = Field(max_length=320)
    organization: str = Field(min_length=1, max_length=200)
    # kind / product are validated in the route (unknown -> 422), so they are
    # plain strings here. `kind` defaults to "waitlist" so the original bare
    # {name,email,organization} payload still validates (contact would demand a
    # message); callers send an explicit kind for preorder/contact.
    kind: str = Field(default="waitlist", max_length=20)
    product: str | None = Field(default=None, max_length=20)
    message: str | None = Field(default=None, max_length=5000)
    # Honeypot: a field no real user sees or fills. When present/non-empty the
    # request is silently dropped (200, no write, no Slack).
    website: str | None = Field(default=None, max_length=500)

    @field_validator("name", "organization", mode="before")
    @classmethod
    def _trim(cls, v: str) -> str:
        return _stripped(v)

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, v: str) -> str:
        if not isinstance(v, str):
            return v
        return v.strip().lower()

    @field_validator("kind", mode="before")
    @classmethod
    def _normalise_kind(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        return v.strip().lower()

    @field_validator("product", mode="before")
    @classmethod
    def _normalise_product(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip().lower()
            if v == "":
                return None
        return v

    @field_validator("message", mode="before")
    @classmethod
    def _blank_message_to_none(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
        return v


class LeadResponse(BaseModel):
    ok: bool = True
    created: bool
