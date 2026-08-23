"""Pydantic v2 request / response models for /api/auth."""

from __future__ import annotations

import re
from typing import Any

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)


#: Longest identifier we will look at. Matches `users.email VARCHAR(320)`.
MAX_IDENTIFIER_LEN = 320

#: A bare (non-email) login identifier. Lowercase only (the value is
#: lowercased before this is applied), must start with a letter or digit, then
#: 1-63 more of [a-z0-9._-] -- so 2-64 characters in total.
#:
#: Deliberately narrow. The only bare identifier that resolves to an account
#: today is the reserved `guest` username (see
#: app.api.routes.auth.RESERVED_USERNAMES); the pattern exists so that a
#: hostile string ("../etc", "a@b@c", a 400-byte blob) is rejected with a 422
#: before it ever reaches a lookup, rather than being carried into the route.
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

#: Used to hold an identifier that *looks* like an email to exactly the same
#: standard as the `email` field. We do NOT weaken email validation to let a
#: username through: "@" in the identifier means it must be a real address.
_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def normalise_identifier(value: Any) -> str:
    """Trim + lowercase a submitted identifier; non-strings become ``""``.

    Shared with app.api.routes.auth so the rate-limiter's view of "which
    account is this login for?" cannot drift from the validated one.
    """
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


class LoginRequest(BaseModel):
    """A login attempt, keyed by an identifier that is an email OR a username.

    The wire accepts either key, and they mean the same thing:

        {"identifier": "...", "password": "..."}   preferred
        {"email": "...",      "password": "..."}   historical, still supported

    `identifier` is always populated after validation and is what the route
    resolves. `email` is kept as a strict `EmailStr` so that every existing
    caller -- and every real user -- gets exactly the validation it got
    before: sending `{"email": "not-an-email"}` is still a 422, not a 401.

    A username is only useful because of one reserved alias (`guest`). If a
    second one ever appears, the right move is a real `users.username` column
    with a unique index, not a bigger constant -- see
    app.api.routes.auth.RESERVED_USERNAMES.
    """

    identifier: str | None = Field(default=None, max_length=MAX_IDENTIFIER_LEN)
    email: EmailStr | None = Field(default=None, max_length=MAX_IDENTIFIER_LEN)
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def _accept_identifier_or_email(cls, data: Any) -> Any:
        """Reconcile the two spellings into `identifier` before field validation.

        * neither present -> rejected
        * both present and disagreeing -> rejected (we will not guess)
        * `email` present -> mirrored into `identifier`, and left in place so
          it still has to satisfy `EmailStr`
        """
        if not isinstance(data, dict):
            return data
        data = {**data}
        ident = normalise_identifier(data.get("identifier"))
        mail = normalise_identifier(data.get("email"))
        if not ident and not mail:
            raise ValueError("Either 'identifier' or 'email' is required.")
        if ident and mail and ident != mail:
            raise ValueError(
                "'identifier' and 'email' disagree; send only one of them."
            )
        data["identifier"] = ident or mail
        if mail:
            data["email"] = mail
        else:
            # A username-only login has no email to validate. Drop the key
            # rather than leaving a None that EmailStr would have to special-case.
            data.pop("email", None)
        return data

    @field_validator("identifier", mode="after")
    @classmethod
    def _validate_identifier(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if "@" in v:
            # Looks like an address, so it must BE one. Same standard as the
            # `email` field -- no back door for real users.
            try:
                _EMAIL_ADAPTER.validate_python(v)
            except ValidationError:
                raise ValueError("Not a valid email address.") from None
            return v
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Must be an email address, or a username of 2-64 characters "
                "made of letters, digits, '.', '_' or '-' and starting with a "
                "letter or digit."
            )
        return v


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    ok: bool = True
    user: UserOut
