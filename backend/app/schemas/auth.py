"""Pydantic v2 request / response models for /api/auth."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def _normalise(cls, v: str) -> str:
        if not isinstance(v, str):
            return v
        return v.strip().lower()


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    ok: bool = True
    user: UserOut
