"""Origin-header check on state-changing portal/auth requests.

Layered on top of `SameSite=Lax` cookies: SameSite blocks most cross-site
form posts, the Origin check is a belt to that suspenders. JSON-only API,
no double-submit token needed.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import get_settings


GUARDED_PREFIXES: tuple[str, ...] = ("/api/auth/", "/api/portal/")


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and any(
            request.url.path.startswith(p) for p in GUARDED_PREFIXES
        ):
            allowed = set(get_settings().cors_origins)
            origin = request.headers.get("origin")
            if origin is None or origin not in allowed:
                return JSONResponse(
                    status_code=403,
                    content={"ok": False, "error": "Forbidden."},
                )
        return await call_next(request)
