"""GET /api/catalog/** — the buyer-facing data catalog, behind the portal cookie.

    GET /api/catalog                  the collection manifest, role-redacted
    GET /api/catalog/clips/{clip_id}  one full clip record, role-redacted
    GET /api/catalog/health           can we reach the bundle and parse it
    GET /api/catalog/local/{path}     dev only: the local driver's byte stream

All four require an authenticated session. Every role in
`catalog_redact.CATALOG_ROLES` may read the catalog; what they get back differs,
and the difference is applied to the DOCUMENT, server-side, before it is
serialised. There is no button to hide and no client-side branch to get wrong.

URL CONTRACT (what the frontend must know)
    The bundle stores every asset URL RELATIVE to the catalog root. This API
    resolves them, so **every URL in a response is absolute and final** — pass
    it to <img>/<video>/fetch untouched, and never join it onto a base. In S3
    mode that is a presigned bucket URL; in local mode it is an HMAC-signed URL
    on this API. Both stop working at the top-level `expires_at`, which is why
    it is returned; `access` says, in the data, what was withheld and how to
    ask for it.

`detail` is absolute too, but it is NOT presigned: it points back at this API,
because a clip record has to come back through here to be redacted. A presigned
URL straight to `clips/{id}.json` would hand a preview account the raw record.

Every failure — missing file, unknown clip, a role denial on the dev driver —
returns the same 404 body. A credential we hand to prospects must not double as
an existence oracle.
"""

from __future__ import annotations

import logging
import mimetypes
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.core.auth_deps import current_user
from app.core.catalog_redact import (
    CATALOG_ROLES,
    STAFF_ROLES,
    access_level,
    open_clip_id,
    present_clip,
    present_manifest,
)
from app.core.catalog_store import (
    CLIP_ID_RE,
    CatalogObjectMissing,
    CatalogStore,
    CatalogUnavailable,
    LocalCatalogStore,
    UnsafeAssetPath,
    get_store,
)
from app.models import User

router = APIRouter(prefix="/api/catalog", tags=["catalog"])
logger = logging.getLogger(__name__)

GET_HEAD = ["GET", "HEAD"]


# --- Auth ---------------------------------------------------------------------

async def catalog_reader(user: User = Depends(current_user)) -> User:
    """Authenticated, and allowed to read the catalog at all.

    A local multi-role dependency rather than `require_role`, which is
    single-role today. If `require_role` gains a multi-role form, this collapses
    into `Depends(require_role(*CATALOG_ROLES))` and nothing else changes.
    """
    if user.role not in CATALOG_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")
    return user


def _log(event: str, request: Request, user: User, **fields: Any) -> None:
    """One structured line per catalog read.

    `guest` is a SHARED credential, so user_id cannot tell two prospects apart;
    the session id can. Never log `email` — logging.PIIFilter strips that key,
    and a silently dropped field is worse than one never sent.
    """
    logger.info(
        event,
        extra={
            "user_id": int(user.id),
            "user_role": user.role,
            "session_id": getattr(request.state, "session_id", None),
            **fields,
        },
    )


# --- Failure modes -------------------------------------------------------------

def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Catalog is temporarily unavailable.",
    )


async def _guarded(build: Callable[[], Any]) -> Any:
    """Run a blocking store call off the event loop and map its failures.

    boto3 is synchronous, and presigning a whole document is CPU work. Both go
    to the threadpool. Nothing about the real failure reaches the client: the
    bucket name, the AWS error code and the offending path stay in our logs.
    """
    try:
        return await run_in_threadpool(build)
    except CatalogObjectMissing:
        raise _not_found()
    except UnsafeAssetPath as exc:
        logger.error("catalog_unsafe_asset_path", extra={"catalog_reason": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Catalog document is malformed.",
        )
    except CatalogUnavailable as exc:
        logger.error("catalog_unavailable", extra={"catalog_reason": str(exc)})
        raise _unavailable()


# --- Shared plumbing ------------------------------------------------------------

def _expires_at(ttl: int) -> str:
    when = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=ttl)
    return when.isoformat().replace("+00:00", "Z")


def detail_url_for(origin: str) -> Callable[[str], str]:
    return lambda clip_id: f"{origin}/api/catalog/clips/{clip_id}"


def request_origin(request: Request) -> str:
    """`scheme://host[:port]` as the CLIENT sees us, with no trailing slash.

    Used to make our own URLs absolute. uvicorn is started without
    --proxy-headers, so behind Railway's TLS terminator `request.base_url` would
    claim http; X-Forwarded-Proto is the only thing that knows better. Trusting
    it can at worst upgrade a self-referential link to https.
    """
    base = str(request.base_url).rstrip("/")
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if forwarded == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    return base


def _signer(store: CatalogStore, ttl: int, origin: str) -> Callable[[str], str]:
    return lambda relative: store.sign(relative, ttl, origin)


def _published_ids(manifest: dict) -> set[str]:
    """Clip ids present in the manifest.

    A take that failed QA and was left in the bucket is unreachable even by
    direct URL: if its id is not in catalog.json, it does not exist.
    """
    clips = manifest.get("clips")
    if not isinstance(clips, list):
        return set()
    return {c["id"] for c in clips if isinstance(c, dict) and isinstance(c.get("id"), str)}


def _json(doc: dict) -> JSONResponse:
    return JSONResponse(
        content=doc,
        headers={
            # These documents are role-redacted and carry expiring signatures.
            # A shared cache holding one would be both a leak and a bug.
            "Cache-Control": "private, no-store",
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- Routes ---------------------------------------------------------------------

@router.get("/health")
async def catalog_health(user: User = Depends(catalog_reader)) -> Response:
    """Can we reach the bundle and parse the manifest?

    Authenticated like everything else. Operational detail — bucket, prefix,
    cache counters — is added only for staff; a prospect gets liveness and
    nothing that names our infrastructure.
    """
    def build() -> dict:
        store = get_store()
        info = store.probe()
        info["fetches"] = store.fetch_count
        info["bucket"] = store.settings.bucket
        info["prefix"] = store.settings.prefix
        info["region"] = store.settings.region
        return info

    try:
        info = await run_in_threadpool(build)
    except (CatalogUnavailable, UnsafeAssetPath, CatalogObjectMissing) as exc:
        logger.error("catalog_health_failed", extra={"catalog_reason": str(exc)})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ok": False, "detail": "Catalog is temporarily unavailable."},
        )

    body = {
        "ok": True,
        "source": info["source"],
        "clips": info["clips"],
        "generated_utc": info["generated_utc"],
    }
    if user.role in STAFF_ROLES:
        body |= {
            "bucket": info["bucket"],
            "prefix": info["prefix"],
            "region": info["region"],
            "backend_fetches": info["fetches"],
        }
    return JSONResponse(content=body, headers={"Cache-Control": "private, no-store"})


@router.get("")
@router.get("/")
async def get_manifest(
    request: Request,
    user: User = Depends(catalog_reader),
) -> Response:
    """The collection manifest, redacted for the caller and fully resolved."""
    level = access_level(user.role)
    origin = request_origin(request)

    def build() -> dict:
        store = get_store()
        ttl = store.settings.presign_ttl
        return present_manifest(
            store.manifest(),
            level=level,
            signer=_signer(store, ttl, origin),
            detail_url=detail_url_for(origin),
            expires_at=_expires_at(ttl),
        )

    doc = await _guarded(build)
    _log("catalog_manifest_served", request, user, access_level=level)
    return _json(doc)


@router.get("/clips/{clip_id}")
async def get_clip(
    clip_id: str,
    request: Request,
    user: User = Depends(catalog_reader),
) -> Response:
    """One clip's full record. `.json` is accepted so the UI can be literal."""
    if clip_id.endswith(".json"):
        clip_id = clip_id[: -len(".json")]
    if not CLIP_ID_RE.match(clip_id):
        raise _not_found()
    level = access_level(user.role)
    origin = request_origin(request)

    def build() -> dict:
        store = get_store()
        manifest = store.manifest()
        if clip_id not in _published_ids(manifest):
            raise CatalogObjectMissing(clip_id)
        collection = manifest.get("collection")
        paths = collection.get("paths") if isinstance(collection, dict) else None
        ttl = store.settings.presign_ttl
        return present_clip(
            store.clip(clip_id),
            level=level,
            signer=_signer(store, ttl, origin),
            detail_url=detail_url_for(origin),
            expires_at=_expires_at(ttl),
            templates=paths if isinstance(paths, dict) else {},
            # The manifest names the open evaluation clip; present_clip re-derives the
            # rights test from the record before it exempts anything. Read from the
            # manifest rather than from the clip so a clip record that names ITSELF
            # cannot open itself.
            open_id=open_clip_id(manifest),
        )

    doc = await _guarded(build)
    _log("catalog_clip_viewed", request, user, clip_id=clip_id, access_level=level)
    return _json(doc)


# --- Local driver: byte streaming -------------------------------------------------
#
# Only reachable with CATALOG_SOURCE=local, i.e. never in production. The URL
# carries its own HMAC and expiry, minted by LocalCatalogStore.sign() only for
# assets that survived redaction for the account that asked, so possession of
# the URL is the authorisation — exactly as it is for a presigned S3 URL. There
# is deliberately no session check: an <img> or <video> in the Vite dev server
# is a cross-origin subresource and does not send the sid cookie, so a
# cookie-gated route would 401 every poster in development while the production
# path (S3, no cookie either) worked fine. An unsigned, tampered or expired path
# is a 404 no matter who asks.

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 64 * 1024

_MIME_OVERRIDES = {
    ".f32": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".md": "text/markdown; charset=utf-8",
    ".webm": "video/webm",
    ".webp": "image/webp",
}


class _Unsatisfiable(Exception):
    """A syntactically valid range that lies outside the file -> 416."""


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Single `Range` header -> inclusive (start, end), or None for "whole file".

    None is spec-legal both for a malformed header and for a multi-range request
    we decline to implement (RFC 9110 s14.2). A valid-but-outside range must be
    416, not 200, hence the exception.
    """
    if not header:
        return None
    match = _RANGE_RE.match(header.strip())
    if match is None:
        return None
    first, last = match.group(1), match.group(2)
    if first == "" and last == "":
        return None
    if first == "":
        length = int(last)
        if length == 0 or size == 0:
            raise _Unsatisfiable
        return max(0, size - length), size - 1
    start = int(first)
    if start >= size:
        raise _Unsatisfiable
    end = size - 1 if last == "" else min(int(last), size - 1)
    if end < start:
        raise _Unsatisfiable
    return start, end


def _chunks(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


@router.api_route("/local/{asset_path:path}", methods=GET_HEAD)
async def get_local_asset(
    asset_path: str,
    request: Request,
    exp: str = Query(default=""),
    sig: str = Query(default=""),
) -> Response:
    """Stream one bundle file, with Range so <video> can seek."""
    try:
        store = get_store()
    except CatalogUnavailable as exc:
        logger.error("catalog_unavailable", extra={"catalog_reason": str(exc)})
        raise _unavailable()
    if not isinstance(store, LocalCatalogStore):
        raise _not_found()

    try:
        expires = int(exp)
    except (TypeError, ValueError):
        raise _not_found()
    if not store.verify(asset_path, expires, sig):
        raise _not_found()

    try:
        path = store.path_for(asset_path)
        stat = path.stat()
    except (UnsafeAssetPath, OSError):
        raise _not_found()
    if not path.is_file():
        raise _not_found()

    size = stat.st_size
    etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
    headers = {
        "ETag": etag,
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=60",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match", "").strip() in {etag, f"W/{etag}", "*"}:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    range_header = request.headers.get("range")
    if_range = request.headers.get("if-range")
    if if_range and if_range.strip() != etag:
        range_header = None
    try:
        span = parse_range(range_header, size)
    except _Unsatisfiable:
        headers["Content-Range"] = f"bytes */{size}"
        # Literal 416: the starlette constant was renamed and requirements only
        # pin fastapi>=0.100, so either name is a version gamble. The number is not.
        return Response(status_code=416, headers=headers)

    if span is None:
        start, end, code, length = 0, max(size - 1, 0), status.HTTP_200_OK, size
    else:
        start, end = span
        code = status.HTTP_206_PARTIAL_CONTENT
        length = end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)
    media_type = media_type_for(path)

    if request.method == "HEAD" or size == 0:
        return Response(status_code=code, headers=headers, media_type=media_type)
    return StreamingResponse(
        _chunks(path, start, end),
        status_code=code,
        headers=headers,
        media_type=media_type,
    )
