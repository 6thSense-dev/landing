"""Environment-based settings (no secrets in repo)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_origins(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    cors_origins: list[str]
    rate_limit: str
    login_rate_limit: str
    cookie_secure: bool


def get_settings() -> Settings:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL is required. Set it to a Postgres connection string "
            "(Railway injects it as ${{Postgres.DATABASE_URL}})."
        )
    raw_origins = os.environ.get(
        "SENSEPROBE_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173",
    )
    return Settings(
        database_url=db_url,
        cors_origins=_parse_origins(raw_origins),
        rate_limit=os.environ.get("SENSEPROBE_RATE_LIMIT", "5/minute"),
        login_rate_limit=os.environ.get("SENSEPROBE_LOGIN_RATE_LIMIT", "10/minute"),
        cookie_secure=_parse_bool(os.environ.get("SENSEPROBE_COOKIE_SECURE"), True),
    )
