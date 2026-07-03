"""Best-effort Slack notification for new leads.

Fired via a FastAPI ``BackgroundTask`` *after* the DB commit so it can never
fail or slow the request. Everything is wrapped in try/except: a missing
webhook, a network error, or a non-2xx response is logged and swallowed.

Uses the stdlib ``urllib`` (no extra dependency). BackgroundTasks run sync
callables in a threadpool, so the blocking call does not stall the event loop.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

SLACK_ENV_VAR = "SLACK_WEBHOOK_URL"
_TIMEOUT_SECONDS = 5


def slack_configured() -> bool:
    return bool(os.environ.get(SLACK_ENV_VAR, "").strip())


def _format_message(
    *,
    kind: str,
    product: str | None,
    name: str,
    organization: str,
    email: str,
    message: str | None,
    is_new: bool,
) -> str:
    verb = "New" if is_new else "Updated"
    scope = f" · {product}" if product else ""
    lines = [
        f"*{verb} lead — {kind}{scope}*",
        f"{name} ({organization}) <{email}>",
    ]
    if message:
        lines.append(f"> {message}")
    return "\n".join(lines)


def notify_new_lead(
    *,
    kind: str,
    product: str | None,
    name: str,
    organization: str,
    email: str,
    message: str | None,
    is_new: bool,
) -> None:
    """Post a lead notification to Slack. Never raises."""
    webhook = os.environ.get(SLACK_ENV_VAR, "").strip()
    if not webhook:
        # Startup already logs loudly when unset; stay quiet per-request.
        return
    try:
        text = _format_message(
            kind=kind,
            product=product,
            name=name,
            organization=organization,
            email=email,
            message=message,
            is_new=is_new,
        )
        body = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", None)
            if status is not None and status >= 300:
                logger.warning("slack_notify_non_2xx", extra={"status": status})
    except Exception as exc:  # noqa: BLE001 — must never break the request
        logger.warning("slack_notify_failed", extra={"error": type(exc).__name__})
