"""The document layer: where the asset URLs are, and which a role may not have.

Both tables live here, next to each other, on purpose. The commercial boundary
is enforced by nulling a pointer BEFORE anything is signed, so the two facts
that must never disagree are "where are the URLs" and "which of them is this
role denied". Splitting them across modules is how a reviewer once found an
`investor` holding an unredacted record whose every pointer then 404'd.

Two access levels, derived from the role and nothing else:

  full     customer, founder, admin   — the delivered package, unchanged
  preview  guest, investor            — the sales surface

What `preview` GETS: the whole manifest, every metadata field, QA, rights,
privacy, sync, the calibration VALUES, the inline segments, posters, the silent
hover loop, the rendered tactile stills, the derived IMU/peak sidecars the
charts draw, the per-take documentation, **the privacy redaction record**, and
**the encoded mp4** — the clip a prospect actually watches. A catalog you cannot
watch does not sell anything.

The two tactile RENDERS beside that mp4 are on the list for the same reason:
`media.video.overview`, the clip with the palms, the raw grid and the force bars
composited onto it, and `media.video.closeup`. They are pixels, not payload --
no per-taxel value can be read back out of a render. They are also the only way
a prospect sees the tactile stream moving in lockstep with the video, which is
the whole proposition; the arrays under `media.tactile` that would let them USE
it stay withheld exactly as before.

The redaction record is on that list deliberately. It is a RIGHTS artefact, not
payload: it says what was searched for, under which policy version, by whom and
when. Withholding it withholds the only evidence for the claim it exists to
support, and counsel screening the dataset asks for it in their first reply.

What `preview` does NOT get, and why each one is a file rather than a fact:
per-frame timestamps, the full-rate IMU CSV/binary, the per-hand tactile .npz
arrays and their geometry sidecar, the segment-caption CSV, the calibration
FILES, the single-file archive, and every per-file download link in
`package_contents`. Each becomes `null`, which is the same signal the UI already
reads to disable a control, and every one of them is named in the `access`
block so the record says "available on request" instead of pretending the thing
does not exist.

`package_contents` keeps its `path`, `bytes` and `sha256`: that is the integrity
evidence a buyer's engineer screens on, and it describes the package without
opening it. Only `url` is nulled.

Redaction runs BEFORE presigning. A withheld asset is therefore never signed at
all — there is no URL to leak, not even an expired one.

THE OPEN EVALUATION CLIP
------------------------

One clip is exempt from part of that list, and the exemption is the difference
between a brochure and an evaluation.

The product's differentiator is time alignment. The list above withholds
`frame_times.csv` — the file the sync notes instruct consumers to "ALWAYS index
the video by" — the per-hand tactile arrays and the geometry sidecar that makes
them indexable. Withholding all three from every clip means nothing on the page
is independently checkable: every figure is vendor-asserted, on a corpus the
page also says is synthetic, and the one action that moves a prospect from
browsing to a procurement call — running a single package through their own
loader — is the one thing they cannot do.

So `collection.sample_archive.clip_id` names one clip that ships complete at
preview level: its archive, its per-frame timestamps, one hand's `.npz` and the
sensor geometry that indexes it. Everything else stays exactly as withheld as
before, on that clip and on every other. It costs a few MB.

Naming is NOT authorisation. `is_open_clip()` re-derives the commercial test
from the clip's OWN `rights` object — all four permissions `granted` — before it
exempts a single path. The ingest already applies that rule when it chooses the
sample (`_open_sample` in catalog_ingest.py), and this is the second lock: a
hand-edited manifest, or one built by an older ingest, that points at a clip
whose rights are anything less opens nothing at all.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


# --- Roles -------------------------------------------------------------------

LEVEL_FULL = "full"
LEVEL_PREVIEW = "preview"

FULL_ROLES = frozenset({"customer", "founder", "admin"})
PREVIEW_ROLES = frozenset({"guest", "investor"})
#: Every role that may read the catalog at all.
CATALOG_ROLES = FULL_ROLES | PREVIEW_ROLES
#: Roles that may see operational detail (bucket, prefix) on /health.
STAFF_ROLES = frozenset({"founder", "admin"})


def access_level(role: str | None) -> str:
    """The one predicate. Anything not explicitly `full` is `preview`."""
    return LEVEL_FULL if role in FULL_ROLES else LEVEL_PREVIEW


# --- Copy ---------------------------------------------------------------------

HOW_TO_REQUEST = (
    "Email data@6thsense.dev to request the delivered package, an evaluation "
    "licence, or access to the withheld files for a specific clip."
)

PREVIEW_NOTICE = (
    "Preview access: every clip's metadata and encoded video are available on "
    "this account. Raw sidecars, per-hand tactile arrays, calibration files and "
    "per-file downloads are available on request."
)


# --- Where the asset URLs are -------------------------------------------------
#
# A path is a tuple of keys; "[]" means "each element of this list". Only these
# locations are ever rewritten into a signed URL. Signing is spec-driven and not
# a heuristic scan, which is what keeps us from mangling the verbatim `metadata`
# passthrough — it is full of package-INTERNAL paths that are not catalog assets
# and must survive untouched.

Path = tuple[str, ...]

MANIFEST_ASSET_PATHS: tuple[Path, ...] = (
    ("collection", "license", "url"),
    ("collection", "sample_archive", "url"),
    ("clips", "[]", "poster"),
    ("clips", "[]", "preview"),
)

CLIP_ASSET_PATHS: tuple[Path, ...] = (
    ("poster",),
    ("preview",),
    ("privacy", "redaction", "record_url"),
    ("media", "video", "stereo_sbs"),
    ("media", "video", "left"),
    ("media", "video", "right"),
    ("media", "video", "mono"),
    ("media", "video", "overview"),
    ("media", "video", "closeup"),
    ("media", "video", "frame_times"),
    ("media", "imu", "csv"),
    ("media", "imu", "f32"),
    ("media", "tactile", "left"),
    ("media", "tactile", "right"),
    ("media", "tactile", "layout"),
    ("media", "tactile", "preview_png", "[]"),
    ("media", "segcap", "json"),
    ("media", "calibration", "raw"),
    ("media", "calibration", "delivered"),
    ("media", "docs", "readme"),
    ("media", "docs", "datasheet"),
    ("media", "docs", "license"),
    ("media", "docs", "sync_protocol"),
    ("media", "docs", "checksums"),
    ("media", "archive", "url"),
    ("imu_preview", "sidecar", "url"),
    ("tactile_preview", "peak_series", "sidecar", "url"),
    ("tactile_preview", "frames", "[]", "png"),
    ("package_contents", "[]", "url"),
)


# --- What preview access does not get ------------------------------------------

@dataclass(frozen=True)
class Withheld:
    path: Path
    label: str


WITHHELD_CLIP: tuple[Withheld, ...] = (
    Withheld(("media", "video", "frame_times"), "per-frame timestamps (frame_times.csv)"),
    Withheld(("media", "imu", "csv"), "full-rate IMU CSV"),
    Withheld(("media", "imu", "f32"), "full-rate IMU binary"),
    Withheld(("media", "tactile", "left"), "per-hand tactile arrays (.npz)"),
    Withheld(("media", "tactile", "right"), "per-hand tactile arrays (.npz)"),
    Withheld(("media", "tactile", "layout"), "tactile sensor geometry sidecar"),
    Withheld(("media", "segcap", "json"), "segment-caption CSV"),
    Withheld(("media", "calibration", "raw"), "calibration files"),
    Withheld(("media", "calibration", "delivered"), "calibration files"),
    Withheld(("media", "archive"), "single-file package archive"),
    Withheld(("package_contents", "[]", "url"), "per-file download links"),
    # NOT withheld: ("privacy", "redaction", "record_url"). See the module
    # docstring — the redaction audit record is the evidence for a rights claim,
    # and a claim whose evidence is withheld from the reader is just a claim.
)

WITHHELD_MANIFEST: tuple[Withheld, ...] = (
    Withheld(("collection", "sample_archive", "url"), "sample package archive"),
)

#: Every asset location that preview access may be denied, as a flat set. The
#: presigning walk asserts against this: a withheld path must never be signed.
WITHHELD_PATHS: frozenset[Path] = frozenset(
    w.path for w in WITHHELD_CLIP + WITHHELD_MANIFEST
)


# --- The open evaluation clip ---------------------------------------------------

#: The four per-clip permissions, all of which must read `granted` before any part
#: of a clip is opened to preview access. Same rule the ingest applies when it picks
#: the sample; re-derived here because naming a clip in the manifest is a pointer,
#: not a grant.
GRANTED_RIGHTS: tuple[str, ...] = (
    "model_training",
    "commercial_use",
    "redistribution",
    "derived_model",
)

#: What the open evaluation clip does NOT have withheld. Chosen to be exactly the
#: set that makes the headline claim CHECKABLE and nothing more:
#:
#:   frame_times   the per-frame host receive times. The sync notes say to index the
#:                 video by frame_idx and look the time up here; without it a buyer
#:                 cannot verify a single alignment figure on the page.
#:   tactile.left  ONE hand's array. Enough to load, decode and compare against the
#:                 published channel census; not the delivered pair.
#:   tactile.layout the geometry sidecar. An .npz with no index rule is a blob — this
#:                 is a few kB of JSON and without it the array above is unusable, so
#:                 shipping one without the other would be a gesture, not an offer.
#:   archive       the same bytes as collection.sample_archive.url. Reachable one way
#:                 and null the other is the kind of disagreement this module exists
#:                 to prevent.
#:
#: Deliberately still withheld, on this clip as on every other: the full-rate IMU
#: CSV and binary, the SECOND hand's array, the segment-caption CSV, the calibration
#: files and every per-file download link.
OPEN_CLIP_EXEMPT: frozenset[Path] = frozenset(
    {
        ("media", "video", "frame_times"),
        ("media", "tactile", "left"),
        ("media", "tactile", "layout"),
        ("media", "archive"),
    }
)

OPEN_CLIP_NOTICE = (
    "Open evaluation clip: this one clip ships complete at preview level — the "
    "package archive, per-frame timestamps, the left glove's tactile array and the "
    "sensor geometry that indexes it — so every figure published about it can be "
    "recomputed rather than taken on trust."
)


def rights_fully_granted(clip: Any) -> bool:
    """True only when all four permissions on THIS clip read `granted`."""
    rights = clip.get("rights") if isinstance(clip, dict) else None
    if not isinstance(rights, dict):
        return False
    return all(rights.get(key) == "granted" for key in GRANTED_RIGHTS)


def open_clip_id(manifest: Any) -> str | None:
    """The clip the manifest offers as its open sample, or None.

    Reads `collection.sample_archive.clip_id` and nothing else. Whether that clip is
    actually opened is decided by `is_open_clip`, against the clip's own rights.
    """
    collection = manifest.get("collection") if isinstance(manifest, dict) else None
    sample = collection.get("sample_archive") if isinstance(collection, dict) else None
    clip_id = sample.get("clip_id") if isinstance(sample, dict) else None
    return clip_id if isinstance(clip_id, str) and clip_id else None


def is_open_clip(clip: Any, open_id: str | None) -> bool:
    """Both locks: the manifest names it AND its own rights are granted end to end."""
    if not open_id or not isinstance(clip, dict) or clip.get("id") != open_id:
        return False
    return rights_fully_granted(clip)


def withheld_clip_spec(open_clip: bool) -> tuple[Withheld, ...]:
    """The withhold spec that applies to one clip at preview level."""
    if not open_clip:
        return WITHHELD_CLIP
    return tuple(w for w in WITHHELD_CLIP if w.path not in OPEN_CLIP_EXEMPT)


# --- Path walking --------------------------------------------------------------

def _visit(node: Any, path: Path, fn: Callable[[Any, Any], None]) -> None:
    """Call `fn(container, key)` at every leaf `path` names. Missing is fine."""
    if node is None or not path:
        return
    head, rest = path[0], path[1:]
    if head == "[]":
        if not isinstance(node, list):
            return
        for index, item in enumerate(node):
            if rest:
                _visit(item, rest, fn)
            else:
                fn(node, index)
        return
    if not isinstance(node, dict):
        return
    if not rest:
        if head in node:
            fn(node, head)
        return
    _visit(node.get(head), rest, fn)


def _dedupe(labels: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for label in labels:
        seen.setdefault(label, None)
    return list(seen)


# --- Redaction -----------------------------------------------------------------

def withhold(doc: dict, spec: tuple[Withheld, ...]) -> list[str]:
    """Null every path in `spec`, in place. Returns the labels actually applied.

    A path that is already null contributes no label: telling a buyer we
    withheld a file that does not exist for this clip is a lie in the other
    direction.
    """
    labels: list[str] = []

    for item in spec:
        hit = False

        def _null(container: Any, key: Any, _item: Withheld = item) -> None:
            nonlocal hit
            if container[key] is not None:
                container[key] = None
                hit = True

        _visit(doc, item.path, _null)
        if hit:
            labels.append(item.label)
    return _dedupe(labels)


def access_block(level: str, withheld: list[str]) -> dict:
    """The machine-readable access notice carried by every response.

    `notice` is the PREVIEW notice and lives here rather than being folded into
    `collection.notice`. The two say different things — one is the producer's
    standing caveat about the data, the other is this account's access level —
    and concatenating them under one 300-character cap silently deleted the
    first for exactly the role that most needs to read it. Two fields, two
    lines on the page, nothing dropped.
    """
    return {
        "level": level,
        "withheld": withheld,
        "how_to_request": HOW_TO_REQUEST if level != LEVEL_FULL else None,
        "notice": PREVIEW_NOTICE if level != LEVEL_FULL else None,
    }


# --- Templates -----------------------------------------------------------------

def expand_template(template: Any, clip: dict) -> str | None:
    """`posters/{id}.jpg` + a clip -> `posters/ego-....jpg`, or None.

    Verbatim substitution: {id} and {slug} are already restricted to [a-z0-9-]
    by the schema, so no percent-encoding is required or permitted.
    """
    if not isinstance(template, str) or not template:
        return None
    out = template
    for key in ("id", "slug"):
        token = "{" + key + "}"
        if token in out:
            value = clip.get(key)
            if not isinstance(value, str) or not value:
                return None
            out = out.replace(token, value)
    return out


def _templates(manifest: dict) -> dict:
    collection = manifest.get("collection")
    paths = collection.get("paths") if isinstance(collection, dict) else None
    return paths if isinstance(paths, dict) else {}


def materialise(clip: dict, templates: dict) -> None:
    """Fill in a clip's poster/preview from the collection templates.

    The contract says an ABSENT key means "expand the template" and a
    present-and-null key means "there is no such asset". Once we sign, the
    template is useless to the client — a signature cannot be templated — so the
    server expands it and the served manifest carries explicit values.
    """
    for kind in ("poster", "preview"):
        if kind not in clip:
            clip[kind] = expand_template(templates.get(kind), clip)


# --- Presentation ---------------------------------------------------------------

Signer = Callable[[str], str]

#: An ExternalUrl (a licence deed, a vendor page) is absolute, points outside
#: the bundle and is not ours to sign. The match is deliberately narrow: only a
#: real `scheme://` or `//host` passes through. Anything else that merely looks
#: odd — `C:\\x`, `mailto:`, a stray backslash — goes to the signer, which
#: rejects it and turns the malformed bundle into a logged 500.
_EXTERNAL_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:)?//")


def _is_external(value: str) -> bool:
    return bool(_EXTERNAL_RE.match(value.strip()))


def sign_asset_urls(doc: dict, paths: tuple[Path, ...], signer: Signer) -> int:
    """Rewrite every asset URL named by `paths` into a signed URL, in place."""
    count = 0

    def _sign(container: Any, key: Any) -> None:
        nonlocal count
        value = container[key]
        if not isinstance(value, str) or not value.strip():
            return
        if _is_external(value):
            return
        container[key] = signer(value)
        count += 1

    for path in paths:
        _visit(doc, path, _sign)
    return count


def present_manifest(
    manifest: dict,
    *,
    level: str,
    signer: Signer,
    detail_url: Callable[[str], str],
    expires_at: str,
) -> dict:
    """The manifest as one role sees it: redacted, then signed, then annotated."""
    doc = copy.deepcopy(manifest)
    templates = _templates(doc)
    for clip in doc.get("clips") or []:
        if isinstance(clip, dict):
            materialise(clip, templates)

    # The open evaluation clip's archive is the one manifest pointer preview access
    # keeps, and it keeps it only when that clip's own rights are granted end to end.
    # Without it CollectionHeader never renders "Download sample clip" for a guest,
    # which is how the sales surface ended up with no way to evaluate anything.
    open_id = open_clip_id(doc)
    summary = next(
        (c for c in doc.get("clips") or [] if isinstance(c, dict) and c.get("id") == open_id),
        None,
    )
    manifest_spec = (
        () if is_open_clip(summary, open_id) else WITHHELD_MANIFEST
    )
    withheld = withhold(doc, manifest_spec) if level != LEVEL_FULL else []
    sign_asset_urls(doc, MANIFEST_ASSET_PATHS, signer)

    # `detail` is never signed: the clip record has to come back through this
    # API so it can be redacted too. Handing out a presigned URL to
    # clips/{id}.json would let a preview account read the unredacted record.
    for clip in doc.get("clips") or []:
        if isinstance(clip, dict) and isinstance(clip.get("id"), str):
            clip["detail"] = detail_url(clip["id"])

    collection = doc.get("collection")
    if isinstance(collection, dict):
        # Templates are spent: every clip now carries explicit values.
        collection["paths"] = {"detail": None, "poster": None, "preview": None}
        # `collection.notice` is the PRODUCER's standing caveat and is passed
        # through byte for byte at every access level. The preview notice is a
        # separate field (`access.notice`); see access_block().

    doc["access"] = access_block(level, withheld)
    doc["expires_at"] = expires_at
    doc["url_form"] = "resolved"
    return doc


def present_clip(
    clip: dict,
    *,
    level: str,
    signer: Signer,
    detail_url: Callable[[str], str],
    expires_at: str,
    templates: dict | None = None,
    open_id: str | None = None,
) -> dict:
    """One clip record as one role sees it. Same predicate as the manifest.

    `open_id` is `collection.sample_archive.clip_id`. Pass it and THIS clip is
    exempted from part of the withhold list — but only if it is that clip and its
    own four permissions all read `granted`. Omit it and nothing is exempt, which
    is the correct default for any caller that has not read the manifest.
    """
    doc = copy.deepcopy(clip)
    materialise(doc, templates or {})

    open_clip = is_open_clip(doc, open_id)
    spec = withheld_clip_spec(open_clip)
    withheld = withhold(doc, spec) if level != LEVEL_FULL else []
    sign_asset_urls(doc, CLIP_ASSET_PATHS, signer)

    if isinstance(doc.get("id"), str):
        doc["detail"] = detail_url(doc["id"])

    if level != LEVEL_FULL and withheld:
        limits = doc.get("known_limitations")
        doc["known_limitations"] = [
            *([OPEN_CLIP_NOTICE] if open_clip else []),
            PREVIEW_NOTICE + " Withheld here: " + ", ".join(withheld) + ".",
            *(limits if isinstance(limits, list) else []),
        ]

    doc["access"] = access_block(level, withheld)
    doc["expires_at"] = expires_at
    doc["url_form"] = "resolved"
    return doc
