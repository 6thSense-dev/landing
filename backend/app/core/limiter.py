"""Shared slowapi Limiter instance.

Lives in its own module so routes can `@limiter.limit(...)` without
importing `app.main` (which would create a cycle). The actual limit
string is provided at decoration time via a callable so it is
re-evaluated on every request — this lets `SENSEPROBE_RATE_LIMIT`
take effect without restarting the process.
"""

from __future__ import annotations

from slowapi import Limiter

from app.core.config import get_settings
from app.core.middleware import get_client_ip


def current_rate_limit() -> str:
    return get_settings().rate_limit


def current_login_rate_limit() -> str:
    return get_settings().login_rate_limit


limiter = Limiter(key_func=get_client_ip)
