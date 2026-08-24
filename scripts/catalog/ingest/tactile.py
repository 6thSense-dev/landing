"""tactile/*.npz -> `clip.tactile_preview`: census, peak envelope, geometry.

WHY the census is the headline: "how many channels actually work" is the first question
a buyer asks and the easiest one to answer misleadingly. A 22x22 glove has 484 readout
SITES; the take we ship has 278 working channels on the left hand. Three independent
fault modes each need their own rule -- silent channels never reported at all,
over-ceiling channels are pinned above any physical press, and intermittent channels
jump implausibly between adjacent samples. A census that reports only "working" hides
the third, which is precisely the one that corrupts time-axis analysis. So we count all
three separately and quote `stable`, never `live`.

WHY we stream the counts array: a .npz member is a deflated zip entry, so it cannot be
memory-mapped, and `np.load(...)['counts'].astype('f4') - baseline` allocates the uint16
array AND a float32 copy twice its size -- 60 MB for an 85 s take, linear in duration
with no ceiling. Instead we parse the .npy header off the zip stream and consume row
blocks, so peak memory is one chunk regardless of take length.

WHY the peak trace is decimated but the IMU sidecar is not: this is an ENVELOPE, not a
sensor. The argmax channel changes between adjacent samples on a quarter of the
reference take, so per-sample fidelity here would be false precision. We max-pool into
bins, which preserves every peak, and say so in the record.
"""

from __future__ import annotations

import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .imu import INLINE_MAX_READINGS
from .probe import sha256_file

HANDS = ("left", "right")
PEAK_MAX_POINTS = 4000
_ROW_CHUNK = 4096

# Defaults measured on our own hardware; overridable per take. See
# .context memory "Taxel noise + dead channels".
DEFAULT_CEILING_COUNTS = 600.0
DEFAULT_DISPLAY_FULL_SCALE = 300.0
DEFAULT_ADC_BITS = 16
_SLEW_COUNTS = 150.0
_SLEW_SAMPLE_FRACTION = 0.001

_SILENT_RULE = "counts.std(axis=0) == 0 over the whole take: the channel never reported anything."
_CEILING_RULE = (
    "delta exceeds {ceiling:.0f} counts anywhere in the take. A maximal human press reaches "
    "~{ceiling:.0f}; faulty channels jump straight past 2000, and the gap between the two "
    "populations is empty, so the threshold is unambiguous."
)
_INTERMITTENT_RULE = (
    "|diff(counts)| > {slew:.0f} counts between adjacent samples on more than "
    "{frac:.1%} of samples. Skin and sensor compliance cannot do that, so the channel "
    "is switching, not measuring."
)

_STILL_NAME = re.compile(
    r"^(?P<label>p\d{1,2}|max)_frame(?P<frame>\d+)_peak(?P<peak>\d+)_t(?P<t>[\d.]+)s\.png$", re.I
)


class TactileError(ValueError):
    """A glove array could not be read; the caller reports it against the take path."""


@dataclass
class HandData:
    """One glove's derived facts. Everything here is measured, nothing is assumed."""

    frames: int
    peak: np.ndarray  # float32, per raw sample, max over stable channels
    t_s: np.ndarray  # float64, seconds from the clip's zero
    census: dict
    reproduced: dict  # the census re-derived here, whatever the record ends up publishing
    census_source: str  # "producer_masks" | "rederived"
    crc_pass_rate: float | None
    frames_lost: int | None
    usable: int | None


@dataclass
class TactileResult:
    """The record plus the summary-level numbers the grid needs without re-reading."""

    preview: dict | None
    hands: list[str] = field(default_factory=list)
    usable_channels: dict = field(default_factory=lambda: {"left": None, "right": None})
    crc_pass_rate: float | None = None
    crc_by_hand: dict | None = None
    crc_source: str | None = None
    census_reproducible: dict | None = None
    frames_lost: dict | None = None
    warnings: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)


def _iter_row_chunks(npz: Path, member: str):
    """Yield row blocks of a 2-D .npy member without materialising the whole array."""
    with zipfile.ZipFile(npz) as zf:
        name = member if member in zf.namelist() else f"{member}.npy"
        with zf.open(name) as raw:
            version = np.lib.format.read_magic(raw)
            reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                      else np.lib.format.read_array_header_2_0)
            shape, fortran, dtype = reader(raw)
            if fortran or len(shape) != 2:
                raise TactileError(f"{npz.name}:{member} must be C-ordered 2-D, got {shape} f={fortran}")
            rows, cols = shape
            row_bytes = cols * dtype.itemsize
            done = 0
            while done < rows:
                take = min(_ROW_CHUNK, rows - done)
                buf = raw.read(row_bytes * take)
                if len(buf) != row_bytes * take:
                    raise TactileError(f"{npz.name}:{member} truncated at row {done}")
                yield np.frombuffer(buf, dtype=dtype).reshape(take, cols)
                done += take


def _small(npz: Path, key: str) -> np.ndarray | None:
    """One small 1-D member, or None when the producer did not ship it."""
    with np.load(npz) as data:
        return np.asarray(data[key]) if key in data.files else None


def _census_from_scan(npz: Path, baseline: np.ndarray, ceiling: float,
                      n_sites: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Derive (silent, over_ceiling, intermittent) masks in one streamed pass."""
    lo = np.full(n_sites, np.inf, dtype=np.float64)
    hi = np.full(n_sites, -np.inf, dtype=np.float64)
    viol = np.zeros(n_sites, dtype=np.int64)
    prev: np.ndarray | None = None
    total = 0
    for chunk in _iter_row_chunks(npz, "counts"):
        block = chunk.astype(np.float64, copy=False)
        np.minimum(lo, block.min(axis=0), out=lo)
        np.maximum(hi, block.max(axis=0), out=hi)
        joined = block if prev is None else np.vstack((prev, block))
        viol += (np.abs(np.diff(joined, axis=0)) > _SLEW_COUNTS).sum(axis=0)
        prev = block[-1:].copy()
        total += len(block)
    silent = lo == hi
    over = (hi - baseline) > ceiling
    live = ~silent & ~over
    frac = viol / max(total - 1, 1)
    intermittent = live & (frac > _SLEW_SAMPLE_FRACTION)
    return silent, over, intermittent


def _peak_series(npz: Path, baseline: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Peak-over-taxels per raw sample, restricted to the given channel mask."""
    idx = np.flatnonzero(mask)
    base = baseline[idx]
    out: list[np.ndarray] = []
    for chunk in _iter_row_chunks(npz, "counts"):
        delta = chunk[:, idx].astype(np.float32) - base
        np.maximum(delta, 0.0, out=delta)
        out.append(delta.max(axis=1) if idx.size else np.zeros(len(chunk), dtype=np.float32))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def _read_hand(npz: Path, *, ceiling: float, clip_t0_us: float | None,
               meta_census: dict | None) -> tuple[HandData, list[str]]:
    """Read one glove file into the facts the record needs."""
    warnings: list[str] = []
    baseline = _small(npz, "baseline")
    if baseline is None:
        raise TactileError(f"{npz} has no `baseline` array; a delta cannot be derived")
    baseline = baseline.astype(np.float64)
    n_sites = int(baseline.size)

    ok = _small(npz, "taxel_ok")
    live_mask = _small(npz, "taxel_live")
    stable_mask = _small(npz, "taxel_stable")

    # The census is ALWAYS re-derived from `counts`, even when the producer shipped its
    # own masks. "Every number it publishes is measured off a file" cannot be true of a
    # boolean array the capture daemon wrote, and `census.rules` exists so a consumer can
    # re-derive rather than trust -- which is worthless if we never did it ourselves.
    d_silent, d_over, d_intermittent = _census_from_scan(npz, baseline, ceiling, n_sites)
    d_live = ~d_silent & ~d_over
    d_stable = d_live & ~d_intermittent
    reproduced = {"silent": int(d_silent.sum()), "over_ceiling": int(d_over.sum()),
                  "intermittent": int(d_intermittent.sum()), "live": int(d_live.sum()),
                  "stable": int(d_stable.sum())}

    if live_mask is not None and stable_mask is not None and ok is not None:
        # The producer shipped its own masks. PUBLISH them: they are what the delivered
        # package's own `derive_delta` snippet refers to, so publishing different ones
        # here would make the catalog disagree with the bytes a buyer downloads. The
        # re-derivation above is kept as the cross-check, and any disagreement is
        # reported as a QA check rather than silently resolved either way.
        source = "producer_masks"
        over = ~ok.astype(bool)
        live = live_mask.astype(bool)
        stable = stable_mask.astype(bool)
        silent = ~live & ~over
        intermittent = live & ~stable
    else:
        warnings.append(f"{npz.name} ships no taxel masks; census re-derived from counts")
        source = "rederived"
        silent, over, intermittent, live, stable = (
            d_silent, d_over, d_intermittent, d_live, d_stable)

    peak = _peak_series(npz, baseline, stable if stable.any() else live)

    host_us = _small(npz, "host_us")
    if host_us is None or host_us.size != peak.size:
        warnings.append(f"{npz.name} has no usable host_us; the peak trace is placed by index")
        rate = 246.5
        t_s = np.arange(peak.size, dtype=np.float64) / rate
    else:
        zero = clip_t0_us if clip_t0_us is not None else float(host_us[0])
        t_s = (host_us.astype(np.float64) - zero) / 1e6

    # VENDOR-REPORTED, and the record says so. `crc_ok` is a boolean column the capture
    # daemon wrote; the on-wire bytes it was computed over are not in the delivered array,
    # so nothing here can recompute it. Counting a flag is not verifying a frame.
    crc = _small(npz, "crc_ok")
    crc_rate = float(np.count_nonzero(crc) / crc.size) if crc is not None and crc.size else None
    seq = _small(npz, "seq")
    lost: int | None = None
    if seq is not None and seq.size > 1:
        # uint32 sequence wraps; take the diff in the wider type then fold negatives.
        d = np.diff(seq.astype(np.int64))
        d = np.where(d < 0, d + (1 << 32), d)
        lost = int(np.clip(d - 1, 0, None).sum())

    # `rules` must describe the rule that produced the PUBLISHED numbers, or a consumer
    # who re-derives with them and gets a different answer cannot tell whether the sensor
    # or the bookkeeping is broken. When the producer's masks are published we quote the
    # producer's own rule strings, and ship null rather than ours when it stated none.
    meta = meta_census or {}
    ingest_rules = {
        "silent": _SILENT_RULE,
        "over_ceiling": _CEILING_RULE.format(ceiling=ceiling),
        "intermittent": _INTERMITTENT_RULE.format(slew=_SLEW_COUNTS, frac=_SLEW_SAMPLE_FRACTION),
    }
    if source == "rederived":
        rules = ingest_rules
    else:
        stated = {k: meta.get(f"{k}_rule") for k in ("silent", "over_ceiling", "intermittent")}
        rules = stated if any(stated.values()) else None

    census = {
        "readout_sites": n_sites,
        "silent": int(silent.sum()),
        "over_ceiling": int(over.sum()),
        "intermittent": int(intermittent.sum()),
        "live": int(live.sum()),
        "stable": int(stable.sum()),
        "rules": rules,
        "damage_note": meta.get("damage_note"),
    }
    return (
        HandData(
            frames=int(peak.size),
            peak=peak,
            t_s=t_s,
            census=census,
            reproduced=reproduced,
            census_source=source,
            crc_pass_rate=crc_rate,
            frames_lost=lost,
            usable=int(stable.sum()),
        ),
        warnings,
    )


def _common_grid(hands: dict[str, HandData]) -> tuple[np.ndarray, float, float]:
    """A single uniform time base for both gloves, at most PEAK_MAX_POINTS long.

    The two gloves start milliseconds apart and run to different lengths (the reference
    take is 20781 left against 20846 right). The schema says both arrays share one time
    base, so we resample onto a grid derived from real host times rather than pretending
    the index axes line up.
    """
    t0 = min(float(h.t_s[0]) for h in hands.values() if h.t_s.size)
    t1 = max(float(h.t_s[-1]) for h in hands.values() if h.t_s.size)
    n_raw = max(h.frames for h in hands.values())
    stride = max(1, math.ceil(n_raw / PEAK_MAX_POINTS))
    n_out = max(1, math.ceil(n_raw / stride))
    dt = (t1 - t0) / (n_out - 1) if n_out > 1 and t1 > t0 else 1.0 / 246.5
    return np.arange(n_out, dtype=np.float64) * dt + t0, t0, dt


def _resample(hand: HandData, t0: float, dt: float, n_out: int) -> list[float]:
    """Max-pool one glove's peak trace into the common grid. Max, never mean: this is
    an envelope and averaging would erase exactly the transients it exists to show."""
    out = np.zeros(n_out, dtype=np.float32)
    seen = np.zeros(n_out, dtype=bool)
    bins = np.clip(np.round((hand.t_s - t0) / dt).astype(np.int64), 0, n_out - 1)
    np.maximum.at(out, bins, hand.peak)
    seen[bins] = True
    if not seen.all():  # hold the previous value across a gap rather than dropping to 0
        idx = np.maximum.accumulate(np.where(seen, np.arange(n_out), 0))
        out = out[idx]
    return [round(float(v), 3) for v in out]


def _stills(paths: list[Path], url_for) -> list[dict]:
    """Parse pre-rendered heatmap filenames into captioned TactileFrame entries."""
    frames: list[dict] = []
    for p in sorted(paths):
        m = _STILL_NAME.match(p.name)
        frames.append(
            {
                "t_s": float(m.group("t")) if m else 0.0,
                "hand": "both",
                "peak_counts": float(m.group("peak")) if m else None,
                "png": url_for(p),
                "label": m.group("label").lower() if m else None,
            }
        )
    return sorted(frames, key=lambda f: f["t_s"])


def _note_with_provenance(note: str | None, reproducible: dict, has_crc: bool) -> str | None:
    """Say where the two headline numbers came from, in the record, in words.

    A buyer prices on `usable_channels` and `tactile_crc_pass_rate`. One is re-derivable
    from the delivered array and the other is not, and the difference belongs in front of
    them rather than in a build log.
    """
    parts = [p for p in [note] if p]
    if reproducible["hands_compared"]:
        parts.append(
            "Channel census: the producer's shipped taxel masks are published, and were "
            "independently re-derived here from `counts` using the stated rules -- they "
            + ("agree." if reproducible["agree"] else
               "DISAGREE; see the tactile_census_reproducible check for both numbers."))
    elif reproducible["source"] == "rederived":
        parts.append("Channel census: re-derived here from `counts`; the producer shipped no "
                     "taxel masks.")
    if has_crc:
        parts.append("tactile_crc_pass_rate is vendor-reported: it counts the `crc_ok` flag "
                     "column in the delivered array, and the on-wire bytes needed to recompute "
                     "it independently are not shipped.")
    text = " ".join(parts)
    return (text[:999] + "\u2026") if len(text) > 1000 else (text or None)


def build_tactile_preview(
    npz_by_hand: dict[str, Path],
    *,
    peak_sidecar_path: Path,
    peak_sidecar_url: str,
    grid: list[int] | None = None,
    ceiling_counts: float = DEFAULT_CEILING_COUNTS,
    display_full_scale: float = DEFAULT_DISPLAY_FULL_SCALE,
    adc_bits: int | None = DEFAULT_ADC_BITS,
    pedestal_counts: float | None = None,
    units: str = "raw_adc_counts",
    index_rule: str | None = None,
    derive_delta: str | None = None,
    note: str | None = None,
    clip_t0_us: float | None = None,
    meta_census: dict | None = None,
    still_paths: list[Path] | None = None,
    still_url: object = None,
) -> TactileResult:
    """Build the whole tactile payload from whichever gloves were instrumented."""
    if not npz_by_hand:
        return TactileResult(None)

    hands: dict[str, HandData] = {}
    warnings: list[str] = []
    for hand in HANDS:
        path = npz_by_hand.get(hand)
        if path is None:
            continue
        hands[hand], warn = _read_hand(path, ceiling=ceiling_counts, clip_t0_us=clip_t0_us,
                                       meta_census=(meta_census or {}).get(hand))
        warnings.extend(warn)

    if not hands:
        return TactileResult(None, warnings=warnings)

    present = [h for h in HANDS if h in hands]
    n_sites = hands[present[0]].census["readout_sites"]
    if grid is None:
        side = int(round(math.sqrt(n_sites)))
        grid = [side, side] if side * side == n_sites else [1, n_sites]
        warnings.append(f"no grid shape was supplied; inferred {grid} from {n_sites} readout sites")

    t_grid, t0, dt = _common_grid(hands)
    n_out = int(t_grid.size)
    series: dict[str, list[float] | None] = {"left": None, "right": None}
    for hand in present:
        series[hand] = _resample(hands[hand], t0, dt, n_out)

    peak_series: dict = {
        "encoding": "inline_f32" if n_out <= INLINE_MAX_READINGS else "sidecar_f32le",
        "n_readings": n_out,
        "rate_hz": (1.0 / dt) if dt > 0 else None,
        "t0_s": t0,
        "units": units,
        "full_scale": ceiling_counts,
        "left": None,
        "right": None,
        "sidecar": None,
    }
    written: list[Path] = []
    if peak_series["encoding"] == "inline_f32":
        peak_series["left"] = series["left"]
        peak_series["right"] = series["right"]
    else:
        order = present
        flat = np.empty((n_out, len(order)), dtype="<f4")
        for col, hand in enumerate(order):
            flat[:, col] = series[hand]
        peak_sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = peak_sidecar_path.with_suffix(peak_sidecar_path.suffix + ".part")
        tmp.write_bytes(flat.tobytes(order="C"))
        tmp.replace(peak_sidecar_path)
        written.append(peak_sidecar_path)
        peak_series["sidecar"] = {
            "url": peak_sidecar_url,
            "dtype": "float32",
            "byte_order": "little",
            "layout": "interleaved",
            "order": order,
            "stride_bytes": 4 * len(order),
            "n_readings": n_out,
            "bytes": peak_sidecar_path.stat().st_size,
            "sha256": sha256_file(peak_sidecar_path),
        }

    usable = {h: (hands[h].usable if h in hands else None) for h in HANDS}
    crc_by_hand = {h: (hands[h].crc_pass_rate if h in hands else None) for h in HANDS}
    measured = [v for v in crc_by_hand.values() if v is not None]

    # Did the published census survive an independent re-derivation from `counts`?
    # `agree` false does not mean the sensor is broken -- it means the shipped masks and
    # the stated rules disagree, and until that is resolved neither number can be quoted.
    disagreements = {
        h: {"published": {k: hands[h].census[k] for k in
                          ("silent", "over_ceiling", "intermittent", "live", "stable")},
            "rederived": hands[h].reproduced}
        for h in present
        if hands[h].census_source == "producer_masks"
        and any(hands[h].census[k] != hands[h].reproduced[k] for k in hands[h].reproduced)
    }
    sources = {hands[h].census_source for h in present}
    reproducible = {
        "agree": not disagreements,
        "source": "producer_masks" if sources == {"producer_masks"} else
                  ("rederived" if sources == {"rederived"} else "mixed"),
        "hands_compared": [h for h in present if hands[h].census_source == "producer_masks"],
        "disagreements": disagreements,
    }
    crc_source = None if not measured else "vendor_reported"
    if measured:
        warnings.append(
            "tactile_crc_pass_rate is VENDOR-REPORTED: it counts the `crc_ok` flag column the "
            "capture daemon wrote. The on-wire bytes are not in the delivered array, so nothing "
            "in the ingest can recompute it.")

    preview = {
        "grid": list(grid), "readout_sites": n_sites, "usable_channels": usable, "units": units,
        "adc_bits": adc_bits if units == "raw_adc_counts" else None,
        "pedestal_counts": pedestal_counts, "ceiling_counts": ceiling_counts,
        "display_full_scale_counts": display_full_scale, "peak_series": peak_series,
        "census": {h: (hands[h].census if h in hands else None) for h in HANDS},
        "frames": _stills(still_paths or [], still_url) if still_url else [],
        "index_rule": index_rule, "derive_delta": derive_delta,
        "note": _note_with_provenance(note, reproducible, bool(measured)),
    }
    return TactileResult(
        preview=preview,
        hands=present,
        usable_channels=usable,
        crc_pass_rate=min(measured) if measured else None,
        crc_by_hand=crc_by_hand,
        crc_source=crc_source,
        census_reproducible=reproducible,
        frames_lost={h: (hands[h].frames_lost if h in hands else None) for h in HANDS},
        warnings=warnings,
        written=written,
    )
