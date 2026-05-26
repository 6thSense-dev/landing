"""Body-size cap middleware + trusted-IP helper."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


MAX_BODY_BYTES = 4096
GUARDED_PATHS = ("/api/leads", "/api/auth/login", "/api/auth/logout")


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies on guarded routes before parsing."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        if request.url.path in GUARDED_PATHS:
            cl = request.headers.get("content-length")
            if cl is not None:
                try:
                    if int(cl) > self.max_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={"ok": False, "error": "Request too large."},
                        )
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={"ok": False, "error": "Invalid Content-Length."},
                    )
            else:
                # No content-length (chunked) — buffer and abort on overflow.
                body = b""
                async for chunk in request.stream():
                    body += chunk
                    if len(body) > self.max_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={"ok": False, "error": "Request too large."},
                        )

                async def _replay():
                    yield {"type": "http.request", "body": body, "more_body": False}

                request._receive = _replay().__anext__  # type: ignore[attr-defined]
        return await call_next(request)


def get_client_ip(request: Request) -> str:
    """Return the client IP appended by Railway's edge proxy.

    Railway terminates TLS at its edge and appends the real client IP as the
    right-most entry of `X-Forwarded-For`. Anything to the left of that entry
    is whatever the client supplied (including spoofed values) — we ignore it.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
