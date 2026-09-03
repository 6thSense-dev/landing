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
    cookie_samesite: str


def _cookie_samesite() -> str:
    v = (os.environ.get("SENSEPROBE_COOKIE_SAMESITE") or "lax").strip().lower()
    if v not in ("lax", "strict", "none"):
        raise RuntimeError(
            f"SENSEPROBE_COOKIE_SAMESITE must be lax, strict or none (got {v!r})")
    if v == "none" and not _parse_bool(os.environ.get("SENSEPROBE_COOKIE_SECURE"), True):
        raise RuntimeError(
            "SENSEPROBE_COOKIE_SAMESITE=none requires SENSEPROBE_COOKIE_SECURE=true; "
            "browsers silently drop a SameSite=None cookie that is not Secure.")
    return v


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
        # The SPA and the API are on different registrable domains in production
        # (6thsense.dev vs the Railway host), which makes every authenticated XHR
        # cross-site. A `lax` cookie is stored on login and then never sent again, so
        # the session appears to succeed and every subsequent request 401s. `none`
        # is what a cross-origin credentialed API needs; CSRF is defended here by
        # OriginCheckMiddleware's allowlist on unsafe methods, not by SameSite.
        # Browsers reject SameSite=None without Secure, so that pairing is enforced.
        cookie_samesite=_cookie_samesite(),
    )


# --------------------------------------------------------------------------- #
# Catalog (buyer-facing data catalog)                                          #
#                                                                              #
# Kept in its own dataclass and its own accessor rather than bolted onto       #
# Settings: the catalog is an optional subsystem, its variables are namespaced #
# CATALOG_*, and a deployment with no bucket configured must still boot.       #
# Nothing above this line changes.                                             #
# --------------------------------------------------------------------------- #

CATALOG_SOURCE_S3 = "s3"
CATALOG_SOURCE_LOCAL = "local"
CATALOG_SOURCES = (CATALOG_SOURCE_S3, CATALOG_SOURCE_LOCAL)

#: SigV4 refuses to sign for longer than seven days, so that is the hard cap.
CATALOG_PRESIGN_TTL_DEFAULT = 900
CATALOG_PRESIGN_TTL_MIN = 60
CATALOG_PRESIGN_TTL_MAX = 7 * 24 * 60 * 60

#: How long a parsed manifest/clip document may be reused before we revalidate.
CATALOG_MANIFEST_TTL_DEFAULT = 60
CATALOG_MANIFEST_TTL_MIN = 0
CATALOG_MANIFEST_TTL_MAX = 3600


def _parse_int(raw: str | None, default: int, *, lo: int, hi: int) -> int:
    """Bounded int from the environment. A garbage value falls back to the
    default rather than crashing the process at import time."""
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _normalise_prefix(raw: str | None) -> str:
    """`v1`, `/v1/`, `v1/` all become `v1/`; empty stays empty.

    The prefix is joined to manifest-relative paths verbatim, so it is
    normalised here once and validated for traversal in catalog_store.
    """
    prefix = (raw or "").strip().strip('"').strip("'").lstrip("/")
    if not prefix:
        return ""
    return prefix if prefix.endswith("/") else prefix + "/"


@dataclass(frozen=True)
class CatalogSettings:
    """Everything the catalog needs to find its bundle.

    `source` selects the driver:
      * `s3`    — private bucket, short-lived presigned GET URLs (production)
      * `local` — a bundle directory on disk, served by the API (development)
    """

    source: str
    bucket: str
    package_bucket: str
    region: str
    prefix: str
    package_prefix: str
    manifest_key: str
    access_key_id: str | None
    secret_access_key: str | None
    session_token: str | None
    endpoint_url: str | None
    presign_ttl: int
    manifest_ttl: int
    local_dir: str | None
    local_signing_key: str | None

    @property
    def is_local(self) -> bool:
        return self.source == CATALOG_SOURCE_LOCAL

    @property
    def has_static_credentials(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key)

    @property
    def credentials_half_configured(self) -> bool:
        """Exactly one of the CATALOG_AWS_* pair is set.

        This is the dangerous state: falling through to the default credential
        chain here would quietly sign catalog URLs with whatever AWS_* key
        happens to be in the environment — on our machines, the
        firmware-publishing key. Treated as a hard misconfiguration instead.
        """
        return bool(self.access_key_id) != bool(self.secret_access_key)

    @property
    def configured(self) -> bool:
        if self.is_local:
            return bool(self.local_dir)
        return (
            bool(self.bucket)
            and bool(self.package_bucket)
            and not self.credentials_half_configured
        )


def get_catalog_settings() -> CatalogSettings:
    source = (os.environ.get("CATALOG_SOURCE") or CATALOG_SOURCE_S3).strip().lower()
    if source not in CATALOG_SOURCES:
        source = CATALOG_SOURCE_S3
    return CatalogSettings(
        source=source,
        bucket=(os.environ.get("CATALOG_S3_BUCKET") or "6thsense-catalog-media").strip(),
        package_bucket=(
            os.environ.get("CATALOG_PACKAGE_BUCKET") or "6thsense-processed"
        ).strip(),
        region=(os.environ.get("CATALOG_S3_REGION") or "us-west-2").strip(),
        prefix=_normalise_prefix(os.environ.get("CATALOG_S3_PREFIX", "v1/")),
        package_prefix=_normalise_prefix(
            os.environ.get(
                "CATALOG_PACKAGE_PREFIX", "imported/2026-08-24_nervous-1/"
            )
        ),
        manifest_key=(os.environ.get("CATALOG_MANIFEST_KEY") or "catalog.json").strip(),
        access_key_id=(os.environ.get("CATALOG_AWS_ACCESS_KEY_ID") or "").strip() or None,
        secret_access_key=(os.environ.get("CATALOG_AWS_SECRET_ACCESS_KEY") or "").strip()
        or None,
        session_token=(os.environ.get("CATALOG_AWS_SESSION_TOKEN") or "").strip() or None,
        endpoint_url=(os.environ.get("CATALOG_S3_ENDPOINT_URL") or "").strip() or None,
        presign_ttl=_parse_int(
            os.environ.get("CATALOG_PRESIGN_TTL"),
            CATALOG_PRESIGN_TTL_DEFAULT,
            lo=CATALOG_PRESIGN_TTL_MIN,
            hi=CATALOG_PRESIGN_TTL_MAX,
        ),
        manifest_ttl=_parse_int(
            os.environ.get("CATALOG_MANIFEST_TTL"),
            CATALOG_MANIFEST_TTL_DEFAULT,
            lo=CATALOG_MANIFEST_TTL_MIN,
            hi=CATALOG_MANIFEST_TTL_MAX,
        ),
        local_dir=(os.environ.get("CATALOG_LOCAL_DIR") or "").strip() or None,
        local_signing_key=(os.environ.get("CATALOG_LOCAL_SIGNING_KEY") or "").strip()
        or None,
    )
