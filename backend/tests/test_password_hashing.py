"""argon2id round-trip + dummy-hash timing helper."""

from __future__ import annotations

import pytest

from app.core.passwords import (
    DUMMY_HASH,
    hash_password,
    verify_password,
)


def test_hash_then_verify_passes():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_wrong_password_fails():
    h = hash_password("correct horse battery staple")
    assert verify_password("wrong password", h) is False


def test_hash_uses_argon2id_prefix():
    h = hash_password("a-12-char-pw")
    assert h.startswith("$argon2id$")


def test_two_hashes_of_same_password_differ():
    a = hash_password("repeat me please")
    b = hash_password("repeat me please")
    assert a != b  # salt differs


def test_dummy_hash_verifies_against_dummy_password_to_keep_timing_constant():
    assert verify_password("anything-12chars", DUMMY_HASH) is False
