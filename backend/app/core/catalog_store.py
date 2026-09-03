"""Where the catalog bundle lives, and how a relative path becomes a URL.

Two drivers, one interface.

`S3CatalogStore` is production: a PRIVATE bucket, and the API never proxies
media bytes. It reads the JSON documents itself (so it can redact them) and
hands the browser a short-lived presigned GET URL for every asset, so bytes go
S3 -> browser and Railway stays out of the data path. Presigning is a local
HMAC, not a network call, so signing every URL on every request is cheap.

`LocalCatalogStore` (`CATALOG_SOURCE=local` + `CATALOG_LOCAL_DIR`) is the same
interface over a directory on disk, so the site runs with no AWS at all. Its
URLs point back at `{origin}/api/catalog/local/...` and carry an HMAC + expiry
of their own, so a dev URL is exactly as unguessable, as short-lived and as
self-authorising as a presigned one. That symmetry is deliberate: the role gate
is the redaction pass, so possession of the URL IS the authorisation in both
drivers — and it is what lets an <img> or <video> in the Vite dev server load a
cross-origin asset, which a cookie-gated route could not do.

Cached: the PARSED documents, with a TTL plus ETag revalidation, behind a
per-key lock so a burst of page loads costs one GetObject and not a herd.
Never cached: signed URLs — they expire, and a cached one is born half-dead.

`resolve_key` is the only place a manifest string becomes an object key, and it
is an allow-list: each segment must match [A-Za-z0-9._-]+ and must not be `.`,
`..` or start with a dot. One rule rejects absolute paths, schemes,
backslashes, `//host`, whitespace, NUL and every percent-encoded traversal,
because `%`, `:`, `\\` and whitespace are simply not in the alphabet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import (
    CATALOG_SOURCE_LOCAL,
    CatalogSettings,
    get_catalog_settings,
)

logger = logging.getLogger(__name__)


# --- Errors ------------------------------------------------------------------

class CatalogUnavailable(RuntimeError):
    """Bundle unreachable or unparseable -> generic 503.

    The message is for our logs only: it may name the bucket, and the HTTP
    layer must never pass it to the client.
    """


class CatalogObjectMissing(LookupError):
    """A specific object is not there. Surfaces as 404."""


class UnsafeAssetPath(ValueError):
    """A manifest asked us to sign something outside the prefix.

    A corrupt or hostile BUNDLE, not a bad request: hard 500 with a logged
    error. Signing it would turn the catalog into a read primitive for the
    whole bucket.
    """


# --- Key resolution ----------------------------------------------------------

#: ClipId per the data contract: lower-kebab over [a-z0-9].
CLIP_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
#: One path segment. Allow-list; see the module docstring.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")

#: AssetUrl maxLength in the schema; S3 keys top out at 1024 bytes.
MAX_RELATIVE_LEN, MAX_KEY_LEN, MAX_SEGMENTS = 512, 1024, 32


def resolve_key(relative: str, prefix: str = "") -> str:
    """Bundle-relative path -> object key, or raise `UnsafeAssetPath`.

    `prefix` is ours, but is still checked: a typo like
    `CATALOG_S3_PREFIX=../` must fail loudly rather than escape.
    """
    if not isinstance(relative, str):
        raise UnsafeAssetPath(f"asset url is {type(relative).__name__}, not str")
    if not relative or len(relative) > MAX_RELATIVE_LEN:
        raise UnsafeAssetPath("asset url is empty or too long")
    if relative != relative.strip():
        raise UnsafeAssetPath("asset url has leading/trailing whitespace")

    segments = relative.split("/")
    if len(segments) > MAX_SEGMENTS:
        raise UnsafeAssetPath("asset url has too many segments")
    for segment in segments:
        # An empty segment means a leading '/', a trailing '/', or '//host'.
        if not segment:
            raise UnsafeAssetPath("asset url has an empty path segment")
        if segment in {".", ".."} or segment.startswith("."):
            raise UnsafeAssetPath("asset url has a dot segment")
        if not _SEGMENT_RE.match(segment):
            raise UnsafeAssetPath("asset url has a disallowed character")

    key = f"{prefix}{relative}"
    if len(key) > MAX_KEY_LEN:
        raise UnsafeAssetPath("object key is too long")
    # Belt and braces: neither the prefix nor the path may reintroduce traversal.
    if ".." in key.split("/") or not key.startswith(prefix):
        raise UnsafeAssetPath("object key escapes the configured prefix")
    return key


def clip_key(clip_id: str, prefix: str = "") -> str:
    """Object key of one clip's detail record. Raises on a bad id."""
    if not isinstance(clip_id, str) or not CLIP_ID_RE.match(clip_id):
        raise UnsafeAssetPath("clip id is not a ClipId")
    return resolve_key(f"clips/{clip_id}.json", prefix)


# --- Parsed-document cache ---------------------------------------------------

@dataclass
class _Entry:
    doc: Any
    etag: str | None
    fetched_at: float


class _DocCache:
    """TTL + ETag cache, one lock per key (single flight, no herd).

    The corpus is ~30 clips; MAX_ENTRIES only stops a hostile id stream from
    growing the cache without bound.
    """

    MAX_ENTRIES = 256

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def peek(self, key: str) -> _Entry | None:
        with self._guard:
            return self._entries.get(key)

    def fresh(self, key: str, ttl: float) -> _Entry | None:
        entry = self.peek(key)
        if entry is None:
            return None
        return entry if (time.monotonic() - entry.fetched_at) < ttl else None

    def put(self, key: str, entry: _Entry) -> None:
        with self._guard:
            if len(self._entries) >= self.MAX_ENTRIES and key not in self._entries:
                oldest = min(self._entries, key=lambda k: self._entries[k].fetched_at)
                self._entries.pop(oldest, None)
                self._locks.pop(oldest, None)
            self._entries[key] = entry

    def touch(self, key: str) -> None:
        with self._guard:
            entry = self._entries.get(key)
            if entry is not None:
                entry.fetched_at = time.monotonic()

    def clear(self) -> None:
        with self._guard:
            self._entries.clear()
            self._locks.clear()


_NOT_MODIFIED = object()


# --- Base store --------------------------------------------------------------

class CatalogStore:
    """Common caching + document access. Drivers implement the two hooks."""

    def __init__(self, settings: CatalogSettings) -> None:
        self.settings = settings
        self._cache = _DocCache()
        #: Real backend reads (GetObject / open()): the cache-hit signal that
        #: tests assert on and that health reports.
        self.fetch_count = 0

    # -- driver hooks ------------------------------------------------------- #

    @property
    def key_prefix(self) -> str:
        raise NotImplementedError

    def _fetch(self, key: str, etag: str | None) -> tuple[Any, str | None]:
        raise NotImplementedError

    def sign(self, relative: str, ttl: int, origin: str = "") -> str:
        """Bundle-relative path -> an absolute, short-lived, fetchable URL.

        `origin` is prefixed by a driver that serves its own bytes; S3 ignores
        it, because a presigned URL already names the bucket host.
        """
        raise NotImplementedError

    # -- documents ---------------------------------------------------------- #

    def _load(self, key: str) -> Any:
        ttl = self.settings.manifest_ttl
        hit = self._cache.fresh(key, ttl)
        if hit is not None:
            return hit.doc
        # Single flight: all who missed queue here; all but the first find a
        # fresh entry on the re-check below.
        with self._cache.lock_for(key):
            hit = self._cache.fresh(key, ttl)
            if hit is not None:
                return hit.doc
            stale = self._cache.peek(key)
            doc, etag = self._fetch(key, stale.etag if stale else None)
            if doc is _NOT_MODIFIED:
                self._cache.touch(key)
                return stale.doc  # type: ignore[union-attr]
            self._cache.put(key, _Entry(doc, etag, time.monotonic()))
            return doc

    def manifest(self) -> dict:
        key = resolve_key(self.settings.manifest_key, self.key_prefix)
        try:
            doc = self._load(key)
        except CatalogObjectMissing as exc:
            raise CatalogUnavailable(f"manifest {key} is missing") from exc
        if not isinstance(doc, dict):
            raise CatalogUnavailable(f"manifest {key} is not a JSON object")
        return doc

    def clip(self, clip_id: str) -> dict:
        """One clip record. Raises CatalogObjectMissing for an unknown id."""
        key = clip_key(clip_id, self.key_prefix)
        doc = self._load(key)
        if not isinstance(doc, dict):
            raise CatalogUnavailable(f"clip document {key} is not a JSON object")
        return doc

    def probe(self) -> dict[str, Any]:
        """Can we reach the bundle and parse the manifest? Raises if not."""
        doc = self.manifest()
        clips = doc.get("clips")
        return {
            "source": self.settings.source,
            "clips": len(clips) if isinstance(clips, list) else 0,
            "generated_utc": doc.get("generated_utc"),
            "package_tier_ok": True,
        }

    def invalidate(self) -> None:
        self._cache.clear()


# --- S3 driver ---------------------------------------------------------------

class S3CatalogStore(CatalogStore):
    def __init__(self, settings: CatalogSettings) -> None:
        super().__init__(settings)
        self._client_obj = None
        self._client_lock = threading.Lock()

    @property
    def key_prefix(self) -> str:
        return self.settings.prefix

    def _client(self):
        if self._client_obj is not None:
            return self._client_obj
        with self._client_lock:
            if self._client_obj is None:
                self._client_obj = self._build_client()
        return self._client_obj

    def _build_client(self):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - packaging error
            raise CatalogUnavailable("boto3 is not installed") from exc

        cfg = self.settings
        if cfg.credentials_half_configured:
            # The default chain here would sign catalog URLs with whatever AWS_*
            # key is lying around — including the firmware key. Refuse instead.
            raise CatalogUnavailable(
                "exactly one of CATALOG_AWS_ACCESS_KEY_ID / "
                "CATALOG_AWS_SECRET_ACCESS_KEY is set; refusing to fall back "
                "to the ambient AWS credential chain"
            )
        if cfg.has_static_credentials:
            session = boto3.session.Session(
                aws_access_key_id=cfg.access_key_id,
                aws_secret_access_key=cfg.secret_access_key,
                aws_session_token=cfg.session_token,
                region_name=cfg.region,
            )
        else:
            session = boto3.session.Session(region_name=cfg.region)
            creds = session.get_credentials()
            logger.warning(
                "catalog_default_credential_chain",
                extra={
                    "catalog_bucket": cfg.bucket,
                    "credential_method": getattr(creds, "method", None),
                },
            )
        return session.client(
            "s3",
            endpoint_url=cfg.endpoint_url,
            config=Config(
                signature_version="s3v4",
                # Force the REGIONAL virtual-hosted endpoint into the signature.
                # Without this, botocore signs presigned URLs against the global
                # host `<bucket>.s3.amazonaws.com` even when the client's own
                # endpoint is regional. S3 answers that with a 307 to
                # `<bucket>.s3-<region>.amazonaws.com` -- and because SigV4 binds
                # the signature to the Host header, the redirected request fails
                # the signature check and every piece of media 403s. Measured
                # against the real bucket: global host -> 403, virtual -> 200.
                # Keep every catalog/package bucket's regional host in the
                # Caddyfile CSP allowlist before switching storage tiers.
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=3,
                read_timeout=10,
            ),
        )

    def _fetch(self, key: str, etag: str | None) -> tuple[Any, str | None]:
        from botocore.exceptions import BotoCoreError, ClientError

        params: dict[str, Any] = {"Bucket": self.settings.bucket, "Key": key}
        if etag:
            params["IfNoneMatch"] = etag
        self.fetch_count += 1
        try:
            obj = self._client().get_object(**params)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            http = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code == "304" or http == 304:
                return _NOT_MODIFIED, etag
            if code in {"NoSuchKey", "404", "NotFound"} or http == 404:
                raise CatalogObjectMissing(key) from exc
            raise CatalogUnavailable(f"s3 get_object {key}: {code}") from exc
        except BotoCoreError as exc:
            raise CatalogUnavailable(f"s3 get_object {key}: {exc}") from exc
        try:
            body = obj["Body"].read()
            return json.loads(body.decode("utf-8")), obj.get("ETag")
        except (KeyError, UnicodeDecodeError, ValueError) as exc:
            raise CatalogUnavailable(f"s3 object {key} is not valid JSON") from exc

    def probe(self) -> dict[str, Any]:
        """Check both catalog documents and one known package-tier object."""
        info = super().probe()
        clips = self.manifest().get("clips")
        first = clips[0] if isinstance(clips, list) and clips else None
        relative: str | None = None
        if isinstance(first, dict):
            contents = first.get("package_contents")
            if isinstance(contents, list) and contents and isinstance(contents[0], dict):
                candidate = contents[0].get("url")
                if isinstance(candidate, str):
                    relative = candidate
            if relative is None and isinstance(first.get("id"), str):
                relative = f"media/{first['id']}/LICENSE.txt"
        if relative is None:
            info["package_tier_ok"] = False
            info["package_tier_error"] = "PackageProbeKeyMissing"
            return info

        try:
            bucket, package_key = self._asset_location(relative)
            if bucket != self.settings.package_bucket:
                info["package_tier_ok"] = False
                info["package_tier_error"] = "PackageProbeKeyNotOnPackageTier"
                return info
            self._client().head_object(Bucket=bucket, Key=package_key)
        except Exception as exc:  # UnsafeAssetPath, boto clients and test doubles
            info["package_tier_ok"] = False
            info["package_tier_error"] = type(exc).__name__
        return info

    def _asset_location(self, relative: str) -> tuple[str, str]:
        if isinstance(relative, str) and relative.startswith("media/"):
            return self.settings.package_bucket, resolve_key(
                relative.removeprefix("media/"), self.settings.package_prefix
            )
        if isinstance(relative, str) and relative.startswith("archives/"):
            return self.settings.package_bucket, resolve_key(
                f"_archives/{relative.removeprefix('archives/')}",
                self.settings.package_prefix,
            )
        return self.settings.bucket, resolve_key(relative, self.settings.prefix)

    def sign(self, relative: str, ttl: int, origin: str = "") -> str:
        bucket, key = self._asset_location(relative)
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return self._client().generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=ttl,
            )
        except (BotoCoreError, ClientError) as exc:
            raise CatalogUnavailable(f"presign {key}: {exc}") from exc


# --- Local driver ------------------------------------------------------------

class LocalCatalogStore(CatalogStore):
    """A bundle directory on disk. Development only; no AWS involved."""

    #: Mount of the streaming route that serves signed local URLs.
    MOUNT = "/api/catalog/local"

    def __init__(self, settings: CatalogSettings) -> None:
        super().__init__(settings)
        if not settings.local_dir:
            raise CatalogUnavailable("CATALOG_LOCAL_DIR is not set")
        try:
            self.root = Path(settings.local_dir).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise CatalogUnavailable(f"CATALOG_LOCAL_DIR is unreadable: {exc}") from exc
        if not self.root.is_dir():
            raise CatalogUnavailable("CATALOG_LOCAL_DIR is not a directory")
        # A restart rotates the key and expires outstanding dev URLs — the same
        # contract a presigned URL has, so nothing downstream notices.
        self._signing_key = (
            settings.local_signing_key or secrets.token_hex(32)
        ).encode("utf-8")

    @property
    def key_prefix(self) -> str:
        # The local directory IS the bundle root: no S3 version prefix.
        return ""

    def path_for(self, relative: str) -> Path:
        """Bundle-relative path -> a real file inside the bundle.

        Two independent checks: `resolve_key` is syntactic, `resolve()` is
        semantic and defeats a symlink inside the bundle pointing at /etc,
        which no string inspection can catch.
        """
        resolve_key(relative)  # raises UnsafeAssetPath
        candidate = (self.root / PurePosixPath(relative)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise UnsafeAssetPath("resolved path escapes the bundle root")
        return candidate

    def _fetch(self, key: str, etag: str | None) -> tuple[Any, str | None]:
        path = self.path_for(key)
        self.fetch_count += 1
        try:
            stat = path.stat()
            current = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            if etag is not None and etag == current:
                return _NOT_MODIFIED, etag
            return json.loads(path.read_text("utf-8")), current
        except FileNotFoundError as exc:
            raise CatalogObjectMissing(key) from exc
        except (OSError, ValueError) as exc:
            raise CatalogUnavailable(f"local document {key}: {exc}") from exc

    # -- signing ------------------------------------------------------------ #

    def _signature(self, relative: str, expires: int) -> str:
        msg = f"{relative}\n{expires}".encode("utf-8")
        return hmac.new(self._signing_key, msg, hashlib.sha256).hexdigest()

    def sign(self, relative: str, ttl: int, origin: str = "") -> str:
        resolve_key(relative)  # never mint a URL for an unsafe path
        expires = int(time.time()) + ttl
        sig = self._signature(relative, expires)
        return f"{origin}{self.MOUNT}/{relative}?exp={expires}&sig={sig}"

    def verify(self, relative: str, expires: int, signature: str) -> bool:
        if expires < int(time.time()):
            return False
        try:
            resolve_key(relative)
        except UnsafeAssetPath:
            return False
        return hmac.compare_digest(self._signature(relative, expires), signature)


# --- Singleton ---------------------------------------------------------------

_store: CatalogStore | None = None
_store_signature: tuple | None = None
_store_lock = threading.Lock()


def _signature_of(cfg: CatalogSettings) -> tuple:
    return (
        cfg.source,
        cfg.bucket,
        cfg.package_bucket,
        cfg.region,
        cfg.prefix,
        cfg.package_prefix,
        cfg.manifest_key,
        cfg.access_key_id,
        cfg.endpoint_url,
        cfg.local_dir,
    )


def get_store() -> CatalogStore:
    """The process-wide store, rebuilt if the environment changed under us.

    Raises CatalogUnavailable when unconfigured; the route layer turns that
    into a generic 503.
    """
    global _store, _store_signature
    cfg = get_catalog_settings()
    signature = _signature_of(cfg)
    with _store_lock:
        if _store is not None and _store_signature == signature:
            return _store
        if not cfg.configured:
            raise CatalogUnavailable(
                f"catalog source {cfg.source!r} is not configured "
                "(bucket/credentials or CATALOG_LOCAL_DIR missing)"
            )
        store: CatalogStore = (
            LocalCatalogStore(cfg)
            if cfg.source == CATALOG_SOURCE_LOCAL
            else S3CatalogStore(cfg)
        )
        _store, _store_signature = store, signature
        return store


def reset_store() -> None:
    """Drop the singleton. Used by tests and by anything that rotates config."""
    global _store, _store_signature
    with _store_lock:
        _store = None
        _store_signature = None
