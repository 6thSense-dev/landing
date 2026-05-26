"""Argon2id password hashing + a fixed dummy hash for timing safety."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError


# Library defaults: time_cost=3, memory_cost=64 MiB, parallelism=4.
_hasher = PasswordHasher()

# Pre-computed hash of a random throwaway password. Used by
# `verify_password(submitted, DUMMY_HASH)` on the "no such user" path so
# that login response time doesn't leak whether an email exists.
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c80VouoHjKLDUmC+uWOHog$5QWdf2eecEIKYzeiCyenZZPC5Zbny4FuklwmVaL4Hx4"


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, encoded: str) -> bool:
    try:
        return _hasher.verify(encoded, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
