"""Session token mint + DB-storage hashing."""

from __future__ import annotations

import hashlib
import secrets


def mint_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
