"""The catalog API: auth, role redaction, presigning, path safety, Range.

Everything runs against the LOCAL driver pointed at
`tests/fixtures/catalog/bundle`: no AWS, and no dependency on a bundle outside
this repository. The local driver is not a stub — same CatalogStore, same
redaction pass, same resolve_key, differing only in how a relative path becomes
a URL — so what is nulled, what is never signed and what a hostile manifest
does all hold identically for S3. The store itself is unit-tested in
test_catalog_store.py.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.catalog_redact import (
    CATALOG_ROLES,
    CLIP_ASSET_PATHS,
    MANIFEST_ASSET_PATHS,
    OPEN_CLIP_EXEMPT,
    WITHHELD_CLIP,
    access_level,
    withheld_clip_spec,
)
from app.core.catalog_store import LocalCatalogStore, get_store, reset_store
from app.core.passwords import hash_password
from app.core.sessions import hash_session_token, mint_session_token
from app.main import create_app
from app.models import Session as SessionRow, User

#: Every URL the API returns is absolute; under ASGITransport the origin is
#: whatever base_url the client used.
ORIGIN = "http://t"
LOCAL = f"{ORIGIN}/api/catalog/local/"

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
BUNDLE = FIXTURES / "bundle"
EVIL = FIXTURES / "evil"

#: Paths that ONLY ever appear behind a withheld pointer. Assets also reachable
#: through a granted field (stereo.mp4, the docs) are excluded: signing those is
#: correct.
EXCLUSIVELY_WITHHELD = {
    "media/clip-one/video/frame_times.csv",
    "media/clip-one/imu/imu.csv",
    "media/clip-one/imu/imu.f32",
    "media/clip-one/tactile/left.npz",
    "media/clip-one/tactile/right.npz",
    "media/clip-one/sensor_layout.json",
    "media/clip-one/segcap/segments.csv",
    "media/clip-one/calibration/calibration.json",
    "media/clip-one/calibration/calibration_delivered.json",
    "archives/clip-one.tar.gz",
}


# --- Harness -------------------------------------------------------------------

def _configure(monkeypatch, bundle: Path | None = BUNDLE, **extra: str):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    monkeypatch.setenv("CATALOG_SOURCE", "local")
    monkeypatch.setenv("CATALOG_LOCAL_SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("CATALOG_PRESIGN_TTL", "900")
    monkeypatch.setenv("CATALOG_MANIFEST_TTL", "60")
    if bundle is None:
        monkeypatch.delenv("CATALOG_LOCAL_DIR", raising=False)
    else:
        monkeypatch.setenv("CATALOG_LOCAL_DIR", str(bundle))
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    reset_store()
    from app.core.limiter import limiter

    limiter.reset()
    return create_app()


@pytest_asyncio.fixture
async def app(db_session, monkeypatch):
    application = _configure(monkeypatch)
    yield application
    reset_store()


async def _session_for(db_session, role: str) -> str:
    user = User(
        email=f"{role}@example.test",
        name=role.title(),
        role=role,
        password_hash=hash_password("twelve-chars!!"),
    )
    db_session.add(user)
    await db_session.commit()
    raw = mint_session_token()
    db_session.add(
        SessionRow(
            user_id=user.id,
            token_hash=hash_session_token(raw),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
    )
    await db_session.commit()
    return raw


def _client(application) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://t")


async def _get(application, path: str, sid: str | None = None, **kwargs):
    async with _client(application) as client:
        cookies = {"sid": sid} if sid else None
        return await client.get(path, cookies=cookies, **kwargs)


@pytest.fixture
def signed_paths(monkeypatch) -> list[str]:
    """Every relative path handed to the signer, in order."""
    calls: list[str] = []
    original = LocalCatalogStore.sign

    def spy(self, relative: str, ttl: int, origin: str = "") -> str:
        calls.append(relative)
        return original(self, relative, ttl, origin)

    monkeypatch.setattr(LocalCatalogStore, "sign", spy)
    return calls


# --- Auth ------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/api/catalog", "/api/catalog/clips/clip-one", "/api/catalog/health"],
)
async def test_unauthenticated_is_401(app, path):
    res = await _get(app, path)
    assert res.status_code == 401


async def test_signed_media_needs_no_session_because_the_url_is_the_capability(
    app, db_session
):
    """Same contract as a presigned S3 URL, and the only one <img> can satisfy.

    A dev-server <img>/<video> is a cross-origin subresource and sends no
    cookie, so gating this route on the session would 401 every poster in
    development while production (S3, also cookie-free) worked.
    """
    sid = await _session_for(db_session, "guest")
    doc = (await _get(app, "/api/catalog/clips/clip-one", sid)).json()
    url = doc["media"]["video"]["stereo_sbs"]
    assert url.startswith(LOCAL)
    assert (await _get(app, url)).status_code == 200


# --- Manifest ---------------------------------------------------------------------

@pytest.mark.parametrize("role", sorted(CATALOG_ROLES))
async def test_manifest_is_readable_by_every_catalog_role(app, db_session, role):
    sid = await _session_for(db_session, role)
    res = await _get(app, "/api/catalog", sid)
    assert res.status_code == 200
    doc = res.json()
    assert doc["schema"] == "6s-catalog/1.0"
    assert len(doc["clips"]) == 2
    assert doc["access"]["level"] == access_level(role)
    assert doc["url_form"] == "resolved"


async def test_manifest_expands_templates_and_never_signs_detail(app, db_session):
    sid = await _session_for(db_session, "guest")
    doc = (await _get(app, "/api/catalog", sid)).json()
    one, two = doc["clips"]

    # clip-one omitted poster/preview: the template was expanded, then signed.
    assert one["poster"].startswith(LOCAL + "posters/clip-one.jpg?")
    assert one["preview"].startswith(LOCAL + "previews/clip-one.mp4?")
    # clip-two carried present-and-null: no asset exists, and none was invented.
    assert two["poster"] is None and two["preview"] is None
    # Detail always points back at this API so the record can be redacted.
    assert one["detail"] == f"{ORIGIN}/api/catalog/clips/clip-one"
    assert two["detail"] == f"{ORIGIN}/api/catalog/clips/clip-two"
    # Templates are spent, so a client cannot expand a second, unsigned copy.
    assert doc["collection"]["paths"] == {"detail": None, "poster": None, "preview": None}


async def test_no_asset_url_reaches_the_client_unresolved(app, db_session):
    """The frontend joins nothing onto nothing: every URL it gets is final."""
    sid = await _session_for(db_session, "customer")
    manifest = (await _get(app, "/api/catalog", sid)).json()
    clip = (await _get(app, "/api/catalog/clips/clip-one", sid)).json()
    for doc, paths in ((manifest, MANIFEST_ASSET_PATHS), (clip, CLIP_ASSET_PATHS)):
        for path in paths:
            for value in _leaves(doc, path):
                assert value is None or value.startswith("http"), (path, value)
    assert all(c["detail"].startswith(ORIGIN) for c in manifest["clips"])
    assert clip["detail"].startswith(ORIGIN)


async def test_manifest_leaves_external_urls_alone(app, db_session):
    sid = await _session_for(db_session, "founder")
    doc = (await _get(app, "/api/catalog", sid)).json()
    assert doc["collection"]["vendor"]["url"] == "https://6thsense.dev"
    assert doc["collection"]["license"]["url"] == "https://6thsense.dev/licence/eval"


async def test_manifest_withholds_the_archive_when_the_named_clip_is_not_rights_clean(
    app, db_session
):
    """Naming a clip in `sample_archive` is a pointer, not a grant.

    The fixture's manifest names clip-one, whose four permissions read
    `on_request`/`denied`. Advertising that as an open sample would hand out bytes the
    rights object refuses, so the second lock in catalog_redact re-derives the test from
    the clip's own `rights` and withholds the pointer anyway.
    """
    guest = await _session_for(db_session, "guest")
    customer = await _session_for(db_session, "customer")

    preview = (await _get(app, "/api/catalog", guest)).json()
    named = preview["collection"]["sample_archive"]["clip_id"]
    assert named == "clip-one"
    assert preview["clips"][0]["rights"]["model_training"] != "granted"
    assert preview["collection"]["sample_archive"]["url"] is None
    assert "sample package archive" in preview["access"]["withheld"]
    assert preview["access"]["how_to_request"]
    # The facts about the archive survive; only the pointer is withdrawn.
    assert preview["collection"]["sample_archive"]["bytes"] == 12

    full = (await _get(app, "/api/catalog", customer)).json()
    assert full["collection"]["sample_archive"]["url"].startswith(LOCAL)
    assert full["access"]["withheld"] == []


def _granted_bundle(tmp_path):
    """A copy of the fixture bundle in which clip-one's rights are granted end to end."""
    out = tmp_path / "granted"
    out.mkdir()
    (out / "clips").mkdir()
    manifest = json.loads((BUNDLE / "catalog.json").read_text())
    for clip in manifest["clips"]:
        if clip["id"] == "clip-one":
            clip["rights"] = dict.fromkeys(clip["rights"], "granted")
    (out / "catalog.json").write_text(json.dumps(manifest))
    for cid in ("clip-one", "clip-two"):
        doc = json.loads((BUNDLE / "clips" / f"{cid}.json").read_text())
        if cid == "clip-one":
            doc["rights"] = {**doc["rights"], **dict.fromkeys(WITHHELD_RIGHTS_KEYS, "granted")}
        (out / "clips" / f"{cid}.json").write_text(json.dumps(doc))
    return out


#: The four permissions the open-clip test flips. Named here rather than reaching into
#: the redaction module's tuple so the test would notice a rename rather than adapt to it.
WITHHELD_RIGHTS_KEYS = ("model_training", "commercial_use", "redistribution", "derived_model")


async def test_the_open_evaluation_clip_ships_complete_enough_to_verify(
    app, db_session, tmp_path
):
    """The one clip a preview account can run through its own loader.

    Every figure the catalog publishes about alignment is derived from
    `frame_times.csv`, and every figure about the tactile channel census is derived from
    the per-hand arrays. Withholding all of them from every clip left nothing on the
    page independently checkable. This asserts the exemption is exactly the set that
    makes the claim verifiable -- and no wider.
    """
    reset_store()
    os.environ["CATALOG_LOCAL_DIR"] = str(_granted_bundle(tmp_path))
    try:
        guest = await _session_for(db_session, "guest")

        manifest = (await _get(app, "/api/catalog", guest)).json()
        assert manifest["collection"]["sample_archive"]["url"].startswith(LOCAL)
        assert "sample package archive" not in manifest["access"]["withheld"]

        openc = (await _get(app, "/api/catalog/clips/clip-one", guest)).json()
        assert openc["access"]["level"] == "preview"
        # Served: the four the exemption names, and their bytes are behind a signature.
        assert openc["media"]["video"]["frame_times"].startswith(LOCAL)
        assert openc["media"]["tactile"]["left"].startswith(LOCAL)
        assert openc["media"]["tactile"]["layout"].startswith(LOCAL)
        assert openc["media"]["archive"]["url"].startswith(LOCAL)
        # Still withheld ON THE OPEN CLIP: the second hand, the full-rate IMU, the
        # segment captions, the calibration files, the per-file download links.
        assert openc["media"]["tactile"]["right"] is None
        assert openc["media"]["imu"]["csv"] is None
        assert openc["media"]["imu"]["f32"] is None
        assert openc["media"]["segcap"]["json"] is None
        assert openc["media"]["calibration"]["raw"] is None
        assert openc["media"]["calibration"]["delivered"] is None
        assert all(p["url"] is None for p in openc["package_contents"])
        # The record says so, above the standing preview notice.
        assert "Open evaluation clip" in openc["known_limitations"][0]

        # A clip the manifest did NOT name is untouched by any of this.
        other = (await _get(app, "/api/catalog/clips/clip-two", guest)).json()
        for item in WITHHELD_CLIP:
            for value in _leaves(other, item.path):
                assert value is None, item
    finally:
        os.environ["CATALOG_LOCAL_DIR"] = str(BUNDLE)
        reset_store()


def test_the_exemption_is_a_subset_of_the_withhold_list_and_nothing_else_moves():
    """Walks the two specs against each other, so neither can drift into the other.

    An exemption naming a path the withhold list does not carry would be dead config
    that reads as an open door; a full-access spec that differs at all would mean two
    predicates for one boundary, which is the bug this module was written to prevent.
    """
    withheld = {w.path for w in WITHHELD_CLIP}
    assert OPEN_CLIP_EXEMPT <= withheld
    assert {w.path for w in withheld_clip_spec(False)} == withheld
    assert {w.path for w in withheld_clip_spec(True)} == withheld - OPEN_CLIP_EXEMPT
    # The exemption may never reach the things a licence, not a signature, gates.
    assert ("media", "imu", "csv") not in OPEN_CLIP_EXEMPT
    assert ("media", "tactile", "right") not in OPEN_CLIP_EXEMPT
    assert ("package_contents", "[]", "url") not in OPEN_CLIP_EXEMPT


# --- Clip records -------------------------------------------------------------------

async def test_clip_full_access_keeps_every_pointer(app, db_session):
    sid = await _session_for(db_session, "customer")
    doc = (await _get(app, "/api/catalog/clips/clip-one", sid)).json()
    media = doc["media"]
    assert media["video"]["stereo_sbs"].startswith(LOCAL)
    assert media["video"]["frame_times"].startswith(LOCAL)
    assert media["tactile"]["left"].startswith(LOCAL)
    assert media["imu"]["csv"].startswith(LOCAL)
    assert media["archive"]["url"].startswith(LOCAL)
    assert all(e["url"].startswith(LOCAL) for e in doc["package_contents"])
    assert doc["access"] == {
        "level": "full", "withheld": [], "how_to_request": None, "notice": None,
    }


@pytest.mark.parametrize("role", ["guest", "investor"])
async def test_clip_preview_access_nulls_every_withheld_pointer(app, db_session, role):
    sid = await _session_for(db_session, role)
    doc = (await _get(app, "/api/catalog/clips/clip-one", sid)).json()

    media = doc["media"]
    assert media["video"]["frame_times"] is None
    assert media["imu"] == {"csv": None, "f32": None}
    assert media["tactile"]["left"] is None
    assert media["tactile"]["right"] is None
    assert media["tactile"]["layout"] is None
    assert media["segcap"]["json"] is None
    assert media["calibration"] == {"raw": None, "delivered": None}
    assert media["archive"] is None
    assert all(entry["url"] is None for entry in doc["package_contents"])

    # The commercial surface survives: the watchable mp4, the poster, the loop,
    # the derived chart sidecars, the docs, and every fact about the package.
    assert media["video"]["stereo_sbs"].startswith(LOCAL)
    assert doc["poster"].startswith(LOCAL)
    assert doc["preview"].startswith(LOCAL)
    assert media["docs"]["readme"].startswith(LOCAL)
    # The redaction audit record is a RIGHTS artefact and is deliberately NOT
    # withheld: it is the evidence for the privacy claim next to it.
    assert doc["privacy"]["redaction"]["record_url"].startswith(LOCAL)
    assert doc["imu_preview"]["sidecar"]["url"].startswith(LOCAL)
    assert doc["tactile_preview"]["frames"][0]["png"].startswith(LOCAL)
    assert doc["package_contents"][0]["sha256"] == "1" * 64
    assert doc["metadata"]["take_id"] == "ego_test"
    assert doc["segments"][0]["verb"] == "grasp"
    assert doc["calibration"]["camera"]["rms_reprojection_px"] == 0.69

    # And the record SAYS what was taken away, in the record.
    assert doc["access"]["level"] == "preview"
    assert "per-hand tactile arrays (.npz)" in doc["access"]["withheld"]
    assert doc["access"]["how_to_request"]
    assert doc["known_limitations"][0].startswith("Preview access:")
    assert "Raw ADC counts, not newtons." in doc["known_limitations"]


async def test_withheld_assets_are_never_signed(app, db_session, signed_paths):
    """Redaction runs BEFORE presigning: there is no URL to leak, not even a dead one."""
    sid = await _session_for(db_session, "guest")
    res = await _get(app, "/api/catalog/clips/clip-one", sid)
    assert res.status_code == 200

    leaked = EXCLUSIVELY_WITHHELD & set(signed_paths)
    assert leaked == set(), f"signed a withheld asset: {sorted(leaked)}"
    # Sanity: the spy is actually wired up and the granted assets DID get signed.
    assert "media/clip-one/video/stereo.mp4" in signed_paths


async def test_full_access_signs_strictly_more_than_preview(app, db_session, signed_paths):
    guest = await _session_for(db_session, "guest")
    admin = await _session_for(db_session, "admin")
    await _get(app, "/api/catalog/clips/clip-one", guest)
    preview_signed = set(signed_paths)
    signed_paths.clear()
    await _get(app, "/api/catalog/clips/clip-one", admin)
    full_signed = set(signed_paths)
    assert preview_signed < full_signed
    assert EXCLUSIVELY_WITHHELD <= full_signed


async def test_preview_never_loses_the_producers_own_notice(app, db_session):
    """The regression: the preview notice used to be prefixed onto
    `collection.notice` under a 300-character cap, and the pair overflowed it —
    so the licence caveat silently vanished for exactly the role that needs it.
    The two notices are separate fields now and neither may truncate the other.
    """
    original = json.loads((BUNDLE / "catalog.json").read_text())["collection"]["notice"]
    assert original  # the fixture must actually carry one, or this proves nothing

    for role in ("guest", "investor"):
        sid = await _session_for(db_session, role)
        doc = (await _get(app, "/api/catalog", sid)).json()
        assert doc["collection"]["notice"] == original
        assert doc["access"]["notice"].startswith("Preview access:")
        # Together they exceed the cap that used to be applied to their join.
        assert len(original) + len(doc["access"]["notice"]) > 300

    sid = await _session_for(db_session, "customer")
    full = (await _get(app, "/api/catalog", sid)).json()
    assert full["collection"]["notice"] == original
    assert full["access"]["notice"] is None


async def test_manifest_and_clip_apply_the_same_predicate(app, db_session):
    """The bug a reviewer caught once: two roles, two predicates, dead pointers."""
    for role in ("guest", "investor"):
        sid = await _session_for(db_session, role)
        manifest = (await _get(app, "/api/catalog", sid)).json()
        clip = (await _get(app, "/api/catalog/clips/clip-one", sid)).json()
        assert manifest["access"]["level"] == clip["access"]["level"] == "preview"
        # Nothing the manifest hands out is something the record withholds.
        assert manifest["collection"]["sample_archive"]["url"] is None
        assert clip["media"]["archive"] is None


def _leaves(node, path):
    """Every value a withhold-spec path names, so the test can walk the spec."""
    if not path:
        yield node
        return
    head, rest = path[0], path[1:]
    if head == "[]":
        for item in node or []:
            yield from _leaves(item, rest)
    elif isinstance(node, dict):
        yield from _leaves(node.get(head), rest)


async def test_every_withheld_path_in_the_spec_is_actually_null(app, db_session):
    """Walks the spec itself, so a new entry cannot be added without enforcement."""
    sid = await _session_for(db_session, "guest")
    doc = (await _get(app, "/api/catalog/clips/clip-one", sid)).json()
    for item in WITHHELD_CLIP:
        for value in _leaves(doc, item.path):
            assert value is None, item


# --- Lookup failures ------------------------------------------------------------------

async def test_unknown_clip_is_404_with_the_same_body_as_a_real_miss(app, db_session):
    sid = await _session_for(db_session, "guest")
    unknown = await _get(app, "/api/catalog/clips/no-such-clip", sid)
    malformed = await _get(app, "/api/catalog/clips/NOT_A_CLIP_ID", sid)
    assert unknown.status_code == malformed.status_code == 404
    assert unknown.json() == malformed.json() == {"detail": "Not found."}


async def test_a_clip_absent_from_the_manifest_is_unreachable(app, db_session, tmp_path):
    """A take left in the bucket but not published does not exist, for anyone."""
    orphan = tmp_path / "bundle"
    orphan.mkdir()
    (orphan / "clips").mkdir()
    manifest = json.loads((BUNDLE / "catalog.json").read_text())
    manifest["clips"] = [c for c in manifest["clips"] if c["id"] != "clip-two"]
    (orphan / "catalog.json").write_text(json.dumps(manifest))
    for cid in ("clip-one", "clip-two"):
        (orphan / "clips" / f"{cid}.json").write_text(
            (BUNDLE / "clips" / f"{cid}.json").read_text()
        )

    reset_store()
    os.environ["CATALOG_LOCAL_DIR"] = str(orphan)
    try:
        sid = await _session_for(db_session, "admin")
        assert (await _get(app, "/api/catalog/clips/clip-one", sid)).status_code == 200
        assert (await _get(app, "/api/catalog/clips/clip-two", sid)).status_code == 404
    finally:
        os.environ["CATALOG_LOCAL_DIR"] = str(BUNDLE)
        reset_store()


async def test_a_traversing_manifest_is_refused_and_leaks_nothing(db_session, monkeypatch):
    application = _configure(monkeypatch, EVIL)
    try:
        sid = await _session_for(db_session, "guest")
        res = await _get(application, "/api/catalog", sid)
        assert res.status_code == 500
        assert res.json() == {"detail": "Catalog document is malformed."}
        assert "passwd" not in res.text
    finally:
        reset_store()


async def test_unconfigured_catalog_is_503_and_names_nothing(db_session, monkeypatch):
    application = _configure(monkeypatch, None)
    try:
        sid = await _session_for(db_session, "guest")
        res = await _get(application, "/api/catalog", sid)
        assert res.status_code == 503
        assert res.json() == {"detail": "Catalog is temporarily unavailable."}
        health = await _get(application, "/api/catalog/health", sid)
        assert health.status_code == 503
        assert health.json() == {
            "ok": False,
            "detail": "Catalog is temporarily unavailable.",
        }
        assert "CATALOG_LOCAL_DIR" not in health.text
    finally:
        reset_store()


# --- Caching and expiry -----------------------------------------------------------------

async def test_the_manifest_cache_serves_the_second_request(app, db_session):
    sid = await _session_for(db_session, "guest")
    assert (await _get(app, "/api/catalog", sid)).status_code == 200
    store = get_store()
    after_first = store.fetch_count
    assert after_first == 1
    assert (await _get(app, "/api/catalog", sid)).status_code == 200
    assert store.fetch_count == after_first


async def test_a_zero_ttl_cache_revalidates(db_session, monkeypatch):
    application = _configure(monkeypatch, CATALOG_MANIFEST_TTL="0")
    try:
        sid = await _session_for(db_session, "guest")
        await _get(application, "/api/catalog", sid)
        store = get_store()
        await _get(application, "/api/catalog", sid)
        assert store.fetch_count == 2
    finally:
        reset_store()


@pytest.mark.parametrize("path", ["/api/catalog", "/api/catalog/clips/clip-one"])
async def test_expires_at_is_present_and_in_the_future(app, db_session, path):
    sid = await _session_for(db_session, "guest")
    doc = (await _get(app, path, sid)).json()
    expires = datetime.fromisoformat(doc["expires_at"].replace("Z", "+00:00"))
    delta = (expires - datetime.now(timezone.utc)).total_seconds()
    assert 600 < delta <= 900


async def test_catalog_documents_are_never_shared_cached(app, db_session):
    sid = await _session_for(db_session, "guest")
    res = await _get(app, "/api/catalog", sid)
    assert res.headers["cache-control"] == "private, no-store"
    assert res.headers["vary"] == "Cookie"


# --- Local media streaming ------------------------------------------------------------

async def _video_url(app, db_session, role: str = "guest") -> tuple[str, str]:
    sid = await _session_for(db_session, role)
    doc = (await _get(app, "/api/catalog/clips/clip-one", sid)).json()
    return doc["media"]["video"]["stereo_sbs"], sid


async def test_local_driver_serves_the_whole_file(app, db_session):
    url, sid = await _video_url(app, db_session)
    res = await _get(app, url, sid)
    assert res.status_code == 200
    assert res.headers["accept-ranges"] == "bytes"
    assert res.headers["content-type"].startswith("video/mp4")
    assert res.content == bytes(i % 256 for i in range(1024))


async def test_local_driver_honours_range(app, db_session):
    url, sid = await _video_url(app, db_session)
    res = await _get(app, url, sid, headers={"Range": "bytes=0-9"})
    assert res.status_code == 206
    assert res.headers["content-range"] == "bytes 0-9/1024"
    assert res.content == bytes(range(10))

    tail = await _get(app, url, sid, headers={"Range": "bytes=-8"})
    assert tail.status_code == 206
    assert tail.headers["content-range"] == "bytes 1016-1023/1024"
    assert len(tail.content) == 8


async def test_local_driver_answers_416_and_head(app, db_session):
    url, sid = await _video_url(app, db_session)
    bad = await _get(app, url, sid, headers={"Range": "bytes=5000-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == "bytes */1024"

    async with _client(app) as client:
        head = await client.head(url, cookies={"sid": sid})
    assert head.status_code == 200
    assert head.headers["content-length"] == "1024"


async def test_local_media_url_is_a_capability_not_a_path(app, db_session):
    """Strip, tamper with or expire the signature and it is a 404 like any miss."""
    url, sid = await _video_url(app, db_session)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    unsigned = await _get(app, parsed.path)
    assert unsigned.status_code == 404
    assert unsigned.json() == {"detail": "Not found."}

    tampered = f"{parsed.path}?exp={query['exp'][0]}&sig={'0' * 64}"
    assert (await _get(app, tampered, sid)).status_code == 404

    expired = f"{parsed.path}?exp=1&sig={query['sig'][0]}"
    assert (await _get(app, expired, sid)).status_code == 404

    # A valid signature for one path does not open another.
    swapped = f"{LOCAL}media/clip-one/tactile/left.npz?{parsed.query}"
    assert (await _get(app, swapped, sid)).status_code == 404


# --- Health -----------------------------------------------------------------------------

async def test_health_reports_liveness_without_naming_our_infrastructure(app, db_session):
    guest = await _session_for(db_session, "guest")
    res = await _get(app, "/api/catalog/health", guest)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["clips"] == 2 and body["source"] == "local"
    assert "bucket" not in body and "prefix" not in body


async def test_health_gives_staff_the_operational_detail(app, db_session):
    admin = await _session_for(db_session, "admin")
    body = (await _get(app, "/api/catalog/health", admin)).json()
    assert body["bucket"] == "6thsense-catalog-media"
    assert body["region"] == "us-west-2"
    assert body["backend_fetches"] >= 1
