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
        upload_manifest = request.url.path.startswith('/api/uploads/')
        form_contract = request.url.path.startswith('/api/form-contracts/')
        bank_details = request.url.path.startswith('/api/contributor/bank')
        max_bytes = 1024 * 1024 if upload_manifest else 8192 if form_contract or bank_details else self.max_bytes
        if request.url.path in GUARDED_PATHS or upload_manifest or form_contract or bank_details:
            cl = request.headers.get("content-length")
            if cl is not None:
                try:
                    if int(cl) < 0 or int(cl) > max_bytes:
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
                    if len(body) > max_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={"ok": False, "error": "Request too large."},
                        )

                # BaseHTTPMiddleware's cached request replays _body downstream.
                # Replacing _receive alone loses an already-consumed stream.
                request._body = body
        return await call_next(request)


class PrivateBankResponseMiddleware:
    """Prevent caching of banking responses, including authentication failures."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/contributor/bank"):
            return await self.app(scope, receive, send)

        async def private_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                message["headers"].append((b"cache-control", b"private, no-store"))
            await send(message)

        await self.app(scope, receive, private_send)


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
