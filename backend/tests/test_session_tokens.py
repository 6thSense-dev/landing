"""Raw session token + sha256 storage hash."""

from __future__ import annotations

from app.core.sessions import hash_session_token, mint_session_token


def test_mint_returns_unique_urlsafe_token():
    a = mint_session_token()
    b = mint_session_token()
    assert a != b
    # token_urlsafe(32) -> 43-char base64url string, padding stripped.
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_hash_is_deterministic_hex_sha256():
    h1 = hash_session_token("abc")
    h2 = hash_session_token("abc")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex
    assert all(c in "0123456789abcdef" for c in h1)


def test_different_tokens_hash_differently():
    assert hash_session_token("abc") != hash_session_token("abd")
