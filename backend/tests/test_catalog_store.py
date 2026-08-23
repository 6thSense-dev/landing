"""The catalog store, unit-tested: key safety, the S3 driver, role bookkeeping.

Pure and offline. The S3 driver is exercised against a fake client, except for
one test that builds a real boto3 client on purpose — presigning is a local HMAC
computation, so it needs no network, and it is the only way to prove which
credential actually signed the URL.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes.catalog import catalog_reader, parse_range, request_origin
from app.core.catalog_redact import (
    CATALOG_ROLES,
    FULL_ROLES,
    LEVEL_FULL,
    LEVEL_PREVIEW,
    PREVIEW_ROLES,
    access_level,
)
from app.core.catalog_store import (
    CatalogObjectMissing,
    CatalogUnavailable,
    S3CatalogStore,
    UnsafeAssetPath,
    get_store,
    reset_store,
    resolve_key,
)
from app.models.user import ROLES


# --- Key resolution (pure) -------------------------------------------------------

@pytest.mark.parametrize(
    "hostile",
    [
        "../../etc/passwd",
        "..",
        "a/../../b",
        "/etc/passwd",
        "//evil.example/x",
        "https://evil.example/x",
        "file:///etc/passwd",
        "s3://other-bucket/x",
        "media\\clip\\x.mp4",
        "media/%2e%2e/%2e%2e/etc/passwd",
        "%2e%2e%2fetc%2fpasswd",
        "media/../../../x",
        "media//x.mp4",
        "media/x.mp4/",
        ".hidden/x",
        "media/.git/config",
        "media/x\x00.mp4",
        "media/ x.mp4",
        "media/x.mp4 ",
        " media/x.mp4",
        "",
        "C:\\Windows\\win.ini",
        "media/x?y=1",
        "media/x#frag",
        "a" * 600,
    ],
)
def test_resolve_key_refuses_hostile_input(hostile):
    with pytest.raises(UnsafeAssetPath):
        resolve_key(hostile, "v1/")


@pytest.mark.parametrize(
    "relative,prefix,expected",
    [
        ("catalog.json", "v1/", "v1/catalog.json"),
        ("posters/clip-one.jpg", "v1/", "v1/posters/clip-one.jpg"),
        ("media/clip-one/video/stereo.mp4", "", "media/clip-one/video/stereo.mp4"),
        ("media/x/preview/p50_t005.1s.png", "v2/", "v2/media/x/preview/p50_t005.1s.png"),
        ("media/x/docs/SYNC_PROTOCOL.md", "v1/", "v1/media/x/docs/SYNC_PROTOCOL.md"),
    ],
)
def test_resolve_key_accepts_real_bundle_paths(relative, prefix, expected):
    assert resolve_key(relative, prefix) == expected


def test_resolve_key_refuses_a_traversing_prefix():
    with pytest.raises(UnsafeAssetPath):
        resolve_key("catalog.json", "../")


def test_parse_range_table():
    assert parse_range(None, 100) is None
    assert parse_range("bytes=0-9", 100) == (0, 9)
    assert parse_range("bytes=90-", 100) == (90, 99)
    assert parse_range("bytes=-10", 100) == (90, 99)
    assert parse_range("bytes=0-999", 100) == (0, 99)
    assert parse_range("nonsense", 100) is None
    assert parse_range("bytes=0-9,20-29", 100) is None


async def test_role_outside_the_catalog_set_is_403():
    with pytest.raises(HTTPException) as exc:
        await catalog_reader(user=SimpleNamespace(role="intern", id=1))
    assert exc.value.status_code == 403


def test_access_level_partitions_every_catalog_role():
    assert access_level("guest") == LEVEL_PREVIEW
    assert access_level("investor") == LEVEL_PREVIEW
    for role in ("customer", "founder", "admin"):
        assert access_level(role) == LEVEL_FULL
    # An unknown role never gets full access by accident.
    assert access_level("intern") == LEVEL_PREVIEW
    assert access_level(None) == LEVEL_PREVIEW
    assert CATALOG_ROLES == {"guest", "investor", "customer", "founder", "admin"}


def test_full_and_preview_partition_the_catalog_roles():
    assert FULL_ROLES & PREVIEW_ROLES == set()
    assert FULL_ROLES | PREVIEW_ROLES == CATALOG_ROLES


def test_catalog_roles_track_the_database_role_list():
    """Tripwire. A new role must not silently inherit catalog access.

    `users.role` is constrained by migration 0007. If a role is added there,
    somebody has to decide whether it may read the catalog at all and whether it
    gets full or preview access — so this test fails until FULL_ROLES /
    PREVIEW_ROLES in catalog_redact.py are updated deliberately.
    """
    assert CATALOG_ROLES == set(ROLES)


# --- The S3 driver, offline ------------------------------------------------------

def _client_error(code: str, http: int):
    from botocore.exceptions import ClientError

    return ClientError(
        {"Error": {"Code": code, "Message": "hidden"},
         "ResponseMetadata": {"HTTPStatusCode": http}},
        "GetObject",
    )


class _FakeS3:
    """Just enough S3: conditional GetObject and presigning, no network."""

    def __init__(self, objects: dict[str, tuple[bytes, str]]):
        self.objects = objects
        self.gets: list[tuple[str, str | None]] = []
        self.signed: list[tuple[str, int]] = []

    def get_object(self, Bucket, Key, IfNoneMatch=None):  # noqa: N803 - boto3 casing
        self.gets.append((Key, IfNoneMatch))
        if Key not in self.objects:
            raise _client_error("NoSuchKey", 404)
        body, etag = self.objects[Key]
        if IfNoneMatch == etag:
            raise _client_error("304", 304)
        return {"Body": SimpleNamespace(read=lambda: body), "ETag": etag}

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        self.signed.append((Params["Key"], ExpiresIn))
        return f"https://{Params['Bucket']}.s3.amazonaws.com/{Params['Key']}"


MANIFEST = b'{"schema":"6s-catalog/1.0","clips":[{"id":"clip-one"}]}'


@pytest.fixture
def s3_env(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "s3")
    monkeypatch.setenv("CATALOG_S3_BUCKET", "6thsense-catalog-media")
    monkeypatch.setenv("CATALOG_S3_REGION", "us-west-2")
    monkeypatch.setenv("CATALOG_S3_PREFIX", "v1/")
    monkeypatch.setenv("CATALOG_AWS_ACCESS_KEY_ID", "AKIACATALOGREADER00000")
    monkeypatch.setenv("CATALOG_AWS_SECRET_ACCESS_KEY", "catalog-secret")
    monkeypatch.setenv("CATALOG_PRESIGN_TTL", "900")
    reset_store()
    yield
    reset_store()


@pytest.fixture
def fake_s3(s3_env, monkeypatch):
    fake = _FakeS3({"v1/catalog.json": (MANIFEST, '"etag-1"')})
    monkeypatch.setattr(S3CatalogStore, "_build_client", lambda self: fake)
    return fake


def test_s3_reads_the_manifest_under_the_version_prefix(fake_s3):
    store = get_store()
    assert store.manifest()["schema"] == "6s-catalog/1.0"
    assert fake_s3.gets == [("v1/catalog.json", None)]


def test_s3_caches_the_manifest(fake_s3):
    store = get_store()
    store.manifest()
    store.manifest()
    assert len(fake_s3.gets) == 1
    assert store.fetch_count == 1


def test_s3_revalidates_with_if_none_match_and_keeps_the_cached_doc(
    fake_s3, monkeypatch
):
    monkeypatch.setenv("CATALOG_MANIFEST_TTL", "0")
    reset_store()
    store = get_store()
    monkeypatch.setattr(S3CatalogStore, "_build_client", lambda self: fake_s3)
    first = store.manifest()
    second = store.manifest()
    assert fake_s3.gets == [("v1/catalog.json", None), ("v1/catalog.json", '"etag-1"')]
    assert second == first  # the 304 kept the parsed document


def test_s3_signs_with_the_prefix_and_the_configured_ttl(fake_s3):
    store = get_store()
    url = store.sign("media/clip-one/video/stereo.mp4", 900)
    assert fake_s3.signed == [("v1/media/clip-one/video/stereo.mp4", 900)]
    assert url.startswith("https://")


def test_s3_refuses_to_sign_a_path_that_escapes_the_prefix(fake_s3):
    store = get_store()
    with pytest.raises(UnsafeAssetPath):
        store.sign("../../secrets/keys.json", 900)
    assert fake_s3.signed == []


def test_s3_missing_clip_is_a_lookup_failure_not_an_outage(fake_s3):
    with pytest.raises(CatalogObjectMissing):
        get_store().clip("no-such-clip")


def test_s3_access_denied_becomes_a_generic_outage(fake_s3, monkeypatch):
    def boom(**kwargs):
        raise _client_error("AccessDenied", 403)

    monkeypatch.setattr(fake_s3, "get_object", boom)
    with pytest.raises(CatalogUnavailable) as exc:
        get_store().manifest()
    # The real reason is kept for our logs; the route never forwards it.
    assert "AccessDenied" in str(exc.value)


def test_s3_corrupt_manifest_is_an_outage_not_a_crash(s3_env, monkeypatch):
    fake = _FakeS3({"v1/catalog.json": (b"{not json", '"etag-1"')})
    monkeypatch.setattr(S3CatalogStore, "_build_client", lambda self: fake)
    with pytest.raises(CatalogUnavailable):
        get_store().manifest()


def test_half_configured_credentials_never_fall_back_to_the_ambient_chain(
    s3_env, monkeypatch
):
    """The firmware-publishing key must never sign a catalog URL."""
    monkeypatch.delenv("CATALOG_AWS_SECRET_ACCESS_KEY")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFIRMWAREPUBLISHER0")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "firmware-secret")
    reset_store()
    with pytest.raises(CatalogUnavailable):
        get_store()


def test_presigning_uses_the_catalog_key_and_not_the_ambient_one(s3_env, monkeypatch):
    """Builds a REAL boto3 client. Presigning is offline, so this costs nothing."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFIRMWAREPUBLISHER0")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "firmware-secret")
    reset_store()
    url = get_store().sign("posters/clip-one.jpg", 900)
    assert url.startswith("https://6thsense-catalog-media.s3.")
    assert "/v1/posters/clip-one.jpg" in url
    assert "AKIACATALOGREADER00000" in url
    assert "AKIAFIRMWAREPUBLISHER0" not in url
    assert "X-Amz-Expires=900" in url
    assert "X-Amz-Signature=" in url


# --- Self-referential URLs ---------------------------------------------------------

def _request(base: str, headers: dict[str, str] | None = None):
    return SimpleNamespace(base_url=base, headers=headers or {})


def test_request_origin_strips_the_trailing_slash():
    assert request_origin(_request("http://localhost:8000/")) == "http://localhost:8000"


def test_request_origin_trusts_x_forwarded_proto():
    """uvicorn runs without --proxy-headers, so this is the only https signal."""
    req = _request("http://api.6thsense.dev/", {"x-forwarded-proto": "https"})
    assert request_origin(req) == "https://api.6thsense.dev"


def test_request_origin_never_downgrades():
    req = _request("https://api.6thsense.dev/", {"x-forwarded-proto": "http"})
    assert request_origin(req) == "https://api.6thsense.dev"


# --------------------------------------------------------------------------- #
# Presigned URLs must carry the REGIONAL virtual-hosted host.                   #
# --------------------------------------------------------------------------- #
def test_presigned_urls_use_the_regional_virtual_hosted_endpoint(monkeypatch):
    """A presigned URL signed against the global S3 host is dead on arrival.

    botocore will happily sign `<bucket>.s3.amazonaws.com` even when the client's
    endpoint is regional. S3 answers that with a 307 to a *different* host, and
    SigV4 binds the signature to Host -- so the redirected request 403s and every
    poster, preview and video in the catalog fails to load. Verified against the
    real bucket before this test existed: global host -> 403, regional -> 200.

    The regional virtual-hosted form is also the exact origin the frontend's CSP
    allowlists, so this assertion guards two things at once.
    """
    from app.core import config as cfg_mod
    from app.core.catalog_store import S3CatalogStore

    monkeypatch.setenv("CATALOG_SOURCE", "s3")
    monkeypatch.setenv("CATALOG_S3_BUCKET", "example-bucket")
    monkeypatch.setenv("CATALOG_S3_REGION", "us-west-2")
    monkeypatch.setenv("CATALOG_S3_PREFIX", "v1/")
    monkeypatch.setenv("CATALOG_AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv(
        "CATALOG_AWS_SECRET_ACCESS_KEY",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    url = S3CatalogStore(cfg_mod.get_catalog_settings()).sign("posters/a.jpg", 900)
    host = url.split("/")[2]

    assert host == "example-bucket.s3.us-west-2.amazonaws.com", (
        f"presigned host is {host!r}; the global endpoint gets a 307 whose "
        "signature no longer matches, so all media 403s"
    )
    assert "X-Amz-Signature" in url
