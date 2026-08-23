"""Shared slowapi Limiter instance.

Lives in its own module so routes can `@limiter.limit(...)` without
importing `app.main` (which would create a cycle). The actual limit
string is provided at decoration time via a callable so it is
re-evaluated on every request — this lets `SENSEPROBE_RATE_LIMIT`
take effect without restarting the process.

LOGIN THROTTLING, AND WHY IT HAS TWO BUCKETS
    `SENSEPROBE_LOGIN_RATE_LIMIT` (default 10/minute) is per client IP. That
    is the right shape for real accounts — it is what stops Argon2 (64 MiB,
    ~50 ms a call) being used as a CPU amplifier, and it follows a stuffing
    run around. It is the wrong shape for the shared read-only demo account:
    a prospect's whole team sits behind one corporate NAT, so ten people
    trying `guest` in the same minute would lock the room out of a sales demo.

    So a login for the guest account gets its OWN bucket, keyed on
    `guest-login:<ip>` instead of `<ip>`, with its own (higher) limit from
    `SENSEPROBE_GUEST_LOGIN_RATE_LIMIT`. Real accounts keep the strict limit,
    byte for byte, and the two buckets never draw down each other:

      * guest attempts cannot exhaust an office's budget for real logins;
      * an attacker cannot get the loose limit for a real account, because
        the bucket is chosen from the identifier they submitted, and a real
        account's identifier is never the guest one.

    Loosening the guest bucket costs us nothing in brute-force terms: the
    guest password is printed in sales emails, so its entropy is not what is
    protecting anything. What protects us is that the account is read-only
    server-side and revocable in one command (`app.cli seed-guest
    --deactivate`).

    The bucket is chosen by `login_rate_limit_key`, which reads a flag that
    `app.api.routes.auth` sets via `mark_guest_login()` before slowapi runs.
    It has to be a flag rather than a lookup here because slowapi's key
    function is synchronous and cannot await the request body — the route
    owns "which account is this?", this module owns "how fast may it go".
"""

from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter

from app.core.config import get_settings
from app.core.middleware import get_client_ip


#: Env var holding the login limit for the shared guest account.
GUEST_LOGIN_RATE_LIMIT_ENV = "SENSEPROBE_GUEST_LOGIN_RATE_LIMIT"

#: Default guest login limit: 6x the real-account default, per IP.
#: Per-MINUTE on purpose. An hourly window with the same average (e.g.
#: "360/hour") would let one burst strand a NATed office for the rest of the
#: hour; a minute-long window self-heals in a minute, which is the difference
#: between "retry" and "call support" during a live demo.
DEFAULT_GUEST_LOGIN_RATE_LIMIT = "60/minute"

#: Prefix that marks the guest bucket. Also how `current_login_rate_limit`
#: recognises which limit to hand back — slowapi passes it the *key*, which is
#: the only per-request context a limit provider gets.
GUEST_LOGIN_KEY_PREFIX = "guest-login:"

_GUEST_LOGIN_STATE_ATTR = "login_is_guest"


def current_rate_limit() -> str:
    return get_settings().rate_limit


def guest_login_rate_limit() -> str:
    """Login limit for the shared guest account (per IP)."""
    return os.environ.get(GUEST_LOGIN_RATE_LIMIT_ENV) or DEFAULT_GUEST_LOGIN_RATE_LIMIT


def mark_guest_login(request: Request) -> None:
    """Flag this request as a login attempt against the shared guest account.

    Called from the login route's dependency, which runs before slowapi's
    check. Not called => the strict per-IP limit applies, so the safe default
    is the strict one.
    """
    setattr(request.state, _GUEST_LOGIN_STATE_ATTR, True)


def is_guest_login(request: Request) -> bool:
    return bool(getattr(request.state, _GUEST_LOGIN_STATE_ATTR, False))


def login_rate_limit_key(request: Request) -> str:
    """Rate-limit key for POST /api/auth/login.

    Guest logins get a separate, parallel bucket per IP so that guest traffic
    and real-account traffic can never exhaust each other.
    """
    ip = get_client_ip(request)
    if is_guest_login(request):
        return f"{GUEST_LOGIN_KEY_PREFIX}{ip}"
    return ip


def current_login_rate_limit(key: str) -> str:
    """Limit string for POST /api/auth/login.

    slowapi calls a limit provider with the rate-limit `key` when — and only
    when — the provider declares a parameter of that exact name (see
    slowapi.wrappers.LimitGroup.__iter__), so the key doubles as the signal
    for which bucket we are being asked about.
    """
    if key.startswith(GUEST_LOGIN_KEY_PREFIX):
        return guest_login_rate_limit()
    return get_settings().login_rate_limit


limiter = Limiter(key_func=get_client_ip)
