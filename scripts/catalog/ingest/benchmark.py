"""Collection-level aggregates: facets, totals and the task-distribution benchmark.

WHY these three live together: they are the only things in the bundle computed ACROSS
clips rather than from a take directory, and they share one invariant -- the UI trusts
them and does not recompute. `facets[].clips` disagreeing with `clips[]` is not a
cosmetic bug; it is a filter that shows "Manipulation (42)" and then renders 41 cards.
Keeping the three derivations in one module means one place can be read to confirm
they all fold over the same list in the same way, and `validate.py` re-derives all
three independently as a cross-check.

WHY labels ship in the data: the UI carries no code table that can drift out of step
with the manifest. `label` is produced here, once, from the machine `value`.

This module also holds the three value-shaping helpers -- `humanise`, `trim` and
`rfc3339` -- that both the per-clip builders and the collection-level ones need. They
live at the bottom of the import graph on purpose: anywhere else and records.py,
validate.py and this file would form a cycle.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from collections.abc import Iterable

# The brand ramp, in stacking order. Taken from the site's own tokens (--dark, --accent,
# --accent-muted, --muted) so a chart rendered from this manifest matches the page it
# sits on without the UI hardcoding anything.
BRAND_RAMP: tuple[str, ...] = ("#14120c", "#592202", "#a69a60", "#5a5236", "#8a6a52", "#c2b89a")

# Our own series, when `[benchmark.series]` says nothing. --dark from the site tokens.
DEFAULT_SERIES_COLOR = "#14120c"

RIGHTS_KEYS = ("model_training", "commercial_use", "redistribution", "derived_model")

# ---------------------------------------------------------------------------
# Units
#
# WHY this is not simply "hours": the delivered corpus is ~30 clips of 30-45 s, so
# about twenty MINUTES. Quoting an hours axis for it produces bars of 0.0027 and a
# "0.04 hours" stat tile -- which a buyer reads as either a rendering fault or a
# padded number, and both cost more than the unit ever saved. The unit is therefore
# chosen from the data, once, here, and PUBLISHED, so the chart and the header
# cannot disagree and no consumer has to re-derive the rule.
# ---------------------------------------------------------------------------

UNITS = ("auto", "hours", "minutes", "clips")

# The crossover. Below two hours a minutes axis is the readable one; at or above it
# minute counts run to four digits and hours win. Two hours -- not one -- because a
# 90-minute corpus still reads better as "90 min" than as "1.5 h".
AUTO_HOURS_MIN_SECONDS = 2 * 3600.0

_SECONDS_PER = {"hours": 3600.0, "minutes": 60.0}

_SERIES_ID_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
_RETRIEVED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BenchmarkConfigError(ValueError):
    """`[benchmark]` in collection.toml is wrong in a way we refuse to paper over."""


class UnlabelledCountryError(BenchmarkConfigError):
    """A clip carries a country code we cannot name in English. The build stops.

    WHY this is fatal rather than a fallback. `country_label` used to return the bare
    code for anything it did not recognise, and the result validated perfectly: the
    schema requires a non-empty `label`, and "HK" is a non-empty string. So the filter
    bar rendered `HK (12)` next to `China (18)` and nobody could tell whether that was
    a deliberate abbreviation or a missing entry in a lookup table -- which is exactly
    the class of silent drift the "labels ship in the data" rule exists to stop.

    The fix at the call site is one of two lines, and the message says both: add the
    code to `_COUNTRY_NAMES` here, or set `country_labels = {XX = "Name"}` in the
    collection config when the vendor wants their own wording.
    """


def resolve_unit(unit: str | None, total_seconds: float) -> str:
    """Config unit -> the unit actually emitted. `auto` picks from the data."""
    name = (unit or "auto").strip().lower()
    if name not in UNITS:
        raise BenchmarkConfigError(
            f"benchmark.unit={unit!r} is not one of {', '.join(UNITS)}")
    if name != "auto":
        return name
    return "hours" if total_seconds >= AUTO_HOURS_MIN_SECONDS else "minutes"


def series_id(value: str) -> str:
    """Any human string -> the closed `^[a-z0-9]+(_[a-z0-9]+)*$` the schema requires."""
    slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value).lower())).strip("_")
    if not _SERIES_ID_RE.fullmatch(slug):
        raise BenchmarkConfigError(
            f"cannot derive a series id from {value!r}: it has no alphanumerics")
    return slug


@dataclass(frozen=True)
class Comparison:
    """A third-party corpus quoted next to ours, with the citation that backs it."""
    id: str
    label: str
    hours: float
    source_url: str
    retrieved: str
    color: str | None = None


def parse_comparisons(cfg: dict) -> list[Comparison]:
    """Read `[[benchmark.comparison]]`, refusing anything that is not sourced.

    WHY the refusal is hard rather than a warning: the whole point of putting Ego4D
    on the same axis as us is that the buyer already knows Ego4D's real number. An
    unsourced figure next to theirs is not a rough estimate, it is a claim we cannot
    defend in the meeting where it is questioned -- so it does not get emitted, and
    the operator hears about it at build time rather than the buyer at demo time.
    """
    raw = (cfg.get("benchmark") or {}).get("comparison") or []
    if isinstance(raw, dict):          # a single [benchmark.comparison] table
        raw = [raw]
    if not isinstance(raw, list):
        raise BenchmarkConfigError(
            "benchmark.comparison must be a list of [[benchmark.comparison]] tables")

    out: list[Comparison] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        where = f"benchmark.comparison[{i}]"
        if not isinstance(entry, dict):
            raise BenchmarkConfigError(f"{where} is not a table")
        label = str(entry.get("label") or "").strip()
        if not label:
            raise BenchmarkConfigError(f"{where} has no label")
        source = str(entry.get("source_url") or "").strip()
        if not source:
            raise BenchmarkConfigError(
                f"{where} ({label}) has no source_url. A comparison series without a "
                f"citation is a number a buyer who knows the real one will catch; "
                f"supply the page the figure came from or delete the entry.")
        if not source.startswith(("https://", "http://")):
            raise BenchmarkConfigError(
                f"{where} ({label}) source_url must be an http(s) URL, got {source!r}")
        retrieved = str(entry.get("retrieved") or "").strip()
        if not _RETRIEVED_RE.fullmatch(retrieved):
            raise BenchmarkConfigError(
                f"{where} ({label}) needs `retrieved` as YYYY-MM-DD: a published corpus "
                f"grows, and an uncited date makes the figure unfalsifiable")
        try:
            hours = float(entry.get("hours"))
        except (TypeError, ValueError):
            raise BenchmarkConfigError(
                f"{where} ({label}) needs `hours` as a number") from None
        if not hours > 0:
            raise BenchmarkConfigError(f"{where} ({label}) hours must be > 0, got {hours}")
        cid = series_id(entry.get("id") or label)
        if cid in seen:
            raise BenchmarkConfigError(f"{where} ({label}) duplicates series id {cid!r}")
        seen.add(cid)
        color = entry.get("color")
        if color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
            raise BenchmarkConfigError(f"{where} ({label}) color must be #rrggbb")
        out.append(Comparison(cid, label, hours, source, retrieved,
                              str(color) if color else None))
    return out


def primary_series(cfg: dict) -> tuple[str, str, str]:
    """id, label and colour for OUR OWN series, from `[benchmark.series]`.

    Renaming the dataset a buyer sees in the legend is a one-line edit in
    collection.toml, never a code change.
    """
    spec = ((cfg.get("benchmark") or {}).get("series")) or {}
    if not isinstance(spec, dict):
        raise BenchmarkConfigError("[benchmark.series] must be a table")
    sid = series_id(spec.get("id") or cfg.get("id") or "6s-collection")
    label = str(spec.get("label") or cfg.get("name") or humanise(sid)).strip()
    color = str(spec.get("color") or DEFAULT_SERIES_COLOR)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise BenchmarkConfigError(f"benchmark.series.color must be #rrggbb, got {color!r}")
    return sid, label, color


def validate_benchmark_config(cfg: dict) -> list[Comparison]:
    """Everything about `[benchmark]` that can be judged before a single take is read.

    Called first thing by `build`, so a typo in collection.toml costs one second and an
    error message rather than a full ingest that dies on the manifest at the end.
    """
    bench = cfg.get("benchmark") or {}
    resolve_unit(bench.get("unit", "auto"), 0.0)          # enum check
    primary_series(cfg)
    comparisons = parse_comparisons(cfg)
    if bench.get("unit") == "clips" and comparisons:
        raise BenchmarkConfigError(
            "benchmark.unit='clips' cannot be mixed with [[benchmark.comparison]]: a "
            "published corpus quotes hours, not clip counts, and stacking the two puts "
            "two different units on one axis. Use unit='hours' or 'auto'.")
    return comparisons


def comparison_note(comparisons: Iterable[Comparison]) -> str | None:
    """The citation line the chart prints under the bars. None when there is nothing."""
    cites = "; ".join(
        f"{c.label} {c.hours:,.0f} h ({c.source_url}, retrieved {c.retrieved})"
        for c in comparisons)
    if not cites:
        return None
    return ("Third-party figures are whole-corpus totals published by their owners, not "
            f"per-task breakdowns, and are plotted as one bar each: {cites}.")

def corpus_shape_note(clips: list[dict], task_of, category_of=None) -> str | None:
    """One sentence stating clips-per-bar, so a flat chart reads as the truth.

    A ~30 clip / ~20 minute sample spread over 25 task labels puts roughly one clip in
    each bar. The chart is then a picket fence, and a staff engineer who has not been
    told the ratio reads it as padding -- which then taints the numbers that DO matter.
    Saying it in the manifest costs one line and removes the ambiguity.

    BOTH ROLL-UPS GET A RATIO when `category_of` is given. `benchmark.categories[]`
    ships alongside `benchmark.tasks[]` and the renderer picks one, so a note that
    quotes only the task fold is printed under a chart it does not describe -- ten
    category bars of three clips each, captioned "roughly one to two takes per task".
    That was live: docs/catalog/screenshots/chart-1440.png, before this change.

    Wording stays render-agnostic. The consumer draws bars for one fold and a table
    for the other, and a note that says "the bars" under a table is the same class of
    small untruth this whole module exists to stop.
    """
    tasks = {t for t in (task_of(c) for c in clips) if t is not None}
    if not tasks or not clips:
        return None
    per = len(clips) / len(tasks)
    n_t, n_c = len(tasks), len(clips)

    cats = set()
    if category_of is not None:
        cats = {c for c in (category_of(cl) for cl in clips) if c is not None}
    # Only worth a second clause when the category fold is genuinely coarser; a 1:1
    # restatement is not a second view and the UI will not offer it either.
    roll = ""
    if cats and len(cats) < len(tasks):
        roll = f", and {len(cats)} categories at {n_c / len(cats):.1f} takes each"

    if per < 2.0:
        return (f"{n_t} tasks across {n_c} clips -- roughly one to two takes per task"
                f"{roll}. This is a record of what was captured, not a distribution to "
                f"generalise from.")
    return f"{n_t} tasks across {n_c} clips ({per:.1f} takes per task){roll}."


_CAPTURE_LABELS = {"stereo_egocentric": "Stereo", "mono_egocentric": "Mono"}
_HAND_LABELS = {"left": "Left hand", "right": "Right hand", "both": "Both hands",
                # A REAL bucket, not a placeholder for a missing value. `hands` is never
                # null, so [] is a determined answer: this is the camera-only product.
                # Returning no bucket at all was worse than mislabelling it -- the clip
                # existed in the grid and in no Hands filter, so the one buyer who wants
                # exactly this product could not select it and could not count it.
                "none": "No gloves (camera only)"}
_ACRONYMS = {"imu": "IMU", "qa": "QA", "rgb": "RGB", "sbs": "SBS", "pii": "PII"}

# ISO 3166-1 alpha-2 -> English name. This is a LOOKUP TABLE, not a scope declaration:
# the delivered collection is CN and HK only (docs/catalog/INTAKE.md section 0), and the
# rest of these are here so a future drop from somewhere else is a one-word edit rather
# than a code change. A code that is NOT in here has no fallback -- `country_label`
# raises and the build stops. Returning the bare code was the old behaviour and it was
# wrong: "HK" is a non-empty string, so it validated, and it rendered as `HK (12)` next
# to `China (18)` where nobody could tell a missing entry from a chosen abbreviation.
_COUNTRY_NAMES = {
    "AE": "United Arab Emirates", "AT": "Austria", "AU": "Australia", "BE": "Belgium",
    "BR": "Brazil", "CA": "Canada", "CH": "Switzerland", "CN": "China", "CZ": "Czechia",
    "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "ES": "Spain", "FI": "Finland",
    "FR": "France", "GB": "United Kingdom", "HK": "Hong Kong", "HU": "Hungary",
    "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India", "IT": "Italy",
    "JP": "Japan", "KR": "South Korea", "MX": "Mexico", "MY": "Malaysia",
    "NL": "Netherlands", "NO": "Norway", "NZ": "New Zealand", "PH": "Philippines",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SE": "Sweden", "SG": "Singapore",
    "TH": "Thailand", "TR": "Turkey", "TW": "Taiwan", "UA": "Ukraine",
    "US": "United States", "VN": "Viet Nam", "ZA": "South Africa",
}


def humanise(value: str) -> str:
    """lower_snake_case -> 'Title case', with known acronyms preserved."""
    words = value.replace("-", "_").split("_")
    out = [_ACRONYMS.get(w.lower(), w) for w in words]
    first = out[0]
    head = first if first in _ACRONYMS.values() else first.capitalize()
    tail = [w if w in _ACRONYMS.values() else w.lower() for w in out[1:]]
    return " ".join([head, *tail])


def country_label(code: str, overrides: dict[str, str] | None = None) -> str:
    """English name for an alpha-2 code. An unnameable code FAILS the build.

    There is deliberately no fallback to the bare code: see `UnlabelledCountryError`.
    """
    if overrides and str(overrides.get(code) or "").strip():
        return str(overrides[code]).strip()
    name = _COUNTRY_NAMES.get(code)
    if not name:
        raise UnlabelledCountryError(
            f"country code {code!r} has no display label, so the country filter would show "
            f"a bare code where every other bucket shows a name. Fix it in one of two "
            f"places: add {code!r} to _COUNTRY_NAMES in ingest/benchmark.py (the ISO name), "
            f"or set country_labels = {{ {code} = \"...\" }} in the collection config. "
            f"The delivered corpus is CN and HK only -- see docs/catalog/INTAKE.md.")
    return name


def trim(text: Any, limit: int) -> str | None:
    """Respect a schema maxLength without silently dropping the whole field."""
    if text is None or text == "":
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def rfc3339(value: Any) -> str | None:
    """Normalise `2026-08-23T09:48:07+00:00` to the trailing-Z form the schema requires."""
    if not isinstance(value, str):
        return None
    text = value.strip().replace("+00:00", "Z")
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", text) else None


def _hours(clips: Iterable[dict]) -> float:
    return round(sum(float(c["duration_s"]) for c in clips) / 3600.0, 6)


def coverage_of(clip: dict) -> float | None:
    """The clip's tactile channel coverage, or None when no glove was worn.

    None and 0.0 are different answers and the difference is load-bearing: a video-only
    clip has no tactile hours at all, while a clip whose whole glove is dead has hours
    that are worth nothing. Only the second is a zero.
    """
    value = (clip.get("qa") or {}).get("tactile_coverage")
    return float(value) if isinstance(value, (int, float)) else None


def _usable_seconds(clip: dict) -> float:
    """Seconds of tactile weighted by how much of the glove actually reported."""
    cov = coverage_of(clip)
    return 0.0 if cov is None else float(clip["duration_s"]) * cov


def _facet(clips: list[dict], key_fn, label_fn) -> list[dict]:
    """Fold clips into buckets. `key_fn` returns 0..n machine values per clip.

    Every bucket carries wall-clock `hours` AND coverage-weighted `usable_hours`, because
    a bucket total that counts a clip with 173 of 484 working channels as a full hour is
    the specific arithmetic by which "10,000 hours" stops being true.
    """
    seconds: dict[str, float] = defaultdict(float)
    usable: dict[str, float] = defaultdict(float)
    counts: Counter[str] = Counter()
    for clip in clips:
        for value in key_fn(clip):
            counts[value] += 1
            seconds[value] += float(clip["duration_s"])
            usable[value] += _usable_seconds(clip)
    return [
        {
            "value": value,
            "label": label_fn(value),
            "clips": counts[value],
            "hours": round(seconds[value] / 3600.0, 6),
            "usable_hours": round(usable[value] / 3600.0, 6),
        }
        for value in sorted(counts)
    ]


def build_facets(clips: list[dict], *, country_overrides: dict[str, str] | None = None) -> dict:
    """Precomputed filter buckets. An empty facet is omitted so its control hides.

    Two of these deliberately do not partition the collection and the UI must not show
    them as percentages: `modality` (a clip contributes to every stream it carries) and
    `rights` (one bucket per permission, four per clip).
    """
    def hands_of(clip: dict) -> list[str]:
        """`[]` -> `none`, two hands -> `left`, `right` AND `both`.

        Like `modality` and `rights`, this facet does not partition the collection, and
        `none` is what makes the partition it does not form legible: every clip lands in
        at least one bucket, so the bucket counts add up to something a buyer can reason
        about instead of silently dropping the camera-only product on the floor.
        """
        hands = list(clip.get("hands") or [])
        if not hands:
            return ["none"]
        return [*hands, "both"] if len(hands) == 2 else hands

    facets = {
        "category": _facet(clips, lambda c: [c["category"]], humanise),
        "subcategory": _facet(
            clips, lambda c: [c["subcategory"]] if c.get("subcategory") else [], humanise
        ),
        "country": _facet(
            clips,
            lambda c: [c["country"]] if c.get("country") else [],
            lambda v: country_label(v, country_overrides),
        ),
        "capture": _facet(clips, lambda c: [c["capture"]], lambda v: _CAPTURE_LABELS.get(v, humanise(v))),
        "modality": _facet(clips, lambda c: list(c.get("modalities") or []), humanise),
        "rights": _facet(
            clips,
            lambda c: [f"{k}_{c['rights'][k]}" for k in RIGHTS_KEYS],
            lambda v: _rights_label(v),
        ),
        "hands": _facet(clips, hands_of, lambda v: _HAND_LABELS.get(v, humanise(v))),
        "split": _facet(clips, lambda c: [c["split"]] if c.get("split") else [], humanise),
        "qa_grade": _facet(clips, lambda c: [c["qa"]["grade"]], lambda v: f"Grade {v}"),
    }
    return {name: buckets for name, buckets in facets.items() if buckets}


def _rights_label(value: str) -> str:
    """`model_training_on_request` -> 'Model training: on request'."""
    for key in RIGHTS_KEYS:
        if value.startswith(key + "_"):
            return f"{humanise(key)}: {value[len(key) + 1:].replace('_', ' ')}"
    return humanise(value)


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list. Never empty."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_values[int(k)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


#: One video frame, in milliseconds, when the clip does not say what its frame rate is.
#: 30 fps is the rig's rate; a clip with no fps is counted against it rather than
#: being quietly excluded from the "over one frame" count.
_FALLBACK_FPS = 30.0


def sync_aggregate(clips: list[dict], details: dict[str, dict] | None) -> dict:
    """H1, at the collection level: the measured worst case, and how common it is.

    H1 says report the MEASURED maximum, not a claim. A collection header that quotes
    a typical alignment and leaves the maximum in the 29th detail record is the single
    most common way a sync caveat is laundered on its way to a buyer, so the maximum,
    the 95th percentile and the count of clips worse than one video frame are all
    computed here and published in `totals`.

    `sync_clips_independently_validated` is counted for the same reason and is the
    figure that says what the others are WORTH. A max alignment error is arithmetic on
    a shared host clock; a clip is independently validated only when a common-mode
    physical event (a clap, visible in video and sharp on both gloves) corroborates
    that arithmetic. Twenty of thirty clips in the reference corpus have no such event,
    and the only place that said so was the tail of the Calib & sync tab, one clip at a
    time -- so the collection-level count is published here and the header states it
    next to the error it qualifies.

    `details` maps clip id -> the full record (`sync` lives there, not in the summary).
    Absent or empty, every figure is null and `sync_clips_measured` is 0 -- which reads
    as "we did not measure this", and must never be mistaken for a good number.
    """
    measured: list[float] = []
    over_frame = 0
    validated = 0
    for clip in clips:
        doc = (details or {}).get(clip.get("id")) or {}
        sync = doc.get("sync")
        if isinstance(sync, dict) and sync.get("validation_result") == "pass":
            validated += 1
        value = sync.get("maximum_alignment_error_ms") if isinstance(sync, dict) else None
        if not isinstance(value, (int, float)):
            continue
        measured.append(float(value))
        fps = clip.get("fps") or doc.get("fps") or _FALLBACK_FPS
        try:
            frame_ms = 1000.0 / float(fps)
        except (TypeError, ValueError, ZeroDivisionError):
            frame_ms = 1000.0 / _FALLBACK_FPS
        if float(value) > frame_ms:
            over_frame += 1
    if not measured:
        return {
            "sync_clips_measured": 0,
            "sync_max_alignment_error_ms": None,
            "sync_p95_alignment_error_ms": None,
            "sync_clips_over_one_frame": None,
            # Counted over the whole corpus, not over the measured subset: a clip with
            # no measured error is also a clip nothing corroborated.
            "sync_clips_independently_validated": validated,
        }
    measured.sort()
    return {
        "sync_clips_measured": len(measured),
        "sync_max_alignment_error_ms": round(measured[-1], 3),
        "sync_p95_alignment_error_ms": round(_percentile(measured, 0.95), 3),
        "sync_clips_over_one_frame": over_frame,
        "sync_clips_independently_validated": validated,
    }


def provenance_class(clips: list[dict], details: dict[str, dict] | None) -> str:
    """`recorded`, `synthetic` or `mixed`, folded over the per-take declaration.

    Unknown counts as `synthetic`: a take that did not say is not evidence of a real
    recording, and the whole point of this field is that the buyer is told before they
    look at a frame rather than after.
    """
    seen = set()
    for clip in clips:
        prov = ((details or {}).get(clip.get("id")) or {}).get("provenance") or {}
        seen.add(prov.get("media_class") if prov.get("media_class") in
                 ("recorded", "synthetic") else "synthetic")
    if not seen:
        return "recorded"
    if seen == {"recorded"}:
        return "recorded"
    if seen == {"synthetic"}:
        return "synthetic"
    return "mixed"


def build_totals(
    clips: list[dict],
    *,
    subjects: int | None,
    sessions: int | None,
    details: dict[str, dict] | None = None,
) -> dict:
    """Headline aggregates.

    `bytes` is null when ANY clip's size is unknown: a partial sum presented as a total
    is a lie, and it is exactly the kind of lie a buyer catches by downloading. `hours`
    stays a float -- 0.023 h is the honest figure for one 84.6 s sample and rounding it
    to 0 hides the whole story.

    `duration_unit` is the unit those hours SHOULD BE RENDERED IN, resolved by the same
    rule the chart uses (>= 2 h reads in hours, below that in minutes). The stored
    figures stay in hours so nothing downstream has to guess at a scale factor; the
    header multiplies by 60 when this says `minutes`. Publishing the resolved unit is
    what stops a "0.04 hours" stat tile sitting next to a minutes axis on the same page.
    """
    sizes = [c.get("bytes") for c in clips]
    months = sorted({c["recorded_month"] for c in clips if c.get("recorded_month")})
    tactile = [c for c in clips if coverage_of(c) is not None]
    return {
        "clips": len(clips),
        "hours": _hours(clips),
        "duration_unit": resolve_unit(
            "auto", sum(float(c["duration_s"]) for c in clips)),
        "tactile_hours": _hours(tactile),
        "tactile_usable_hours": round(sum(_usable_seconds(c) for c in clips) / 3600.0, 6),
        "subjects": subjects,
        "sessions": sessions,
        "bytes": None if any(s is None for s in sizes) else int(sum(sizes)),
        "countries": sorted({c["country"] for c in clips if c.get("country")}),
        "categories": sorted({c["category"] for c in clips}),
        "date_range": [months[0], months[-1]] if months else None,
        **sync_aggregate(clips, details),
    }


def _roll(clips: list[dict], series_of, key_of) -> tuple[list[str], dict, Counter, list[str]]:
    """Fold clips into bars keyed by `key_of`, in first-seen order.

    Returns (bar order, seconds[bar][series], clips-per-bar, series ids in first-seen
    order). Tasks and categories are the SAME fold over the SAME clips with a different
    key, so they share this function: two hand-written loops is how a category roll-up
    ends up totalling something the task bars above it do not.
    """
    seconds: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: Counter[str] = Counter()
    order: list[str] = []
    series_ids: list[str] = []
    for clip in clips:
        sid, bar = series_of(clip), key_of(clip)
        if sid is None or bar is None:
            continue
        if sid not in series_ids:
            series_ids.append(sid)
        if bar not in order:
            order.append(bar)
        seconds[bar][sid] += float(clip["duration_s"])
        counts[bar] += 1
    return order, seconds, counts, series_ids


def build_benchmark(
    clips: list[dict],
    *,
    series_of,
    task_of,
    category_of=None,
    unit: str = "auto",
    series_labels: dict[str, str] | None = None,
    series_colors: dict[str, str] | None = None,
    comparisons: Iterable[Comparison] = (),
    note: str | None = None,
) -> dict | None:
    """Stacked-bar data for the 'Task distribution' chart, or None to hide the section.

    Render-ready by construction: no nesting, no sparse keys, no derived totals. A
    series contributing nothing to a task is OMITTED from that task's values map rather
    than written as 0, which is what keeps the manifest small at 30 bars.

    Magnitudes are accumulated in SECONDS and converted once, at the end, because the
    unit is not known until the total is: `auto` reads `minutes` for a twenty-minute
    corpus and `hours` for a real one, and a chart whose bars are all 0.0027 is not a
    chart. `unit` on the returned dict is the resolved one -- never `auto`.

    TWO ROLL-UPS SHIP, not one. `tasks` is keyed by subcategory and is what the corpus
    actually holds: ~24 bars over ~30 clips, one to two clips each, which is a picket
    fence rather than a distribution (`corpus_shape_note` says so in words). `categories`
    is the same clips folded to ~10 bars by `ClipSummary.category`, which is the view a
    buyer can actually read at a glance. The renderer picks; it does NOT aggregate, and
    it must not, because it holds no clip->category map and would have to reverse one out
    of the labels. Both lists carry the same `unit`, the same `series`, and the same
    total, because they are the same fold (`_roll`) over the same clips.

    The 'Overall | Top 20' toggle is a pure UI operation (sort by stack sum, slice 20)
    and needs no extra data, so none is emitted.
    """
    comparisons = list(comparisons)
    if not clips and not comparisons:
        return None
    if category_of is None:
        category_of = lambda c: c.get("category")  # noqa: E731

    order, seconds, clip_counts, series_ids = _roll(clips, series_of, task_of)
    cat_order, cat_seconds, cat_counts, cat_series = _roll(clips, series_of, category_of)
    cat_labels = {value: humanise(value) for value in cat_order}
    # A clip categorised but not tasked (or the reverse) still has to find its series in
    # `series`: the schema's contract is that every id in a values map is declared there,
    # and a legend that silently omits a stack segment is a chart with a hole in it.
    series_ids += [sid for sid in cat_series if sid not in series_ids]

    # A third-party corpus ships one number, so it gets one bar of its own rather than
    # an invented split across our task labels. See docs/catalog/INTAKE.md.
    own_bars = set(order) | set(cat_labels.values())
    for comp in comparisons:
        if comp.label in own_bars:
            raise BenchmarkConfigError(
                f"comparison label {comp.label!r} is also one of our own task or category "
                f"bars; the two would silently stack into one. Rename the comparison.")
        if comp.id in cat_labels:
            raise BenchmarkConfigError(
                f"comparison id {comp.id!r} is also one of our own category values; the "
                f"category roll-up keys on that value. Give the comparison an explicit id.")
        if comp.id not in series_ids:
            series_ids.append(comp.id)
        if comp.label not in order:
            order.append(comp.label)
        seconds[comp.label][comp.id] += comp.hours * 3600.0
        # The comparison appears once in EACH roll-up, so switching the chart between
        # 'by task' and 'by category' cannot make a cited corpus appear or disappear.
        cat_order.append(comp.id)
        cat_labels[comp.id] = comp.label
        cat_seconds[comp.id][comp.id] += comp.hours * 3600.0

    if not order:
        return None

    total_seconds = sum(v for bucket in seconds.values() for v in bucket.values())
    resolved = resolve_unit(unit, total_seconds)
    if resolved == "clips" and comparisons:
        raise BenchmarkConfigError(
            "benchmark.unit='clips' cannot be mixed with [[benchmark.comparison]]: a "
            "published corpus quotes hours, not clip counts, and stacking the two puts "
            "two different units on one axis. Use unit='hours' or 'auto'.")

    labels = series_labels or {}
    colors = {**{c.id: c.color for c in comparisons if c.color}, **(series_colors or {})}
    comp_labels = {c.id: c.label for c in comparisons}
    series = [
        {
            "id": sid,
            "label": labels.get(sid) or comp_labels.get(sid) or humanise(sid),
            "color": colors.get(sid, BRAND_RAMP[i % len(BRAND_RAMP)]),
        }
        for i, sid in enumerate(series_ids)
    ]
    divisor = _SECONDS_PER.get(resolved)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    cat_unit_counts: dict[str, Counter[str]] = defaultdict(Counter)
    if resolved == "clips":
        for clip in clips:
            sid = series_of(clip)
            if sid is None:
                continue
            if (task := task_of(clip)) is not None:
                counts[task][sid] += 1
            if (cat := category_of(clip)) is not None:
                cat_unit_counts[cat][sid] += 1

    # A series contributing nothing to a bar is OMITTED, not written as 0. `seconds`
    # carries every (bar, series) pair either way, so a zero-length clip still counts
    # as a clip when the unit is `clips`.
    def _values(bar: str, src: dict, tally: dict) -> dict[str, float]:
        if divisor is None:
            return {sid: n for sid, n in tally[bar].items() if n > 0}
        return {sid: round(v / divisor, 6) for sid, v in src[bar].items() if v > 0}

    # How many of OUR clips are behind each bar. Published, not derived by the UI,
    # because the UI has no way to recover it from a duration sum -- and it is the
    # number that decides whether a stacked bar chart is a distribution or a picket
    # fence. A comparison bar gets null: it is a whole-corpus total, not our clips.
    comparison_labels = {c.label for c in comparisons}
    comparison_ids = {c.id for c in comparisons}
    tasks = [
        {
            "label": task,
            "values": _values(task, seconds, counts),
            "clips": None if task in comparison_labels else clip_counts[task],
        }
        for task in order
    ]
    categories = [
        {
            "value": value,
            "label": cat_labels[value],
            "values": _values(value, cat_seconds, cat_unit_counts),
            "clips": None if value in comparison_ids else cat_counts[value],
        }
        for value in cat_order
    ]
    out = {"unit": resolved, "series": series, "tasks": tasks, "categories": categories}
    if note:
        out["note"] = trim(note, 800)
    return out


SPLITS = ("train", "val", "test")


def build_splits(cfg: dict, clips: list[dict], normalization: dict | None) -> dict | None:
    """The published train/val/test partition and the constants derived from it (H10).

    Returns None when no clip carries a split, because an empty partition published as if
    it were one is worse than admitting there is none. The normalisation constants are
    passed in already computed over the TRAIN clips only -- the scope is the whole point
    of the field, and `validate_bundle` recomputes it from clips[] and fails on a mismatch.
    """
    assigned = [c for c in clips if c.get("split") in SPLITS]
    if not assigned:
        return None
    buckets = _facet(assigned, lambda c: [c["split"]], humanise)
    order = {name: i for i, name in enumerate(SPLITS)}
    buckets.sort(key=lambda b: order.get(b["value"], len(SPLITS)))
    return {
        "policy": trim(cfg.get("split_policy"), 600),
        "buckets": buckets,
        "normalization": normalization,
    }


def build_collection(cfg: dict, clips: list[dict], *, paths: dict[str, str],
                     subjects: int | None, sessions: int | None,
                     splits: dict | None = None,
                     sample_archive: dict | None = None,
                     details: dict[str, dict] | None = None) -> dict:
    """The collection header: identity, vendor, licence, totals and path templates.

    `license` here is CONTEXT ONLY and the summary says so in words: H5 makes rights
    per-clip, and a clip's `rights` object always wins over anything stated at this
    level. A buyer's engineer has to be able to see that at a glance.
    """
    vendor, lic = cfg.get("vendor") or {}, cfg.get("license") or {}
    return {
        "id": cfg.get("id") or "6s-collection", "name": cfg.get("name") or "Untitled collection",
        "version": cfg.get("version") or "0.0.0",
        "description": " ".join(str(cfg.get("description") or "No description supplied.").split()),
        # The one line the header promotes. AUTHORED, never sliced off `description`:
        # taking "the first sentence or two" is a position rule, and a position rule
        # promotes whatever the writer put first, which is always the claim and never
        # the limit. Null when the drop did not author one -- the header then shows no
        # standfirst at all, which is better than showing an unqualified half of one.
        "standfirst": " ".join(str(cfg.get("standfirst") or "").split()) or None,
        "vendor": {"name": vendor.get("name") or "6thSense", "url": vendor.get("url"),
                   "contact": vendor.get("contact")},
        "license": {"id": lic.get("id"), "name": lic.get("name") or "No licence stated",
                    "url": lic.get("url"),
                    "summary": lic.get("summary") or "No licence has been settled for this "
                    "collection. Per-clip rights in each clip's rights object override this "
                    "and are authoritative."},
        "totals": build_totals(clips, subjects=subjects, sessions=sessions, details=details),
        "collection_wide_limitations": collection_wide_limitations(details),
        "paths": dict(paths), "splits": splits, "sample_archive": sample_archive,
        "provenance_class": provenance_class(clips, details),
        "notice": cfg.get("notice"),
    }


def _uniform_misses(details: dict[str, dict]) -> tuple[dict[str, list[str]], dict[str, str],
                                                        dict[str, int]]:
    """Checks that miss their bound on every clip they APPLY to, with the explaining note.

    The single definition of "collection-wide". `collection_wide_limitations` renders it and
    `measured_scope` stamps it onto the clip records, so the manifest and the clip pages
    cannot disagree about which checks describe the programme rather than the take.

    It has to be MEASURED and not a list of ids. A hand-maintained list said
    `privacy_redaction_record` was collection-wide; on a 30-clip corpus it warns on 10 of
    them, so ten clips would have filed a privacy warning of their own under a heading
    reading "applies to the whole collection, not to this clip" -- while the 10/30 tally
    also failed the uniformity test here, so no collection page would have stated it either.
    A check that varies has to stay on the clip that varies.

    THE DENOMINATOR IS THE CLIPS THE CHECK APPLIES TO, not the whole drop. A collection may
    hold both products, and a tactile check on a camera-only clip is `not_applicable` -- it
    has no opinion. Counting those as "did not miss" would mean one camera-only clip in a
    thirty-clip drop knocks a genuinely programme-wide tactile warning off collection scope
    and reprints it on twenty-nine tactile clip pages, which is the exact noise this
    function exists to remove. A clip that abstains does not get a vote either way.

    Two or more clips must apply, so a check that is inapplicable everywhere but one cannot
    be promoted to "collection-wide" off a single clip's warn.

    Returns (misses-by-check, note-by-check, applicable-count-by-check).
    """
    by_check: dict[str, list[str]] = {}
    notes: dict[str, str] = {}
    applicable: dict[str, int] = {}
    for doc in details.values():
        for c in ((doc.get("qa") or {}).get("checks") or []):
            if c.get("result") == "not_applicable":
                continue
            applicable[c["check_id"]] = applicable.get(c["check_id"], 0) + 1
            if c.get("result") in ("warn", "fail"):
                by_check.setdefault(c["check_id"], []).append(c["result"])
                notes.setdefault(c["check_id"], c.get("note") or "")
    uniform = {k: v for k, v in by_check.items()
               if applicable.get(k, 0) > 1 and len(v) == applicable[k]}
    return uniform, notes, applicable


def measured_scope(details: dict[str, dict]) -> set[str]:
    """The check ids that genuinely describe the whole collection, measured over `details`."""
    return set(_uniform_misses(details)[0]) if details else set()


def collection_wide_limitations(details: dict[str, dict] | None) -> list[dict]:
    """Checks that miss their bound identically on EVERY clip.

    These are not clip facts. `annotation_present`, `split_assigned`,
    `sync_independent_validation` and their neighbours describe the programme, not the
    take, and rendering them on each clip page repeats the same seven statements ten
    times. A buyer clicking through five clips reads them five times and concludes the
    data is riddled with problems, when in reality only two or three warnings per clip are
    specific to that clip.

    Nothing is hidden by moving them: the per-clip `checks` array is unchanged and still
    carries every one, machine-readable and re-derivable. This exists so the clip page can
    show what makes THAT clip different, and the collection page can state the shared
    limitations once, properly, where they belong.

    A `by_design` entry would be a decision with a published rationale rather than a
    shortfall. Nothing qualifies today: the one candidate, `split_assigned`, was justified
    by "one operator, one rig and one day", which this drop contradicts on rig, day and
    jurisdiction -- and `build_splits` returns None without a split, so the rationale had
    nowhere to ship even if it had been true. An unpublished split is a gap and is
    coloured as one.
    """
    if not details:
        return []
    by_check, notes, applicable = _uniform_misses(details)
    BY_DESIGN: set[str] = set()      # see the docstring; nothing earns this yet
    out = []
    for cid, results in sorted(by_check.items()):
        out.append({
            "check_id": cid,
            "result": results[0],
            "kind": "by_design" if cid in BY_DESIGN else "not_yet_measured",
            # The clips this applies to, which is len(details) unless some clip reported
            # it `not_applicable`. Printing the whole drop there would claim the statement
            # covers clips it has nothing to say about.
            "clips": applicable.get(cid, len(details)),
            "note": notes.get(cid) or None,
        })
    return out


def build_manifest(cfg: dict, clips: list[dict], *, paths: dict[str, str], generated_utc: str,
                   subjects: int | None, sessions: int | None, series_of, task_of,
                   category_of=None,
                   series_labels: dict[str, str] | None = None,
                   splits: dict | None = None,
                   sample_archive: dict | None = None,
                   details: dict[str, dict] | None = None) -> dict:
    """Assemble catalog.json: one fetch, everything the grid and the chart need."""
    # Resolved here as well as in build_benchmark, because the shape note has to
    # describe the SAME two folds the chart is handed.
    if category_of is None:
        category_of = lambda c: c.get("category")  # noqa: E731
    bench = cfg.get("benchmark") or {}
    comparisons = parse_comparisons(cfg)
    # The operator's own note, then the shape of the corpus, then the citations we
    # generate. The shape line is not optional: at one to two clips per task a stacked
    # bar chart is a picket fence, and a reader who is not told the ratio reads the
    # flatness as a rendering fault instead of as the truth about a 20-minute sample.
    note = " ".join(t for t in (trim(bench.get("note"), 400),
                                corpus_shape_note(clips, task_of, category_of),
                                comparison_note(comparisons)) if t) or None
    own_id, own_label, own_color = primary_series(cfg)
    return {
        "schema": "6s-catalog/1.0", "generated_utc": generated_utc,
        "collection": build_collection(cfg, clips, paths=paths, subjects=subjects,
                                       sessions=sessions, splits=splits,
                                       sample_archive=sample_archive, details=details),
        "facets": build_facets(clips, country_overrides=cfg.get("country_labels")),
        "benchmark": build_benchmark(clips, unit=bench.get("unit", "auto"),
                                     series_of=series_of, task_of=task_of,
                                     category_of=category_of,
                                     series_colors={own_id: own_color,
                                                    **(bench.get("colors") or {})},
                                     series_labels={own_id: own_label,
                                                    **(series_labels or {}),
                                                    **(bench.get("labels") or {})},
                                     comparisons=comparisons, note=note),
        "clips": clips,
    }
