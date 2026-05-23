"""Pydantic models for /api/auth."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import LoginRequest, LoginResponse, UserOut


def test_login_request_lowercases_and_trims_email():
    req = LoginRequest(email="  Alex@Example.COM  ", password="12chars!!aaa")
    assert req.email == "alex@example.com"


def test_login_request_rejects_invalid_email():
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="12chars!!aaa")


def test_login_request_rejects_empty_password():
    with pytest.raises(ValidationError):
        LoginRequest(email="a@x.com", password="")


def test_login_request_rejects_too_long_password():
    with pytest.raises(ValidationError):
        LoginRequest(email="a@x.com", password="x" * 129)


def test_user_out_shape():
    u = UserOut(id=1, email="a@x.com", name="A", role="founder")
    assert u.model_dump() == {"id": 1, "email": "a@x.com", "name": "A", "role": "founder"}


def test_login_response_includes_ok_and_user():
    r = LoginResponse(ok=True, user=UserOut(id=1, email="a@x.com", name="A", role="founder"))
    dumped = r.model_dump()
    assert dumped["ok"] is True
    assert dumped["user"]["email"] == "a@x.com"
