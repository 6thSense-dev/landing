"""Facts about files on disk, measured rather than believed.

WHY this module exists: the contract's first rule is that a `null` means "the ingest
could not determine this". The corollary is that a non-null value must have been
*determined* -- and for media that means asking ffprobe, not reading whatever a
hand-maintained sidecar claims. Every take we have seen so far ships a metadata.json
whose `duration_s` is a rounded human figure (84.6) while the container holds
84.630739 s; picking the sidecar silently is how a catalog starts lying.

So: this module only measures. It never reconciles, never prefers and never warns --
the caller compares the measurement against the sidecar and records the disagreement.
It also owns file-level facts (size, SHA-256), take-directory layout and the media
file-pointer block: same kind of thing, objective and about what is on disk.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

_FFPROBE = shutil.which("ffprobe")
_FFMPEG = shutil.which("ffmpeg")

# Read in 4 MiB blocks: large enough that syscall overhead vanishes, small enough
# that hashing a 1.7 GB archival master never grows the resident set.
_HASH_BLOCK = 4 << 20


class ProbeError(RuntimeError):
    """A media probe failed in a way the caller must report against a named take."""


@dataclass(frozen=True)
class VideoProbe:
    """What the container actually says, in the container's own terms."""

    path: Path
    bytes: int
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    frames: int | None
    constant_frame_rate: bool | None

    @property
    def resolution(self) -> list[int] | None:
        if self.width is None or self.height is None:
            return None
        return [self.width, self.height]


def missing_tools() -> list[str]:
    """External binaries that are absent, so the CLI can degrade with a named reason."""
    return [n for n, path in (("ffprobe", _FFPROBE), ("ffmpeg", _FFMPEG)) if not path]


def file_bytes(path: Path) -> int:
    """Exact size in bytes. Never a formatted string -- the UI formats, we measure."""
    return path.stat().st_size


def sha256_file(path: Path) -> str:
    """Lower-case hex SHA-256, streamed -- lower case so a string compare against
    `sha256sum` output is exact, which is what H2 asks a buyer to be able to do."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_HASH_BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def digest_files(layout: TakeLayout, cache: dict[str, str]) -> dict[Path, str]:
    """SHA-256 per file, memoised on (path, size, mtime).

    H2 wants these anyway for the package manifest, so using the same digests as the
    build's content-hash key makes idempotency free after the first run.
    """
    out: dict[Path, str] = {}
    for path in layout.files:
        st = path.stat()
        key = f"{path}|{st.st_size}|{st.st_mtime_ns}"
        out[path] = cache[key] = cache.get(key) or sha256_file(path)
    return out


def _run(cmd: list[str], *, timeout: float = 300.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ProbeError(f"{cmd[0]} not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"{cmd[0]} timed out after {timeout:.0f}s on {cmd[-1]}") from exc


def _fraction(text: str | None) -> float | None:
    """Parse ffprobe's 'num/den' rate strings. '0/0' means 'the container did not say'."""
    try:
        value = Fraction(text) if text and "/" in text else Fraction(0)
    except (ValueError, ZeroDivisionError):
        return None
    return float(value) if value > 0 else None


def _as_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    try:
        out = float(str(value))
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN is not a measurement


def probe_video(path: Path) -> VideoProbe:
    """Measure a video container with ffprobe.

    Frame count comes from `nb_frames`, else `nb_read_packets`, else None. We do NOT
    compute frames as duration*fps: that manufactures the very number H2 checks against
    the timestamp file, turning a real defect into a silent pass.
    """
    if _FFPROBE is None:
        raise ProbeError("ffprobe is not installed; cannot measure media")
    proc = _run([_FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                 "-show_streams", "-count_packets", "-select_streams", "v:0", str(path)])
    if proc.returncode != 0:
        raise ProbeError(f"ffprobe failed on {path}: {proc.stderr.strip().splitlines()[-1:] or ['?']}")
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe emitted unparseable JSON for {path}") from exc

    streams = doc.get("streams") or []
    if not streams:
        raise ProbeError(f"{path} holds no video stream")
    st, fmt = streams[0], doc.get("format") or {}
    frames = _as_int(st.get("nb_frames")) or _as_int(st.get("nb_read_packets"))
    duration = _as_float(st.get("duration")) or _as_float(fmt.get("duration"))
    avg = _fraction(st.get("avg_frame_rate"))
    r = _fraction(st.get("r_frame_rate"))
    codec, profile = st.get("codec_name"), st.get("profile")
    # A container is CFR when the nominal rate and the average rate agree; ffprobe reports
    # both, and equality to 1e-6 is far tighter than any real VFR encode.
    cfr = None if (avg is None or r is None) else abs(avg - r) < 1e-6
    return VideoProbe(
        path=path,
        bytes=file_bytes(path),
        duration_s=duration,
        width=_as_int(st.get("width")),
        height=_as_int(st.get("height")),
        fps=avg or r,
        codec=f"{codec} ({profile})" if codec and profile else codec,
        frames=frames,
        constant_frame_rate=cfr,
    )


def extract_poster(src: Path, dest: Path, *, duration_s: float | None, width: int = 960) -> None:
    """Grab a still ~12% into the clip, scaled to `width`, as JPEG q=4. 12% rather than
    0% because every take opens on an auto-exposure ramp and a black tile reads broken."""
    if _FFMPEG is None:
        raise ProbeError("ffmpeg is not installed; cannot extract a poster")
    at = max(0.0, (duration_s or 0.0) * 0.12)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Keep the real extension on the temp name: ffmpeg picks its muxer from it.
    tmp = dest.with_name(f".{dest.stem}.part{dest.suffix}")
    proc = _run([_FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(src),
                 "-frames:v", "1", "-vf", f"scale={width}:-2:flags=lanczos", "-q:v", "4", str(tmp)])
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise ProbeError(f"poster extraction failed for {src}: {proc.stderr.strip()[-300:]}")
    tmp.replace(dest)


def extract_preview(
    src: Path, dest: Path, *, duration_s: float | None, seconds: float = 3.0, width: int = 480
) -> None:
    """Cut a short, silent, 480px h264 loop for card hover. Silent by construction
    (`-an`): an autoplaying card with audio is an accessibility failure."""
    if _FFMPEG is None:
        raise ProbeError("ffmpeg is not installed; cannot cut a preview")
    at = max(0.0, (duration_s or 0.0) * 0.12)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Keep the real extension on the temp name: ffmpeg picks its muxer from it.
    tmp = dest.with_name(f".{dest.stem}.part{dest.suffix}")
    proc = _run([_FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{at:.3f}",
                 "-t", f"{seconds:.3f}", "-i", str(src), "-an",
                 "-vf", f"scale={width}:-2:flags=lanczos", "-c:v", "libx264",
                 "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-crf", "28",
                 "-preset", "veryfast", "-movflags", "+faststart", str(tmp)], timeout=600.0)
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise ProbeError(f"preview encode failed for {src}: {proc.stderr.strip()[-300:]}")
    tmp.replace(dest)


def place_file(src: Path, dest: Path, mode: str) -> None:
    """Materialise a take file under the chosen media mode. `copy` hard-links within a
    filesystem (a 159 MB take costs an inode) and copies across devices; `link` symlinks;
    `reference` never touches bytes. The manifest is byte-identical in all three."""
    if mode == "reference":
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    if mode == "link":
        dest.symlink_to(src.resolve())
        return
    if mode != "copy":
        raise ValueError(f"unknown media mode {mode!r}")
    try:
        dest.hardlink_to(src)
    except OSError:
        shutil.copy2(src, dest)


# Take-directory layout. Two shapes are tolerated on purpose: INTAKE.md asks for
# video/ tactile/ imu/ docs/, but every take we already hold was packaged flat, with
# calibration.json and README.md at the top level. Refusing the flat shape would mean
# re-arranging 159 MB of bytes to satisfy a folder convention, so we look in both
# places. Nothing here guesses -- a file is claimed only when its name matches.

_SKIP_NAMES = {".DS_Store", "Thumbs.db"}
TAKE_CONFIG_NAMES = ("take.toml", "take.json", "take.yaml", "take.yml")

# The two rendered clips, by the key they take in `TakeLayout.video`. Neither is a camera
# feed: overview.mp4 is the stereo frame with the tactile overlays composited over it, and
# force_transient_closeup.mp4 is one named taxel through a contact at 1/16 speed. They are
# claimed by name and kept out of the feed glob, because the clip's duration, resolution
# and fps are measured off whichever feed the classifier claims -- and a composite's
# dimensions are not the clip's.
_RENDER_KEYS = {"overview.mp4": "overview", "force_transient_closeup.mp4": "closeup"}

_ROLE_RULES: tuple[tuple[str, str], ...] = (
    (r"(^|/)frame_times\.csv$", "video_index"), (r"\.(mp4|mkv|mov|webm)$", "video"),
    (r"(^|/)tactile/[^/]*\.npz$", "tactile"), (r"(^|/)sensor_layout\.json$", "layout"),
    (r"(^|/)imu/[^/]*\.(csv|f32|npy)$", "imu"), (r"(^|/)segcap/[^/]*\.(csv|json)$", "annotation"),
    (r"(^|/)calibration[^/]*\.json$", "calibration"), (r"(^|/)checksums\.sha256$", "checksums"),
    (r"(^|/)LICEN[SC]E[^/]*$", "license"), (r"(^|/)preview/[^/]*\.(png|jpg|jpeg|mp4)$", "preview"),
    (r"(^|/)lerobot/", "export"), (r"\.(md|txt|pdf)$", "doc"), (r"\.py$", "script"),
)


class LayoutError(RuntimeError):
    """A take directory cannot be ingested; the message names the path and the reason."""


@dataclass
class TakeLayout:
    """Every input file we recognised, resolved to absolute paths."""
    take_dir: Path
    take_id: str
    video: dict[str, Path] = field(default_factory=dict)
    tactile: dict[str, Path] = field(default_factory=dict)
    docs: dict[str, Path] = field(default_factory=dict)
    stills: list[Path] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    frame_times: Path | None = None
    imu_csv: Path | None = None
    segcap: Path | None = None
    calibration_raw: Path | None = None
    calibration_delivered: Path | None = None
    sensor_layout: Path | None = None
    config_path: Path | None = None
    metadata_path: Path | None = None


def classify_role(relpath: str) -> str:
    """Map a package-relative path to a `PackageEntry.role`, so the Metadata tab can
    group PACKAGE CONTENTS without pattern-matching filenames in the browser."""
    for pattern, role in _ROLE_RULES:
        if re.search(pattern, relpath, re.IGNORECASE):
            return role
    return "other"


def _first(base: Path, *candidates: str) -> Path | None:
    for rel in candidates:
        hit = base / rel
        if hit.is_file():
            return hit
    return None


def _glob(base: Path, pattern: str) -> list[Path]:
    return sorted(p for p in base.glob(pattern) if p.is_file() and p.name not in _SKIP_NAMES)


def _feeds(base: Path) -> list[Path]:
    """Every mp4 in one directory that is a camera feed rather than a render."""
    return [p for p in _glob(base, "*.mp4") if p.name.lower() not in _RENDER_KEYS]


def resolve_layout(take_dir: Path) -> TakeLayout:
    """Work out which file is which inside one take directory."""
    lay = TakeLayout(take_dir=take_dir, take_id=take_dir.name)
    lay.files = sorted(
        p for p in take_dir.rglob("*")
        if p.is_file() and p.name not in _SKIP_NAMES and not p.name.endswith(".part")
    )
    lay.config_path = _first(take_dir, *TAKE_CONFIG_NAMES)
    lay.metadata_path = _first(take_dir, "metadata.json")

    videos = _feeds(take_dir / "video") or _feeds(take_dir)
    for path in videos:
        name = path.name.lower()
        key = ("stereo_sbs" if ("stereo" in name or "sbs" in name) else
               "left" if name.startswith("left") else "right" if name.startswith("right") else
               "mono" if "mono" in name else None)
        if key:
            lay.video.setdefault(key, path)
    if not lay.video and videos:
        lay.video["mono"] = videos[0]  # unlabelled: mono, rather than guess a stereo layout
    # Both renders sit at the package root in every take we hold, where the feed glob above
    # never looks once video/ is non-empty; INTAKE.md's tree would put them in video/.
    for name, key in _RENDER_KEYS.items():
        if (hit := _first(take_dir, f"video/{name}", name)) is not None:
            lay.video[key] = hit
    lay.frame_times = _first(take_dir, "video/frame_times.csv", "frame_times.csv")
    for hand in ("left", "right"):
        if (hit := _first(take_dir, f"tactile/{hand}.npz", f"{hand}.npz")) is not None:
            lay.tactile[hand] = hit
    lay.imu_csv = _first(take_dir, "imu/imu.csv", "imu.csv")
    lay.segcap = _first(take_dir, "segcap/segments.csv", "segments.csv", "segcap/segments.json")
    lay.calibration_raw = _first(take_dir, "calibration/calibration.json", "calibration.json")
    lay.calibration_delivered = _first(take_dir, "calibration/calibration_delivered.json",
                                       "calibration_delivered.json")
    lay.sensor_layout = _first(take_dir, "sensor_layout.json", "calibration/sensor_layout.json")
    for key, names in (("readme", ("docs/README.md", "README.md")),
                       ("datasheet", ("docs/DATASHEET.md", "DATASHEET.md")),
                       ("license", ("docs/LICENSE.txt", "LICENSE.txt", "docs/LICENSE", "LICENSE")),
                       ("sync_protocol", ("docs/SYNC_PROTOCOL.md", "SYNC_PROTOCOL.md")),
                       ("checksums", ("docs/checksums.sha256", "checksums.sha256"))):
        if (hit := _first(take_dir, *names)) is not None:
            lay.docs[key] = hit
    lay.stills = _glob(take_dir / "preview", "*.png")
    return lay


def primary_video(layout: TakeLayout) -> Path | None:
    """The camera feed that stands for the clip, or None when none was delivered.

    This is the file `probe_video` measures, so the search order holds the feeds and only
    the feeds: a take that ships a render and no camera has no primary asset, and saying
    so is better than putting a composite's duration and resolution in the clip's
    headline facts.
    """
    for key in ("stereo_sbs", "mono", "left"):
        if (hit := layout.video.get(key)) is not None:
            return hit
    return None


@dataclass(frozen=True)
class FrameTimes:
    """What the per-frame timestamp index says, measured off the file.

    `cfr_divergence_ms` is the worst gap, in milliseconds, between a constant-rate
    timeline and the real arrival times in this file:

        max over i of | (host_us[i] - host_us[0]) - i * mean_interval |

    It needs no fps argument because the constant rate it compares against is the
    file's own mean interval, which is what a CFR container encodes. This is the
    number `media.video.timing_note` is required to quantify and, because a
    container timeline is a stream timeline, it is also one of the three components
    of `sync.maximum_alignment_error_ms`. A dropped frame shows up here as a step,
    which is exactly right: a consumer who seeks the mp4 by timestamp lands that far
    from the frame they asked for.
    """

    rows: int | None
    first_us: float | None
    cfr_divergence_ms: float | None


def frame_times(path: Path | None) -> FrameTimes:
    """Measure the per-frame timestamp index. Row count is half the H2 parity check."""
    if path is None:
        return FrameTimes(None, None, None)
    stamps: list[float] = []
    rows = 0
    with path.open(encoding="utf-8") as fh:
        next(fh, None)
        for parts in (ln.split(",") for ln in fh if ln.strip()):
            rows += 1
            if len(parts) > 1:
                try:
                    stamps.append(float(parts[1]))
                except ValueError:  # a malformed row is not a timestamp; the count still holds
                    pass
    first = stamps[0] if stamps else None
    divergence = None
    if len(stamps) > 1:
        mean = (stamps[-1] - stamps[0]) / (len(stamps) - 1)
        divergence = max(abs((stamps[i] - stamps[0]) - i * mean)
                         for i in range(len(stamps))) / 1000.0
    return FrameTimes(rows, first, divergence)


def verify_checksums(layout: TakeLayout, digests: dict[Path, str]) -> bool | None:
    """Re-hash against the package's own checksums.sha256. None means it did not ship."""
    manifest = layout.docs.get("checksums")
    if manifest is None:
        return None
    rel = {p.relative_to(layout.take_dir).as_posix(): d for p, d in digests.items()}
    rows = (ln.split(None, 1) for ln in manifest.read_text(encoding="utf-8").splitlines())
    return all(rel.get(r[1].strip().lstrip("*")) == r[0] for r in rows if len(r) == 2)


_DOC_KEYS = ("readme", "datasheet", "license", "sync_protocol", "checksums")


def video_eye_layout(meta_video: dict, capture: str) -> str | None:
    """Eye order inside a composite frame, from the packager's own measurement. Get this
    wrong and every disparity flips sign, so we fall back to null rather than guess."""
    text = str(meta_video.get("layout") or "").lower()
    for needle, tag in (("side", "side_by_side"), ("|", "side_by_side"), ("top", "top_bottom")):
        if needle in text:
            return f"{tag}_rl" if 0 <= text.find("right") < text.find("left") else f"{tag}_lr"
    return "single" if capture == "mono_egocentric" else None


def build_media(layout: TakeLayout, *, capture: str, probe: VideoProbe | None, meta: dict,
                url, trim, imu_f32: str | None) -> dict:
    """Where every stream lives, as catalog-root-relative URLs. File pointers only:
    duration, resolution and fps are clip facts and live at the record's top level, once,
    so there is exactly one source of truth for each."""
    mv = (meta.get("modalities") or {}).get("video") or {}
    sync = meta.get("synchronisation") or {}
    docs = {k: url(layout.docs.get(k)) for k in _DOC_KEYS}
    return {
        "video": None if probe is None else {
            "stereo_sbs": url(layout.video.get("stereo_sbs")), "left": url(layout.video.get("left")),
            "right": url(layout.video.get("right")), "mono": url(layout.video.get("mono")),
            "overview": url(layout.video.get("overview")),
            "closeup": url(layout.video.get("closeup")),
            "frame_times": url(layout.frame_times), "layout": video_eye_layout(mv, capture),
            "codec": trim(mv.get("codec") or probe.codec, 200),
            "source_resolution": mv.get("source_resolution"), "frames": probe.frames,
            "constant_frame_rate": probe.constant_frame_rate,
            "timing_note": trim(sync.get("cfr_vfr_warning"), 1000),
            "orientation_note": trim(mv.get("orientation_note"), 1500),
            "master_note": trim(mv.get("master_note"), 500)},
        "imu": None if layout.imu_csv is None else {"csv": url(layout.imu_csv), "f32": imu_f32},
        "tactile": None if not layout.tactile else {
            "left": url(layout.tactile.get("left")), "right": url(layout.tactile.get("right")),
            "preview_png": [u for u in (url(p) for p in layout.stills) if u],
            "layout": url(layout.sensor_layout)},
        "segcap": None if layout.segcap is None else {"json": url(layout.segcap)},
        "calibration": None if not (layout.calibration_raw or layout.calibration_delivered) else {
            "raw": url(layout.calibration_raw), "delivered": url(layout.calibration_delivered)},
        "docs": docs if any(docs.values()) else None,
        "archive": None,
    }
