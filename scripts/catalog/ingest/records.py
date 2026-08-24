"""One take directory -> one full clip record, and its ClipSummary projection.

WHY the summary is projected rather than built: the contract calls the clip record a
"strict SUPERSET of the ClipSummary ... identical name, type and meaning". Two
independent builders would drift on the first field anyone edited, so we build the full
record once and cut the summary out of it with `summary_from_clip` -- which makes the
superset property true by construction rather than by review.

WHY nothing here guesses: an undeterminable field is written as `null`, the UI renders
it as an em-dash, and the report names the take that produced it. The one place we fail
CLOSED instead of to null is `rights` -- there is no "unknown" permission, so an
unreviewed clip reads `denied` on all four.
"""

from __future__ import annotations

import csv
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

from .benchmark import RIGHTS_KEYS, humanise, rfc3339, trim
from .probe import LayoutError, TakeLayout, VideoProbe, build_media, classify_role
from .tactile import TactileResult
from .validate import build_qa, build_sync

PERMISSIONS = ("granted", "denied", "on_request")
PII_VALUES = ("passed", "pending", "failed", "not_required")
CAPTURES = ("stereo_egocentric", "mono_egocentric")
_SNAKE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
SPLITS = ("train", "val", "test")
# Only these five may appear in `modalities`, and every one has a file pointer in `media`.
# `extra_modalities` in a take config is checked against this set AND against the pointer
# actually being non-null, because a chip on the card that resolves to no file and no
# quality block is the overstatement the whole contract exists to prevent.
MODALITIES = ("video", "tactile", "imu", "segcap", "calibration")
_SUMMARY_SCALARS = ("id", "slug", "title", "description_short", "category", "subcategory",
                    "country", "recorded_month", "capture", "duration_s", "resolution", "fps",
                    "modalities", "hands", "subjects", "bytes", "split")
_PRIVACY_SUMMARY = ("faces_redacted", "consent_on_file", "pii_review")
_QA_SUMMARY = ("grade", "disposition", "checks_warn", "checks_fail",
               "video_frames_dropped", "tactile_crc_pass_rate", "usable_channels",
               # A grade with no sync-validation state next to it lets a card claim
               # quality for a clip whose alignment nothing physical corroborates.
               "tactile_coverage", "sync_validated")


def read_structured(path: Path) -> dict[str, Any]:
    """Read a .toml / .json / .yaml sidecar.

    YAML works when PyYAML happens to be installed but is deliberately NOT pinned:
    requirements.txt stays at jsonschema + numpy, and TOML is in the standard library.
    """
    suffix = path.suffix.lower()
    if suffix == ".toml":
        with path.open("rb") as fh:
            return tomllib.load(fh)
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix not in (".yaml", ".yml"):
        raise LayoutError(f"{path} has an unsupported extension; use .toml, .json or .yaml")
    try:
        import yaml  # noqa: PLC0415 -- optional, resolved at call time by design
    except ImportError as exc:
        raise LayoutError(f"{path} is YAML but PyYAML is not installed. `pip install pyyaml`, or "
                          f"rename it to {path.with_suffix('.toml').name}.") from exc
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def clip_id_from(take_id: str) -> str:
    """`ego_20260823_000821_16A260` -> `ego-20260823-000821-16a260`, stable forever."""
    out = re.sub(r"[^a-z0-9]+", "-", take_id.lower()).strip("-")[:96].strip("-")
    if not out:
        raise LayoutError(f"take id {take_id!r} contains no alphanumeric characters")
    return out


def slugify(title: str | None, fallback: str, taken: set[str]) -> str:
    """URL form of the title, disambiguated with a numeric suffix on collision."""
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:88] or fallback
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def expand_template(template: str | None, clip_id: str, slug: str) -> str | None:
    """Verbatim substitution; both ids are already [a-z0-9-] so nothing needs escaping."""
    return None if not template else template.replace("{id}", clip_id).replace("{slug}", slug)


def build_rights(cfg: dict, collection: dict,
                 *, license_file_url: str | None = None) -> tuple[dict, list[str]]:
    """Four independent permissions plus the paperwork behind them.

    Fails CLOSED. If the rights review has not happened, the correct and only honest
    value is `denied` -- there is deliberately no null and no "unknown", because a blank
    that renders as an implied grant is how a buyer ends up in court.
    """
    src, warn, out = cfg.get("rights") or {}, [], {}
    for key in RIGHTS_KEYS:
        value = src.get(key)
        if value not in PERMISSIONS:
            warn.append(f"rights.{key}={value!r} is not one of {PERMISSIONS}; failing closed"
                        if value is not None else f"rights.{key} not stated; failing closed to 'denied'")
            value = "denied"
        out[key] = value
    lic = collection.get("license") or {}
    out |= {"license_id": trim(src.get("license_id", lic.get("id")), 64),
            "license_name": trim(src.get("license_name", lic.get("name")), 160),
            # The schema names the per-take LICENSE.txt as the canonical bundled licence
            # location, so a take that ships one gets it for free rather than leaving the
            # field null and asserting permissions with no document behind them.
            "license_url": src.get("license_url") or license_file_url
                           or (lic.get("url") if isinstance(lic.get("url"), str) else None),
            "restrictions": [trim(r, 500) for r in (cfg.get("restrictions") or [])],
            "attribution_required": src.get("attribution_required"),
            "holder": trim(src.get("holder", (collection.get("vendor") or {}).get("name")), 200),
            "determined_utc": rfc3339(src.get("determined_utc")),
            "notes": trim(src.get("notes"), 2000)}
    if out["determined_utc"] is None and any(out[k] != "denied" for k in RIGHTS_KEYS):
        warn.append("a permission is granted but rights.determined_utc is null: no human review "
                    "is on record for a permission we are asserting")
    if out["license_url"] is None and any(out[k] != "denied" for k in RIGHTS_KEYS):
        warn.append("a permission is softer than 'denied' but rights.license_url is null: there "
                    "is no licence document behind the permission we are asserting")
    return out, warn


def build_privacy(cfg: dict) -> tuple[dict, list[str]]:
    """H6 record. Unassessed stays null -- counsel reads null as worse than false."""
    src, pii = cfg.get("privacy") or {}, (cfg.get("privacy") or {}).get("pii_review")
    warn = [f"privacy.{k} not stated; shipping null, which renders as an em-dash"
            for k in _PRIVACY_SUMMARY if src.get(k) is None]
    for key in ("notice_given", "identifiable_persons", "identifiable_premises",
                "redaction", "retention", "consent"):
        if src.get(key) is None:
            warn.append(f"privacy.{key} not stated; shipping null. H6 asks for it by name.")
    if pii is not None and pii not in PII_VALUES:
        warn.append(f"privacy.pii_review={pii!r} is not one of {PII_VALUES}; shipping null")
        pii = None
    # NOT defaulted to true. It is a LICENCE TERM, and the ingest is in no position to
    # assert one on a take whose operator did not state it -- least of all on a clip whose
    # licence_url is null. false here means "we do not assert this", which is exactly the
    # state a take that never said so is in.
    reid = src.get("reidentification_prohibited")
    if reid is None:
        warn.append("privacy.reidentification_prohibited not stated; shipping false. This is a "
                    "licence term and the ingest will not assert one on the operator's behalf.")
    return {"faces_redacted": src.get("faces_redacted"), "pii_review": pii,
            "consent_on_file": src.get("consent_on_file"), "notice_given": src.get("notice_given"),
            "identifiable_persons": src.get("identifiable_persons"),
            "identifiable_premises": src.get("identifiable_premises"),
            "redaction": src.get("redaction"), "retention": src.get("retention"),
            "consent": src.get("consent"), "notes": trim(src.get("notes"), 2000),
            "reidentification_prohibited": bool(reid)}, warn


def build_segments(path: Path | None) -> tuple[list[dict], list[str]]:
    """segcap/segments.csv -> ordered Segment rows. Empty is a determined answer."""
    if path is None:
        return [], []
    if path.suffix == ".json":
        return sorted(json.loads(path.read_text(encoding="utf-8")), key=lambda s: s["t0_s"]), []
    out, warn = [], []
    with path.open(newline="", encoding="utf-8") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            try:
                t0, t1 = float(row["t0_s"]), float(row["t1_s"])
            except (KeyError, TypeError, ValueError):
                warn.append(f"{path.name}:{lineno} has no parseable t0_s/t1_s; row skipped")
                continue
            if t1 <= t0:
                warn.append(f"{path.name}:{lineno} ends at or before it starts; row skipped")
                continue
            out.append({"index": 0, "t0_s": t0, "t1_s": t1,
                        "label": trim(row.get("label"), 120) or "segment",
                        "description": trim(row.get("description"), 2000),
                        "verb": trim(row.get("verb"), 48), "source": row.get("source") or "human",
                        "objects": [o.strip() for o in (row.get("objects") or "").split(";") if o.strip()]})
    out.sort(key=lambda s: s["t0_s"])
    for i, seg in enumerate(out):
        seg["index"] = i
    return out, warn


def build_package_contents(layout: TakeLayout, digests: dict[Path, str],
                           url: Callable[[Path | None], str | None]) -> tuple[list[dict], int | None]:
    """Every delivered file with size, digest and role -- H2's manifest, in machine form."""
    entries, total = [], 0
    for path in layout.files:
        size = path.stat().st_size
        total += size
        rel = path.relative_to(layout.take_dir).as_posix()
        entries.append({"path": rel, "url": url(path), "bytes": size,
                        "sha256": digests.get(path), "role": classify_role(rel)})
    return entries, (total if entries else None)


def _pick(key: str, *sources: dict) -> Any:
    """First non-null value for `key` across the sources, in priority order."""
    for src in sources:
        if isinstance(src, dict) and src.get(key) is not None:
            return src[key]
    return None


def build_calibration(layout: TakeLayout, meta: dict, cfg: dict, *, imu_status: str,
                      grid: list[int] | None, index_rule: str | None,
                      pitch_mm: float | None) -> tuple[dict | None, str, list[str]]:
    """H7 values, not files -- the files are in `media.calibration`.

    The camera block prefers `calibration_delivered.json` over the raw solve: shipping
    only the raw solve plus a prose note about how to transform it is how a rig ends up
    with 19.6 px of rectification error instead of the 0.20 px it actually achieves.

    Every H7 value is looked for in the CALIBRATION FILES first and the take config only
    as an operator override. Reading them from take.yaml alone -- which is what this did
    -- meant a rig that shipped a complete cam-IMU solve, a rolling-shutter readout time
    and a full IMU noise characterisation still published four nulls and reached grade A
    with H7 entirely unmet.

    Returns (record, effective imu status, warnings).
    """
    warn: list[str] = []
    raw = read_structured(layout.calibration_raw) if layout.calibration_raw else {}
    deliv = read_structured(layout.calibration_delivered) if layout.calibration_delivered else {}
    meta_cal = meta.get("calibration") or {}
    src = deliv or raw
    # Priority: what the operator typed, then the file a consumer is told to apply, then
    # the raw solve, then whatever the packaging pipeline transcribed.
    chain = (cfg, deliv, raw, meta_cal)
    camera = None
    if src:
        cams = []
        for cid in ("cam0", "cam1", "cam"):
            block = src.get(cid)
            if isinstance(block, dict):
                k = block.get("K") or [[None] * 3] * 3
                cams.append({"id": cid, "role": block.get("role") or block.get("position"),
                             "fx": k[0][0], "fy": k[1][1], "cx": k[0][2], "cy": k[1][2],
                             "distortion": block.get("dist")})
        st, res = src.get("stereo") or {}, deliv.get("measured_rectification_residual_px")
        mstereo = meta_cal.get("stereo") or {}
        camera = {"model": src.get("distortion_model"), "image_size": src.get("image_size"),
                  "cameras": cams, "shutter": _pick("shutter", *chain),
                  "readout_time_ms": _pick("readout_time_ms", *chain),
                  "stereo": None if not st else {"R": st.get("R"), "T": st.get("T"),
                                                 "baseline_m": st.get("baseline_m")},
                  "rms_reprojection_px": (raw.get("stereo") or {}).get("rms_px") or mstereo.get("rms_px"),
                  "rectification_residual_px": (res.get("using_this_file")
                                                if isinstance(res, dict) else None),
                  "note": trim(src.get("note") or mstereo.get("intrinsics_scale_note"), 1500)}
        if camera["readout_time_ms"] is None and camera["shutter"] == "rolling":
            warn.append("calibration: shutter is rolling but no readout_time_ms was solved, so "
                        "rolling-shutter motion cannot be compensated (H7 gap)")
    i = _pick("imu", *chain) or {}
    noise = ("accel_noise_density", "accel_random_walk",
             "gyro_noise_density", "gyro_random_walk")
    characterised = any(i.get(k) is not None for k in noise) and i.get("rate_hz") is not None
    status = imu_status
    if status == "operational" and not characterised:
        # "operational" is a claim about usability. An inertial stream with no noise
        # density and no declared rate cannot be fed to any fusion pipeline, so calling it
        # operational is a claim we cannot support; `unverified` is the honest enum value.
        status = "unverified"
        warn.append("calibration.imu.status downgraded from 'operational' to 'unverified': the "
                    "stream produces samples but has no noise characterisation and no declared "
                    "rate, so it is unusable for VIO (H7)")
    imu = {"model": trim(i.get("model"), 64), "status": status, "rate_hz": i.get("rate_hz"),
           "accel_range_g": i.get("accel_range_g"), "gyro_range_dps": i.get("gyro_range_dps"),
           "accel_noise_density": i.get("accel_noise_density"), "axes": i.get("axes"),
           "accel_random_walk": i.get("accel_random_walk"),
           "gyro_noise_density": i.get("gyro_noise_density"),
           "gyro_random_walk": i.get("gyro_random_walk"), "units_note": trim(i.get("units_note"), 300)}
    cam_imu = _pick("cam_imu", *chain)
    if cam_imu is None and camera is not None:
        warn.append("calibration: no camera-IMU extrinsics or time offset ship with this take "
                    "(H7 gap); nothing downstream can fuse the two")
    tactile = None if not grid else {"grid": grid, "index_rule": trim(index_rule, 300),
                                     "taxel_pitch_mm": pitch_mm,
                                     "force_calibration": meta_cal.get("tactile_force")}
    if camera is None and tactile is None and status in ("absent", "unverified"):
        return None, status, warn
    return {"camera": camera, "imu": imu, "cam_imu": cam_imu, "tactile": tactile}, status, warn


def build_provenance(layout: TakeLayout, meta: dict, cfg: dict, *,
                     pipeline: str) -> tuple[dict, list[str]]:
    """Reproducible from the pipeline, except `operator`, a pseudonym by policy."""
    operator, warn = cfg.get("operator"), []
    if operator and ("@" in str(operator) or " " in str(operator)):
        warn.append(f"provenance.operator={operator!r} looks like a name or an email. The operator "
                    f"is a data subject; use a pseudonym such as op-01. Shipping null instead.")
        operator = None
    task = meta.get("task") or {}
    # `recorded` unless the take says otherwise, in as many words. A generator that
    # forgets to declare itself is a bug in the generator; defaulting the other way
    # would relabel every real capture the moment the key were misspelt.
    media_class = str(meta.get("media_class") or cfg.get("media_class") or "recorded")
    if media_class not in ("recorded", "synthetic"):
        warn.append(f"media_class={media_class!r} is not 'recorded' or 'synthetic'; "
                    f"treating this take as synthetic, which is the safe direction.")
        media_class = "synthetic"
    return {"take_id": trim(meta.get("take_id") or layout.take_id, 128),
            "media_class": media_class,
            "device_id": trim(meta.get("device_id") or cfg.get("device_id"), 64),
            "firmware": trim(meta.get("firmware") or cfg.get("firmware"), 64),
            "operator": trim(operator, 64), "pipeline_version": pipeline,
            "recorded_local": trim(meta.get("recorded_local"), 64),
            "packaged_utc": rfc3339(meta.get("packaged_utc")),
            "session_id": trim(cfg.get("session_id") or meta.get("session_id"), 128),
            "note": trim(meta.get("recorded_local_note"), 1000),
            "environment": trim(cfg.get("environment") or task.get("environment"), 200)}, warn


@dataclass
class ClipInputs:
    """Everything one clip record needs, gathered by the CLI before assembly."""

    layout: TakeLayout
    clip_id: str
    slug: str
    cfg: dict
    collection: dict
    metadata: dict | None
    probe: VideoProbe | None
    tactile: TactileResult
    imu_preview: dict | None
    imu_status: str
    imu_f32_url: str | None
    segments: list[dict]
    package: list[dict]
    total_bytes: int | None
    urls: dict[str, str | None]
    media_url: Callable[[Path | None], str | None]
    frame_timestamps: int | None
    checksums_verified: bool | None
    pipeline: str
    split: str | None = None
    cfr_divergence_ms: float | None = None
    license_file_url: str | None = None
    geometry: dict = field(default_factory=dict)
    extra_limitations: list[str] = field(default_factory=list)


# Each auto-generated limitation carries a topic pattern. When the take's own metadata
# already says the same thing in its own words, the auto one is dropped -- dedupe on the
# first sixty alphanumerics silently kept both halves of "Peak-over-taxels traces are an
# ENVELOPE" and "The tactile peak trace is an ENVELOPE", which is how a limitations list
# starts reading like filler.
_LIMITATION_TOPICS: tuple[tuple[str, str], ...] = (
    ("no_segments", r"no (temporal )?annotation|there are no segments"),
    ("no_metadata", r"shipped no metadata document"),
    ("no_frame_times", r"per-frame timestamp index"),
    ("raw_counts", r"raw adc counts|no calibration to newtons"),
    ("peak_envelope", r"envelope, not a sensor|peak.{0,40}envelope"),
    ("no_readout_time", r"readout time"),
    ("no_cam_imu", r"camera-imu"),
    ("no_sync_validation", r"independent (physical )?(common-mode )?(sync )?event|shared host clock"),
    ("crc_vendor_reported", r"vendor-reported|crc_ok flag"),
    ("no_split", r"train/val/test|no split"),
)


def _limitation_id(text: str) -> str:
    """A stable id for a limitation, so the same statement never ships twice."""
    low = text.lower()
    for key, pattern in _LIMITATION_TOPICS:
        if re.search(pattern, low):
            return key
    return "text:" + re.sub(r"[^a-z0-9]+", "", low)[:80]


def _check_limitations(qa: dict) -> list[str]:
    """One plain-language entry per check that did not pass, quoting the numbers.

    CONTRACT.md defines grade C as "accepted with a NAMED caveat". A measured exceedance
    that produces a `warn` buried in the fourth tab and nothing in `known_limitations` is
    the opposite of that: the machine knew, and the buyer had to go looking. So every
    non-pass check states itself here, with its measured value, its bound and its units.
    """
    out: list[str] = []
    for c in qa.get("checks") or []:
        if c["result"] not in ("warn", "fail"):
            continue
        unit = f" {c['units']}" if c.get("units") and c["units"] != "fraction" else ""
        measured = c.get("measured_value")
        if isinstance(measured, float):
            measured = f"{measured:.4g}"
        verb = "FAILS" if c["result"] == "fail" else "misses"
        out.append(
            f"QA check `{c['check_id']}` {verb} its bound: measured {measured}{unit} against "
            f"{c.get('threshold')}{unit}."
            + (f" {c['note']}" if c.get("note") else ""))
    return out


def _auto_limitations(ci: ClipInputs, sync: dict | None, calib: dict | None) -> list[str]:
    """State the structural gaps ourselves. Measured misses come from `_check_limitations`."""
    tp, cam = ci.tactile.preview or {}, (calib or {}).get("camera") or {}
    candidates = (
        (not ci.segments, "No temporal annotation ships with this clip: `segments` is empty and "
         "the Segcap tab is disabled."),
        (ci.metadata is None, "The source pipeline shipped no metadata document, so "
         "synchronisation, calibration provenance and the channel census could not be transcribed."),
        (ci.layout.frame_times is None and ci.probe is not None, "No per-frame timestamp index "
         "ships, so the H2 frame-count-equals-timestamp-count check could not be run and container "
         "PTS is the only timing available."),
        (tp.get("units") == "raw_adc_counts",
         "Tactile values are raw ADC counts; no calibration to newtons or kPa exists."),
        (bool(tp.get("peak_series")), "The tactile peak trace is an ENVELOPE, not a sensor: the "
         "argmax channel can change between adjacent samples, so an apparent rise may be two taxels."),
        (ci.tactile.crc_source == "vendor_reported",
         "tactile_crc_pass_rate is vendor-reported: it counts the `crc_ok` flag column the capture "
         "daemon wrote into the delivered array. The on-wire bytes are not shipped, so no consumer "
         "-- and no part of this ingest -- can recompute it independently."),
        (bool(calib) and cam.get("readout_time_ms") is None, "Image readout time is not "
         "characterised, so rolling-shutter motion on a head-mounted camera cannot be compensated "
         "(H7 gap)."),
        (bool(calib) and calib.get("cam_imu") is None,
         "No camera-IMU extrinsics or time offset have been solved (H7 gap)."),
        (bool(sync) and sync.get("validation_result") == "not_validated", "Alignment rests on a "
         "shared host clock; there is no independent common-mode physical event to validate it."),
        (ci.split is None, "No train/val/test split is assigned to this clip, so any number "
         "computed against it cannot be compared with anyone else's."),
    )
    return [text for cond, text in candidates if cond]


def _identity(cfg: dict, layout: TakeLayout, clip_id: str, meta: dict) -> tuple[dict, list[str]]:
    """Title, taxonomy, country and month -- the values no machine can derive."""
    warn = []
    stereo = "stereo_sbs" in layout.video or {"left", "right"} <= set(layout.video)
    capture = cfg.get("capture")
    capture = capture if capture in CAPTURES else ("stereo_egocentric" if stereo else "mono_egocentric")
    title = trim(cfg.get("title"), 120)
    if not title:
        title = trim(humanise(clip_id.replace("-", "_")), 120)
        warn.append(f"no title in take config; derived {title!r} from the directory name")
    category = cfg.get("category")
    if not (isinstance(category, str) and _SNAKE.fullmatch(category)):
        warn.append(f"category={category!r} missing or not lower_snake_case; 'uncategorised'")
        category = "uncategorised"
    sub = cfg.get("subcategory")
    if sub is not None and not _SNAKE.fullmatch(str(sub)):
        warn.append(f"subcategory={sub!r} is not lower_snake_case; shipping null")
        sub = None
    country = cfg.get("country")
    if country is not None and not re.fullmatch(r"[A-Z]{2}", str(country)):
        warn.append(f"country={country!r} is not an ISO 3166-1 alpha-2 code; shipping null")
        country = None
    if country is None:
        warn.append("no country: the card shows an em-dash and the clip drops out of every country "
                    "filter. It cannot be inferred -- a +08:00 offset spans nine countries.")
    month = cfg.get("recorded_month") or (meta.get("recorded_local") or "")[:7]
    month = month if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(month or "")) else None
    return {"capture": capture, "title": title, "category": category, "subcategory": sub,
            "country": country, "recorded_month": month}, warn


def build_clip(ci: ClipInputs) -> tuple[dict, list[str]]:
    """Assemble the full clip record. Returns (record, warnings)."""
    meta, cfg = ci.metadata or {}, ci.cfg
    task = meta.get("task") or {}
    ident, warn = _identity(cfg, ci.layout, ci.clip_id, meta)
    hands = ci.tactile.hands
    has_cal = bool(ci.layout.calibration_raw or ci.layout.calibration_delivered)
    # A modality is listed only when the stream is present AND `media` has a non-null
    # pointer at it. An operator's `extra_modalities` is not an escape hatch around that:
    # a chip that filters, that adds its full duration to facets.modality[].hours and that
    # resolves to no file is the overstatement this contract exists to prevent.
    present = {*(["video"] if ci.probe else []), *(["tactile"] if hands else []),
               *(["imu"] if ci.imu_preview else []), *(["segcap"] if ci.segments else []),
               *(["calibration"] if has_cal else [])}
    for extra in (cfg.get("extra_modalities") or []):
        if extra not in MODALITIES:
            warn.append(f"extra_modalities lists {extra!r}, which is not one of {MODALITIES}. "
                        f"A modality with no slot in `media` cannot be listed; dropped.")
        elif extra in present:
            warn.append(f"extra_modalities lists {extra!r}, which the ingest already detected; "
                        f"the declaration is redundant and was ignored.")
        else:
            warn.append(f"extra_modalities lists {extra!r} but no {extra} stream was found in "
                        f"the take, so `media.{extra}` would be null; dropped.")
    modalities = sorted(present)
    streams = [*(["video"] if ci.probe else []), *(f"tactile_{h}" for h in hands),
               *(["imu"] if ci.imu_preview else [])]
    description = trim(cfg.get("description") or task.get("description"), 20000)
    short = trim(cfg.get("description_short"), 160) or (
        trim(re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0], 160) if description else None)

    duration = ci.probe.duration_s if ci.probe and ci.probe.duration_s else meta.get("duration_s")
    duration = float(duration or 0.0) or 1.0

    rights, w = build_rights(cfg, ci.collection, license_file_url=ci.license_file_url); warn += w
    privacy, w = build_privacy(cfg); warn += w
    provenance, w = build_provenance(ci.layout, meta, cfg, pipeline=ci.pipeline); warn += w
    sync = build_sync(meta, streams=streams, hands=hands, duration_s=duration,
                      cfr_divergence_ms=ci.cfr_divergence_ms)
    calib, _imu_status, w = build_calibration(
        ci.layout, meta, cfg, imu_status=ci.imu_status, grid=ci.geometry.get("grid"),
        index_rule=ci.geometry.get("index_rule"), pitch_mm=ci.geometry.get("taxel_pitch_mm"))
    warn += w
    qa, w = build_qa(ci, sync=sync, calibration=calib, rights=rights, privacy=privacy); warn += w

    seen: set[str] = set()
    limitations: list[str] = []
    for item in [*_check_limitations(qa), *(meta.get("known_limitations") or []),
                 *(cfg.get("known_limitations") or []), *ci.extra_limitations,
                 *_auto_limitations(ci, sync, calib)]:
        text = trim(item, 1000)
        if not text:
            continue
        key = _limitation_id(text)
        if key not in seen:
            seen.add(key)
            limitations.append(text)

    clip = {"schema": "6s-clip/1.0", "id": ci.clip_id, "slug": ci.slug, "split": ci.split, **ident,
            "description_short": short, "description": description,
            "duration_s": duration,
            "resolution": ci.probe.resolution if ci.probe else None,
            "fps": ci.probe.fps if ci.probe else None,
            "modalities": modalities, "hands": hands, "bytes": ci.total_bytes,
            "subjects": cfg.get("subjects", task.get("subjects")),
            "poster": ci.urls.get("poster"), "preview": ci.urls.get("preview"),
            "detail": ci.urls.get("detail"), "rights": rights, "privacy": privacy, "qa": qa,
            "media": build_media(ci.layout, capture=ident["capture"], probe=ci.probe, meta=meta,
                                 url=ci.media_url, trim=trim, imu_f32=ci.imu_f32_url),
            "imu_preview": ci.imu_preview, "tactile_preview": ci.tactile.preview,
            "segments": ci.segments, "package_contents": ci.package,
            "sync": sync, "calibration": calib, "provenance": provenance,
            "metadata": ci.metadata, "known_limitations": limitations}
    return clip, warn


def summary_from_clip(clip: dict, paths: dict[str, str | None]) -> dict:
    """Cut the ClipSummary out of the full record.

    Three-state on poster/preview/detail: OMIT when the value equals the expanded
    template (the UI re-derives it, saving ~125 B a clip), carry an explicit null when
    the asset genuinely does not exist, carry the string otherwise.
    """
    out: dict[str, Any] = {k: clip[k] for k in _SUMMARY_SCALARS}
    out["rights"] = {k: clip["rights"][k] for k in RIGHTS_KEYS}
    out["privacy"] = {k: clip["privacy"][k] for k in _PRIVACY_SUMMARY}
    out["qa"] = {k: clip["qa"][k] for k in _QA_SUMMARY}
    for key in ("poster", "preview", "detail"):
        value = clip.get(key)
        if value is None:
            out[key] = None
        elif value != expand_template(paths.get(key), clip["id"], clip["slug"]):
            out[key] = value
    return out
