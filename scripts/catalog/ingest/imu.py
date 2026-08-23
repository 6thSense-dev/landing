"""imu.csv -> `clip.imu_preview`, plus the little-endian float32 sidecar.

WHY the sidecar is the point: the IMU tab renders EVERY reading and scrolls
horizontally. It is explicitly not a decimation, so the payload has to make the whole
series reachable in one predictable fetch. 29,507 readings are 708 KB as interleaved
f32 against ~1.4 MB as JSON numbers, and the binary parses in a single pass with no
per-sample allocation. The contract fixes the inline/sidecar threshold at 2000
readings so a producer and a consumer can never disagree about which branch is live,
and it forbids the client from sniffing: `encoding` alone dispatches.

Consequence worth stating out loud: because `channels` MUST be null under
`sidecar_f32le`, there is no contract-legal slot for a separately decimated card
sparkline. We do not invent one. Below 2000 readings the inline arrays already are
that preview; above it the client range-reads the sidecar. See README.

WHY we drop an all-zero stream: our own BNO086 is dead in hardware and emits hard
zeros. Listing `imu` as a delivered modality for a stream that carries no information
is the fastest way to lose a buyer's trust, so a zero stream is reported and dropped
rather than shipped.
"""

from __future__ import annotations

import array
import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from .probe import sha256_file

# Fixed by the contract. Do not make this configurable: producer and consumer would
# then be able to disagree about which branch of `encoding` is live.
INLINE_MAX_READINGS = 2000

_AXES = ("ax", "ay", "az", "gx", "gy", "gz")

# Header synonyms, longest-first within each group so `accel_x` wins over `a_x`.
_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "t": ("t_s", "t_sec", "time_s", "timestamp_s", "t", "time", "timestamp"),
    "t_us": ("host_us", "t_us", "time_us", "timestamp_us", "ts_us"),
    "ax": ("accel_x", "acc_x", "accelerometer_x", "a_x", "ax"),
    "ay": ("accel_y", "acc_y", "accelerometer_y", "a_y", "ay"),
    "az": ("accel_z", "acc_z", "accelerometer_z", "a_z", "az"),
    "gx": ("gyro_x", "gyr_x", "gyroscope_x", "g_x", "gx"),
    "gy": ("gyro_y", "gyr_y", "gyroscope_y", "g_y", "gy"),
    "gz": ("gyro_z", "gyr_z", "gyroscope_z", "g_z", "gz"),
}

_ACCEL_UNITS = ("m/s^2", "g")
_GYRO_UNITS = ("rad/s", "deg/s")


class ImuError(ValueError):
    """The IMU CSV could not be read in a way the caller must report by take path."""


@dataclass
class ImuResult:
    """What the caller needs: the record, why it is shaped that way, and what we wrote."""

    preview: dict | None
    warnings: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    n_readings: int = 0


def _resolve_columns(header: list[str]) -> tuple[dict[str, int], str | None]:
    """Map canonical channel names to column indices. Returns (index map, time kind)."""
    lowered = {name.strip().lower(): i for i, name in enumerate(header)}
    found: dict[str, int] = {}
    for canonical, synonyms in _COLUMN_SYNONYMS.items():
        for syn in synonyms:
            if syn in lowered:
                found[canonical] = lowered[syn]
                break
    missing = [a for a in _AXES if a not in found]
    if missing:
        raise ImuError(
            f"imu.csv is missing column(s) {','.join(missing)}; "
            f"header was {','.join(header)}. Expected t_s,ax,ay,az,gx,gy,gz or an "
            f"accel_x/gyro_x style equivalent."
        )
    time_kind = "t_us" if "t_us" in found else ("t" if "t" in found else None)
    return found, time_kind


def _read_rows(path: Path, cols: dict[str, int], time_kind: str | None) -> tuple[array.array, array.array]:
    """Stream the CSV into flat float arrays. Returns (samples, times)."""
    samples = array.array("f")
    times = array.array("d")
    axis_idx = [cols[a] for a in _AXES]
    t_idx = cols[time_kind] if time_kind else None
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header, already consumed by the caller's sniff
        for lineno, row in enumerate(reader, start=2):
            if not row or all(not c.strip() for c in row):
                continue
            try:
                samples.extend(float(row[i]) for i in axis_idx)
                if t_idx is not None:
                    times.append(float(row[t_idx]))
            except (IndexError, ValueError) as exc:
                raise ImuError(f"{path.name}:{lineno} is not parseable as numbers: {exc}") from exc
    return samples, times


def _time_base(
    times: array.array, time_kind: str | None, n: int, clip_t0_us: float | None
) -> tuple[float, float | None, float | None, list[str]]:
    """Derive (t0_s, dt_s, rate_hz, warnings) from the raw time column.

    Uniformity is decided on the spread of the sample period against its median. A
    series is declared uniform only when the worst gap is within 5% of the median;
    otherwise dt_s and rate_hz go null and a per-sample `t` channel ships, because a
    rounded rate accumulates visible axis error at 29,507 points.
    """
    warnings: list[str] = []
    if time_kind is None or n < 2:
        return 0.0, None, None, ["imu.csv has no time column; the axis will be sample index only"]

    scale = 1e-6 if time_kind == "t_us" else 1.0
    first = times[0] * scale
    if time_kind == "t_us":
        # host_us is an absolute epoch; rebase onto the clip's own zero when we know it.
        t0 = first - (clip_t0_us * scale) if clip_t0_us is not None else 0.0
        if clip_t0_us is None:
            warnings.append(
                "imu.csv times are absolute host_us but no video frame_times.csv was "
                "available to rebase them; t0_s is reported as 0.0"
            )
    else:
        t0 = first

    span = times[n - 1] * scale - first
    if span <= 0:
        return t0, None, None, warnings + ["imu.csv timestamps do not increase; treating as non-uniform"]

    mean_dt = span / (n - 1)
    worst = 0.0
    for i in range(1, n):
        worst = max(worst, abs((times[i] - times[i - 1]) * scale - mean_dt))
    if worst <= 0.05 * mean_dt:
        return t0, mean_dt, 1.0 / mean_dt, warnings
    warnings.append(
        f"imu.csv sampling is non-uniform (worst gap deviates {worst / mean_dt:.1%} from "
        f"the mean period); shipping a per-sample 't' channel instead of dt_s"
    )
    return t0, None, None, warnings


def _min_max(samples: array.array, offset: int, n: int) -> tuple[float, float] | None:
    """Extremes over three interleaved axes starting at `offset`, stride 6."""
    if n == 0:
        return None
    lo = math.inf
    hi = -math.inf
    for i in range(n):
        base = i * 6 + offset
        for c in range(3):
            v = samples[base + c]
            lo = v if v < lo else lo
            hi = v if v > hi else hi
    return (lo, hi) if lo <= hi else None


def _clip_times(times: array.array, n: int, scale: float, t0_s: float) -> list[float]:
    """The `t` channel in SECONDS FROM CLIP ZERO, which is the only form that fits f32.

    The raw column may be absolute epoch microseconds. 1.8e15 needs sixteen significant
    digits; float32 carries about seven, so writing it unconverted collapses every sample
    onto one value -- the whole axis becomes a single point and the chart silently dies.
    Both the inline and the sidecar branch therefore go through here, and neither is
    allowed to touch the raw column directly.
    """
    base = times[0] * scale - t0_s
    return [times[i] * scale - base for i in range(n)]


def _write_sidecar(samples: array.array, dest: Path, times: list[float] | None) -> int:
    """Write the headerless little-endian f32 sidecar atomically. Returns byte size.

    `times`, when given, is already scaled and rebased by `_clip_times`.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    # array.tofile() writes NATIVE byte order. Every target platform is little-endian,
    # but we assert it rather than silently emitting a big-endian file that a client
    # reading through Float32Array would decode as garbage.
    if array.array("f", [1.0]).tobytes() != b"\x00\x00\x80\x3f":
        raise ImuError("host is not little-endian; refusing to write an f32le sidecar")
    out = samples
    if times is not None:
        n = len(times)
        out = array.array("f", bytes(7 * 4 * n))
        for i in range(n):
            out[i * 7] = times[i]
            for c in range(6):
                out[i * 7 + 1 + c] = samples[i * 6 + c]
        # Read the values back THROUGH float32 and assert the axis survived the cast.
        # A monotone check on the source list would pass while the written file was flat.
        if n > 1:
            span = out[(n - 1) * 7] - out[0]
            want = times[-1] - times[0]
            if not (span > 0 and abs(span - want) <= max(1e-3, abs(want) * 1e-3)):
                raise ImuError(
                    f"the f32 't' channel does not survive float32: span {span!r} s against "
                    f"{want!r} s in the CSV. Times must be seconds from clip zero, not an "
                    f"absolute epoch.")
            if any(out[i * 7] <= out[(i - 1) * 7] for i in range(1, n)):
                raise ImuError("the f32 't' channel is not strictly increasing after the "
                               "float32 cast; the series cannot be plotted")
    with tmp.open("wb") as fh:
        out.tofile(fh)
    tmp.replace(dest)
    return dest.stat().st_size


def build_imu_preview(
    csv_path: Path,
    *,
    sidecar_path: Path,
    sidecar_url: str,
    accel_units: str = "m/s^2",
    gyro_units: str = "rad/s",
    clip_t0_us: float | None = None,
    frame: str | None = None,
    allow_zero_stream: bool = False,
) -> ImuResult:
    """Turn one imu.csv into an `ImuPreview` object plus, when large, its sidecar.

    `sidecar_url` is the catalog-root-relative URL the record will carry; the caller
    owns bundle layout, this module only fills the field.
    """
    if accel_units not in _ACCEL_UNITS:
        raise ImuError(f"accel units {accel_units!r} is not one of {_ACCEL_UNITS}")
    if gyro_units not in _GYRO_UNITS:
        raise ImuError(f"gyro units {gyro_units!r} is not one of {_GYRO_UNITS}")

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh), None)
    if not header:
        return ImuResult(None, [f"{csv_path} is empty; IMU tab disabled"])
    cols, time_kind = _resolve_columns(header)

    samples, times = _read_rows(csv_path, cols, time_kind)
    n = len(samples) // 6
    if n == 0:
        return ImuResult(None, [f"{csv_path} holds a header but no readings; IMU tab disabled"])

    if not allow_zero_stream and not any(samples):
        return ImuResult(
            None,
            [
                f"{csv_path} carries {n} readings that are all exactly zero -- this is a "
                f"dead IMU, not data. `imu` dropped from modalities and imu_preview set "
                f"to null. Set imu_allow_zero = true in take.toml to override."
            ],
            n_readings=n,
        )

    t0_s, dt_s, rate_hz, warnings = _time_base(times, time_kind, n, clip_t0_us)
    non_uniform = dt_s is None and time_kind is not None
    order = (["t", *_AXES] if non_uniform else list(_AXES))

    accel_range = _min_max(samples, 0, n)
    gyro_range = _min_max(samples, 3, n)

    preview: dict = {
        "n_readings": n,
        "rate_hz": rate_hz,
        "t0_s": t0_s,
        "dt_s": dt_s,
        "encoding": "inline_f32" if n <= INLINE_MAX_READINGS else "sidecar_f32le",
        "units": {"accel": accel_units, "gyro": gyro_units},
        "channels": None,
        "sidecar": None,
        "range": {
            "accel": None if accel_range is None else {"min": accel_range[0], "max": accel_range[1]},
            "gyro": None if gyro_range is None else {"min": gyro_range[0], "max": gyro_range[1]},
        },
        "frame": frame,
        "note": None,
    }

    scale = 1e-6 if time_kind == "t_us" else 1.0
    t_channel = _clip_times(times, n, scale, t0_s) if non_uniform else None

    written: list[Path] = []
    if preview["encoding"] == "inline_f32":
        chan: dict = {
            "accel": {
                "x": [samples[i * 6 + 0] for i in range(n)],
                "y": [samples[i * 6 + 1] for i in range(n)],
                "z": [samples[i * 6 + 2] for i in range(n)],
            },
            "gyro": {
                "x": [samples[i * 6 + 3] for i in range(n)],
                "y": [samples[i * 6 + 4] for i in range(n)],
                "z": [samples[i * 6 + 5] for i in range(n)],
            },
        }
        if t_channel is not None:
            chan["t"] = t_channel
        preview["channels"] = chan
    else:
        size = _write_sidecar(samples, sidecar_path, t_channel)
        written.append(sidecar_path)
        stride = 4 * len(order)
        if size != n * stride:
            raise ImuError(f"sidecar {sidecar_path} is {size} B, expected {n * stride} B")
        preview["sidecar"] = {
            "url": sidecar_url,
            "dtype": "float32",
            "byte_order": "little",
            "layout": "interleaved",
            "order": order,
            "stride_bytes": stride,
            "n_readings": n,
            "bytes": size,
            "sha256": sha256_file(sidecar_path),
        }

    return ImuResult(preview, warnings, written, n_readings=n)
