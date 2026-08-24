# Catalog fixtures

Synthetic takes so the buyer-facing catalog is demoable **before the real data lands**.

`generate_fixtures.py` writes a `takes/` tree in exactly the shape [`docs/catalog/INTAKE.md`](../../../docs/catalog/INTAKE.md)
describes, so the ingest CLI consumes it with no special-casing and no fixture-only branch.
Everything the CLI reads off a file — durations, frame counts, channel census, CRC rates,
byte counts, SHA-256s — is measured from the bytes this script actually wrote. Nothing is a
stale copy of the reference package.

```bash
make -C scripts/catalog fixtures            # the usual way
# or, longhand:
python3 fixtures/generate_fixtures.py --out ../sample --clips 30 --min-seconds 30 --max-seconds 45
```

Defaults come from `[fixtures]` in `collection.toml` and match the **delivered corpus shape:
30 takes of 30-45 s, about twenty minutes of runtime, every one of them egocentric stereo video
plus both tactile gloves, recorded in CN or HK**. That shape is not cosmetic — it is what makes
the ingest resolve `benchmark.unit` to `minutes` and the chart lay out 30 bars, so a fixture
run at 18 takes of 8 s proves neither.

Roughly **40 s and 8 MB per take** at that length: a full run is ~20 minutes and ~240 MB.
`--clips 5` is the fast loop while iterating.

## Requirements

| | |
|---|---|
| `ffmpeg` + `ffprobe` on PATH | real, playable video. The script checks and exits with install instructions if either is missing. |
| `numpy` | the tactile `.npz` arrays. |

`drawtext` / libfreetype is **not** required. Burn-ins are rasterised by a 5×7 bitmap font in
this script and composited as PNG overlays, so output is byte-identical regardless of how
ffmpeg was built.

## Flags

| flag | default | what |
|---|---|---|
| `--out DIR` | *required* | writes `DIR/takes/…` (or straight into `DIR` if it is already named `takes`) |
| `--clips N` | 30 (`collection.toml`) | number of takes. The content pool holds 31 entries across 10 categories and cycles beyond that. |
| `--seed N` | 7 (`collection.toml`) | everything is deterministic under this. |
| `--min-seconds S` | 30 (`collection.toml`) | shortest take. Video length drives tactile, IMU and segment length too. |
| `--max-seconds S` | 45 (`collection.toml`) | longest take. |
| `--collection PATH` | `fixtures/collection.toml` | collection-level metadata. |
| `--force` | off | re-encode video even when an up-to-date file is present. |
| `--with-gaps` | off | put the [deliberate gaps](#deliberate-gaps-with-gaps) back. The default corpus has none. |
| `--clean` | off | delete the `takes/` tree first. |

`--uniform` is accepted and does nothing: gapless is the default now. It prints a note and
carries on, so an old command line still works.

**Deterministic and idempotent.** Same `--seed` ⇒ byte-identical tree, verified including the
x264 output and including `--force`. A re-run over an existing directory reproduces the same
bytes and skips re-encoding video whose frame count already matches.

## What each take contains

```
ego_20260818_173621_17C902/
├── take.yaml                the eleven values no machine can derive (INTAKE §3)
├── metadata.json            egotac-1.0, ~20 KB, every number measured
├── video/
│   ├── stereo_upright.mp4   1920×600 SBS, 30 fps, 30-45 s, ~2 MB (or mono.mp4, 1280×720)
│   └── frame_times.csv      frame_idx,host_us — exactly one row per container frame
├── tactile/{left,right}.npz counts uint16 (frames,484) @246.5 Hz + baseline, three channel
│                            masks, device_us, host_us, seq, crc_ok
├── imu/imu.csv              t_s,ax,ay,az,gx,gy,gz @200 Hz, 6 000–9 000 rows
├── segcap/
│   ├── segments.csv         t0_s,t1_s,label,verb,objects,description — the CLI's input
│   └── subtasks.json        the same segments in richer JSON form
├── calibration/
│   ├── calibration.json             raw Kannala-Brandt solve at 1920×1200
│   └── calibration_delivered.json   already scaled + de-rotated for the delivered panes
├── sensor_layout.json       per-taxel row/col/region/MANO point for both hands
├── preview/
│   ├── poster.jpg  preview.mp4      grabbed at 10 %, 4 s silent loop
│   └── p50_ p75_ p90_ p95_ p99_ max_ *.png   tactile heatmap stills
└── docs/  README.md DATASHEET.md LICENSE.txt SYNC_PROTOCOL.md checksums.sha256
```

### The video is real footage, not a black rectangle

A warm synthetic bench scene: a gradient wall, a floor band and three animated objects, with
a `testsrc2` inset for texture. The two eyes are rendered as **separate chains with per-object
disparity** — the near box shifts 52 px between eyes, the far box 26 px — so
`d = x_left − x_right > 0` on every object, which is the sign a correct `[left | right]` pair
must have. Burned in: `LEFT CAMERA` / `RIGHT CAMERA` corner labels, a hairline down the split,
a per-frame `FRAME 000123` counter, and the title and take id along the bottom. Mono takes get
`FRONT CAMERA`, no hairline and no split.

### The tactile arrays have a real channel census

484 readout sites per hand on a 22×22 grid, indexed `i = row*22 + P[col]` with the confirmed
per-hand permutation (rows 0–9 fingers, 10–21 palm). Each hand gets:

- a **worn-snug pedestal** — the glove is strapped on, so a band of taxels is loaded from the
  first sample and the median per-frame peak lands around 100–150 counts, not 3;
- **2–4 grasp events** ramping a contiguous patch to 200–575 counts on a raised-cosine envelope;
- **silent** channels (~⅓, concentrated in the palm array) with literally zero variance;
- **over-ceiling** channels in contiguous runs at a grid edge, spiking past 2 000 counts —
  a connector fault, and the damage note in `metadata.json` says so anatomically;
- **intermittent** channels that violate the ±150-counts-per-sample slew rule;
- idle residual at sd 0.94 counts with lag-1 correlation 0.41.

Host timestamps carry the reader's burst quantisation — ~16 tactile frames arrive per USB read,
so every stamp, including the first and the last, is jittered by up to the profile's `align`
milliseconds. **The cross-hand relative rate is therefore a least-squares slope over the whole
series, never `(host_us[-1] - host_us[0]) / (n - 1)`.** Endpoint division reports that jitter as
a rate error of thousands of ppm; the ingest believes it, carries it over the take
(`|ppm| * 1e-6 * duration_s * 1000`) into `sync.maximum_alignment_error_ms`, and quarantines a
take whose clocks were fine. That is exactly what used to happen to one take in thirty.

The healthy population is clamped below 575 so the gap to the >2 000 faults stays empty and the
600-count rejection rule is unambiguous. The census in `metadata.json` is then **recomputed
from the finished array** — never asserted — so `silent + over_ceiling + live = 484` and
`stable + intermittent = live` hold by construction.

### Variety, so the filters have something to filter

10 categories · **2 countries, CN and HK** (18/12 at 30 clips, apportioned by weight rather
than sampled, so the mix holds at any `--clips`) · **every take stereo, every take both
hands** · 5 rights profiles from all-denied to CC-BY · QA grades A/B/C · 4 rigs, 5 operators,
3 splits.

The country set is **closed at two**: mainland China (`CN`) and Hong Kong SAR (`HK`), which are
two separate ISO 3166-1 alpha-2 codes and not one code with a subdivision. Widening it is a
scope change — say so in [`docs/catalog/INTAKE.md`](../../../docs/catalog/INTAKE.md) first, and
make sure `_COUNTRY_NAMES` in `ingest/benchmark.py` can name the new code, because **a country
code with no display label now fails the build** rather than falling back to the bare code.

Grades are not stamped on: the generator shapes the census, CRC rate, dropout and alignment
error, and the ingest recomputes the grade with the published rule. The summary table prints
the *predicted* grade so you can diff it against what the CLI produces.

**Every take must reach the catalog.** A prediction of grade C and a QUARANTINE are not the
same outcome, and the summary table cannot tell you about the second — so the invariant to
hold when you touch `QA_PROFILES` is that `catalog-ingest build` reports `0 quarantined`. The
one that bites is `drop`: `cfr_divergence_ms` is measured against the file's own mean frame
interval, so each lost frame adds a step of one frame period (33 ms) to the worst deviation,
and `sync.maximum_alignment_error_ms` composes that. `drop` is therefore an absolute frame
count, not a fraction — as a fraction it scaled with take length and quarantined five of
thirty takes at 30-45 s while still predicting C for all of them.

Titles are concrete gerund phrases — *Applying red coating to a cylindrical part*,
*Hand-shaping green rice cakes*, *Attaching tags to blue garments*. Never Lorem Ipsum, never
"Sample Clip 1".

### Deliberate gaps (`--with-gaps`)

**The default corpus has no gaps.** Every take is egocentric **stereo** video plus **both**
tactile gloves plus IMU plus segcap, recorded in **CN or HK**. That is the product, so that is
what `make fixtures` produces — a buyer scrolling the grid must not have to work out which
cards are the real offer.

The gaps below are still generated, behind `--with-gaps`, and they are still tested
([`tests/test_fixture_corpus.py`](../tests/test_fixture_corpus.py)). They stay because the UI
paths they reach are live code with no other fixture behind them: a **disabled** tab is not an
empty tab, an em-dash for a genuinely unknown value is not a blank, a one-hand channel census
is not half of a two-hand one, and a mono pane has no disparity to check. Delete the only
input that reaches those branches and they rot un-run until a real take finally has a hole in
it — at which point the hole is discovered by a buyer.

```bash
make -C scripts/catalog fixtures                     # the delivered corpus: no gaps
python3 fixtures/generate_fixtures.py --out ../sample-gaps --clips 30 --with-gaps
```

| index | gap | what it exercises |
|---|---|---|
| 4 | one hand only | a single-hand `usable_channels` |
| 6 | no `imu/` | IMU tab **disabled**, not empty |
| 9 | no `country` in `take.yaml` | em-dash on the card; clip drops out of the country filter |
| 11 | no `segcap/` | Segcap tab disabled, automatic `known_limitations` entry |
| 15 | no `tactile/` | `hands: []`, tactile view disabled — legal, a video-only clip |
| 19 | `mono.mp4` instead of the SBS pair | the single-pane player and `capture: mono_egocentric` |

`--with-gaps` also leaves one clip's `privacy.faces_redacted` unassessed (`null`), which is the
only way to see the difference between "nobody looked" and "we looked and there were none".

## `collection.toml`

Collection-level metadata (INTAKE §4): id, name, version, description, vendor, licence,
notice, the whole `[benchmark]` table (chart unit, our series' label and colour, and any
`[[benchmark.comparison]]` entries — carried through verbatim), plus the `[fixtures]` defaults
for `clips`, `seed`, `min_seconds` and `max_seconds`. The generator reads it and emits
`takes/collection.yaml`. **Edit the TOML, not the emitted YAML** — the YAML is regenerated on
every run.

When the real takes land, copy `collection.toml` next to them, change the four
`[collection]` fields and the licence, and the same `catalog-build` command works unchanged.

## Reading the summary table

```
  #  take_id                     title                          cat                  cc  cap   dur  frm  hands  usable   crc     imu  seg  drop  skew  QA  rights      files   size  note
  0  ego_20260818_173621_17C902  Hand-shaping green rice cakes  commercial_food_pre… HK  STE  34.4 1032  LR     355/360  1.0000  6880   3     0  17.3  A   train_only     25  7.2MB
```

`usable` is live-**and**-stable channels per hand — quote that, never 484. `crc` is the worst
hand. `skew` is the measured worst-case inter-stream alignment in ms; above 33.0 (one frame at
30 fps) a clip cannot be grade A. `drop` is an absolute frame count, not a rate.

## Checks worth re-running after a change

The generator has no test suite of its own; these one-liners are the contract it must keep.

- `catalog-ingest build` reports **0 failed and 0 quarantined** — see the grade note above;
- `catalog-ingest validate` reports **PASS on every row**, including `every country facet
  bucket carries a display label`;
- the summary footer reads `stereo 30  mono 0`, `both hands 30`, `CN 18  HK 12`, `gaps none`;
- every `frame_times.csv` row count equals the container's frame count (H2);
- `docs/checksums.sha256` covers exactly the files on disk and every digest verifies;
- the census in `metadata.json` matches the masks in the `.npz`;
- segments start at 0, do not overlap, and end within 0.3 s of `duration_s`;
- no take with `rights.model_training: granted` has `consent_on_file` false or absent.
