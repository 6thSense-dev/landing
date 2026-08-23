# INTAKE — what to hand the catalog ingest

**The bytes are already fine.** ~30 clips of 30–45 s, already encoded to web mp4. Duration,
resolution, fps, byte counts, SHA-256s, channel census, CRC rates, sync numbers and
calibration are all measured off the files. What no machine can derive is about eight values
per take: **~90 seconds of typing each.** The rest is copying files.

Pipeline and S3: [`README.md`](./README.md) · Field-by-field spec: [`CONTRACT.md`](./CONTRACT.md)

---

## 0. What this collection is

Every clip in the delivered drop is **egocentric stereo video plus tactile on both hands**.
That is the product; there is no mono clip, no video-only clip and no one-handed clip in it.
Concretely, every take carries `video/stereo_upright.mp4` **and** both `tactile/left.npz` and
`tactile/right.npz`, and every clip therefore reads `capture: "stereo_egocentric"` with
`hands: ["left", "right"]`.

**Two countries, and only two.** Captures are in **mainland China (`CN`)** and **Hong Kong SAR
(`HK`)**. These are two separate ISO 3166-1 alpha-2 codes, not one code with a subdivision,
because a buyer's jurisdiction review treats them separately — so `HK` is never folded into
`CN`, and neither is ever written as a name, a flag or a lower-case code. `country` in
`take.toml` is one of exactly these two strings:

| code | `facets.country[].label` | notes |
|---|---|---|
| `CN` | China | mainland; UTC+08:00, no DST |
| `HK` | Hong Kong | Hong Kong SAR; UTC+08:00, no DST |

Every country code the catalog emits must have a display **label** in the data — the UI carries
no code table that could drift out of step with the manifest. A code the ingest cannot name in
English is a **build failure**, not a fallback to the bare code: `catalog-ingest build` exits 2
naming the code, and `catalog-ingest validate` re-checks the emitted buckets
(`every country facet bucket carries a display label`). The reason is narrow and specific:
`{"value": "HK", "label": "HK"}` satisfies every constraint the schema can express — the label
is a non-empty string — and still renders `HK (12)` next to `China (18)` in the filter bar,
where it is indistinguishable from a deliberate abbreviation.

Adding a third country is a scope change, not a data tweak. Do it in this order: amend this
section, add the code to `_COUNTRY_NAMES` in
[`scripts/catalog/ingest/benchmark.py`](../../scripts/catalog/ingest/benchmark.py) (or set
`country_labels` in the collection config if the vendor wants their own wording), then widen
`COUNTRY_WEIGHTS` in the fixture generator.

The **fixture** corpus mirrors all of this exactly — 30 takes, 30–45 s, all stereo, all
two-handed, 18 CN / 12 HK. The holes that exercise the UI's disabled-tab and em-dash paths live
behind `--with-gaps` and are never what `make fixtures` produces. See
[`scripts/catalog/fixtures/README.md`](../../scripts/catalog/fixtures/README.md).

---

## 1. The tree

```
takes/
├── collection.toml                     REQUIRED once, for the whole drop  (§4)
│
├── ego_20260823_000821_16A260/         one dir per take; the NAME BECOMES THE CLIP ID
│   ├── take.toml                       REQUIRED — the hand-written values  (§3)
│   ├── metadata.json                   your pipeline's own metadata, any schema
│   ├── video/
│   │   ├── stereo_upright.mp4          the web mp4 the guest watches. [left | right] SBS
│   │   │                               (mono rig: name it mono.mp4)
│   │   └── frame_times.csv             header exactly: frame_idx,host_us — 1 row per frame
│   ├── tactile/{left,right}.npz        omit the hand you did not instrument
│   ├── imu/imu.csv                     header exactly: t_s,ax,ay,az,gx,gy,gz
│   ├── segcap/segments.csv             t0_s,t1_s,label,verb,objects,description
│   ├── calibration/
│   │   ├── calibration.json            the raw solve
│   │   └── calibration_delivered.json  the one a consumer should actually apply
│   ├── sensor_layout.json              per-taxel geometry
│   ├── preview/poster.jpg              optional; the CLI grabs a frame if absent
│   └── docs/{README.md,DATASHEET.md,LICENSE.txt,SYNC_PROTOCOL.md,checksums.sha256}
│
└── ego_20260823_014402_16A260/…        same shape, every take
```

```bash
T=takes/ego_20260823_000821_16A260
mkdir -p $T/{video,tactile,imu,segcap,calibration,preview,docs}
```

**The directory name is permanent.** It becomes the clip id — lowercased, non-alphanumerics
collapsed to `-` (`ego_20260823_000821_16A260` → `ego-20260823-000821-16a260`). That id keys
deep links, S3 object keys and download receipts. Renaming a take later breaks all three.

---

## 2. Required / costs a grade / optional

Build with `--strict`. Under `--strict` **anything in the WARN column also drops the clip** —
a smaller catalog you were told about beats a wrong one you were not.

| | | if absent |
|---|---|---|
| **REQUIRED** | the take dir, plus `video/*.mp4` **or** `tactile/*.npz` | take fails, named in `INGEST_REPORT.md`, exit 1 |
| | `collection.toml`, once | nothing builds, exit 2 |
| | `rights.*`, all four | fails closed to `denied`, and WARNs |
| | `privacy.consent`, when any right is `granted` | **QUARANTINED** — never enters the catalog |
| | `privacy.redaction`, when `faces_redacted: true` | **QUARANTINED** — claims a pass the schema defines as never run |
| **WARN** (ships, grade suffers) | `title` | derived from the directory name |
| | `category` | ships `uncategorised`, polluting every category filter |
| | `country` | em-dash on the card, out of every country filter. **Cannot be inferred** — `+08:00` spans nine countries, including both of ours. `CN` or `HK` (§0); any other code needs a display label first or the build fails |
| | `metadata.json` | sync, calibration, CRC, census all null; **grade capped at C** |
| | `video/frame_times.csv` | H2 frame-count check `not_run`; **grade capped at C** |
| | `calibration/` | H7 unmet; unsellable to anyone doing geometry |
| | only `calibration.json`, no `_delivered` | ships with a caveat; expect ~20 px of rectification error |
| | `sensor_layout.json` | a zero-reading taxel is indistinguishable from a missing one |
| | `privacy.retention`, `privacy.reidentification_prohibited` | null / `false`; grade capped below A |
| | `split` | out of the split filter and out of `collection.splits` |
| **OPTIONAL** (silent) | `subcategory`, `description`, `operator`, `environment`, `subjects`, `restrictions`, `known_limitations`, `grade_override`, `task` | null → em-dash |
| | `imu/`, `segcap/`, `tactile/` | that tab is **disabled**, not empty. A video-only clip is legal |
| | `preview/*`, `docs/checksums.sha256` | the CLI cuts / hashes them itself |

**Nothing is ever guessed.** An undeterminable value is `null`, the UI renders `null` as an
em-dash, and `INGEST_REPORT.md` names the take that produced it.

---

## 3. `take.toml`

```toml
title       = "Bimanual industrial bin-picking"   # the ACTIVITY, not the equipment. <= 48 chars
category    = "manipulation"                      # lower_snake_case
subcategory = "bin_picking"                       # lower_snake_case, or omit
country     = "CN"                                # ISO 3166-1 alpha-2, UPPERCASE. CN or HK (§0)
operator    = "op-01"                             # PSEUDONYM. Never a name, email or initials
subjects    = 1
session_id  = "sess-2026-08-23-a"
# split     = "train"                             # train | val | test
# task      = "Parts transfer"                    # chart bar label; defaults to the subcategory

[rights]                          # granted | denied | on_request. There is NO "unknown":
model_training = "denied"         # if the review has not happened, the honest value is denied.
commercial_use = "denied"         # `derived_model` is separate from `model_training` on
redistribution = "denied"         # purpose — consent to train is not consent to ship weights.
derived_model  = "denied"
# determined_utc = "2026-08-24T09:00:00Z"   # REQUIRED once any value above is not denied

[privacy]
consent_on_file = false           # true only if a signed release covers the rights above
faces_redacted  = false           # true only if every identifiable face is blurred/masked
pii_review      = "pending"       # passed | pending | failed | not_required
notice_given    = true            # was everyone in frame, bystanders included, told?
identifiable_persons  = 0         # count AFTER redaction. 0 is an answer; null is not
identifiable_premises = false
reidentification_prohibited = true   # a LICENCE TERM; unstated ships as false
# [privacy.retention]  policy / delete_after_utc / deletion_request_contact
# [privacy.redaction]  REQUIRED when faces_redacted = true
# [privacy.consent]    REQUIRED when any permission is granted
```

The two that **quarantine** rather than warn are `privacy.consent` and `privacy.redaction`. If
you are not ready to fill them in, set the permissions to `denied` and `faces_redacted` to what
is actually true. Both are honest, and both build.

---

## 4. `collection.toml` — once for the whole drop

Copy [`scripts/catalog/fixtures/collection.toml`](../../scripts/catalog/fixtures/collection.toml)
next to your takes and edit `[collection]`, `[vendor]`, `[license]`, `[benchmark.series]`.
Everything is documented inline. The part that bites:

```toml
[benchmark]
unit = "auto"                 # auto | hours | minutes | clips — leave it on auto

[benchmark.series]            # OUR legend label and bar colour. A rename is this one line.
label = "EGO-TAC evaluation sample"
color = "#14120c"
```

`auto` picks **hours at or above a 2 h total, minutes below it**, from the data, and publishes
the answer twice — `benchmark.unit` and `collection.totals.duration_unit` — so the chart and
the header cannot disagree. A ~20 minute corpus forced onto an hours axis draws bars of
`0.0027` and a stat tile reading `0.04 hours`: a buyer reads that as a bug or as padding.

### Two roll-ups ship, and the chart picks one

`benchmark` carries the same clips folded twice, in the same unit, off the same seconds:

| | keyed by | bars, at 30 clips | what it is |
|---|---|---|---|
| `benchmark.tasks[]` | `task` in `take.toml`, else the subcategory | ~24 | one to two clips a bar — a picket fence |
| `benchmark.categories[]` | `category` in `take.toml` | ~10 | differences a buyer can see |

```jsonc
"categories": [
  { "value": "industrial_inspection",   // == facets.category[].value — the join key
    "label": "Industrial inspection",   // == facets.category[].label
    "values": { "6s_egotac_eval": 3.28 },   // same unit and same series ids as tasks[]
    "clips": 3 }                        // null on a third-party comparison bar
]
```

Both lists total the same, because they are the same fold over the same clips. **The chart
must not aggregate `tasks` itself** — it holds no clip-to-category map, so doing it client-side
means parsing display labels, and a label parse that silently mis-buckets is invisible until a
buyer counts the bars. Clicking a category bar sets the category filter to `value`, never to
`label`. A cited `[[benchmark.comparison]]` gets one bar in **each** list, so switching the view
cannot make a comparison appear or disappear; on the category side its `value` is the series id,
its `clips` is `null`, and it joins to no facet.

### Comparison datasets: why the chart shows only us

The reference design stacks our corpus against Ego4D, EgoDex, Xperience-10M and
Egocentric-100K. **We do not have per-task hour breakdowns for any of them, and the people we
sell to do.** Publishing an invented split for a corpus a buyer already knows the shape of is
not a rounding error — it is the moment they stop trusting every other number on the page,
including the ones we measured. So the chart shows **our own task distribution** and nothing
else until sourced figures exist.

The mechanism is ready for when they do:

```toml
[[benchmark.comparison]]
label      = "Ego4D"
hours      = 3670
source_url = "https://ego4d-data.org/docs/start-here/"   # REQUIRED — no URL, no series
retrieved  = "2026-08-23"                                # REQUIRED — corpora grow
```

The ingest **refuses to build** a comparison with no `source_url`, and writes the citation into
`benchmark.note`, which the chart renders under the bars. A comparison is one whole-corpus
total, so it is plotted as **one bar of its own** — never split across our task labels.

One thing to look at before adding one: Ego4D's 3,670 h on the same linear axis as our twenty
minutes flattens every one of our bars to `0.0015`. Render it before you ship it.

---

## 5. Build, check, ship

```bash
python3 -m pip install -r scripts/catalog/requirements.txt      # + ffmpeg/ffprobe on PATH
cd scripts/catalog
python3 -m ingest.catalog_ingest build --takes <takes> --out <bundle> \
        --media-mode copy --posters --previews --strict
python3 -m ingest.catalog_ingest validate --out <bundle>        # must be all PASS
python3 -m ingest.catalog_ingest stats    --out <bundle>
python3 upload_bundle.py --bundle <bundle> --prefix v1/         # -> private S3
```

`--media-mode copy` is not optional for a real drop: the default, `reference`, writes URLs for
bytes it never materialised, so nothing useful uploads.

Then check three things by eye in `<bundle>/catalog.json`:

- `collection.totals.clips` equals the number of takes you handed it;
- `collection.totals.countries` is exactly `["CN", "HK"]` (a shorter list means a `take.toml`
  is missing its `country`; a longer one means the drop left the declared scope, §0);
- `facets.capture` has one bucket, `stereo_egocentric`, and `facets.hands` shows `both` on
  every clip — anything else means a take is missing an eye or a glove (§0);
- no `qa.grade: "C"` you did not expect — a surprise C is a missing file, not bad data (§2).

---

## 6. Formats that are load-bearing

| | |
|---|---|
| directory name | = the clip id, forever (§1) |
| `video/frame_times.csv` | header exactly `frame_idx,host_us`, one row per frame, row count == the container's frame count. This is H2, the most common automated rejection in the industry |
| `imu/imu.csv` | header exactly `t_s,ax,ay,az,gx,gy,gz`. `t_s` is seconds from take start, not an epoch. Accel m/s², gyro rad/s — if yours are g and deg/s say so under `imu_units`, do not convert by hand |
| `segcap/segments.csv` | header exactly `t0_s,t1_s,label,verb,objects,description`. `objects` semicolon-separated (`tray;bolt;bin`), seconds from take start, ascending |
| tactile stills | a leading `p50_`/`p75_`/`p90_`/`p95_`/`p99_`/`max_` becomes the frame's caption. Sample **across** the force distribution: a reel of nothing but `max_` frames is a highlight reel, and a buyer who spots that stops trusting the package |
