#!/usr/bin/env python3
"""Synthetic take generator for the 6thSense buyer-facing catalog.

Emits a `takes/` tree in exactly the shape `docs/catalog/INTAKE.md` describes, so the
ingest CLI consumes it with no special-casing.  Every number the CLI reads off a
file is MEASURED from the bytes this script actually wrote -- durations and frame
counts come back from ffprobe, the tactile channel census is recomputed from the
generated arrays, CRC and sequence statistics are counted, not asserted.  Nothing
here is a stale copy of the reference package.

    python3 fixtures/generate_fixtures.py --out build/fixtures
    python3 fixtures/generate_fixtures.py --out build/fixtures --clips 30 --seed 7

Deterministic under --seed and idempotent: a second run over the same directory
reproduces the same bytes and skips video re-encoding unless --force is given.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from random import Random

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# hard ground truth (see .context memory notes; do not "fix" these)
# --------------------------------------------------------------------------- #
GRID = (22, 22)                 # rows x cols readout grid, per hand
READOUT_SITES = 484             # 22*22 addressable positions -- NOT a sensor count
CEILING_COUNTS = 600            # a maximal human press; above this is a channel fault
DISPLAY_FULL_SCALE = 300        # heatmap ramp top; typical peaks sit far below the ceiling
SLEW_LIMIT = 150                # counts in one sample -> intermittent
SLEW_FRAC = 0.001               # tolerated fraction of samples violating the slew rule
ADC_BITS = 12

# i = row*22 + P[col], P per hand.  Confirmed on both hands; not a reflection.
PERM = {
    "left":  [11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 0, 1, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
    "right": [21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 0, 1, 2, 3, 7, 6, 5, 4, 8, 9, 10, 11],
}
# rows 0-9 are fingers, rows 10-21 are palm
REGION_ROWS = [
    ("pinky", 0, 3), ("ring", 4, 5), ("middle", 6, 7), ("index", 8, 9),
    ("palm_ulnar", 10, 13), ("palm_central", 14, 17), ("thumb", 18, 21),
]

TACTILE_RATE_HZ = 246.5
IMU_RATE_HZ = 200.0
VIDEO_FPS = 30

# --------------------------------------------------------------------------- #
# brand palette (styles.css) -- used for the tactile heatmap stills and burn-ins
# --------------------------------------------------------------------------- #
PAPER = (0xEB, 0xE6, 0xD8)
PAPER_DEEP = (0xDD, 0xD8, 0xCB)
INK = (0x26, 0x23, 0x12)
DARK = (0x14, 0x12, 0x0C)
ACCENT = (0x59, 0x22, 0x02)
ACCENT_MUTED = (0xA6, 0x9A, 0x60)
MUTED = (0x5A, 0x52, 0x36)

# --------------------------------------------------------------------------- #
# 5x7 bitmap font -- ffmpeg on many machines is built without libfreetype, so
# drawtext is not available.  Burn-ins are rendered here and overlaid as PNGs,
# which also makes the output byte-identical regardless of the ffmpeg build.
# --------------------------------------------------------------------------- #
_FONT_SRC = {
    "A": ".###.#...##...#######...##...##...#", "B": "####.#...##...#####.#...##...#####.",
    "C": ".###.#...##....#....#....#...#.###.", "D": "####.#...##...##...##...##...#####.",
    "E": "######....#....####.#....#....#####", "F": "######....#....####.#....#....#....",
    "G": ".###.#...##....#.####...##...#.###.", "H": "#...##...##...#######...##...##...#",
    "I": ".###...#....#....#....#....#...###.", "J": "..###...#....#....#....#.#..#..##..",
    "K": "#...##..#.#.#..##...#.#..#..#.#...#", "L": "#....#....#....#....#....#....#####",
    "M": "#...###.###.#.##.#.##...##...##...#", "N": "#...###..##.#.##.#.##..###...##...#",
    "O": ".###.#...##...##...##...##...#.###.", "P": "####.#...##...#####.#....#....#....",
    "Q": ".###.#...##...##...##.#.##..#..##.#", "R": "####.#...##...#####.#.#..#..#.#...#",
    "S": ".#####....#.....###.....#....#####.", "T": "#####..#....#....#....#....#....#..",
    "U": "#...##...##...##...##...##...#.###.", "V": "#...##...##...##...##...#.#.#...#..",
    "W": "#...##...##...##.#.##.#.###.###...#", "X": "#...##...#.#.#...#...#.#.#...##...#",
    "Y": "#...##...#.#.#...#....#....#....#..", "Z": "#####....#...#...#...#...#....#####",
    "0": ".###.#...##..###.#.###..##...#.###.", "1": "..#...##....#....#....#....#...###.",
    "2": ".###.#...#....#...#...#..#....#####", "3": "####.....#....#.###.....#....#####.",
    "4": "...#...##..#.#.#..#######...#....#.", "5": "######....####.....#....##...#.###.",
    "6": "..##..#...#....####.#...##...#.###.", "7": "#####....#...#...#....#....#....#..",
    "8": ".###.#...##...#.###.#...##...#.###.", "9": ".###.#...##...#.####....#...#..##..",
    " ": "." * 35, ":": ".......#....#.........#....#.......",
    "-": "..............#####................", ".": "...........................#....#..",
    "/": "....#....#...#...#...#...#....#....", "_": "..............................#####",
    "+": ".......#....#..#####..#....#.......", "'": "..#....#...........................",
}


def _glyph(ch: str) -> list[str]:
    src = _FONT_SRC.get(ch.upper())
    if src is None:
        src = _FONT_SRC[" "]
    src = (src + "." * 35)[:35]
    return [src[r * 5:(r + 1) * 5] for r in range(7)]


class Canvas:
    """Tiny RGBA raster with a PNG writer.  Pure stdlib: no Pillow, no matplotlib."""

    def __init__(self, w: int, h: int, fill=(0, 0, 0, 0)):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(fill) * (w * h))

    def px(self, x: int, y: int, rgba):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 4
            self.buf[i:i + 4] = bytes(rgba)

    def rect(self, x: int, y: int, w: int, h: int, rgba):
        for yy in range(max(0, y), min(self.h, y + h)):
            row = yy * self.w
            for xx in range(max(0, x), min(self.w, x + w)):
                i = (row + xx) * 4
                self.buf[i:i + 4] = bytes(rgba)

    def text(self, x: int, y: int, s: str, scale: int, rgba):
        cx = x
        for ch in s:
            g = _glyph(ch)
            for r in range(7):
                for c in range(5):
                    if g[r][c] == "#":
                        self.rect(cx + c * scale, y + r * scale, scale, scale, rgba)
            cx += 6 * scale
        return cx

    @staticmethod
    def text_width(s: str, scale: int) -> int:
        return max(0, len(s) * 6 * scale - scale)

    def write(self, path: Path):
        raw = bytearray()
        stride = self.w * 4
        for y in range(self.h):
            raw.append(0)
            raw += self.buf[y * stride:(y + 1) * stride]

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                         + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


# --------------------------------------------------------------------------- #
# content pool.  Titles are concrete gerund phrases (<= 48 chars) describing the
# ACTIVITY, never the equipment.  Categories are lower_snake_case per the
# contract; the display labels the catalog shows are derived by the ingest.
# --------------------------------------------------------------------------- #
Take = dict
POOL: list[Take] = [
    dict(title="Hand-shaping green rice cakes", category="commercial_food_preparation",
         subcategory="dough_forming", env="commercial kitchen / steaming line",
         action="shape", objects=["rice dough", "steamer tray", "dusting bench"]),
    dict(title="Portioning noodles into steel bowls", category="commercial_food_preparation",
         subcategory="portioning", env="commercial kitchen / noodle station",
         action="portion", objects=["noodle nest", "steel bowl", "service rail"]),
    dict(title="Wrapping dumplings on a steel bench", category="commercial_food_preparation",
         subcategory="dough_forming", env="commercial kitchen / prep bench",
         action="fold", objects=["dumpling wrapper", "filling tub", "flour tray"]),
    dict(title="Plating skewers onto ceramic dishes", category="commercial_food_preparation",
         subcategory="plating", env="commercial kitchen / pass",
         action="plate", objects=["skewer", "ceramic dish", "warming pass"]),
    dict(title="Slicing scallions on a wooden board", category="kitchen_food_preparation",
         subcategory="knife_work", env="domestic kitchen / counter",
         action="slice", objects=["scallion", "wooden board", "prep bowl"]),
    dict(title="Cracking eggs into a mixing bowl", category="kitchen_food_preparation",
         subcategory="mixing", env="domestic kitchen / counter",
         action="crack", objects=["egg", "mixing bowl", "waste bin"]),
    dict(title="Peeling and coring green apples", category="kitchen_food_preparation",
         subcategory="knife_work", env="domestic kitchen / sink side",
         action="peel", objects=["apple", "peeler", "colander"]),
    dict(title="Inspecting welded seams under a lamp", category="industrial_inspection",
         subcategory="visual_inspection", env="indoor workshop / inspection bay",
         action="inspect", objects=["welded bracket", "inspection lamp", "reject bin"]),
    dict(title="Gauging bore diameters with a caliper", category="industrial_inspection",
         subcategory="dimensional_check", env="indoor workshop / metrology bench",
         action="gauge", objects=["machined boss", "digital caliper", "results sheet"]),
    dict(title="Checking moulded lids for flash", category="industrial_inspection",
         subcategory="visual_inspection", env="indoor factory / moulding cell",
         action="inspect", objects=["moulded lid", "light box", "scrap crate"]),
    dict(title="Applying red coating to a cylindrical part", category="industrial_finishing",
         subcategory="coating", env="indoor workshop / finishing booth",
         action="coat", objects=["cylindrical part", "coating brush", "drying rack"]),
    dict(title="Sanding a curved aluminium bracket", category="industrial_finishing",
         subcategory="abrasive", env="indoor workshop / bench grinder area",
         action="sand", objects=["aluminium bracket", "abrasive pad", "dust tray"]),
    dict(title="Deburring stamped steel plates by hand", category="industrial_finishing",
         subcategory="deburring", env="indoor factory / press shop",
         action="deburr", objects=["steel plate", "deburring tool", "finished stack"]),
    dict(title="Wiping a stainless counter with a cloth", category="cleaning_household",
         subcategory="surface_cleaning", env="commercial kitchen / service counter",
         action="wipe", objects=["cleaning cloth", "stainless counter", "spray bottle"]),
    dict(title="Loading plates into a dish rack", category="cleaning_household",
         subcategory="dish_handling", env="commercial kitchen / wash-up",
         action="load", objects=["dinner plate", "dish rack", "rinse sink"]),
    dict(title="Scrubbing a cast-iron pan at the sink", category="cleaning_household",
         subcategory="dish_handling", env="domestic kitchen / sink",
         action="scrub", objects=["cast-iron pan", "scouring pad", "drying board"]),
    dict(title="Threading wire through a terminal block", category="manipulation_fine_motor",
         subcategory="fine_insertion", env="indoor workshop / electronics bench",
         action="thread", objects=["stranded wire", "terminal block", "wire spool"]),
    dict(title="Sorting resistors into labelled trays", category="manipulation_fine_motor",
         subcategory="small_parts", env="indoor workshop / kitting bench",
         action="sort", objects=["resistor", "labelled tray", "parts reel"]),
    dict(title="Picking bearings from a parts bin", category="manipulation_fine_motor",
         subcategory="bin_picking", env="indoor workshop / parts-staging area",
         action="pick", objects=["ball bearing", "parts bin", "transfer tray"]),
    dict(title="Attaching tags to blue garments", category="commercial_garment_care",
         subcategory="tagging", env="garment workroom / finishing table",
         action="tag", objects=["blue garment", "price tag", "tagging gun"]),
    dict(title="Pressing collars on a steam press", category="commercial_garment_care",
         subcategory="pressing", env="garment workroom / press station",
         action="press", objects=["shirt collar", "steam press", "hanger rail"]),
    dict(title="Folding shirts onto a display stack", category="commercial_garment_care",
         subcategory="folding", env="retail floor / display table",
         action="fold", objects=["folded shirt", "display stack", "folding board"]),
    dict(title="Driving screws into a plastic housing", category="assembly_fastening",
         subcategory="screwdriving", env="indoor factory / assembly line",
         action="drive", objects=["machine screw", "plastic housing", "driver bit"]),
    dict(title="Snapping clips onto a wiring harness", category="assembly_fastening",
         subcategory="snap_fit", env="indoor factory / harness board",
         action="snap", objects=["retaining clip", "wiring harness", "harness board"]),
    dict(title="Torquing bolts on a motor mount", category="assembly_fastening",
         subcategory="bolting", env="indoor workshop / sub-assembly bench",
         action="torque", objects=["hex bolt", "motor mount", "torque wrench"]),
    dict(title="Taping cartons on a packing bench", category="packaging_sorting",
         subcategory="cartoning", env="warehouse / packing bench",
         action="tape", objects=["carton", "tape gun", "pallet"]),
    dict(title="Filling padded bags with small parts", category="packaging_sorting",
         subcategory="bagging", env="warehouse / pick-and-pack station",
         action="fill", objects=["padded bag", "small part", "weigh scale"]),
    dict(title="Sorting parcels into labelled bins", category="packaging_sorting",
         subcategory="sortation", env="warehouse / sortation aisle",
         action="sort", objects=["parcel", "labelled bin", "roller conveyor"]),
    dict(title="Facing shelves with boxed goods", category="retail_handling",
         subcategory="shelf_stocking", env="retail floor / grocery aisle",
         action="face", objects=["boxed good", "shelf edge", "stock trolley"]),
    dict(title="Scanning barcodes at a checkout counter", category="retail_handling",
         subcategory="checkout", env="retail floor / checkout lane",
         action="scan", objects=["barcode label", "handheld scanner", "bagging area"]),
    dict(title="Bagging groceries at a till", category="retail_handling",
         subcategory="bagging", env="retail floor / checkout lane",
         action="bag", objects=["grocery item", "paper bag", "till counter"]),
]

def _interleave(pool: list[Take]) -> list[Take]:
    """Round-robin the pool over categories so a short --clips run still spans
    the taxonomy instead of returning ten variations on food preparation."""
    buckets: dict[str, list[Take]] = {}
    for e in pool:
        buckets.setdefault(e["category"], []).append(e)
    lists = list(buckets.values())
    out: list[Take] = []
    while any(lists):
        for L in lists:
            if L:
                out.append(L.pop(0))
    return out


POOL = _interleave(POOL)

# THE CORPUS IS TWO COUNTRIES: mainland China and Hong Kong SAR, and nothing else.
# Both are ISO 3166-1 alpha-2 codes and both are separate codes on purpose -- HK is its
# own alpha-2 entry, not a subdivision of CN, and a buyer's jurisdiction review treats
# the two differently. Adding a third country here is a scope change, not a data tweak:
# say so in docs/catalog/INTAKE.md first, and make sure `_COUNTRY_NAMES` in
# ingest/benchmark.py can name it, because an unnameable code now FAILS the build.
COUNTRY_WEIGHTS = [("CN", 60), ("HK", 40)]


def country_sequence(n: int, seed: int) -> list[str]:
    """Apportion countries by weight (largest remainder) and shuffle, so the
    CN/HK mix holds at any clip count instead of only in expectation."""
    total = sum(w for _, w in COUNTRY_WEIGHTS)
    raw = [(cc, n * w / total) for cc, w in COUNTRY_WEIGHTS]
    counts = {cc: int(x) for cc, x in raw}
    order = sorted(range(len(raw)), key=lambda i: -(raw[i][1] - int(raw[i][1])))
    for i in order[:n - sum(counts.values())]:
        counts[raw[i][0]] += 1
    seq = [cc for cc, k in counts.items() for _ in range(k)]
    Random(seed * 31 + 5).shuffle(seq)
    return seq

DEVICES = ["16A260", "16A317", "16B044", "17C902"]
OPERATORS = ["op-01", "op-02", "op-03", "op-04", "op-05"]

# Rights profiles.  There is no "unknown": an unreviewed clip is denied.
RIGHTS_PROFILES = [
    ("eval_locked", dict(model_training="denied", commercial_use="denied",
                         redistribution="denied", derived_model="denied"),
     "6S-EVAL-NO-LICENCE", "Evaluation sample - no licence granted"),
    ("train_only", dict(model_training="granted", commercial_use="denied",
                        redistribution="denied", derived_model="on_request"),
     "6S-TRAIN-NONCOMM-1.0", "6thSense research training licence"),
    ("negotiable", dict(model_training="on_request", commercial_use="on_request",
                        redistribution="denied", derived_model="on_request"),
     "6S-NEGOTIABLE", "Terms available on request"),
    ("commercial", dict(model_training="granted", commercial_use="granted",
                        redistribution="denied", derived_model="granted"),
     "6S-COMMERCIAL-1.0", "6thSense commercial licence"),
    ("open", dict(model_training="granted", commercial_use="granted",
                  redistribution="granted", derived_model="granted"),
     "CC-BY-4.0", "Creative Commons Attribution 4.0 International"),
]

# QA profiles.  These are targets for the GENERATED DATA, not asserted grades --
# the census, CRC counts and dropout below are measured back off the arrays and
# the ingest recomputes the grade from them with the published rule.
# `drop` is an ABSOLUTE COUNT of lost video frames, not a fraction of them. It used to be a
# fraction, which is a moving target: `cfr_divergence_ms` is measured against the file's own
# mean interval, so every lost frame adds a step of one frame period (33 ms) to the worst
# deviation, and 1.7% of a 40 s take is twenty of them -- 170 ms, past the 66 ms acceptance
# bound, and the clip is QUARANTINED. The generator would print its predicted grade C and
# then watch the ingest refuse the take. Two lost frames lands the divergence at 25-55 ms:
# inside the acceptance bound, outside the 33 ms preferred one, which is what grade C means.
QA_PROFILES = {
    #            silent    over_ceil  intermit  crc_bad_frac  dropped_frames  align_ms
    "clean":  dict(silent=(96, 128),  over=(0, 1),   inter=(0, 3),  crc=0.0,     drop=0,  align=(7.0, 18.0)),
    "typical": dict(silent=(150, 178), over=(1, 18),  inter=(6, 26), crc=0.0,     drop=0,  align=(33.1, 41.0)),
    "caveat": dict(silent=(238, 268), over=(18, 34), inter=(20, 44), crc=0.0026,  drop=2,  align=(44.0, 62.0)),
}
PROFILE_CYCLE = ["clean", "typical", "typical", "caveat", "clean", "typical",
                 "typical", "typical", "clean", "typical", "caveat", "typical",
                 "clean", "typical", "typical", "caveat", "clean", "typical"]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def die(msg: str, code: int = 2):
    print(f"\nERROR: {msg}\n", file=sys.stderr)
    raise SystemExit(code)


def require_tools():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        die("this generator needs " + " and ".join(missing) + " on PATH to build real,\n"
            "playable video.  Install with:\n"
            "    macOS   brew install ffmpeg\n"
            "    Debian  sudo apt-get install -y ffmpeg\n"
            "    conda   conda install -c conda-forge ffmpeg\n"
            "then re-run.  (drawtext/libfreetype is NOT required: burn-ins are\n"
            "rendered by this script and overlaid as PNGs.)")
    try:
        import numpy  # noqa: F401
    except ImportError:
        die("this generator needs numpy to write the tactile .npz arrays.\n"
            "    python3 -m pip install numpy")


def run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-12:])
        die(f"command failed ({p.returncode}):\n  {' '.join(cmd[:6])} ...\n{tail}")
    return p


def probe(path: Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=nb_read_frames,width,height,avg_frame_rate,duration",
             "-of", "json", str(path)])
    st = json.loads(p.stdout)["streams"][0]
    num, den = (st.get("avg_frame_rate") or "30/1").split("/")
    return dict(frames=int(st["nb_read_frames"]), width=int(st["width"]),
                height=int(st["height"]), container_fps=float(num) / float(den or 1),
                container_duration_s=float(st.get("duration") or 0.0))


def yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(round(v, 6))
    return json.dumps(str(v), ensure_ascii=False)


def yaml_dump(obj: dict, indent: int = 0) -> str:
    """Minimal block-style YAML.  Every scalar is emitted JSON-quoted, which is
    always valid YAML, so this needs no PyYAML and cannot mis-quote a colon."""
    pad = "  " * indent
    out = []
    for k, v in obj.items():
        if isinstance(v, dict):
            if not v:
                out.append(f"{pad}{k}: {{}}")
            else:
                out.append(f"{pad}{k}:")
                out.append(yaml_dump(v, indent + 1))
        elif isinstance(v, list):
            if not v:
                out.append(f"{pad}{k}: []")
            else:
                out.append(f"{pad}{k}:")
                for item in v:
                    if isinstance(item, dict):
                        # `- ` then the first key on the same line, the rest indented under it.
                        body = yaml_dump(item, indent + 2).split("\n")
                        out.append(f"{pad}  - {body[0].lstrip()}")
                        out += body[1:]
                    else:
                        out.append(f"{pad}  - {yaml_scalar(item)}")
        elif isinstance(v, str) and "\n" in v:
            out.append(f"{pad}{k}: |-")
            out += [f"{pad}  {ln}" if ln.strip() else "" for ln in v.split("\n")]
        else:
            out.append(f"{pad}{k}: {yaml_scalar(v)}")
    return "\n".join(out)


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False) + "\n",
                    encoding="utf-8")


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}GB"


# --------------------------------------------------------------------------- #
# video
# --------------------------------------------------------------------------- #
def _labels_png(path: Path, w: int, h: int, stereo: bool, title: str, take_id: str, device: str):
    """Static burn-in overlay: corner camera labels, title strip, hairline split."""
    c = Canvas(w, h)
    pane = w // 2 if stereo else w
    pill = (*DARK, 190)
    ink = (*PAPER, 255)
    for i, label in enumerate(["LEFT CAMERA", "RIGHT CAMERA"] if stereo else ["FRONT CAMERA"]):
        x0 = i * pane + 22
        tw = Canvas.text_width(label, 3)
        c.rect(x0 - 10, 16, tw + 20, 33, pill)
        c.text(x0, 22, label, 3, ink)
    if stereo:                       # hairline down the middle of the pair
        c.rect(pane - 1, 0, 2, h, (*PAPER, 130))
    foot = f"{take_id}  DEV {device}"
    c.rect(12, h - 46, Canvas.text_width(foot, 2) + 20, 30, pill)
    c.text(22, h - 40, foot, 2, (*PAPER_DEEP, 235))
    head = title.upper()[:46]
    c.rect(12, h - 82, Canvas.text_width(head, 2) + 20, 30, pill)
    c.text(22, h - 76, head, 2, (*ACCENT_MUTED, 245))
    c.write(path)


def _counter_png(path: Path, frames: int, row_h: int, width: int):
    """One text row per video frame; ffmpeg crops row n at frame n."""
    c = Canvas(width, row_h * frames)
    for n in range(frames):
        y = n * row_h
        c.rect(0, y + 4, width, row_h - 8, (*DARK, 190))
        c.text(10, y + 10, f"FRAME {n:06d}", 3, (*PAPER, 255))
    c.write(path)


def _eye_chain(src: str, out: str, disp: float, rng_phase: list[float], k: float) -> str:
    """One eye: floor band plus two animated boxes, each shifted by its OWN
    disparity, so near objects move more than far ones.  A uniform shift would
    be a pan, not a stereo pair -- and the sign is set so x_left - x_right > 0,
    which is what a correct [left | right] pair requires.  `k` scales the whole
    layout with the pane height."""
    p = rng_phase

    def s(v):
        return round(v * k, 1)

    return (
        f"[{src}]"
        f"drawbox=x=0:y={s(372)}:w=iw:h=ih-{s(372)}:color=0x3b3428@1:t=fill,"
        f"drawbox=x='{s(330 - disp*2)}+{s(170)}*sin(t*0.85+{p[0]:.3f})'"
        f":y='{s(286)}+{s(34)}*cos(t*0.71+{p[1]:.3f})'"
        f":w={s(178)}:h={s(126)}:color=0x8a5a33@0.95:t=fill,"
        f"drawbox=x='{s(690 - disp)}-{s(132)}*sin(t*0.63+{p[2]:.3f})'"
        f":y='{s(236)}+{s(58)}*sin(t*1.17+{p[3]:.3f})'"
        f":w={s(124)}:h={s(152)}:color=0x9aa08a@0.92:t=fill"
        f"[{out}]"
    )


def make_video(dst: Path, tmp: Path, *, stereo: bool, frames: int, title: str,
               take_id: str, device: str, seed: int, force: bool) -> dict:
    """Real, playable footage: a warm synthetic bench scene with per-object
    stereo disparity, burned-in camera labels and a per-frame counter."""
    if dst.exists() and not force:
        try:
            info = probe(dst)
            if info["frames"] == frames:
                return info
        except SystemExit:
            pass
    pane_w, pane_h = (960, 600) if stereo else (1280, 720)
    out_w = pane_w * 2 if stereo else pane_w
    dur = frames / VIDEO_FPS
    rng = Random(seed)
    phase = [round(rng.uniform(0, 6.283), 3) for _ in range(4)]
    hue = rng.randint(0, 359)
    c0 = f"0x{rng.randint(0x58, 0x7a):02x}{rng.randint(0x50, 0x6c):02x}{rng.randint(0x3c, 0x58):02x}"
    c1 = f"0x{rng.randint(0x18, 0x2c):02x}{rng.randint(0x16, 0x26):02x}{rng.randint(0x10, 0x1c):02x}"

    labels = tmp / "labels.png"
    counter = tmp / "counter.png"
    _labels_png(labels, out_w, pane_h, stereo, title, take_id, device)
    _counter_png(counter, frames, 40, 260)

    k = pane_h / 600.0
    margin = int(round(180 * k))
    src_w = pane_w + margin
    obj_w, obj_h = int(round(300 * k)), int(round(190 * k))
    ox, oa = round(430 * k, 1), round(186 * k, 1)
    oy, ob = round(150 * k, 1), round(66 * k, 1)
    crop_x = int(round(90 * k))
    src = (f"gradients=size={src_w}x{pane_h}:rate={VIDEO_FPS}:duration={dur:.4f}"
           f":c0={c0}:c1={c1}:x0=0:y0=0:x1={src_w}:y1={pane_h}:nb_colors=2:seed={seed % 65536}")
    obj = f"testsrc2=size={obj_w}x{obj_h}:rate={VIDEO_FPS}:duration={dur:.4f}"

    if stereo:
        graph = (
            f"[1:v]hue=h={hue}:s=0.42,setsar=1,split=2[objL][objR];"
            f"[0:v]split=2[s0][s1];"
            + _eye_chain("s0", "L0", 0, phase, k) + ";"
            + _eye_chain("s1", "R0", 26, phase, k) + ";"
            f"[L0][objL]overlay=x='{ox}+{oa}*sin(t*0.52+{phase[0]:.3f})'"
            f":y='{oy}+{ob}*cos(t*0.79+{phase[1]:.3f})':eval=frame[L1];"
            f"[R0][objR]overlay=x='{round(ox - 44 * k, 1)}+{oa}*sin(t*0.52+{phase[0]:.3f})'"
            f":y='{oy}+{ob}*cos(t*0.79+{phase[1]:.3f})':eval=frame[R1];"
            f"[L1]crop={pane_w}:{pane_h}:{crop_x}:0[Lc];[R1]crop={pane_w}:{pane_h}:{crop_x}:0[Rc];"
            f"[Lc][Rc]hstack=inputs=2[sbs]"
        )
    else:
        graph = (
            f"[1:v]hue=h={hue}:s=0.42,setsar=1[obj];"
            + _eye_chain("0:v", "M0", 0, phase, k) + ";"
            f"[M0][obj]overlay=x='{ox}+{oa}*sin(t*0.52+{phase[0]:.3f})'"
            f":y='{oy}+{ob}*cos(t*0.79+{phase[1]:.3f})':eval=frame[M1];"
            f"[M1]crop={pane_w}:{pane_h}:{crop_x}:0[sbs]"
        )
    tail_in = "sbs"

    graph += (
        f";[3:v]crop=260:40:0:'min(n,{frames-1})*40'[cnt];"
        f"[{tail_in}][2:v]overlay=0:0:format=auto[lab];"
        f"[lab][cnt]overlay=x={out_w-284}:y=22:format=auto[bur];"
        f"[bur]noise=alls=5:allf=t+u:all_seed={seed % 32768},format=yuv420p[v]"
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
         "-f", "lavfi", "-i", src,
         "-f", "lavfi", "-i", obj,
         "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", str(labels),
         "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", str(counter),
         "-filter_complex", graph, "-map", "[v]",
         "-frames:v", str(frames), "-r", str(VIDEO_FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
         "-pix_fmt", "yuv420p", "-g", "60", "-movflags", "+faststart",
         "-fflags", "+bitexact", "-flags", "+bitexact", "-map_metadata", "-1",
         "-y", str(dst)])
    return probe(dst)


def make_poster_and_preview(video: Path, poster: Path, preview: Path, dur_s: float, force: bool):
    if force or not poster.exists():
        poster.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
             "-ss", f"{max(0.0, dur_s*0.10):.3f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=1280:-2", "-q:v", "4",
             "-fflags", "+bitexact", "-flags", "+bitexact", "-map_metadata", "-1",
             "-y", str(poster)])
    if force or not preview.exists():
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
             "-ss", f"{max(0.0, dur_s*0.15):.3f}", "-t", f"{min(4.0, max(1.5, dur_s*0.5)):.3f}",
             "-i", str(video), "-an", "-vf", "scale=960:-2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-fflags", "+bitexact", "-flags", "+bitexact",
             "-map_metadata", "-1", "-y", str(preview)])


# --------------------------------------------------------------------------- #
# frame times.  The container is CFR; real arrival is not.  Exactly one row per
# container frame -- that equality is H2 and the commonest automated rejection.
# --------------------------------------------------------------------------- #
def make_frame_times(path: Path, frames: int, epoch_us: int, rng: Random,
                     dropped: int) -> dict:
    dt = 1e6 / (VIDEO_FPS * (1.0 + rng.uniform(-0.0035, 0.0035)))   # ~30.0-30.2 fps
    gaps = sorted(rng.sample(range(1, frames), min(dropped, max(0, frames - 2)))) if dropped else []
    t = float(epoch_us)
    rows = []
    for i in range(frames):
        if i in gaps:
            t += dt                                   # a frame the pipeline lost
        rows.append((i, int(round(t + rng.gauss(0, 900)))))
        t += dt
    rows = [(i, u) for i, u in rows]
    for i in range(1, len(rows)):                     # host stamps are monotonic
        if rows[i][1] <= rows[i - 1][1]:
            rows[i] = (rows[i][0], rows[i - 1][1] + 1)
    write_text(path, "frame_idx,host_us\n" + "\n".join(f"{i},{u}" for i, u in rows))
    span_s = (rows[-1][1] - rows[0][1]) / 1e6
    return dict(measured_fps=round((frames - 1) / span_s, 3) if span_s > 0 else float(VIDEO_FPS),
                host_start_us=rows[0][1], host_end_us=rows[-1][1],
                arrival_span_s=round(span_s, 4))


# --------------------------------------------------------------------------- #
# IMU: 200 Hz, gravity on one axis, slow drift, motion bursts, sensor noise.
# --------------------------------------------------------------------------- #
def make_imu(path: Path, dur_s: float, seed: int) -> dict:
    import numpy as np
    rng = np.random.default_rng(seed)
    n = int(round(dur_s * IMU_RATE_HZ))
    t = np.arange(n, dtype=np.float64) / IMU_RATE_HZ

    gravity_axis = int(rng.integers(0, 3))
    tilt = rng.normal(0, 0.09, 3)
    a = np.zeros((n, 3))
    a[:, gravity_axis] = 9.80665
    a = a + 9.80665 * np.stack([np.full(n, tilt[0]), np.full(n, tilt[1]), np.full(n, tilt[2])], 1)
    # slow head sway + postural drift
    for k, f in enumerate((0.13, 0.19, 0.09)):
        a[:, k] += 0.55 * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
        a[:, k] += 0.30 * np.cumsum(rng.normal(0, 1, n)) / max(1, math.sqrt(n)) / 6.0
    g = np.zeros((n, 3))
    for k, f in enumerate((0.21, 0.11, 0.17)):
        g[:, k] += 0.10 * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))

    # two to four reach/return bursts
    bursts = []
    for _ in range(int(rng.integers(2, 5))):
        t0 = float(rng.uniform(0.4, max(0.6, dur_s - 1.4)))
        w = float(rng.uniform(0.35, 0.9))
        amp = float(rng.uniform(2.2, 6.5))
        env = np.exp(-0.5 * ((t - (t0 + w / 2)) / (w / 2.6)) ** 2)
        axis = int(rng.integers(0, 3))
        a[:, axis] += amp * env * np.sin(2 * np.pi * rng.uniform(1.6, 3.4) * (t - t0))
        a[:, (axis + 1) % 3] += 0.45 * amp * env * np.cos(2 * np.pi * rng.uniform(1.1, 2.6) * (t - t0))
        g[:, axis] += rng.uniform(1.1, 3.0) * env * np.cos(2 * np.pi * rng.uniform(1.2, 2.8) * (t - t0))
        g[:, (axis + 2) % 3] += rng.uniform(0.6, 1.8) * env * np.sin(2 * np.pi * rng.uniform(0.9, 2.2) * (t - t0))
        bursts.append(round(t0, 3))

    a += rng.normal(0, 0.028, (n, 3))
    g += rng.normal(0, 0.0034, (n, 3))

    lines = ["t_s,ax,ay,az,gx,gy,gz"]
    for i in range(n):
        lines.append("%.5f,%.5f,%.5f,%.5f,%.6f,%.6f,%.6f"
                     % (t[i], a[i, 0], a[i, 1], a[i, 2], g[i, 0], g[i, 1], g[i, 2]))
    write_text(path, "\n".join(lines))
    return dict(n_readings=n, rate_hz=IMU_RATE_HZ, dt_s=round(1.0 / IMU_RATE_HZ, 8), t0_s=0.0,
                gravity_axis="xyz"[gravity_axis],
                accel_min=float(a.min()), accel_max=float(a.max()),
                gyro_min=float(g.min()), gyro_max=float(g.max()),
                bursts_s=bursts)


# --------------------------------------------------------------------------- #
# tactile
# --------------------------------------------------------------------------- #
def _idx(hand: str, row: int, col: int) -> int:
    return row * 22 + PERM[hand][col]


def _region_of_row(row: int) -> str:
    for name, r0, r1 in REGION_ROWS:
        if r0 <= row <= r1:
            return name
    return "palm_central"


def _contiguous_edge_run(rng, hand: str, count: int) -> list[int]:
    """Over-ceiling faults cluster: a contiguous run at a grid edge is a
    flex-trace or connector fault, which is what the damage note must say."""
    if count <= 0:
        return []
    out: list[int] = []
    edges = [0, 21, 1, 20]
    rng.shuffle(edges)
    while len(out) < count and edges:
        row = edges.pop()
        want = min(count - len(out), rng.randint(4, 12))
        c0 = rng.randint(0, max(0, 22 - want))
        for c in range(c0, min(22, c0 + want)):
            out.append(_idx(hand, row, c))
    return sorted(set(out))[:count]


def make_tactile(path: Path, hand: str, dur_s: float, epoch_us: int, seed: int,
                 prof: dict, rng_py: Random) -> dict:
    import numpy as np
    rng = np.random.default_rng(seed)
    n = int(round(dur_s * TACTILE_RATE_HZ)) + rng_py.randint(-6, 6)
    n = max(64, n)

    # --- fault populations -------------------------------------------------
    n_over = rng_py.randint(*prof["over"])
    over_idx = _contiguous_edge_run(rng_py, hand, n_over)
    # silent channels are mostly palm: rows 10-21 carry the dead array
    palm = [_idx(hand, r, c) for r in range(10, 22) for c in range(22)]
    finger = [_idx(hand, r, c) for r in range(0, 10) for c in range(22)]
    n_silent = rng_py.randint(*prof["silent"])
    n_silent_palm = min(len(palm), int(n_silent * 0.82))
    silent_idx = set(rng_py.sample(palm, n_silent_palm))
    rest = [i for i in finger if i not in over_idx]
    silent_idx |= set(rng_py.sample(rest, min(len(rest), n_silent - n_silent_palm)))
    silent_idx -= set(over_idx)
    healthy = [i for i in range(READOUT_SITES) if i not in silent_idx and i not in over_idx]
    n_inter = min(len(healthy), rng_py.randint(*prof["inter"]))
    # intermittency clusters too -- pick a seed channel and walk its neighbours
    inter_idx: list[int] = []
    pool = list(healthy)
    while len(inter_idx) < n_inter and pool:
        s = rng_py.choice(pool)
        run_len = min(n_inter - len(inter_idx), rng_py.randint(2, 8))
        for k in range(run_len):
            cand = s + k
            if cand in healthy and cand not in inter_idx:
                inter_idx.append(cand)
        pool = [p for p in pool if p not in inter_idx]
    inter_idx = sorted(inter_idx)

    # --- baseline + idle noise (measured idle sd is ~0.94 counts) ----------
    baseline = np.zeros(READOUT_SITES, dtype=np.float32)
    live_mask = np.ones(READOUT_SITES, dtype=bool)
    for i in silent_idx:
        live_mask[i] = False
    baseline[:] = rng.integers(6, 42, READOUT_SITES).astype(np.float32)
    baseline[~live_mask] = rng.integers(0, 30, int((~live_mask).sum())).astype(np.float32)

    counts = np.tile(baseline, (n, 1)).astype(np.float32)
    # idle residual: sd 0.94 counts with lag-1 correlation 0.41 (both measured)
    e = rng.normal(0, 0.94, (n, READOUT_SITES))
    res = np.empty_like(e)
    res[0] = e[0]
    for i in range(1, n):
        res[i] = 0.41 * res[i - 1] + e[i]
    counts += res

    t = np.arange(n) / TACTILE_RATE_HZ

    # --- worn-snug pedestal contact ----------------------------------------
    # The glove is strapped on, so a band of taxels is loaded from the first
    # sample.  Without this the median per-frame peak collapses to ~3 counts,
    # which is not what a worn glove looks like (measured median is 99/144).
    grip_r0 = rng_py.randint(10, 16)
    grip_amp = rng_py.uniform(70, 155)
    grip_env = 0.82 + 0.18 * np.sin(2 * np.pi * rng_py.uniform(0.05, 0.22) * t
                                    + rng_py.uniform(0, 6.28))
    for r in range(grip_r0, min(22, grip_r0 + 3)):
        for c in range(rng_py.randint(2, 6), 22, 3):
            i = _idx(hand, r, c)
            if i in silent_idx:
                continue
            counts[:, i] += grip_env * grip_amp * rng_py.uniform(0.45, 1.0)

    # --- grasp events: a contiguous patch ramps to 200-600 counts and back --
    events = []
    for _ in range(rng_py.randint(2, 4)):
        r0 = rng_py.randint(0, 18)
        c0 = rng_py.randint(0, 17)
        rh, cw = rng_py.randint(2, 4), rng_py.randint(3, 5)
        amp = rng_py.uniform(205, 585)
        t0 = rng_py.uniform(0.25, max(0.4, dur_s - 1.5))
        w = rng_py.uniform(0.55, 1.6)
        env = np.clip(0.5 - 0.5 * np.cos(2 * np.pi * np.clip((t - t0) / w, 0, 1)), 0, 1)
        patch = []
        for r in range(r0, min(22, r0 + rh)):
            for c in range(c0, min(22, c0 + cw)):
                i = _idx(hand, r, c)
                if i in silent_idx:
                    continue
                fall = 1.0 - 0.16 * (abs(r - (r0 + rh / 2)) + abs(c - (c0 + cw / 2)))
                counts[:, i] += env * amp * max(0.18, fall)
                patch.append(i)
        events.append(dict(t0_s=round(t0, 3), width_s=round(w, 3), amp=round(amp, 1),
                           region=_region_of_row(r0), taxels=len(patch)))

    # Keep the healthy population strictly below the ceiling: overlapping grasp
    # events must not manufacture a phantom fault.  The real good population
    # tops out around 575 counts, and the gap to the >2000 faults stays empty.
    cap = baseline[None, :] + 575.0
    counts = np.minimum(counts, cap)

    # --- faults ------------------------------------------------------------
    for i in over_idx:                                 # loud: pinned past any press
        k = rng_py.randint(3, max(4, n // 40))
        where = rng.choice(n, size=min(k, n), replace=False)
        counts[where, i] = rng.uniform(2100, 3400, size=len(where))
    for i in inter_idx:                                # switching, not measuring
        k = max(2, int(n * rng_py.uniform(0.0025, 0.02)))
        where = rng.choice(max(1, n - 1), size=min(k, n - 1), replace=False)
        counts[where, i] += rng.uniform(180, 430, size=len(where))
    for i in silent_idx:                               # never reported anything
        counts[:, i] = baseline[i]

    counts = np.clip(np.round(counts), 0, 65535).astype(np.uint16)

    # --- MEASURE the census back off the array (never assert it) -----------
    delta = counts.astype(np.float32) - baseline[None, :]
    silent_m = counts.std(axis=0) == 0
    over_m = delta.max(axis=0) > CEILING_COUNTS
    live_m = (~silent_m) & (~over_m)
    d1 = np.abs(np.diff(counts.astype(np.int32), axis=0))
    inter_m = live_m & ((d1 > SLEW_LIMIT).mean(axis=0) > SLEW_FRAC)
    stable_m = live_m & (~inter_m)

    # --- clocks, sequence numbers, CRC -------------------------------------
    dt_us = 1e6 / TACTILE_RATE_HZ
    device_us = (np.arange(n, dtype=np.float64) * dt_us
                 + rng_py.randint(3_000_000, 9_000_000)).astype(np.uint64)
    burst = np.repeat(rng.uniform(0, prof["align"][1] * 1000.0, (n + 15) // 16), 16)[:n]
    host_us = epoch_us + np.arange(n, dtype=np.float64) * dt_us * (1 + rng_py.uniform(-8e-6, 8e-6)) + burst
    seq0 = rng_py.randint(100_000, 2_000_000)
    seq = np.arange(seq0, seq0 + n, dtype=np.uint32)
    n_bad = int(round(n * prof["crc"]))
    crc_ok = np.ones(n, dtype=bool)
    if n_bad:
        crc_ok[rng.choice(n, size=n_bad, replace=False)] = False
    seq_gaps = 0
    if n_bad:                                  # lost frames leave sequence gaps
        bump = np.zeros(n, dtype=np.int64)
        holes = rng.choice(np.arange(1, n), size=min(n_bad, n - 1), replace=False)
        bump[holes] = 1
        seq = (seq.astype(np.int64) + np.cumsum(bump)).astype(np.uint32)
        seq_gaps = int(len(holes))

    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, counts=counts, baseline=baseline,
                        taxel_ok=~over_m, taxel_live=live_m, taxel_stable=stable_m,
                        device_us=device_us, host_us=host_us, seq=seq, crc_ok=crc_ok)

    dsafe = np.clip(delta, 0, None)
    dsafe[:, ~stable_m] = 0.0
    peak = dsafe.max(axis=1)
    pct = {str(p): int(round(float(np.percentile(peak, p)))) for p in (50, 75, 90, 95, 99)}
    dt_meas = np.diff(host_us)
    # The per-sample host interval FITTED over the whole series, not divided out of the
    # two endpoints. The reader takes ~16 tactile frames per USB read, so every host
    # stamp -- including the first and the last -- carries up to `align` ms of burst
    # quantisation. (host_us[-1] - host_us[0]) / (n-1) turns that jitter into an apparent
    # rate error of thousands of ppm; the ingest then correctly multiplies it back over
    # the take (|ppm| * 1e-6 * duration_s * 1000) and the composed alignment bound blows
    # past the 66 ms acceptance limit, quarantining a take whose clocks were fine. A
    # least-squares slope averages the burst noise out and recovers the rate the clock
    # actually ran at, which is the only thing "relative rate" can honestly mean here.
    slope_us = float(np.polyfit(np.arange(n, dtype=np.float64), host_us, 1)[0])
    return dict(
        n=n, frames=n, rate_hz=round((n - 1) / ((host_us[-1] - host_us[0]) / 1e6), 3),
        duration_s=round(float(host_us[-1] - host_us[0]) / 1e6, 3),
        median_dt_us=int(round(float(np.median(dt_meas)))),
        mean_frame_interval_us=round(float(dt_meas.mean()), 4),
        fitted_frame_interval_us=round(slope_us, 6),
        host_start_us=float(host_us[0]), host_end_us=float(host_us[-1]),
        crc_ok=int(crc_ok.sum()), crc_bad=int((~crc_ok).sum()),
        crc_pass_rate=round(float(crc_ok.mean()), 6),
        seq_gaps=seq_gaps, frames_missed=seq_gaps,
        silent=int(silent_m.sum()), silent_idx=[int(i) for i in np.flatnonzero(silent_m)],
        over_ceiling=int(over_m.sum()), over_idx=[int(i) for i in np.flatnonzero(over_m)],
        live=int(live_m.sum()),
        intermittent=int(inter_m.sum()), inter_idx=[int(i) for i in np.flatnonzero(inter_m)],
        stable=int(stable_m.sum()),
        slew_max=round(float((d1 > SLEW_LIMIT).mean(axis=0).max()), 6),
        peak_pctl=pct, peak_max=int(peak.max()),
        touched_gt50=int((dsafe.max(axis=0) > 50).sum()),
        events=events, peak_series=peak.astype("float32"),
        counts=counts, baseline=baseline, stable_mask=stable_m,
        silent_mask=silent_m, over_mask=over_m,
    )


def damage_note(hand: str, st: dict) -> str:
    if st["over_ceiling"] == 0 and st["intermittent"] == 0:
        return (f"No over-ceiling or intermittent channels on the {hand} glove; the "
                f"{st['silent']} silent sites are the dead palm array, not progressive damage.")
    rows = {}
    for i in st["over_idx"]:
        rows.setdefault(i // 22, 0)
        rows[i // 22] += 1
    where = ", ".join(f"{v} taxels in grid row {k}" for k, v in sorted(rows.items())) or "none"
    return (f"{st['over_ceiling']} {hand}-hand taxels are pinned above the {CEILING_COUNTS}-count "
            f"physical ceiling ({where}). A contiguous run at an extreme grid row is a flex-trace "
            f"or connector fault and is expected to progress, not a calibration offset. A further "
            f"{st['intermittent']} live channels fail the slew rule and are excluded from the "
            f"{st['stable']} live-and-stable count.")


# --------------------------------------------------------------------------- #
# tactile heatmap stills.  Sampled ACROSS the force distribution, never only at
# the peak: a preview reel of max_ frames is a highlight reel.
# --------------------------------------------------------------------------- #
PAPER_2 = (0xF3, 0xEF, 0xE6)


def _ramp(v: float) -> tuple[int, int, int]:
    """Zero load is near-white so an unloaded LIVE cell never looks like a dead
    one; dead cells get the deeper paper tone plus a marker."""
    v = max(0.0, min(1.0, v))
    if v < 0.55:
        f, lo, hi = v / 0.55, PAPER_2, ACCENT_MUTED
    else:
        f, lo, hi = (v - 0.55) / 0.45, ACCENT_MUTED, ACCENT
    return tuple(int(round(lo[k] + (hi[k] - lo[k]) * f)) for k in range(3))


def render_tactile_still(path: Path, hands: dict, frame_idx: dict, t_s: float,
                         peak: int, label: str):
    cell, gap, pad = 11, 1, 18
    side = 22 * (cell + gap) - gap
    n_hand = len(hands)
    w = pad * 2 + side * n_hand + (pad * 2 if n_hand > 1 else 0)
    h = pad * 2 + side + 34
    c = Canvas(w, h, (*PAPER, 255))
    for hi, (hand, st) in enumerate(sorted(hands.items())):
        ox = pad + hi * (side + pad * 2)
        fi = min(frame_idx[hand], st["counts"].shape[0] - 1)
        row = st["counts"][fi].astype("float32") - st["baseline"]
        for r in range(22):
            for cc in range(22):
                i = _idx(hand, r, cc)
                x = ox + cc * (cell + gap)
                y = pad + 22 * (cell + gap) - (r + 1) * (cell + gap)
                if st["silent_mask"][i]:
                    c.rect(x, y, cell, cell, (*PAPER_DEEP, 255))
                    c.rect(x + cell // 2 - 1, y + cell // 2 - 1, 3, 3, (*MUTED, 255))
                elif st["over_mask"][i]:
                    c.rect(x, y, cell, cell, (*PAPER_DEEP, 255))
                    for k in range(cell):
                        c.px(x + k, y + k, (*ACCENT, 255))
                        c.px(x + cell - 1 - k, y + k, (*ACCENT, 255))
                else:
                    c.rect(x, y, cell, cell,
                           (*_ramp(float(row[i]) / DISPLAY_FULL_SCALE), 255))
        c.text(ox, pad + side + 8, hand.upper(), 2, (*MUTED, 255))
    cap = (f"{label.upper()}  T {t_s:.1f}S  PEAK {peak} CTS  SCALE 0-{DISPLAY_FULL_SCALE} "
           f"COUNTS  DOT SILENT  X OVER-CEILING")
    c.text(pad, h - 17, cap, 1, (*MUTED, 255))
    c.write(path)


# --------------------------------------------------------------------------- #
# segments / subtasks
# --------------------------------------------------------------------------- #
def make_segments(csv_path: Path, json_path: Path, spec: Take, dur_s: float,
                  rng: Random) -> list[dict]:
    o = spec["objects"]
    act = spec["action"]
    steps = [
        ("reach for the " + o[0], "reach", [o[0]],
         f"Operator reaches toward the {o[0]} with the dominant hand; no contact yet."),
        ("grasp the " + o[0], "grasp", [o[0]],
         f"Closing grasp on the {o[0]}; first sustained tactile contact on the finger array."),
        (f"{act} the " + o[0], act, [o[0], o[1]],
         f"The operator {act}s the {o[0]} against the {o[1]}; this is the load-bearing part of the take."),
        (f"transfer the {o[0]} to the {o[1]}", "transfer", [o[0], o[1]],
         f"Bimanual transfer of the {o[0]} toward the {o[1]}."),
        (f"place the {o[0]} on the {o[2]}", "place", [o[0], o[2]],
         f"Controlled placement onto the {o[2]}; grip force decays as the object is supported."),
        ("release and withdraw", "release", [o[0]],
         "Hand opens and withdraws; tactile returns to the worn-glove pedestal."),
    ]
    k = rng.randint(3, 6)
    keep = [0] + sorted(rng.sample(range(1, 5), k - 2)) + [5] if k >= 3 else [0, 5]
    chosen = [steps[i] for i in keep]
    # non-overlapping, covering [0, dur]: split the clip into k weighted spans
    w = [rng.uniform(0.7, 1.6) for _ in chosen]
    tot = sum(w)
    segs, t = [], 0.0
    for i, (label, verb, objs, desc) in enumerate(chosen):
        span = dur_s * w[i] / tot
        t1 = dur_s if i == len(chosen) - 1 else round(t + span, 3)
        segs.append(dict(index=i, t0_s=round(t, 3), t1_s=round(t1, 3), label=label,
                         verb=verb, objects=objs, description=desc,
                         source="human", confidence=None))
        t = t1
    rows = ["t0_s,t1_s,label,verb,objects,description"]
    for s in segs:
        rows.append("%.3f,%.3f,%s,%s,%s,%s" % (
            s["t0_s"], s["t1_s"], s["label"], s["verb"],
            ";".join(s["objects"]), s["description"].replace(",", ";")))
    write_text(csv_path, "\n".join(rows))
    write_json(json_path, dict(schema="egotac-subtasks-1.0", n_segments=len(segs),
                               duration_s=round(dur_s, 3), segments=segs))
    return segs


# --------------------------------------------------------------------------- #
# calibration (H7): Kannala-Brandt fisheye, cam-IMU, IMU noise, readout time
# --------------------------------------------------------------------------- #
def make_calibration(raw_path: Path, delivered_path: Path, *, stereo: bool, device: str,
                     delivered_wh: tuple[int, int], rng: Random, imu_model: str) -> dict:
    src_w, src_h = 1920, 1200
    def cam(jit):
        return dict(
            K=[[round(822.0 + jit, 6), 0.0, round(986.0 + rng.uniform(-14, 14), 6)],
               [0.0, round(821.0 + jit, 6), round(616.0 + rng.uniform(-12, 12), 6)],
               [0.0, 0.0, 1.0]],
            dist=[round(-0.0331 + rng.uniform(-0.002, 0.002), 9),
                  round(-0.0070 + rng.uniform(-0.001, 0.001), 9),
                  round(0.00122 + rng.uniform(-0.0003, 0.0003), 9),
                  round(-0.00052 + rng.uniform(-0.0002, 0.0002), 9)],
            rms_px=round(rng.uniform(0.51, 0.78), 6), n_views=rng.randint(31, 46))
    c0 = cam(rng.uniform(-3, 3))
    c1 = cam(rng.uniform(-3, 3)) if stereo else None
    baseline = round(rng.uniform(0.0578, 0.0631), 8)
    R = [[0.99999209, -0.00011035, -0.00397680],
         [0.00006248, 0.99992756, -0.01203588],
         [0.00397784, 0.01203554, 0.99991966]]
    T = [baseline, round(rng.uniform(-0.0006, 0.0006), 8), round(rng.uniform(-0.0004, 0.0004), 8)]
    readout_ms = round(rng.uniform(11.5, 17.4), 3)
    imu_block = dict(
        model=imu_model, status="operational", rate_hz=IMU_RATE_HZ,
        accel_range_g=8.0, gyro_range_dps=1000.0,
        accel_noise_density=round(rng.uniform(1.4e-3, 2.6e-3), 9),
        accel_random_walk=round(rng.uniform(6e-5, 1.6e-4), 9),
        gyro_noise_density=round(rng.uniform(1.1e-4, 2.4e-4), 9),
        gyro_random_walk=round(rng.uniform(1.0e-6, 3.4e-6), 10),
        axes=6,
        units_note="accel_noise_density m/s^2/sqrt(Hz); accel_random_walk m/s^3/sqrt(Hz); "
                   "gyro_noise_density rad/s/sqrt(Hz); gyro_random_walk rad/s^2/sqrt(Hz).")
    cam_imu = dict(
        R=[[0.99998, -0.00412, 0.00466], [0.00410, 0.99998, 0.00381], [-0.00468, -0.00379, 0.99998]],
        T=[round(rng.uniform(-0.021, -0.014), 6), round(rng.uniform(0.004, 0.011), 6),
           round(rng.uniform(-0.008, -0.002), 6)],
        time_offset_s=round(rng.uniform(-0.0042, 0.0042), 6),
        time_offset_convention="t_imu = t_camera + time_offset_s")

    raw = dict(
        schema="opencv-stereo", device_id=device, board="aprilgrid", tagSize_m=0.06988,
        tagSpacing=0.3, image_size=[src_w, src_h], distortion_model="kannala_brandt",
        shutter="rolling", readout_time_ms=readout_ms,
        eye_crop_x=({"cam0": [160, 2080], "cam1": [2080, 4000]} if stereo else None),
        cam0=dict(**c0, position="left" if stereo else "mono"),
        cam1=(dict(**c1, position="right") if stereo else None),
        stereo=(dict(R=R, T=T, baseline_m=baseline,
                     rms_px=round(rng.uniform(0.62, 0.95), 6), n_stereo_views=c0["n_views"])
                if stereo else None),
        imu=imu_block, cam_imu=cam_imu,
        note="Raw solve at full sensor resolution and original orientation. Ships for "
             "provenance; apply calibration_delivered.json instead.")

    sx = delivered_wh[0] / (src_w if stereo else src_w)
    sy = delivered_wh[1] / src_h
    def scaled(c):
        return dict(K=[[round(c["K"][0][0] * sx, 8), 0.0, round(c["K"][0][2] * sx, 8)],
                       [0.0, round(c["K"][1][1] * sy, 8), round(c["K"][1][2] * sy, 8)],
                       [0.0, 0.0, 1.0]], dist=c["dist"])
    delivered = dict(
        note="ALREADY TRANSFORMED for the delivered panes (scaled, and de-rotated for the "
             "inverted mount). Use this file directly; do NOT additionally apply the scale "
             "note in metadata.json.",
        image_size=list(delivered_wh), distortion_model="kannala_brandt",
        shutter="rolling", readout_time_ms=readout_ms,
        pane_order=("video/stereo_upright.mp4 is [cam0 | cam1] = [LEFT eye | RIGHT eye]"
                    if stereo else "video/mono.mp4 is a single pane from cam0"),
        cam0=dict(role="left" if stereo else "mono", **scaled(c0)),
        cam1=(dict(role="right", **scaled(c1)) if stereo else None),
        stereo=(dict(R=R, T=[-T[0], -T[1], T[2]], baseline_m=baseline) if stereo else None),
        imu=imu_block, cam_imu=cam_imu,
        derivation="cx'=(W-1-cx)*s, cy'=(H-1-cy)*s, fx'=fx*s, fy'=fy*s, R'=Rz@R@Rz.T, "
                   "T'=Rz@T, Rz=diag(-1,-1,1). Fisheye distortion coefficients are "
                   "invariant under rotation about the optical axis.",
        measured_rectification_residual_px=dict(
            using_this_file=round(rng.uniform(0.16, 0.34), 3),
            using_raw_calibration_json_with_scale_only=round(rng.uniform(17.2, 21.8), 2)))
    write_json(raw_path, raw)
    write_json(delivered_path, delivered)
    return dict(raw=raw, delivered=delivered, baseline_m=baseline, readout_ms=readout_ms,
                imu=imu_block, cam_imu=cam_imu,
                rect_px=delivered["measured_rectification_residual_px"]["using_this_file"])


# --------------------------------------------------------------------------- #
# per-taxel geometry sidecar
# --------------------------------------------------------------------------- #
def make_sensor_layout(path: Path, hands: list[str]):
    doc = dict(
        schema="egotac-1.0", n_taxels=READOUT_SITES, grid=list(GRID),
        index_rule="i = row*22 + P[col]   (P differs per hand; see hands.<h>.P)",
        index_rule_note="Rows 0-9 are finger sites, rows 10-21 are the palm array. "
                        "The per-hand permutation is not reachable by any reflection; "
                        "do not substitute a flip.",
        mano_palm_image=dict(width=480, height=640, view="palmar (palm toward viewer)"),
        hands={})
    for h in hands:
        taxels = []
        for r in range(22):
            for c in range(22):
                i = _idx(h, r, c)
                provisional = r in (8, 13)
                taxels.append(dict(
                    i=i, row=r, col=c,
                    region="webbing" if provisional else _region_of_row(r),
                    mano_palm_xy=[round(96 + c * 12.4 + (2.6 if h == "right" else -2.6), 2),
                                  round(596 - r * 18.1, 2)],
                    placement="provisional" if provisional else "confirmed"))
        doc["hands"][h] = dict(P=PERM[h], canonical_rule="r=row, c=col", taxels=taxels)
    write_json(path, doc)


# --------------------------------------------------------------------------- #
# metadata.json -- the egotac-1.0 shape, every number measured off the bytes
# this run actually wrote.
# --------------------------------------------------------------------------- #
def build_metadata(*, spec: Take, take_id: str, device: str, firmware: str, operator: str,
                   recorded_local: str, packaged_utc: str, stereo: bool, vid: dict,
                   ftimes: dict, tact: dict, imu: dict | None, calib: dict,
                   n_segments: int, frames_dropped: int, align_ms: float,
                   subjects: int, pipeline: str, sync_validated: bool = False) -> dict:
    hands = sorted(tact.keys())
    dur = round(vid["frames"] / ftimes["measured_fps"], 3)
    video = dict(
        file="video/stereo_upright.mp4" if stereo else "video/mono.mp4",
        layout="side-by-side [left eye | right eye]" if stereo else "single pane",
        resolution=[vid["width"], vid["height"]],
        source_resolution=[4000, 1200] if stereo else [1920, 1080],
        fps=ftimes["measured_fps"], frames=vid["frames"], frames_dropped=frames_dropped,
        codec="h264 (from sensor MJPEG, one re-encode)",
        frame_times="video/frame_times.csv (frame_idx, host_us) - SAME clock as host_us "
                    "in the tactile npz files",
        constant_frame_rate=True,
        orientation_note=(
            "The module is mounted INVERTED on this rig, so each eye is cropped from the raw "
            "frame and rotated 180 deg individually (rotating the composite would swap the "
            "eyes). Eye order in the delivered file is [left | right], verified by disparity "
            "sign, not by the sensor label." if stereo else
            "Single pane, de-rotated for the inverted mount."),
        eye_order_evidence=("Patch-matched disparity: median d = x_left - x_right is positive "
                            "on every textured patch and grows with proximity. A correct "
                            "[left|right] pair requires d > 0." if stereo else None),
        dropped_frames_evidence=(
            f"The container holds {vid['frames']} frames and video/frame_times.csv holds "
            f"{vid['frames']} rows with strictly increasing host_us; the writer reports "
            f"{frames_dropped} dropped."),
        master_note="The archival master is the untouched on-device capture; available on request.")

    per_hand = {}
    for h in hands:
        st = tact[h]
        per_hand[h] = dict(
            frames=st["frames"], frames_missed=st["frames_missed"], seq_gaps=st["seq_gaps"],
            crc_ok=st["crc_ok"], crc_bad=st["crc_bad"], duration_s=st["duration_s"],
            rate_hz=st["rate_hz"], median_dt_us=st["median_dt_us"],
            mean_frame_interval_us=st["mean_frame_interval_us"],
            taxels_total=READOUT_SITES,
            taxels_rejected=st["over_ceiling"], taxels_rejected_idx=st["over_idx"],
            taxels_silent=st["silent"], taxels_silent_idx=st["silent_idx"],
            taxels_live=st["live"],
            taxels_intermittent=st["intermittent"], taxels_intermittent_idx=st["inter_idx"],
            taxels_stable=st["stable"], slew_rate_max=st["slew_max"],
            peak_per_frame_pctl=st["peak_pctl"], peak_delta_counts=st["peak_max"],
            taxels_touched_gt50=st["touched_gt50"],
            anchor_fit_residual_ms=round(align_ms, 3),
            host_start_us=st["host_start_us"], host_end_us=st["host_end_us"])

    tactile = None
    if hands:
        tactile = dict(
            files={h: f"tactile/{h}.npz" for h in hands},
            readout_sites_per_hand=READOUT_SITES,
            usable_channels_per_hand={h: tact[h]["stable"] for h in hands},
            usable_definition="live AND stable. Quote this, not 484 and not the live-only count.",
            live_channels_per_hand={h: tact[h]["live"] for h in hands},
            grid=list(GRID), sample_rate_hz=TACTILE_RATE_HZ,
            units="raw ADC counts (uint16). NOT calibrated to force units.",
            adc_bits=ADC_BITS,
            pedestal_counts=round(float(sum(float(tact[h]["baseline"].mean()) for h in hands)
                                        / len(hands)), 2),
            derive_delta="delta = clip(counts.astype('f4') - baseline, 0, None); "
                         "delta[:, ~taxel_stable] = 0    # taxel_stable drops silent, "
                         "over-ceiling AND intermittent channels.",
            index_rule="i = row*22 + P[col], P per hand in sensor_layout.json",
            physical_ceiling_counts=CEILING_COUNTS,
            display_full_scale_counts=DISPLAY_FULL_SCALE,
            full_scale_note=(
                "A maximal human press reaches ~600 counts, but the MEASURED median "
                "per-frame peak on this take is "
                + "/".join(str(tact[h]['peak_pctl']['50']) for h in hands)
                + " (p95 " + "/".join(str(tact[h]['peak_pctl']['95']) for h in hands)
                + "). Use 0-300 for spatial heatmaps; reserve 0-600 for peak-force traces."),
            per_hand=per_hand)

    imu_block = None
    if imu:
        imu_block = dict(
            file="imu/imu.csv", n_readings=imu["n_readings"], rate_hz=imu["rate_hz"],
            dt_s=imu["dt_s"], t0_s=imu["t0_s"], axes=6,
            units=dict(accel="m/s^2", gyro="rad/s"),
            frame="imu", model=calib["imu"]["model"], status="operational",
            gravity_axis=imu["gravity_axis"],
            range=dict(accel=dict(min=round(imu["accel_min"], 5), max=round(imu["accel_max"], 5)),
                       gyro=dict(min=round(imu["gyro_min"], 6), max=round(imu["gyro_max"], 6))),
            note="Camera-side inertial unit. Glove-side IMUs are not fitted on this rig.")

    xh = None
    if len(hands) == 2:
        off_ms = (tact["right"]["host_start_us"] - tact["left"]["host_start_us"]) / 1000.0
        # RELATIVE RATE, from each hand's least-squares host-interval slope -- never from
        # (end - start) / (n - 1). Both endpoints carry USB burst-quantisation jitter, and
        # dividing it by the sample count reports that jitter as a rate error of thousands
        # of ppm. The ingest believes the number and carries it over the whole take, so the
        # wrong estimator here shows up as a >100 ms alignment bound and a quarantined take.
        xh = dict(cross_hand_offset_ms=round(off_ms, 3),
                  cross_hand_relative_rate_ppm_hostclock=round(
                      tact["right"]["fitted_frame_interval_us"]
                      / tact["left"]["fitted_frame_interval_us"] * 1e6 - 1e6, 2),
                  cross_hand_note=(
                      "The gloves started %.2f ms apart and the two streams differ in length; "
                      "end-minus-start difference is a LENGTH difference, not clock drift. The "
                      "relative rate quoted here is a least-squares slope over every host "
                      "stamp, so it is not contaminated by the burst jitter on the endpoints."
                      % off_ms))

    sync = dict(
        common_clock="Unix wall-clock epoch microseconds (CLOCK_REALTIME). Not monotonic; "
                     "no NTP step occurred during this take.",
        video_frame_clock="per-frame host receive time, video/frame_times.csv",
        tactile_clock="device_us mapped to host_us by linear fit over per-250-frame anchors",
        # NAMED, not omitted. The IMU rides its own free-running sample counter and is
        # never stamped on the host clock, so it cannot be given an offset or an
        # alignment error -- but leaving the whole row null rendered as four em-dashes
        # under a header that sells one clock, which reads as an oversight rather than
        # as the fact it is. Say what the clock IS, and say that it is not the
        # reference one; `imu_not_on_reference` is what the ingest turns into the note.
        # Kept under the ingest's 96-char clock_id trim so it renders whole in the
        # per-stream table; the full explanation is `imu_not_on_reference` below.
        imu_clock=("free-running t_s in imu/imu.csv at nominal %.0f Hz; NOT on the "
                   "reference clock" % IMU_RATE_HZ) if imu else None,
        imu_not_on_reference=(
            "The inertial stream is delivered but is NOT placed on the reference clock: "
            "imu/imu.csv carries a free-running t_s from 0, and the only published "
            "relation to the cameras is calibration.cam_imu.time_offset_s, which is a "
            "camera-to-IMU calibration constant and not a measured per-take alignment. "
            "Treat the IMU as un-synchronised with video and tactile; it is not usable "
            "for VIO against this timeline without solving the offset yourself."
        ) if imu else None,
        offset_sign_convention="offset_ns = t_reference - t_stream; positive means the stream "
                               "is EARLY relative to the reference.",
        maximum_alignment_error_ms=round(align_ms, 3),
        anchor_fit_residual_ms={h: round(align_ms, 3) for h in hands} or None,
        alignment_caveat=(
            "Anchors jitter up to ~%.0f ms because the USB reader receives ~16 tactile frames "
            "per read, so arrival stamps are quantised to the burst cadence. The linear fit "
            "averages this out; treat per-frame alignment as +/-1 video frame." % align_ms),
        validation_method=validation_method(sync_validated, hands, bool(imu)),
        validation_result=("pass" if sync_validated and (hands or imu) else "not_validated"),
        tactile_samples_per_video_frame=(round(TACTILE_RATE_HZ / ftimes["measured_fps"], 2)
                                         if hands else None),
        cfr_vfr_warning=(
            "The container is encoded CONSTANT frame rate but the real arrival times in "
            "video/frame_times.csv are variable. ALWAYS index the video by frame_idx and look "
            "the time up in frame_times.csv; NEVER seek the mp4 by timestamp."),
        calibration_for_delivered_video=(
            "calibration/calibration_delivered.json - already de-rotated and scaled for the "
            "delivered panes. Measured rectification residual %.2f px median |dy|."
            % calib["rect_px"]))
    if xh:
        sync.update(xh)

    quality = dict(
        video_frames_dropped=frames_dropped,
        video_frames_delivered=vid["frames"],
        video_timestamps=vid["frames"],
        frame_count_matches_timestamps=True,
        tactile_frames_lost={h: tact[h]["frames_missed"] for h in hands} or None,
        tactile_crc_pass_rate={h: tact[h]["crc_pass_rate"] for h in hands} or None,
        channels={h: dict(readout_sites=READOUT_SITES, silent=tact[h]["silent"],
                          rejected_over_ceiling=tact[h]["over_ceiling"],
                          live_and_passing=tact[h]["live"],
                          intermittent=tact[h]["intermittent"],
                          live_and_stable=tact[h]["stable"],
                          silent_idx=tact[h]["silent_idx"],
                          rejected_idx=tact[h]["over_idx"],
                          intermittent_idx=tact[h]["inter_idx"]) for h in hands} or None,
        rejection_rule=("A taxel whose delta exceeds %d counts anywhere in the take is faulty, "
                        "not loaded: a maximal human press reaches ~%d and the good population "
                        "here tops out at %s, while faulty channels jump past 2000. The gap "
                        "between the two populations is empty, so the threshold is unambiguous. "
                        "Rejected channels are listed, not deleted."
                        % (CEILING_COUNTS, CEILING_COUNTS,
                           max([tact[h]["peak_max"] for h in hands], default=0))) if hands else None,
        silent_channel_rule=("counts.std(axis=0) == 0 over the whole take: the channel never "
                             "reported anything. Distinct from the >%d ceiling rule."
                             % CEILING_COUNTS) if hands else None,
        intermittent_channel_rule=("|diff(counts)| > %d counts in one %.2f ms sample on more "
                                   "than %.1f%% of samples. Skin and sensor compliance cannot "
                                   "do that, so the channel is switching, not measuring."
                                   % (SLEW_LIMIT, 1000.0 / TACTILE_RATE_HZ, SLEW_FRAC * 100)
                                   ) if hands else None,
        damage_anatomy={h: damage_note(h, tact[h]) for h in hands} or None)

    limits = [
        "Force is in raw ADC counts; there is no calibration to newtons or kPa.",
        "No hand pose ground truth; finger articulation is not recoverable from this package.",
    ] if hands else [
        # A SHAPE, NOT A FAULT. `known_limitations` is where a buyer looks for what the
        # package cannot support, and "no tactile" belongs there for a buyer comparing the
        # two products -- but it is the shape of the camera-only product, and the sentence
        # has to say so or the list reads as a defect report. The old line also said "video
        # and inertial only" unconditionally, which is wrong on a take with no IMU.
        "This is the camera-only product: stereo video%s, and no tactile glove was worn. "
        "That is the shape of the capture, not something missing from it. Nothing here "
        "supports contact timing or contact force."
        % (" plus the inertial stream" if imu else " only, with no inertial stream"),
    ]
    if hands:
        worst = min(tact[h]["stable"] for h in hands)
        limits.append(
            "Only %d of %d readout sites per hand are live AND stable on the worst hand; "
            "quote the usable-channel count, never the 484-site grid size."
            % (worst, READOUT_SITES))
        if any(tact[h]["over_ceiling"] for h in hands):
            limits.append("Over-ceiling channels form contiguous runs at grid edges, which is a "
                          "connector or flex-trace fault and is expected to progress.")
        limits.append("Peak-over-taxels traces are an ENVELOPE, not a sensor: the argmax channel "
                      "changes between adjacent samples, so an apparent rise can be two "
                      "different taxels.")
    if frames_dropped:
        limits.append("%d video frames were lost upstream of the container (%.2f%% of delivered "
                      "frames); the gaps are visible in video/frame_times.csv."
                      % (frames_dropped, 100.0 * frames_dropped / max(1, vid["frames"])))
    if n_segments == 0:
        limits.append("No temporal annotation ships with this take; there are no segments, "
                      "verbs or object labels.")
    if imu is None:
        limits.append("No inertial stream ships with this take.")
    if not sync_validated:
        limits.append("There is no independent physical sync event in this take, so alignment "
                      "rests on the shared host clock rather than on a measured common-mode "
                      "event.")
    limits.append("Synthetic evaluation fixture: the media and sensor streams were generated for "
                  "catalog development and are not a recording of a real workspace.")

    return dict(
        schema="egotac-1.0", take_id=take_id, device_id=device, firmware=firmware,
        # Declared, not inferred. The ingest folds this into
        # collection.provenance_class and the catalog renders a banner from it, so a
        # buyer is told these are generated frames before they look at one.
        media_class="synthetic",
        recorded_local=recorded_local,
        recorded_local_note="Device wall clock with its UTC offset. NTP was not stepped "
                            "during the take.",
        packaged_utc=packaged_utc, duration_s=dur,
        task=dict(description=spec["title"] + ". " + spec["long"], environment=spec["env"],
                  subjects=subjects, sessions=1,
                  annotations=(f"{n_segments} human time segments with verb and object labels"
                               if n_segments else None)),
        pipeline_version=pipeline, operator=operator,
        modalities=dict(video=video, tactile=tactile, imu=imu_block),
        calibration=dict(
            stereo=(dict(model="kannala_brandt", baseline_m=calib["baseline_m"],
                         rms_px=calib["raw"]["stereo"]["rms_px"],
                         image_size=calib["raw"]["image_size"],
                         source="calibration/calibration.json, shipped verbatim",
                         intrinsics_scale_note="DO NOT hand-transform calibration.json. Use "
                                               "calibration_delivered.json.",
                         measured_rectification_residual_px=calib["rect_px"])
                    if stereo else None),
            shutter="rolling", readout_time_ms=calib["readout_ms"],
            imu=calib["imu"], cam_imu=calib["cam_imu"], tactile_force=None),
        synchronisation=sync, quality=quality, known_limitations=limits)


# --------------------------------------------------------------------------- #
# docs + checksums
# --------------------------------------------------------------------------- #
def write_docs(d: Path, *, meta: dict, spec: Take, take_id: str, lic_name: str,
               lic_id: str, rights: dict, collection: dict, hands: list[str]):
    v = meta["modalities"]["video"]
    t = meta["modalities"]["tactile"]
    rows = [f"| `{v['file']}` | {v['layout'].replace('|', '/')}, "
            f"{v['resolution'][0]}x{v['resolution'][1]}, "
            f"{v['fps']} fps, {v['frames']} frames |",
            "| `video/frame_times.csv` | one row per container frame: `frame_idx,host_us` |"]
    if hands:
        rows.append("| `tactile/{%s}.npz` | uint16 counts at %.1f Hz, %d readout sites "
                    "per hand |" % (",".join(hands), TACTILE_RATE_HZ, READOUT_SITES))
        rows.append("| `sensor_layout.json` | per-taxel grid position and anatomical region |")
    if meta["modalities"]["imu"]:
        rows.append("| `imu/imu.csv` | `t_s,ax,ay,az,gx,gy,gz`, %d readings at %.0f Hz |"
                    % (meta["modalities"]["imu"]["n_readings"], IMU_RATE_HZ))
    if (d.parent / "segcap" / "segments.csv").exists():
        rows.append("| `segcap/segments.csv` | temporal annotation, seconds from take start |")
    rows.append("| `calibration/` | raw solve plus the pre-transformed file to actually apply |")
    rows.append("| `preview/` | poster, silent loop, and tactile stills sampled across the "
                "force distribution |")
    contents = "\n".join(rows)
    gone = []
    if not hands:
        gone.append("tactile (no glove was worn)")
    elif len(hands) == 1:
        gone.append("the %s glove (not instrumented)" % ("right" if hands[0] == "left" else "left"))
    if not meta["modalities"]["imu"]:
        gone.append("inertial data")
    if not (d.parent / "segcap" / "segments.csv").exists():
        gone.append("temporal annotation")
    absent = "; ".join(gone) if gone else "nothing -- every modality this rig captures ships here"
    write_text(d / "README.md", f"""# {spec['title']}

Take `{take_id}` -- {spec['category'].replace('_', ' ')} / {spec['subcategory'].replace('_', ' ')}.
Environment: {spec['env']}.

## What is in this package

| path | what |
|---|---|
{contents}

## Read this before you index anything

1. **Index the video by `frame_idx` and look the time up in `frame_times.csv`.**
   The container is constant frame rate; real arrival was not.
2. **Apply `calibration/calibration_delivered.json`, not `calibration.json`.**
   Hand-transforming the raw solve leaves tens of pixels of rectification error.
3. **Quote `usable_channels`, never 484.** 484 is the size of the readout grid.
   {'This take has ' + ' / '.join('%s %d' % (h, t['usable_channels_per_hand'][h]) for h in hands) + ' live-and-stable channels.' if hands else ''}

Licence: {lic_name} (`{lic_id}`). Per-clip rights are authoritative: model_training
{rights['model_training']}, commercial_use {rights['commercial_use']}, redistribution
{rights['redistribution']}, derived_model {rights['derived_model']}.

Not in this package: {absent}.

Contact {collection['vendor']['contact']}.
""")
    write_text(d / "DATASHEET.md", f"""# Datasheet -- {take_id}

## Motivation
Collected for {collection['name']} to demonstrate time-aligned egocentric video and
high-rate tactile capture on a real task ({spec['title'].lower()}).

## Composition
{meta['task']['subjects']} subject, 1 session, {meta['duration_s']} s.
{v['frames']} video frames; {'%s tactile frames' % ' / '.join('%s %d' % (h, t['per_hand'][h]['frames']) for h in hands) if hands else 'no tactile stream'}.

## Collection process
Head-mounted {'stereo' if v['layout'].startswith('side') else 'monocular'} camera and
{len(hands)} instrumented glove(s) on one host clock. Firmware {meta['firmware']},
device {meta['device_id']}, operator {meta['operator']} (pseudonym).

## Preprocessing
One re-encode from the sensor stream. No temporal resampling. No taxel values deleted:
faulty channels are listed in `quality.channels`, not removed.

## Uses
Suitable for contact-timing and force-envelope work. NOT suitable for absolute force,
finger pose, or anything requiring a physical-unit calibration.

## Distribution
{lic_name}. See LICENSE.txt.

## Limitations
""" + "\n".join(f"- {x}" for x in meta["known_limitations"]))
    write_text(d / "LICENSE.txt", f"""{lic_name}
Licence identifier: {lic_id}

Per-clip permissions (authoritative; these override any collection-level statement):
  model training      : {rights['model_training']}
  commercial use      : {rights['commercial_use']}
  redistribution      : {rights['redistribution']}
  derived model release: {rights['derived_model']}

Re-identification of any person, premises or device appearing in or inferable from this
data is prohibited.

Rights questions: {collection['vendor']['contact']}
""")
    s = meta["synchronisation"]
    write_text(d / "SYNC_PROTOCOL.md", f"""# Synchronisation protocol -- {take_id}

Reference clock
: {s['common_clock']}

Sign convention
: {s['offset_sign_convention']}

Measured worst-case alignment error
: **{s['maximum_alignment_error_ms']} ms** ({'above' if s['maximum_alignment_error_ms'] > 33.0 else 'within'} the 33.0 ms one-frame bound at 30 fps)

Validation
: {s['validation_result']} -- {s['validation_method'] or 'no validation was performed'}

## Caveats

- {s['alignment_caveat']}
- {s['cfr_vfr_warning']}
{'- ' + s['cross_hand_note'] if 'cross_hand_note' in s else ''}

## How to join a video frame to a tactile sample

```python
import numpy as np, csv
ft = np.loadtxt('video/frame_times.csv', delimiter=',', skiprows=1)   # frame_idx, host_us
z  = np.load('tactile/{hands[0] if hands else 'left'}.npz')
j  = np.searchsorted(z['host_us'], ft[:, 1])          # nearest tactile sample per frame
j  = np.clip(j, 0, len(z['host_us']) - 1)             # clamp: one stream ends first
```
""")


def write_checksums(take_dir: Path) -> tuple[int, int]:
    out, total = [], 0
    target = take_dir / "docs" / "checksums.sha256"
    files = sorted(p for p in take_dir.rglob("*") if p.is_file() and p != target)
    for p in files:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        n = p.stat().st_size
        total += n
        out.append(f"{h.hexdigest()}  {p.relative_to(take_dir).as_posix()}")
    write_text(target, "\n".join(out))
    return len(out) + 1, total + target.stat().st_size


# --------------------------------------------------------------------------- #
# the published grade rule, so the summary can be diffed against the CLI
# --------------------------------------------------------------------------- #
def predict_grade(*, hands: list[str], tact: dict, frames_dropped: int, frames: int,
                  align_ms: float, sync_validated: bool = False,
                  has_frame_times: bool = True) -> str:
    """A local echo of CONTRACT.md 4.2, so the fixture summary can be diffed against the CLI.

    This is an APPROXIMATION and the CLI is authoritative: the real rule also composes
    drift and container divergence into the skew, and A additionally requires that no
    check warns at all -- H7 completeness, the redaction record, the census cross-check.
    """
    crc = min([tact[h]["crc_pass_rate"] for h in hands], default=None)
    cov = min([tact[h]["stable"] / READOUT_SITES for h in hands], default=1.0)
    drp = frames_dropped / max(1, frames)
    skew_ok = align_ms <= 33.0
    if (frames_dropped == 0 and (crc is None or crc >= 0.9999) and cov >= 0.60
            and skew_ok and sync_validated and has_frame_times):
        return "A"
    if drp <= 0.01 and (crc is None or crc >= 0.999) and cov >= 0.40 and skew_ok \
            and has_frame_times:
        return "B"
    return "C"


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #
import datetime as _dt

# One entry per country in COUNTRY_WEIGHTS. Both of ours are UTC+08:00 and neither
# observes DST, so the local wall clock in take.yaml is unambiguous year-round.
TZ = {"CN": "+08:00", "HK": "+08:00"}
ANCHOR = _dt.datetime(2026, 8, 23, 0, 8, 21, tzinfo=_dt.timezone.utc)
FIRMWARES = ["1.3.15.glove", "1.3.16.glove", "1.4.0.glove"]
IMU_MODELS = ["BMI270", "ICM-42688-P", "LSM6DSV16X"]
PIPELINE = "egotac-pack/0.4.2"

# THE DELIVERED DROP IS ALL CAMERA + TACTILE. Every clip in the default corpus is
# egocentric STEREO video plus BOTH tactile hands plus IMU plus segcap, in CN or HK.
# That is what THIS drop contains, and the default fixture is that drop.
#
# The variations below are kept, behind --with-gaps, because the paths they exercise are
# real code. TWO DIFFERENT KINDS OF THING LIVE IN THIS DICT and the difference matters:
#
#   GAPS proper -- `right_hand_only`, `no_imu`, `no_country`, `no_segcap`, `mono`. Each is
#   something missing that should not be: an em-dash where a value is genuinely unknown, a
#   disabled tab, a one-hand census, a mono pane with no disparity. Delete the only fixture
#   that reaches those branches and they rot un-run until a real take has a hole in it.
#
#   THE SECOND PRODUCT -- `no_tactile` and `camera_only_clean`. Camera-only (stereo camera,
#   no gloves) is NOT a gap. It is one of the two things this rig sells and the packaging
#   pipeline builds it deliberately; it lives here only because this particular drop has
#   none, so this is the only place the catalog's camera-only path gets exercised. Two of
#   them on purpose, at opposite ends of the quality range, because the grader has to get
#   both right and they are different failures if it does not:
#      0  camera_only_clean   clean profile, and the ONLY warn this index would otherwise
#                             carry -- sync_independent_validation -- is inapplicable here
#                             because the take delivers one clocked stream. Must reach
#                             grade A. If it cannot, the grade rule is penalising a product
#                             for questions about a different product, which is exactly the
#                             defect `not_applicable` was added to fix.
#     15  no_tactile          caveat profile, IMU kept -- camera-only WITH real defects, and
#                             with a genuine alignment question it has not answered. Must
#                             still grade DOWN. If it ever reaches A, `not_applicable` has
#                             become a loophole.
#
# The gap corpus is tested (scripts/catalog/tests/test_fixture_corpus.py) and is never what
# `make fixtures` produces.
GAPS = {0: "camera_only_clean", 4: "right_hand_only", 6: "no_imu", 9: "no_country",
        11: "no_segcap", 15: "no_tactile", 19: "mono"}

#: The two `gap` ids that are not gaps at all: they build the OTHER product.
CAMERA_ONLY = frozenset({"no_tactile", "camera_only_clean"})

#: `camera_only_clean` ships NO IMU either, and that is deliberate rather than incidental.
#: It makes the take a single-clocked-stream package, which is the only shape where
#: `sync_max_skew_ms` and `sync_independent_validation` are honestly inapplicable -- there
#: is no second stream for the video to be out of step with. That is the second half of the
#: grader change and `no_tactile` (which keeps its IMU) does not reach it.
#:
#: It is also the only way this fixture can reach grade A without lying. A camera-only take
#: that DOES carry the fixture's IMU has a real alignment question and no answer to it: the
#: fixture's IMU rides a free-running sample counter that is explicitly declared NOT on the
#: reference clock, so nothing physical corroborates the pair and `sync_independent_validation`
#: warns -- exactly as it warns on a tactile take with no clap staged. Faking a "pass" there
#: would put a staged common-mode event in the same document as `imu_not_on_reference`, which
#: says nobody solved that offset. B is the right grade for that take and it is the same B a
#: tactile take in the same state gets, which is the equality this whole change is about.
_NO_IMU_GAPS = frozenset({"no_imu", "camera_only_clean"})


def validation_method(sync_validated: bool, hands: list[str], imu: bool) -> str | None:
    """What physically corroborated this take's stream alignment, if anything.

    A CLAP CORROBORATES VIDEO AGAINST GLOVES. On a camera-only take there are no gloves, so
    quoting the clap would publish a measurement that could not have happened -- and the
    clip record renders this string verbatim on the Calib & sync tab. The common-mode event
    there is the video frame against the IMU accelerometer instead.

    With neither a glove nor an IMU the take delivers ONE clocked stream, so there is no
    cross-stream alignment for anything to corroborate. That is not "we did not validate
    it"; it is "there is nothing here to validate". This returns null, `build_sync` returns
    no record, and the ingest marks the check `not_applicable` rather than `not_run`.
    """
    if not (hands or imu):
        return None
    if not sync_validated:
        return ("No independent common-mode physical event was staged in this take; "
                "alignment rests on the shared host clock.")
    if hands:
        return ("A bimanual clap was staged at the head of the take: the frame in which the "
                "hands meet is identified in video/frame_times.csv and the impact transient "
                "is picked on both gloves. The three timestamps are compared directly, so "
                "this is independent evidence rather than a restatement of the clock "
                "arithmetic.")
    return ("A single sharp table strike was staged at the head of the take: the frame in "
            "which the hand lands is identified in video/frame_times.csv and the impact "
            "transient is picked on the IMU accelerometer. The two timestamps are compared "
            "directly, so this is independent evidence rather than a restatement of the "
            "clock arithmetic.")


def _article(phrase: str) -> str:
    """`a` or `an` for a following phrase. Every clip description prints this.

    Eight of the 29 environments start with "indoor", so the naive "in a {env}"
    put "in a indoor workshop" on the Metadata tab of a third of the corpus --
    a grammar error on the buyer-facing surface, visible in
    docs/catalog/screenshots/modal-1440-metadata.png before this fix.

    Sound, not spelling, is what decides the article, so this is a vowel-letter
    test with the usual exceptions rather than a regex. It only has to be right
    for the environment strings this file emits, and it is asserted for all of
    them in tests/test_fixture_corpus.py.
    """
    w = phrase.strip().split()[0].lower().strip("(\"'") if phrase.strip() else ""
    if not w:
        return "a"
    # "a one-piece", "a unit", "a European" -- vowel letter, consonant sound.
    if w.startswith(("one", "uni", "use", "user", "euro", "ubiq")):
        return "a"
    # "an hour", "an honest" -- consonant letter, vowel sound.
    if w.startswith(("hour", "honest", "honour", "heir")):
        return "an"
    return "an" if w[0] in "aeiou" else "a"


def plan(i: int, seed: int, with_gaps: bool, countries: list[str],
         seconds: tuple[float, float] = (30.0, 45.0)) -> dict:
    rng = Random(seed * 7919 + i * 131 + 17)
    spec = dict(POOL[i % len(POOL)])
    gap = GAPS.get(i) if with_gaps else None
    country = countries[i % len(countries)]
    device = DEVICES[(i + seed) % len(DEVICES)]
    when = ANCHOR - _dt.timedelta(days=i * 9 + rng.randint(0, 6),
                                  hours=rng.randint(0, 20), minutes=rng.randint(0, 59))
    take_id = "ego_%s_%s" % (when.strftime("%Y%m%d_%H%M%S"), device)
    # Stereo unless the gap corpus explicitly asks for the mono pane.
    stereo = gap != "mono"
    # The DELIVERED corpus is ~30 clips of 30-45 s. The fixture has to be that shape or
    # the two things it exists to prove -- that the chart picks a legible unit, and that
    # 30 bars lay out -- are both proved against the wrong numbers.
    frames = rng.randint(int(round(seconds[0] * VIDEO_FPS)),
                         int(round(seconds[1] * VIDEO_FPS)))
    prof_name = PROFILE_CYCLE[i % len(PROFILE_CYCLE)]
    hands = ["left", "right"]
    if gap in CAMERA_ONLY:
        hands = []
    elif gap == "right_hand_only":
        hands = ["right"]
    rp_name, rights, lic_id, lic_name = RIGHTS_PROFILES[(i * 3 + 1) % len(RIGHTS_PROFILES)]
    # Consent must cover what the rights claim. The ingest FAILS a clip that grants a
    # permission with no consent record, no licence document and no dated review behind
    # it, so a take that asserts anything softer than 'denied' has to carry the whole H6
    # paperwork -- notice, redaction record with a policy version and a reviewer, a
    # retention policy with a deletion address, and a consent record naming what it covers.
    asserts = any(v != "denied" for v in rights.values())
    consented = rights["model_training"] == "granted" or rights["commercial_use"] == "granted"
    reviewed_utc = (when + _dt.timedelta(hours=30, minutes=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    privacy = dict(
        consent_on_file=True if asserts else rng.choice([False, False, True]),
        faces_redacted=True if consented else rng.choice([True, False, False]),
        pii_review="passed" if consented else rng.choice(["pending", "passed", "not_required"]),
        notice_given=True,
        identifiable_persons=0,
        identifiable_premises=False,
        reidentification_prohibited=True)
    if with_gaps and i % 7 == 5:                       # one clip with an unassessed field
        privacy["faces_redacted"] = None
    if privacy["faces_redacted"] is True:
        # H6 wants the RECORD, not the outcome. `faces_redacted: true` with a null
        # redaction block asserts a pass that the schema itself defines as never run.
        privacy["redaction"] = dict(
            policy_version="6s-redaction/1.2", targets=["faces", "screens", "documents"],
            method="blur", reviewer="rev-%02d" % (1 + i % 3), reviewed_utc=reviewed_utc,
            items_redacted=rng.randint(0, 4))
    privacy["retention"] = dict(
        policy="Source material is held for 24 months from capture, then destroyed. "
               "Delivered packages are the buyer's to retain under their licence.",
        delete_after_utc=(when + _dt.timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        deletion_request_contact="privacy@6thsense.dev")
    if asserts:
        privacy["consent"] = dict(
            subjects_consented=1,
            covers_model_training=True,
            covers_redistribution=rights["redistribution"] != "denied"
                                  or rights["derived_model"] != "denied",
            document_ref="consent/%s-%02d" % (when.strftime("%Y%m"), i))
    # H10. Assigned BY CAPTURE DEVICE, not at random, so no device appears in two splits
    # and a model cannot memorise a rig. Deterministic from the device id.
    split = {"16A260": "train", "16A317": "train", "16B044": "val", "17C902": "test"}[device]
    # A CAMERA-ONLY TAKE GETS ITS OWN SENTENCES, not the tactile ones with the nouns filed
    # off. The old template produced "the camera share one host clock" on a glove-less take
    # -- ungrammatical, and worse, it went on to sell time alignment as "the value of the
    # take" for a package that has one stream to align. Camera-only is a product, so it is
    # described as one: what it is, not what it is missing.
    _worn = ("The take is continuous and unstaged: the hands enter frame already working, "
             "and the tactile arrays are worn snug, so contact is present from the first "
             "sample rather than starting from a clean baseline."
             if hands else
             "The take is continuous and unstaged: the hands enter frame already working. "
             "No tactile glove is worn on this take -- this is the camera-only product, "
             "which is one of the two this rig ships, and not a capture with a stream "
             "missing from it.")
    # NO PRECISION CLAIM IN EITHER BRANCH. The clip's own measured
    # sync.maximum_alignment_error_ms is rendered on the Calib & sync tab, next to this
    # clip's frame period, and the build refuses a description that claims a bound the
    # measurement does not support (validate.py, "clip copy does not overstate measured
    # sync"). Point at the number; do not restate it.
    _value = (
        f"The value of the take is the time alignment: "
        f"{'both gloves and the ' if len(hands) == 2 else 'the glove and the '}"
        f"camera share one host clock, and the resulting worst-case inter-stream error is "
        f"measured and published per clip rather than claimed -- see Calib & sync. What it "
        f"is not is a force dataset: the tactile values are raw ADC counts with no mapping "
        f"to newtons."
        if hands else
        "What ships is the calibrated stereo pair and its per-frame exposure index: the "
        "delivered panes, the fisheye intrinsics and the rectification residual actually "
        "measured on a delivered frame -- see Calib & sync. What it is not is a tactile "
        "take; there is no contact signal here to align anything to, and the tactile QA "
        "checks read not_applicable rather than not_run for that reason.")
    spec["long"] = (
        f"A single operator performs {spec['title'][0].lower() + spec['title'][1:]} in "
        f"{_article(spec['env'])} "
        f"{spec['env']}. {_worn}\n\n" + _value)
    return dict(
        i=i, spec=spec, take_id=take_id, device=device, country=country, gap=gap,
        stereo=stereo, frames=frames, hands=hands, prof=prof_name,
        imu=gap not in _NO_IMU_GAPS,
        rights=rights, rights_profile=rp_name, license_id=lic_id, license_name=lic_name,
        privacy=privacy, when=when, tz=TZ[country], split=split,
        # A staged bimanual clap -- visible in video, sharp on both gloves -- is the only
        # thing that turns "the clocks agree" into measured evidence. The operator runs one
        # on every third take, so the fixture exercises both the pass and the not_validated
        # branch rather than only the second.
        sync_validated=(i % 3 == 1),
        # One fully-open take is packaged as a downloadable archive so a prospect can run a
        # real clip through their own loader without a contract. It has to be both `open`
        # on rights and `clean` on QA, which picks a handful out of thirty.
        publish_archive=(rp_name == "open" and prof_name == "clean"),
        operator=OPERATORS[(i * 3 + seed) % len(OPERATORS)],
        firmware=FIRMWARES[i % len(FIRMWARES)], imu_model=IMU_MODELS[i % len(IMU_MODELS)],
        subjects=1, seed=seed * 7919 + i * 131 + 17)


# --------------------------------------------------------------------------- #
# one take
# --------------------------------------------------------------------------- #
def build_take(p: dict, takes_dir: Path, tmp: Path, collection: dict, force: bool) -> dict:
    import numpy as np
    rng = Random(p["seed"])
    d = takes_dir / p["take_id"]
    for sub in ("video", "calibration", "preview", "docs", "segcap"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    spec, hands, prof = p["spec"], p["hands"], QA_PROFILES[p["prof"]]

    # ---- video -----------------------------------------------------------
    vname = "stereo_upright.mp4" if p["stereo"] else "mono.mp4"
    vpath = d / "video" / vname
    for stale in ("stereo_upright.mp4", "mono.mp4"):
        if stale != vname and (d / "video" / stale).exists():
            (d / "video" / stale).unlink()
    vid = make_video(vpath, tmp, stereo=p["stereo"], frames=p["frames"], title=spec["title"],
                     take_id=p["take_id"], device=p["device"], seed=p["seed"], force=force)

    dropped = min(int(prof["drop"]), max(0, vid["frames"] - 2))
    epoch_us = int(p["when"].timestamp() * 1e6)
    ftimes = make_frame_times(d / "video" / "frame_times.csv", vid["frames"], epoch_us,
                              Random(p["seed"] + 1), dropped)
    dur_s = round(vid["frames"] / ftimes["measured_fps"], 4)

    # ---- tactile ---------------------------------------------------------
    tact = {}
    for k, h in enumerate(hands):
        tact[h] = make_tactile(d / "tactile" / f"{h}.npz", h, dur_s,
                               epoch_us + rng.randint(1200, 14000), p["seed"] + 11 * (k + 1),
                               prof, Random(p["seed"] + 31 * (k + 1)))
    if not hands and (d / "tactile").exists():
        shutil.rmtree(d / "tactile")

    align_ms = round(rng.uniform(*prof["align"]), 3)

    # ---- imu -------------------------------------------------------------
    imu = None
    if p["imu"]:
        imu = make_imu(d / "imu" / "imu.csv", dur_s, p["seed"] + 7)
    elif (d / "imu").exists():
        shutil.rmtree(d / "imu")

    # ---- segments --------------------------------------------------------
    segs = []
    if p["gap"] != "no_segcap":
        segs = make_segments(d / "segcap" / "segments.csv", d / "segcap" / "subtasks.json",
                             spec, dur_s, Random(p["seed"] + 3))
    elif (d / "segcap").exists():
        shutil.rmtree(d / "segcap")

    # ---- calibration + layout -------------------------------------------
    calib = make_calibration(d / "calibration" / "calibration.json",
                             d / "calibration" / "calibration_delivered.json",
                             stereo=p["stereo"], device=p["device"],
                             delivered_wh=((vid["width"] // 2, vid["height"]) if p["stereo"]
                                           else (vid["width"], vid["height"])),
                             rng=Random(p["seed"] + 5), imu_model=p["imu_model"])
    if hands:
        make_sensor_layout(d / "sensor_layout.json", hands)
    elif (d / "sensor_layout.json").exists():
        (d / "sensor_layout.json").unlink()

    # ---- previews --------------------------------------------------------
    make_poster_and_preview(vpath, d / "preview" / "poster.jpg",
                            d / "preview" / "preview.mp4", dur_s, force)
    for old in (d / "preview").glob("*.png"):
        old.unlink()
    if hands:
        # Select on the combined peak across hands so the caption and the frame
        # agree, and sample ACROSS the distribution rather than at the peak.
        m = min(tact[h]["peak_series"].shape[0] for h in hands)
        peak = tact[hands[0]]["peak_series"][:m]
        for h in hands[1:]:
            peak = np.maximum(peak, tact[h]["peak_series"][:m])
        for label, q in (("p50", 50), ("p75", 75), ("p90", 90), ("p95", 95),
                         ("p99", 99), ("max", 100)):
            target = float(np.percentile(peak, q))
            fi = int(np.argmin(np.abs(peak - target)))
            t_s = fi / TACTILE_RATE_HZ
            idxs = {h: min(fi, tact[h]["counts"].shape[0] - 1) for h in hands}
            pk = int(round(float(peak[fi])))
            render_tactile_still(
                d / "preview" / f"{label}_frame{fi:04d}_peak{pk}_t{t_s:05.1f}s.png",
                tact, idxs, t_s, pk, label)

    # ---- metadata --------------------------------------------------------
    packaged = (p["when"] + _dt.timedelta(hours=9, minutes=37)).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = build_metadata(
        spec=spec, take_id=p["take_id"], device=p["device"], firmware=p["firmware"],
        operator=p["operator"],
        recorded_local=p["when"].astimezone(
            _dt.timezone(_dt.timedelta(
                hours=int(p["tz"][:3]),
                minutes=int(p["tz"][0] + p["tz"][4:])))).isoformat(timespec="microseconds"),
        packaged_utc=packaged, stereo=p["stereo"], vid=vid, ftimes=ftimes, tact=tact,
        imu=imu, calib=calib, n_segments=len(segs), frames_dropped=dropped,
        align_ms=align_ms, subjects=p["subjects"], pipeline=PIPELINE,
        sync_validated=p["sync_validated"])
    write_json(d / "metadata.json", meta)

    # ---- take.yaml -- the eleven values a machine cannot derive ----------
    ty = {"title": spec["title"], "category": spec["category"],
          "subcategory": spec["subcategory"]}
    if p["gap"] != "no_country":
        ty["country"] = p["country"]
    ty["rights"] = dict(p["rights"])
    # CONTRACT: rights.determined_utc null means "never reviewed", and then all four
    # permissions must read 'denied'. Any profile that asserts anything softer therefore has
    # to carry the review timestamp, or the ingest fails the rights_reviewed check and no
    # take can ever reach grade A.
    if any(v != "denied" for v in p["rights"].values()):
        ty["rights"]["determined_utc"] = (
            p["when"] + _dt.timedelta(hours=30, minutes=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ty["privacy"] = {k: v for k, v in p["privacy"].items() if v is not None}
    ty["split"] = p["split"]
    if p["publish_archive"]:
        ty["publish_archive"] = True
    ty["operator"] = p["operator"]
    ty["environment"] = spec["env"]
    ty["subjects"] = p["subjects"]
    ty["recorded_month"] = p["when"].strftime("%Y-%m")
    ty["description"] = spec["long"]
    ty["license_id"] = p["license_id"]
    ty["license_name"] = p["license_name"]
    if p["rights_profile"] == "eval_locked":
        ty["restrictions"] = ["Named recipient only; shared solely for technical evaluation."]
    header = ("# take.yaml -- the values no machine can derive (see docs/catalog/INTAKE.md §3).\n"
              "# Generated by fixtures/generate_fixtures.py; edit freely, it is plain text.\n")
    write_text(d / "take.yaml", header + yaml_dump(ty))

    # ---- docs + checksums ------------------------------------------------
    write_docs(d / "docs", meta=meta, spec=spec, take_id=p["take_id"],
               lic_name=p["license_name"], lic_id=p["license_id"], rights=p["rights"],
               collection=collection, hands=hands)
    n_files, total_bytes = write_checksums(d)

    grade = predict_grade(hands=hands, tact=tact, frames_dropped=dropped,
                          frames=vid["frames"], align_ms=align_ms,
                          sync_validated=p["sync_validated"])
    return dict(
        take_id=p["take_id"], title=spec["title"], country=p["country"] if p["gap"] != "no_country" else None,
        category=spec["category"], capture="stereo" if p["stereo"] else "mono",
        duration_s=dur_s, frames=vid["frames"], fps=ftimes["measured_fps"],
        resolution=f'{vid["width"]}x{vid["height"]}', hands=hands,
        usable={h: tact[h]["stable"] for h in hands},
        crc=min([tact[h]["crc_pass_rate"] for h in hands], default=None),
        imu_readings=imu["n_readings"] if imu else 0, segments=len(segs),
        dropped=dropped, align_ms=align_ms, grade=grade, rights=p["rights_profile"],
        files=n_files, bytes=total_bytes, gap=p["gap"] or "")


# --------------------------------------------------------------------------- #
# collection.toml -> takes/collection.yaml
# --------------------------------------------------------------------------- #
def load_collection(path: Path) -> dict:
    import tomllib
    if not path.exists():
        die(f"collection metadata not found: {path}\n"
            "It ships next to this script as fixtures/collection.toml.")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    for key in ("id", "name", "version", "description"):
        if key not in raw.get("collection", {}):
            die(f"collection.toml is missing collection.{key}")
    c = raw["collection"]
    return dict(id=c["id"], name=c["name"], version=c["version"],
                description=" ".join(c["description"].split()),
                # The authored standfirst. Optional: a drop that omits it gets a header
                # with no promoted line rather than a sliced one, which is the honest
                # failure -- see the note above the field in collection.toml.
                standfirst=" ".join((c.get("standfirst") or "").split()) or None,
                vendor=dict(raw["vendor"]), license=dict(raw["license"]),
                notice=c.get("notice"),
                split_policy=" ".join((c.get("split_policy") or "").split()) or None,
                # Carried through verbatim: the chart's unit, our own series identity and
                # any [[benchmark.comparison]] entries live here, and the ingest reads them
                # off the emitted collection.yaml. Dropping the table on the floor is how
                # the fixture bundle silently loses the legend label.
                benchmark=raw.get("benchmark") or {},
                fixtures=raw.get("fixtures", {}))


def write_collection_yaml(path: Path, c: dict):
    doc = {"id": c["id"], "name": c["name"], "version": c["version"],
           "description": c["description"],
           "standfirst": c.get("standfirst"),
           "vendor": {"name": c["vendor"]["name"], "url": c["vendor"].get("url"),
                      "contact": c["vendor"].get("contact")},
           "license": {"id": c["license"].get("id"), "name": c["license"]["name"],
                       "url": c["license"].get("url"),
                       "summary": " ".join(c["license"]["summary"].split())},
           "split_policy": c.get("split_policy"),
           "notice": c.get("notice")}
    if c.get("benchmark"):
        doc["benchmark"] = c["benchmark"]
    header = ("# collection.yaml -- one per drop (see docs/catalog/INTAKE.md §4).\n"
              "# Generated from fixtures/collection.toml.\n")
    write_text(path, header + yaml_dump(doc))


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def summary_table(rows: list[dict]) -> str:
    cols = [("#", 3, "r"), ("take_id", 27, "l"), ("title", 34, "l"), ("cat", 20, "l"),
            ("cc", 2, "l"), ("cap", 3, "l"), ("dur", 5, "r"), ("frm", 4, "r"),
            ("hands", 5, "l"), ("usable", 7, "l"), ("crc", 6, "r"), ("imu", 5, "r"),
            ("seg", 3, "r"), ("drop", 4, "r"), ("skew", 5, "r"), ("QA", 2, "l"),
            ("rights", 11, "l"), ("files", 5, "r"), ("size", 7, "r"), ("note", 15, "l")]

    def cell(v, w, a):
        s = str(v)
        s = s if len(s) <= w else s[:w - 1] + "…"
        return s.rjust(w) if a == "r" else s.ljust(w)

    out = ["  ".join(cell(n, w, a) for n, w, a in cols),
           "  ".join("-" * w for _, w, _ in cols)]
    for k, r in enumerate(rows):
        hands = "".join(h[0].upper() for h in r["hands"]) or "-"
        usable = "/".join(str(r["usable"][h]) for h in r["hands"]) or "-"
        vals = [k, r["take_id"], r["title"], r["category"], r["country"] or "—",
                r["capture"][:3].upper(), f'{r["duration_s"]:.1f}', r["frames"], hands, usable,
                "-" if r["crc"] is None else f'{r["crc"]:.4f}', r["imu_readings"],
                r["segments"], r["dropped"], f'{r["align_ms"]:.1f}', r["grade"], r["rights"],
                r["files"], human_bytes(r["bytes"]), r["gap"] or ""]
        out.append("  ".join(cell(v, w, a) for v, (_, w, a) in zip(vals, cols)))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="generate_fixtures.py",
        description="Generate a synthetic takes/ tree for the 6thSense catalog ingest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The tree conforms to docs/catalog/INTAKE.md; feed it straight to the ingest CLI:\n"
               "    catalog-build <out>/takes --out <out>/catalog --strict")
    ap.add_argument("--out", required=True, type=Path,
                    help="output directory; a takes/ tree is written inside it "
                         "(or directly into it if it is already named 'takes')")
    ap.add_argument("--clips", type=int, default=None,
                    help="number of takes (default from [fixtures] in collection.toml)")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed (default 7)")
    ap.add_argument("--min-seconds", type=float, default=None,
                    help="shortest take, in seconds (default from [fixtures], 30)")
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="longest take, in seconds (default from [fixtures], 45)")
    ap.add_argument("--collection", type=Path, default=HERE / "collection.toml",
                    help="collection metadata TOML (default fixtures/collection.toml)")
    ap.add_argument("--force", action="store_true",
                    help="re-encode video even when an up-to-date file is already present")
    ap.add_argument("--with-gaps", action="store_true",
                    help="add the deliberate variations that exercise the UI's disabled-tab "
                         "and em-dash paths, and the catalog's camera-only path: one mono "
                         "take, one with no IMU, one with no segcap, one right-hand-only, one "
                         "with no country, and TWO camera-only takes (the second product -- "
                         "one at the caveat profile that must still grade down, one clean and "
                         "IMU-less that must reach grade A). OFF by default: this drop is "
                         "stereo + both hands throughout, and the default fixture is the drop.")
    ap.add_argument("--uniform", action="store_true",
                    help=argparse.SUPPRESS)   # deprecated: gapless is now the default
    ap.add_argument("--clean", action="store_true",
                    help="delete the takes/ tree before generating")
    a = ap.parse_args(argv)

    require_tools()
    coll = load_collection(a.collection)
    fx = coll["fixtures"]
    clips = a.clips if a.clips is not None else int(fx.get("clips", 30))
    seed = a.seed if a.seed is not None else int(fx.get("seed", 7))
    lo = a.min_seconds if a.min_seconds is not None else float(fx.get("min_seconds", 30.0))
    hi = a.max_seconds if a.max_seconds is not None else float(fx.get("max_seconds", 45.0))
    if clips < 1:
        die("--clips must be at least 1")
    if not 0.5 <= lo <= hi:
        die(f"need 0.5 <= --min-seconds <= --max-seconds, got {lo} and {hi}")

    out = a.out.expanduser().resolve()
    takes = out if out.name == "takes" else out / "takes"
    if a.clean and takes.exists():
        shutil.rmtree(takes)
    takes.mkdir(parents=True, exist_ok=True)

    if a.uniform:
        print("note: --uniform is the default now and does nothing; --with-gaps is the "
              "flag that adds the deliberate gaps back.", file=sys.stderr)

    print(f"6thSense catalog fixtures -> {takes}")
    print(f"  collection {coll['id']} {coll['version']}   clips {clips}   seed {seed}   "
          f"{lo:g}-{hi:g} s{'   with-gaps' if a.with_gaps else '   gapless (delivered shape)'}")
    write_collection_yaml(takes / "collection.yaml", coll)

    rows = []
    ccs = country_sequence(clips, seed)
    tmp = Path(tempfile.mkdtemp(prefix="6s-fixtures-"))
    try:
        for i in range(clips):
            p = plan(i, seed, a.with_gaps, ccs, (lo, hi))
            print(f"  [{i+1:>3}/{clips}] {p['take_id']:<27} {p['spec']['title'][:44]}",
                  end="", flush=True)
            row = build_take(p, takes, tmp, coll, a.force)
            print(f"   {row['grade']}  {human_bytes(row['bytes']):>8}")
            rows.append(row)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print(summary_table(rows))
    print()
    grades = {g: sum(1 for r in rows if r["grade"] == g) for g in "ABC"}
    countries = sorted({r["country"] for r in rows if r["country"]})
    cats = sorted({r["category"] for r in rows})
    secs = sum(r["duration_s"] for r in rows)
    total = sum(r["bytes"] for r in rows)
    # Printed in the unit the ingest will choose, so the fixture summary and the catalog
    # header cannot quote the same corpus two different ways.
    span = f"{secs / 3600.0:.4f} h" if secs >= 7200.0 else f"{secs / 60.0:.1f} min"
    print(f"{len(rows)} takes   {span}   {human_bytes(total)} on disk   "
          f"{sum(r['files'] for r in rows)} files")
    print(f"  grades      A {grades['A']}  B {grades['B']}  C {grades['C']}   "
          f"(predicted with the published rule; the ingest recomputes them)")
    print(f"  capture     stereo {sum(1 for r in rows if r['capture']=='stereo')}  "
          f"mono {sum(1 for r in rows if r['capture']=='mono')}")
    # Per-country counts, not just the set: the country filter bar is built from these
    # and a mix that drifts is easier to see as 18/12 than as "CN HK".
    cc_counts = {cc: sum(1 for r in rows if r["country"] == cc) for cc in countries}
    print("  countries   " + "  ".join(f"{cc} {n}" for cc, n in sorted(cc_counts.items()))
          + (f"   ({sum(1 for r in rows if not r['country'])} take with country omitted "
             f"on purpose -> em-dash)" if any(not r["country"] for r in rows) else ""))
    both = sum(1 for r in rows if len(r["hands"]) == 2)
    print(f"  tactile     both hands {both}  one hand "
          f"{sum(1 for r in rows if len(r['hands']) == 1)}  none "
          f"{sum(1 for r in rows if not r['hands'])}")
    print(f"  categories  {len(cats)}   rights profiles "
          f"{len({r['rights'] for r in rows})}")
    gaps = [r for r in rows if r["gap"]]
    if gaps:
        print("  gaps        " + ", ".join(f"{r['take_id']}: {r['gap']}" for r in gaps)
              + "   (drop --with-gaps to remove)")
    else:
        print("  gaps        none -- every take is stereo + both hands + IMU + segcap "
              "(--with-gaps adds them back)")
    print()
    # takes.parent, not `out`: when --out is already named `takes`, out/'catalog' would put
    # the bundle INSIDE the takes tree, where the next build would try to ingest it as a take.
    print(f"Next: python3 -m ingest.catalog_ingest build --takes {takes} "
          f"--out {takes.parent / 'bundle'} --media-mode copy --posters --previews --strict")
    return 0


if __name__ == "__main__":
    sys.exit(main())
