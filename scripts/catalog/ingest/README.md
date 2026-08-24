# catalog-ingest

Turns a directory of raw takes into the catalog bundle the buyer-facing UI fetches:
`catalog.json` (validated by `schema/catalog.schema.json`), one `clips/<id>.json` per clip
(validated by `schema/clip.schema.json`), the binary sidecars the IMU and tactile views
stream, and `INGEST_REPORT.md`.

Nothing here guesses. A value the ingest cannot determine is written as `null`, the UI
renders `null` as an em-dash, and the report names the take that produced it. The one
place we fail **closed** rather than to null is `rights`: there is no "unknown"
permission, so an unreviewed clip reads `denied` on all four.

## Install

```bash
python3 -m pip install -r requirements.txt   # jsonschema, numpy
```

`ffprobe` and `ffmpeg` must be on `PATH`. Nothing else is required: TOML parsing is
`tomllib` from the standard library. `.yaml` intake files work **if** PyYAML happens to be
installed; it is deliberately not pinned, and a YAML file with no parser present fails with
the fix in the message.

## Use

Run from the catalog root (the directory containing `ingest/` and `schema/`):

```bash
python3 -m ingest.catalog_ingest build --takes takes/ --out catalog/ --posters --previews
python3 -m ingest.catalog_ingest validate --out catalog/
python3 -m ingest.catalog_ingest stats    --out catalog/
```

| flag | default | effect |
|---|---|---|
| `--media-mode copy\|link\|reference` | `reference` | how take media is materialised (below) |
| `--collection PATH` | `<takes>/collection.{toml,json,yaml}` | collection header input |
| `--posters` | off | extract a poster frame at ~12% into each clip, 960 px, JPEG q=4 |
| `--previews` | off | cut a 3 s silent 480 px h264 hover loop |
| `--jobs N` | `cpu_count-1` | parallel takes (threads: the work is ffmpeg, hashing and numpy) |
| `--force` | off | rebuild even when the inputs hash the same |
| `--dry-run` | off | list what would be built, write nothing |
| `--strict` | off | any warning is fatal **for its take**: the take is skipped and the run exits 1 |
| `--schema-dir` | `../schema` | where the two JSON Schemas live |

**Exit codes.** `0` clean · `1` at least one take failed (or `--strict` with warnings, or a
`validate` FAIL) · `2` the run could not start (no collection config, unreadable takes dir).

## Input layout

One immediate subdirectory of `--takes` per take. **The directory name becomes the clip
id**, lowercased with runs of non-alphanumerics collapsed to `-`
(`ego_20260823_000821_16A260` → `ego-20260823-000821-16a260`). That id keys bookmarks and
download receipts; renaming a take directory breaks every shared link.

Both the tidy `INTAKE.md` shape (`video/ tactile/ imu/ segcap/ calibration/ docs/`) and the
flat shape our packaged takes already use (`calibration.json`, `README.md` at the top level)
are recognised. Files are claimed by name, never guessed at.

```
takes/
├── collection.toml                    # required once, for the whole drop
└── ego_20260823_000821_16A260/
    ├── take.toml                      # the values no machine can derive
    ├── metadata.json                  # your pipeline's own metadata, any schema
    ├── video/{stereo_upright.mp4|mono.mp4, frame_times.csv}
    ├── tactile/{left.npz,right.npz}
    ├── imu/imu.csv                    #   t_s,ax,ay,az,gx,gy,gz (synonyms accepted)
    ├── segcap/segments.csv            #   t0_s,t1_s,label,verb,objects,description
    ├── calibration/{calibration.json,calibration_delivered.json}
    ├── sensor_layout.json
    ├── preview/{poster.jpg,preview.mp4,p50_*.png,…}
    └── docs/{README.md,DATASHEET.md,LICENSE.txt,SYNC_PROTOCOL.md,checksums.sha256}
```

### `take.toml`

```toml
title       = "Bimanual industrial bin-picking"   # the ACTIVITY, not the equipment
category    = "manipulation"                      # lower_snake_case
subcategory = "bin_picking"
country     = "CN"                                # ISO 3166-1 alpha-2; cannot be inferred.
                                                  # CN or HK -- see docs/catalog/INTAKE.md §0
operator    = "op-01"                             # PSEUDONYM; never a name or an email
subjects    = 1
session_id  = "sess-2026-08-23-a"
# dataset   = "pilot_mono"        # stack series for the task-distribution chart
# task      = "Parts transfer"    # bar label; defaults to the subcategory
# grade_override = "C"            # may lower the computed grade, never raise it
# imu_units  = { accel = "g", gyro = "deg/s" }
# imu_allow_zero = true           # ship an all-zero IMU stream anyway (default: drop it)
# shutter = "rolling"; readout_time_ms = 8.3      # H7
# known_limitations = ["…"]
# restrictions      = ["Named recipient only."]

[rights]                          # granted | denied | on_request — no other value, no null
model_training = "denied"
commercial_use = "denied"
redistribution = "denied"
derived_model  = "denied"
# determined_utc = "2026-08-24T09:00:00Z"   # required before any permission may be granted

[privacy]
consent_on_file = false
faces_redacted  = false
pii_review      = "pending"       # passed | pending | failed | not_required
```

`collection.toml` mirrors `collection` in the manifest: `id`, `name`, `version`,
`description`, `notice`, `[vendor]`, `[license]`, optional `country_labels` and
`[benchmark]`.

**Country codes must be nameable.** Every `facets.country` bucket ships a human `label`, and
the label is produced once, here, from the machine value — the UI carries no code table that
could drift out of step with the manifest. A code that `_COUNTRY_NAMES` in `benchmark.py` does
not know **fails the build** (exit 2) rather than falling back to the bare code, because
`{"value": "HK", "label": "HK"}` validates perfectly and still reads as a missing entry next to
`China`. Fix it by adding the ISO name to `_COUNTRY_NAMES`, or by setting
`country_labels = { XX = "…" }` in `collection.toml` when the vendor wants their own wording.

### `[benchmark]`

```toml
[benchmark]
unit = "auto"                 # auto | hours | minutes | clips
# note = "…"                  # prepended to any generated citation
# labels = { other_series = "…" }   # per-series overrides for takes that set `dataset`
# colors = { other_series = "#a69a60" }

[benchmark.series]            # OUR series. id defaults to the collection id, label to its
label = "nervous-1"      # name, color to #14120c. Renaming is this one line.
color = "#14120c"

# [[benchmark.comparison]]    # third-party corpora, OPTIONAL, empty by default
# label      = "Ego4D"
# hours      = 3670
# source_url = "https://…"    # REQUIRED. No URL -> the build FAILS, exit 2.
# retrieved  = "2026-08-23"   # REQUIRED, YYYY-MM-DD
```

`unit = "auto"` resolves from the data: **hours at or above a 2 h total, minutes below it**
(`benchmark.AUTO_HOURS_MIN_SECONDS`). The emitted `benchmark.unit` is always the resolved
value, never `auto`, and `collection.totals.duration_unit` carries the same answer for the
header, so the axis and the stat tiles cannot disagree. A ~20 minute corpus quoted in hours
draws bars of 0.0027; that is the defect this rule exists to prevent.

**Two roll-ups are emitted, not one.** `benchmark.tasks[]` is keyed by `task` (falling back to
the subcategory) and `benchmark.categories[]` is the same clips folded to `category`. At 30
clips the first is ~24 bars of one to two clips each and the second is ~10 bars with real
differences between them, so the chart picks. Both carry the same `unit`, the same `series` and
the same total, because they are the same fold (`_roll`) over the same clips. A category bar
carries the machine `value` as well as the `label`, so clicking it filters by
`facets.category[].value` and the chart and the filter bar cannot disagree about what a bar
selects. The chart must never aggregate `tasks` itself: it holds no clip-to-category map and
would have to reverse one out of display labels.

A `[[benchmark.comparison]]` entry is a **whole-corpus total published by someone else**. It
becomes a series of its own and one bar of its own — never an invented split across our task
labels — and its citation is written into `benchmark.note`, which the chart renders under the
bars. Missing or unparseable `source_url`, `retrieved`, `label` or `hours` fails the build
before a single take is read. `unit = "clips"` with comparisons present also fails: a clip
count and a published hour count are two units on one axis.

## What the build does

**Measures, never believes.** Duration, resolution, fps, codec, frame count and byte sizes
come from `ffprobe` and the filesystem. When `metadata.json` disagrees, the measurement is
used and the disagreement is listed under *ffprobe vs metadata.json* in the report. Our own
reference take claims `84.6 s` where the container holds `84.630739 s`; you see both.

**IMU.** `imu/imu.csv` is sniffed for its header (`t_s`/`t`/`timestamp`/`host_us` plus
`ax…gz` or `accel_x…gyro_z`). The **full** series is written to `imu/<id>.f32` — headerless,
little-endian float32, interleaved `ax,ay,az,gx,gy,gz` (`t` prepended when sampling is
non-uniform). It is never decimated: the IMU tab scrolls through every reading. Below the
contract's fixed 2000-reading threshold the samples go inline instead and the sidecar is
`null`. A stream that is exactly zero everywhere is a dead IMU, not data: it is reported and
dropped from `modalities`.

**Tactile.** `.npz` members are streamed off the zip a row-block at a time, so peak memory
does not grow with take length. The channel census counts three independent fault modes
separately — silent, over-ceiling, intermittent — and the record quotes `stable`, never
`live` and never the 484 readout sites. Where the producer ships `taxel_ok/live/stable`
masks we use them; otherwise the census is re-derived from the counts (on our reference take
the derived census reproduces the shipped masks exactly: 164 silent, 18 over-ceiling, 24
intermittent, 278 stable). The peak trace is max-pooled to ≤ 4000 points onto one time base
shared by both gloves — max, not mean, because it is an envelope.

**Posters and previews** are always bundle-owned (`posters/<id>.jpg`, `previews/<id>.mp4`),
copied from `preview/poster.jpg` when the take ships one, otherwise cut with ffmpeg under
`--posters`/`--previews`. That keeps the grid working in `reference` mode.

**Grade** follows the published deterministic rule in `docs/catalog/CONTRACT.md` §4.2 and can be
overridden downward only. A missing `metadata.json` or `frame_times.csv` caps it at C. A
clip with any `fail` check is not dispositioned `accepted`, so it never reaches the manifest
— it is listed in the report as a failure and the run exits 1.

## Output layout

```
catalog/
├── catalog.json           clips/<id>.json          INGEST_REPORT.md
├── posters/<id>.jpg       previews/<id>.mp4        stills/<id>/*.png
├── imu/<id>.f32           tactile/<id>.peak.f32
├── media/<id>/…           the take package (copy and link modes only)
└── .ingest-state.json     digest cache + per-take summaries; safe to delete
```

## Media modes

`reference` (default) writes only relative URLs and copies no bytes. `copy` hard-links
within a filesystem and copies across devices. `link` symlinks. **The manifest and every
clip record are byte-identical in all three** — verified in the smoke test — so the cheap
mode is also the correct one for local work.

Under `reference` the `media/<id>/…` URLs point at files that were never materialised, so
`validate` reports *referenced take media exists* as **WARN** rather than FAIL; under `copy`
or `link` the same row must be PASS.

## Idempotence

Each take is keyed by a content hash: the SHA-256 of every input file (which H2 needs anyway
for `package_contents`, so it is free after the first run), plus the pipeline version, the
media mode, the poster/preview flags and a hash of the collection config. Unchanged takes
are served from `.ingest-state.json`. Every output goes through a write-if-changed guard,
and when nothing moved `catalog.json` keeps its previous `generated_utc`, so a no-op rebuild
prints `0 changed` and touches no bytes.

## `validate`

Beyond both JSON Schemas it re-derives what the manifest precomputes, because a manifest
that validates and then lies is worse than one that fails:

- every clip resolves to a detail record that exists and parses;
- each summary is a strict subset of its detail record (identical `title`, `duration_s`,
  `category`, `capture`, `bytes`, `country`);
- every bundle-relative URL resolves to a file on disk;
- facet buckets equal a recount over `clips[]`;
- every `facets.country` bucket carries a display label that is not just its own code back
  again — the second lock on the rule above, for a hand-edited or older bundle;
- `collection.totals` equals the sum over `clips[]`;
- each `.f32` sidecar is exactly `n_readings * stride_bytes` long.

## Two places we deviate, and why

1. **No decimated card sparkline for the IMU.** The contract requires `channels` to be
   `null` whenever `encoding` is `sidecar_f32le`, and `ClipSummary` has no IMU field at all,
   so there is no schema-legal slot for a second, smaller copy of the series. We do not
   invent one. Under 2000 readings the inline arrays already are that preview; above it a
   client range-reads the head of `imu/<id>.f32`.
2. **`--strict` skips the take rather than only flagging it.** "Fatal" is taken literally:
   a warning is a field that will render as an em-dash in front of a buyer, and a smaller
   catalog you were told about beats a wrong one you were not. The run still writes the
   bundle and always exits 1.

## Module map

| file | holds |
|---|---|
| `catalog_ingest.py` | argparse surface, per-take pipeline, idempotence, manifest assembly |
| `probe.py` | ffprobe/ffmpeg, hashing, take-directory layout, media file pointers |
| `imu.py` | `imu.csv` → `imu_preview` + the f32 sidecar |
| `tactile.py` | `.npz` → `tactile_preview`: census, peak envelope, geometry |
| `records.py` | rights, privacy, segments, package contents, calibration, the clip record |
| `validate.py` | sync (H1/H3), QA checks and grade (H2/H4), bundle validation, the report |
| `benchmark.py` | facets, totals, the task and category roll-ups, and the shared value-shaping helpers |
