# 6thSense catalog data contract — `6s-catalog/1.0`

Two JSON Schemas, one job: let a buyer-facing catalog render a thousand clips from **one
request**, and let a buyer's engineer read the schema alone and know exactly what they are
getting.

| file | validates | fetched |
|---|---|---|
| `catalog.schema.json` | `catalog.json` — the collection manifest | once, on page load |
| `clip.schema.json` | `clips/<id>.json` — one full clip record | on demand, when a clip is opened |

Both are **draft 2020-12** and both are **self-contained**: neither carries a cross-file
`$ref`, so either can be run through any validator with no registry wiring.

```bash
python3 -c "
import json,sys
from jsonschema import Draft202012Validator as V
s=json.load(open(sys.argv[1])); V.check_schema(s)
print(sorted(V(s).iter_errors(json.load(open(sys.argv[2]))), key=lambda e:list(e.path)) or 'OK')
" catalog.schema.json catalog.json
```

---

## 1. The six rules that govern every field

**R1 — Every asset URL is relative to the catalog root.**
The catalog root is the directory containing `catalog.json`, *not* the directory containing
the clip record. No scheme, no `//host`, no leading `/`, no leading `./` or `../`, no
embedded `/../`, no whitespace. This is the whole portability story: the same bundle works on
`localhost:5173`, behind a signed-URL CDN, and behind the portal proxy, because the **host**
rewrites the base and the manifest never does.
The single exception is `ExternalUrl` — an absolute `https://` link to something that is not
in the bundle (a vendor homepage, a licence deed). Plain `http` is rejected: the catalog is
served over TLS and a mixed-content link is blocked by the browser.

**R2 — `null` means "the ingest could not determine this". Always.**
It never means zero, never means false, never means "none". **The UI renders `null` as an
em-dash (—), never as `0`, never as an empty cell, never as "No".** Where *none* is a real,
determined answer, the schema uses an empty array (`"restrictions": []`, `"segments": []`) or
an explicit enum value (`"method": "none"`) instead. An empty string is never a legal
substitute for `null` and is rejected by `minLength: 1`.

**R3 — Presence is required; the value carries the uncertainty.**
Every key of a clip summary is in `required`, even when its value may be `null`. That makes
the UI total: no optional chaining, no ambiguity between "the producer forgot" and "we do
not know". The only exceptions are the three templated URLs (§3.3).

**R4 — Sizes are integer bytes, named `bytes`.**
Never `size`, never `size_mb`, never a formatted string. Durations are floats in seconds
named `duration_s`; the UI formats `M:SS`. A preformatted duration string cannot be summed,
sorted or converted, and `"1:24"` is rejected by the schema.

**R5 — Enumerations are closed.**
Every categorical field is a JSON Schema `enum`. Adding a value is a **minor version bump**
of the schema, never an ad-hoc string. This is what lets a buyer diff two deliveries.

**R6 — Objects are closed, except `metadata`.**
`additionalProperties: false` at every object level. The sole exception is
`clip.metadata`, an intentional verbatim passthrough (§5). Two objects are keyed maps
(`benchmark.tasks[].values`) and are closed with `propertyNames` instead, which is the
correct construct for a map with data-dependent keys.

---

## 2. Bundle layout

```
catalog/                          <- the "catalog root"; all AssetUrls resolve against this
├── catalog.json                  <- validated by catalog.schema.json
├── clips/
│   └── ego-20260823-000821-16a260.json   <- validated by clip.schema.json
└── media/
    └── ego-20260823-000821-16a260/
        ├── poster.jpg
        ├── preview.mp4           <- silent hover loop
        ├── imu.f32               <- sidecar, only when n_readings > 2000
        ├── peak.f32              <- sidecar, only when n_readings > 2000
        └── …                     <- the take package, verbatim
```

---

## 3. `catalog.json`

### 3.1 Top level

| key | type | notes |
|---|---|---|
| `schema` | const `"6s-catalog/1.0"` | refuse an unknown major before parsing |
| `generated_utc` | RFC 3339, trailing `Z` | build time of the manifest, not of any clip |
| `collection` | object | identity, vendor, licence, totals, path templates |
| `facets` | object | precomputed filter buckets with counts |
| `benchmark` | object \| null | task-distribution chart; `null` hides the section. See §3.1.1 for the unit rule and the citation rule |
| `clips` | `ClipSummary[]` | default grid order |

`collection.totals` is precomputed so the header renders without iterating. If a consumer
finds `totals` disagreeing with `clips[]`, trust `clips[]` and treat the manifest as stale.

### 3.1.0 The two collection-level facts a buyer reads before anything else

**`totals.sync_max_alignment_error_ms`** — the MAXIMUM of every clip's measured
`sync.maximum_alignment_error_ms`, with `sync_p95_alignment_error_ms`,
`sync_clips_over_one_frame`, `sync_clips_measured` and
`sync_clips_independently_validated` alongside it.

H1 says report the measured maximum, not a claim, and this is that requirement applied to the
collection rather than to one record. A header that quotes a typical alignment while the 29th
detail record says 56.7 ms is the H4 failure mode with the copy deck instead of the
disposition field: every per-clip caveat is technically present, and the sentence the buyer
reads first is still false. `sync_clips_over_one_frame` counts the clips for which a
frame-level claim would be wrong, measured against each clip's own frame period — it is what
distinguishes one bad take from a corpus-wide property. All four are null / 0 when no clip
measured its alignment, which reads as "we did not measure this" and is a worse answer than a
large number, not a better one.

`sync_clips_independently_validated` is the figure that says what the other four are
WORTH. An alignment error is arithmetic over a shared host clock; a clip is *validated*
only when a common-mode PHYSICAL event — a clap, visible in video and sharp on both
gloves — corroborates that arithmetic. A corpus can publish a small measured error with
nothing physical confirming it for two thirds of its clips, and until this figure existed
the only way to find that out was to open the Calib & sync tab on each clip in turn and
read its tail. It is counted over EVERY clip, not over the measured subset: a clip that
measured nothing is also a clip nothing corroborated.

The build enforces the pairing: `validate` FAILS a bundle whose `collection.standfirst`,
`description` or `notice` makes a frame-level precision claim while
`sync_clips_over_one_frame > 0`.

Two more copy rules run over the same three strings, for the same reason — a sentence a
buyer reads first may not contradict the record shipped underneath it:

- **`collection copy quotes the channel census, not the grid size`** — FAILS on `22x22`
  or `484`. Every clip's `known_limitations` says, verbatim, *"quote the usable-channel
  count, never the 484-site grid size"*, and the header quoted the grid anyway. Measured
  worst-hand coverage across the reference corpus is a median of 0.60, so the grid size
  overstates the working sensor by about 1.7×.
- **`collection copy matches provenance_class`** — FAILS on "captured/recorded/filmed in"
  while `provenance_class` is `synthetic` or `mixed`. The UI renders a banner from that
  field saying the streams are not recordings; a sentence one line above it claiming a
  capture location contradicts it, and on a generated clip the location has no referent
  at all. Use "modelled on" until the corpus is real.

**`collection.standfirst`** — the one or two sentences the header promotes above the
fold, and the only prose most readers will see. It is AUTHORED, never sliced off
`description`. Taking "the first sentence or two" is a position rule, and a position rule
promotes whatever the writer put first, which is always the claim and never the limit:
measured on the reference corpus it promoted exactly one sentence — the only one in the
paragraph with no qualification in it — and pushed "a capability sample and not a corpus"
and "no calibration into force units" behind a disclosure. Write ONE CLAIM AND ONE LIMIT.
Null is legal and means the header shows no promoted line, which is better than showing
an unqualified half of one.

**`collection.provenance_class`** — `recorded`, `synthetic` or `mixed`, folded from each
clip's `provenance.media_class`, which each take declares for itself (absent reads
`recorded`, so a generator that forgets to declare itself is a bug in the generator, never a
silent reclassification). The UI renders anything but `recorded` as a banner above the grid,
and `upload_bundle.py` refuses to publish a non-`recorded` bundle without `--allow-synthetic`.
The fixture pipeline emits colour-bar test patterns; "do not upload the fixtures" being a
convention rather than a guard is how a buyer ends up looking at one captioned as a real
workspace, and no amount of downstream rigour recovers from that.

### 3.1.1 The chart's unit, and what may appear on it

**The producer chooses the unit; the consumer obeys it.** `benchmark.unit` is one of
`hours`, `minutes` or `clips`, and `collection.totals.duration_unit` is one of `hours` or
`minutes`. Both are resolved by the same rule — **hours at or above a 2 h total, minutes
below it** — and both are published rather than left to be re-derived, so the y-axis and the
header stat tiles cannot disagree about the same corpus.

This is not cosmetic. The delivered corpus is ~30 clips of 30-45 s, about twenty minutes.
Rendered as hours it produces bars of `0.0027` and a stat tile reading `0.04 hours`, which a
buyer reads as either a rendering fault or a padded number. A consumer that renders `minutes`
values through an hours formatter is **wrong by a factor of sixty**; the field exists so that
cannot happen silently. `totals.hours` and friends stay stored in hours in every case —
`duration_unit` says how to display them, not what they are.

**Below two clips per task, do not draw bars.** Each task bar carries `clips`, the number of
OUR clips behind it (null for a third-party comparison bar, which is a whole-corpus total).
At ~30 clips over 24 task labels that ratio is about one, and a stacked bar chart of 24
near-identical slabs is a claim of a distribution that is not there — which a reader
correctly discounts, and then discounts the numbers that do matter. The consumer switches to
a plain count list below the threshold, and the producer states the ratio in `benchmark.note`.

**Two roll-ups ship, and the consumer picks one.** `benchmark.tasks[]` is keyed by `task`
(falling back to the subcategory); `benchmark.categories[]` is the same clips folded to
`ClipSummary.category`. At 30 clips that is ~24 bars against ~10, so the coarse view is
usually the readable one and the fine view is the audit trail. Both are REQUIRED, both carry
the same `unit` and the same `series`, and both total the same, because they are the same fold
over the same clips.

| | `tasks[]` | `categories[]` |
|---|---|---|
| item shape | `{label, short_label?, values, clips}` | `{value, label, short_label?, values, clips}` |
| join key to a facet | none — a task label is free text | `value` == `facets.category[].value` |
| `clips: null` means | a third-party comparison bar | a third-party comparison bar (and `value` is then the comparison's series id, which joins to no facet) |

**A consumer MUST NOT aggregate `tasks[]` into categories itself.** It holds no clip-to-
category map, so client-side aggregation means parsing display labels, and a label parse that
silently mis-buckets is invisible until someone counts the bars. Clicking a category bar sets
the category filter to `value`, never to `label`.

**Every bar must be traceable.** A series built from `clips[]` needs no citation: it is
measured. A series quoting a third-party corpus is not, and MUST be named in `benchmark.note`
with its source URL and the date the figure was retrieved. The producer refuses to emit an
uncited comparison series at all, so `note: null` means every bar on the chart came from
`clips[]`. A third-party corpus ships one whole-corpus total, so it is plotted as one bar of
its own; splitting it across our task labels would be an invention, and the buyers who read
this chart are the ones who already know the real figures.

`collection.license` is **context only**. H5 makes rights per-clip, and a clip's `rights`
object always wins. `license.summary` must say so in words.

### 3.2 Facets

Closed set of nine names, each optional; an absent facet hides its control.

`category` · `subcategory` · `country` · `capture` · `modality` · `rights` · `hands` ·
`split` · `qa_grade`

Each bucket is `{value, label, clips, hours, usable_hours}`. Filtering is equality on `value`;
`label` ships in the data so the UI carries no lookup table that can drift.

Three of the nine do not partition the collection and the UI must not draw them as
percentages: `modality` and `rights` (a clip contributes several buckets each), and `hands`,
where a two-glove clip fills `left`, `right` **and** `both`. `hands` also carries **`none`**,
for `hands: []` — the camera-only product, which is one of the two this rig ships. `none` is a
real determined value, not a placeholder for a missing one (`hands` is never null), and it
exists so that every clip lands in at least one bucket: a clip in no bucket is a clip a buyer
cannot filter for, cannot count and cannot price.

**`label` must be a human name, and for `country` that is enforced.** A code the producer
cannot name in English **fails the build** (exit 2) rather than falling back to the code, and
`validate` re-checks the emitted buckets (`every country facet bucket carries a display
label`). `{"value": "HK", "label": "HK"}` satisfies every constraint this schema can express —
the label is a non-empty string — and still renders `HK (12)` beside `China (18)`, where it is
indistinguishable from a deliberate abbreviation. The delivered collection is `CN` (China) and
`HK` (Hong Kong) only; see [`INTAKE.md`](./INTAKE.md) §0.

`hours` is **wall clock**: it counts a clip whose glove was two-thirds dead exactly as
heavily as one whose glove was whole. `usable_hours` is the same span weighted by
`qa.tactile_coverage`, and clips with no tactile stream contribute nothing to it — so it is
"hours of usable tactile", not a discount. Both ship, and the header renders both, because
quoting the first alone is the specific arithmetic by which "10,000 hours" stops being true.
`collection.totals` carries the same pair as `tactile_hours` / `tactile_usable_hours`. Two facets do not partition the
collection and the UI must not present them as percentages: `modality` (a clip contributes to
every modality it carries) and `rights` (one bucket per permission, values shaped
`<permission>_<value>`, e.g. `model_training_granted`).

### 3.3 Path templates — and why they exist

Repeating three full URLs on every clip costs ~125 B/clip, a sixth of the entire budget. So
`collection.paths` carries `{detail, poster, preview}` templates containing `{id}` or
`{slug}`, expanded by verbatim substitution (both are already `[a-z0-9-]`, so no
percent-encoding is possible or permitted).

Three-state semantics on `poster`, `preview` and `detail` **in the summary only**:

| state | meaning | UI |
|---|---|---|
| key **absent** | expand the template | fetch the expanded URL |
| key present, `null` | the asset genuinely does not exist | placeholder tile / no hover loop / disable modal tabs |
| key present, string | use it verbatim | fetch it |

If `paths.detail` is `null`, every clip **must** carry an explicit `detail`. That is enforced
by an `allOf` at the root of the schema, not just by prose.

In `clip.schema.json` these keys are **required and nullable** — a detail record is fetched
standalone and must not depend on the manifest.

### 3.4 Size budget — measured, not hoped for

A fully populated `ClipSummary` minifies to **845 bytes** (the worked example below).
Measured on a 1000-clip manifest with realistic per-clip variation:

| manifest | raw | gzip -9 |
|---|---|---|
| 1000 clips, `description_short` populated | **895 KB** | **194 KB** |
| 1000 clips, `description_short: null` | 743 KB | 104 KB |
| 484 clips (the largest that fits 400 KB raw) | 400 KB | ~90 KB |

**The "< 400 KB for 1000 clips" target is not achievable at this per-clip payload, and we do
not pretend otherwise.** It holds to roughly **450 clips**. Three consequences, in order of
preference:

1. **Serve the manifest compressed.** Every static host and CDN does this. 194 KB on the wire
   for 1000 clips is well inside a single-request budget; treat **< 250 KB gzipped** as the
   real target.
2. **Above ~600 clips, emit `description_short: null`.** It is the single largest field
   (up to 160 B) and the prose still lives in the detail record. This alone saves 152 KB raw
   / 90 KB gzipped per 1000 clips.
3. **Above ~1500 clips, this schema is the wrong shape** and `6s-catalog/1.1` will introduce
   paged `clips/index-<n>.json` shards. Do not improvise sharding inside 1.0.

---

## 4. `ClipSummary` — the grid contract

Everything the card, the filter bar and the sort need; nothing else.

| field | type | null? | drives |
|---|---|---|---|
| `id` | slug, `^[a-z0-9]+(-[a-z0-9]+)*$` | no | stable key, bookmarks, cache |
| `slug` | slug | no | URL path segment |
| `title` | string ≤120 | no | bold left of the card title row |
| `description_short` | string ≤160 | yes | hover / modal subhead |
| `category` | `lower_snake` | **no** | primary grouping |
| `subcategory` | `lower_snake` | yes | grey line under the title |
| `country` | ISO-3166-1 alpha-2, upper | yes | uppercase mono label, right of title |
| `recorded_month` | `YYYY-MM` | yes | recency, `date_range` |
| `capture` | `stereo_egocentric` \| `mono_egocentric` | no | Stereo/Mono pill toggle |
| `duration_s` | float > 0 | no | mono `M:SS`, right of subcategory |
| `resolution` | `[w,h]` int | yes | composite width for SBS: `[1920,600]` |
| `fps` | float > 0 | yes | `30.06`, never rounded to `30` |
| `modalities` | enum[] unique | no | modality facet, which tabs enable |
| `hands` | `left`/`right`, unique | no | `[]` = no glove — the camera-only product, legal, ≠ null, buckets as `none` (§3.2, §4.2.1) |
| `subjects` | int ≥ 0 | yes | |
| `bytes` | int ≥ 0 | yes | download size |
| `poster` | AssetUrl | 3-state | card thumbnail |
| `preview` | AssetUrl | 3-state | hover loop |
| `rights` | 4 × `granted\|denied\|on_request` | **no** | rights facet, licence badge |
| `privacy` | `{faces_redacted, consent_on_file, pii_review}` | values nullable | counsel screen |
| `qa` | `{grade, disposition, checks_warn, checks_fail, video_frames_dropped, tactile_crc_pass_rate, usable_channels{left,right}, tactile_coverage, sync_validated}` | values nullable except grade, disposition and the two counts | sort, badge |

`qa.disposition` and `qa.checks_warn` are on the CARD, not only in the record. Every clip in a
published manifest is dispositioned `accepted` — a fail quarantines it and it never reaches
the catalog — so the word alone carries no information, and a bare `Grade C` carries none
either while its rule is nowhere on the page. `checks_warn` is the part that distinguishes one
card from another: **"accepted, 3 warns"**. `qa.sync_validated` is on the card for the
same reason: a grade shown with no sync-validation state beside it lets the card imply a
quality the sync record does not support. `true` means a common-mode physical event
corroborated this clip's alignment, `false` means nothing did, `null` means the clip
ships no `sync` record. It counts the entries in the detail record's
`qa.checks` whose `result` is `warn`, and the detail record renders the whole table, each row
with both its measured value and the bound it missed. Publishing the disposition without the
warn count is the H4 failure mode in miniature.
| `detail` | AssetUrl | 3-state | modal deep content |

**Poster alt text is deliberately not a field.** The poster is a frame of the clip, so the UI
derives its accessible name from the title — `"<title>, still frame"` — which is correct,
consistent, and one fewer string per clip. Decorative chrome (the category glyph, the play
triangle) is `aria-hidden`; the play control is a real `<button>` named
`"Play <title>"`.

### 4.1 Rights (H5) — four separate enums, failing closed

`model_training` · `commercial_use` · `redistribution` · `derived_model`

| our key | EGXO field name |
|---|---|
| `model_training` | `model_training_permission` |
| `commercial_use` | `commercial_use_permission` |
| `redistribution` | `redistribution_permission` |
| `derived_model` | `derived_model_permission` |

Values: `granted` (permitted today under the stated licence) · `denied` (not permitted, and
not currently negotiable) · `on_request` (obtainable by agreement).

There is **no `null` and no `"unknown"`**, and the schema rejects both. *If the rights review
has not happened, the correct and only honest value is `denied`.* Buyers treat "the file
downloaded" as not implying training rights, and so do we. `derived_model` is separate from
`model_training` on purpose: consent to train is routinely given without consent to publish
or sell the resulting weights.

### 4.2 QA grade — a published, deterministic rule

Computed by the ingest; a human may override it **downward only**, never upward.

```
let cov = qa.tactile_coverage = min(usable_channels[h]) / readout_sites, over hands h
let drp = video_frames_dropped / video_frames_delivered
let NA  = { c.check_id : c in qa.checks, c.result == "not_applicable" }

# a bound this package has nothing to meet it with is not a bound it missed
let met(check_id, bound) = check_id in NA  or  <the bound holds>

grade = "A"  if  no check result is "warn", "fail" or "not_run"    # "not_applicable" is not
             and video_frames_dropped == 0                         #   in that list
             and met("tactile_crc_pass_rate",    crc >= 0.9999)
             and met("tactile_channel_coverage", cov >= 0.60)
             and met("sync_max_skew_ms",         sync.maximum_alignment_error_ms <= 33.0)

      = "B"  if  no check result is "fail"
             and drp <= 0.01                                       # H2
             and met("tactile_crc_pass_rate",    crc >= 0.999)
             and met("tactile_channel_coverage", cov >= 0.40)
             and met("sync_max_skew_ms",         sync.maximum_alignment_error_ms <= 33.0)  # H1

      = "C"  otherwise, provided disposition == "accepted"
```

**Every input to this rule is in the record.** `NA` is read off `qa.checks[].result`, which
ships in full, so a buyer holding one clip JSON can re-derive its grade exactly. That is the
point of putting inapplicability in the record rather than in the grader: the alternative —
a grader that quietly ignores certain `not_run` rows when it recognises a camera-only clip —
publishes a grade nobody outside this repository can reproduce or audit.

**`not_applicable` is the only result that does not cap the grade**, and it is reachable only
from a structural fact published in the same document. See §4.2.1.

**B tests H1 too.** It used not to, and the consequence was that a clip measured 24% over
the single most common rejection cause on a new rig was still labelled "within the H2
tolerance". A clip that misses the H1 bound is grade **C** — *accepted, with the exceedance
named in `known_limitations`*, quoting the measured value, the bound and the units. That is
what grade C is for, and every non-`pass` check produces exactly one such entry.

#### Two bounds per measured check, both published

Each measured-quality check carries a **preferred** bound and an **acceptance** bound. The
preferred bound is the requirement's own number, is what the check reports as `threshold`,
and missing it is a `warn` that caps the grade. The acceptance bound is wider, and missing
**that** is a `fail`: `disposition` becomes `quarantined` and the clip never appears in the
catalog at all.

| check | preferred (`warn` beyond) | acceptance (`fail` beyond) | why the acceptance bound is there |
|---|---|---|---|
| `sync_max_skew_ms` | 33.0 ms (H1: one camera frame at 30 fps) | **66.0 ms** (two frames) | past two frames a contact event cannot be attributed to a frame at all, which is the one thing time-aligned tactile is bought for |
| `video_frame_dropout` | 0.01 (H2 alert) | **0.05** | 5% of frames gone is a broken capture, not a clip |
| `tactile_crc_pass_rate` | 0.9999 for A, 0.999 for B | **0.99** | below one frame in a hundred verifying, loss is not quantifiable |
| `tactile_channel_coverage` | 0.60 for A, 0.40 for B | **0.25** | under a quarter of the readout working, the glove is broken hardware and no spatial contact map can be reconstructed |
| `calibration_rectification_residual_px` | 0.5 px | **2.0 px** | beyond ~2 px the delivered calibration is not the one that was solved |

A grade rule whose `fail` bound is infinity cannot express *"this one is not good enough"*,
which makes the grade marketing rather than QA. Both numbers ship so a buyer can see what we
would actually refuse to release.

A clip with any `fail` check cannot be dispositioned `accepted`, and only `accepted` clips
appear in the manifest at all. A quarantined take is reported under its own heading in
`INGEST_REPORT.md` — it is the rule working, not the ingest breaking. **Never convert a
warning into acceptance because a volume target is at risk.**

#### Checks the grade reads

Beyond the five measured ones above, `qa.checks[]` carries the structural and compliance
checks, all of which can `warn` and therefore all of which block grade A:
`sync_independent_validation` (H1/H3), `video_frame_timestamp_parity` and
`package_checksums` (H2), `tactile_census_reproducible`, `camera_calibration_model`,
`calibration_cam_imu_present`, `calibration_readout_time_ms` and `imu_noise_characterised`
(H7), `rights_reviewed` (H5), `privacy_consent_covers_granted_rights`,
`privacy_redaction_record`, `privacy_retention_policy` and `privacy_pii_review` (H6),
`annotation_present`, and `split_assigned` (H10).

`privacy_consent_covers_granted_rights` **fails** the clip when any permission reads
`granted` while the consent record does not cover it, `rights.license_url` is null, or
`rights.determined_utc` is null. A `granted` permission with no paperwork behind it is worse
than `denied`: it is an assertion a buyer's counsel will ask us to indemnify. `on_request`
asserts only that terms exist to negotiate, so an unbacked one warns rather than fails.
`privacy_redaction_record` fails on `faces_redacted: true` with `redaction: null`, which
claims an outcome this schema itself defines as never having happened.

#### 4.2.1 `not_run` vs `not_applicable` — the two ways a check has no number

This rig ships **two products and they are equals**: *egocentric only* (stereo camera, no
gloves) and *egocentric + tactile* (stereo camera plus two gloves). Both are always stereo.
Camera-only is a shape the product ships, not a capture that went wrong, and the grade rule
has to be able to say so.

| result | means | caps the grade |
|---|---|---|
| `not_run` | the check **applies** to this package and was not executed | **yes, always** — an unmeasured bound is never evidence of passing |
| `not_applicable` | the package **does not carry the stream the check tests**, so there was never a number to take | **no** |

The distinction is the whole point, and the cheap version of this fix — making tactile checks
"pass" on a camera-only clip, or dropping them from the gate — destroys it. A glove that was
worn and whose CRC rate could not be read is `not_run` and still caps the grade. Only the
*absence of the glove* is `not_applicable`.

**Two rules keep it honest, and they are enforced in `ingest/validate.py`:**

1. **`not_applicable` is derived from a structural fact, never from a missing measurement.**
   The only two facts that produce it are `hands == []` (no glove was worn) and fewer than
   two clocked streams in the package (nothing for an inter-stream skew to be between). A
   measurement coming back `null` never produces it.
2. **That fact is published in the same record**, so the claim is checkable rather than
   assertable: `hands` for the tactile checks, `sync: null` for the inter-stream ones. Every
   `not_applicable` row also states the fact in its `note`, and still carries the `threshold`
   it *would* be held to on a package that carries the stream, so the check table stays
   diffable between the two products.

The checks that can report `not_applicable`, and on what:

| check | inapplicable when | why |
|---|---|---|
| `tactile_crc_pass_rate` | `hands == []` | no tactile frame exists to have carried a CRC |
| `tactile_channel_coverage` | `hands == []` | no readout sites to be covered. A **dead** glove is a coverage of zero and still fails; an absent one has no coverage |
| `tactile_census_reproducible` | `hands == []` | no channel census to re-derive |
| `sync_max_skew_ms` | fewer than two clocked streams | H1 is a *relation between* streams. The single delivered stream's own timeline is still checked, by `video_frame_timestamp_parity` |
| `sync_independent_validation` | fewer than two clocked streams | there is no cross-stream alignment for a common-mode physical event to corroborate |

A `not_applicable` row is neither a warn nor a fail: it is not counted in `qa.checks_warn` or
`qa.checks_fail`, and it produces no `known_limitations` entry, because there is no limitation
to state — the package's shape is already published in `modalities` and `hands`.

**A camera-only clip is still fully gradeable down.** Everything that applies to it is run:
frame dropout, frame/timestamp parity, checksums, the camera calibration model, rectification
residual, cam-IMU extrinsics, readout time, IMU noise, all four rights checks, all four
privacy checks, annotation and split. Nothing in this section touches consent, `pii_review`,
rights or hold.

---

## 5. `clips/<id>.json` — the full record

A strict superset of `ClipSummary` (identical names, types and meaning) plus:

| block | purpose | requirement served |
|---|---|---|
| `description` | long prose for the Metadata tab | |
| `media` | file pointers: `video`, `imu`, `tactile`, `segcap`, `calibration`, `docs`, `archive` | |
| `imu_preview` | render-ready payload for the IMU tab (§5.1) | |
| `tactile_preview` | grid, channel census, peak trace, stills (§5.2) | H9 |
| `segments` | the Segcap tab; `[]` = unannotated | |
| `package_contents` | every file with `bytes` + `sha256` + `role` | **H2** |
| `sync` | reference clock, per-stream offsets, measured max skew | **H1, H3** |
| `calibration` | fisheye intrinsics, cam-IMU, IMU noise, readout time | **H7** |
| `rights` | the four permissions + licence + restrictions + holder | **H5** |
| `privacy` | notice, consent, redaction record, retention | **H6** |
| `qa` | disposition + per-check table with measured value *and* threshold | **H2, H4** |
| `provenance` | take id, device, firmware, pseudonymous operator, pipeline | |
| `metadata` | the source metadata document, **verbatim** | |
| `known_limitations` | plain-language statements of what this cannot support | |

**`metadata` is the only `additionalProperties: true` object in the contract.** It carries the
upstream document byte-for-byte — no key renaming, no unit conversion, no pruning — which
guarantees the catalog is *lossless* with respect to whatever the capture pipeline knew.
Everything the grid needs is **lifted** to the top level precisely so nothing ever parses this
blob at render time.

`provenance.operator` is a **pseudonym** (`op-03`), never a name, email or initials. The
operator is a data subject too, and H6 does not stop at the video.

### 5.1 IMU: two encodings, one dispatch field

The IMU tab renders **every reading** — it scrolls horizontally and is explicitly not a
decimation. So the payload has two forms and the client dispatches on **`encoding` alone**.
It must never sniff, guess or fall back.

| `encoding` | when | read |
|---|---|---|
| `inline_f32` | `n_readings <= 2000` | `channels.accel.{x,y,z}`, `channels.gyro.{x,y,z}`; `sidecar` is `null` |
| `sidecar_f32le` | `n_readings > 2000` | `sidecar`; `channels` is `null` |

The 2000 threshold is **fixed by this contract** so producer and consumer cannot disagree.
Rationale: 6 channels × 2000 readings of JSON numbers ≈ 96 KB, acceptable inside an on-demand
record. The reference 29,507-reading stream would be ~1.4 MB as JSON against **708 KB** as
`f32`, and the binary parses in one pass with no per-sample allocation.

Sidecar layout — headerless, little-endian, channel-interleaved:

```
order        ["ax","ay","az","gx","gy","gz"]      (prepend "t" iff dt_s is null)
stride_bytes 4 * order.length                     ( = 24, or 28 with "t")
file size    n_readings * stride_bytes            ( = 708168 for 29507 readings)
value(i, c)  float index  i * order.length + c
```

```js
const r = await fetch(new URL(p.sidecar.url, catalogRoot));
const buf = await r.arrayBuffer();
if (buf.byteLength !== p.sidecar.n_readings * p.sidecar.stride_bytes) throw new Error("short read");
const f = new Float32Array(buf);              // every target platform is little-endian
const k = p.sidecar.order.length;
const ax = i => f[i * k + p.sidecar.order.indexOf("ax")];
const t  = i => p.imu_t0 + i * p.dt_s;         // dt_s, not 1/rate_hz: rounding drifts at 29k points
```

A big-endian consumer must read through a `DataView` with `littleEndian = true` rather than
assume. `range.{accel,gyro}.{min,max}` ships so the SVG can fix its y scale and dashed
gridlines **without** a full pass over 29,507 samples.

`imu_preview: null` means the clip has no IMU. The UI **disables** the IMU tab; it does not
render an empty axis.

### 5.2 Tactile: quote the census, not the grid

`tactile_preview` carries the channel census because "how many channels actually work" is the
first question a buyer asks and the easiest one to answer misleadingly.

```
readout_sites   484   <- the size of the 22x22 grid. NOT a sensor count.
  silent        164   <- std == 0 over the whole take: never reported anything
  over_ceiling   18   <- exceeded the physical ceiling: faulty, not loaded
  live          302   <- neither silent nor over-ceiling. DO NOT QUOTE THIS.
  intermittent   24   <- live but fails the slew rule: switching, not measuring
  stable        278   <- QUOTE THIS. Use it for anything on the time axis.
```

Three independent fault modes, three separate rules, all shipped in `census.rules` so a
consumer can re-derive rather than trust. `damage_note` states *where* the faults are
anatomically — "10 of 40 thumb taxels in a contiguous run at a grid edge" tells a buyer this
is a connector fault that will progress; a bare count does not.

H9 compliance: `units` is a closed enum, and `raw_adc_counts` is only honest when
`adc_bits`, `pedestal_counts` and `ceiling_counts` ship alongside. Quoting a physical range in
prose while shipping bare integers is the field's most common defect.

`display_full_scale_counts` (300) is deliberately lower than `ceiling_counts` (600): scaling a
heatmap to a ceiling nobody reaches renders every real contact as a faint smudge.

`peak_series` uses the same two-encoding rule as the IMU. It is an **envelope, not a sensor** —
the argmax channel can change between adjacent samples, so an apparent rise in this trace may
be two different taxels and must never be quoted as a rise time.

### 5.2.1 Two numbers, two provenances

`usable_channels` is **re-derived here** from `counts` on every build, using the rules in
`census.rules`, and compared against the producer's shipped `taxel_ok` / `taxel_live` /
`taxel_stable` masks. The shipped masks are what the record publishes — they are what the
package's own `derive_delta` snippet refers to, so publishing different ones would make the
catalog disagree with the bytes a buyer downloads — but the comparison ships as the
`tactile_census_reproducible` check, with **both** numbers when they differ, and it *fails*
when the shipped `stable` count is higher than the one we could reproduce. `census.rules`
always describes the numbers actually published: the producer's own rule strings when the
producer's masks are used, and `null` rather than ours when it stated none.

`tactile_crc_pass_rate` is **vendor-reported** and the record says so in
`tactile_preview.note`, in the check's `note` and in `known_limitations`. It counts the
`crc_ok` flag column the capture daemon wrote; the on-wire bytes it was computed over are not
in the delivered array, so no consumer — and no part of this ingest — can recompute it.

### 5.3 Sync (H1, H3) — there is no `synced: true`

The schema offers no boolean sync field, because it cannot be checked and is therefore
worthless. Required instead: `reference_clock_id`, `offset_sign_convention` (the sentence that
makes every `offset_ns` interpretable), per-stream `{stream_id, clock_id, offset_ns,
estimated_drift_ppm, interpolation_policy, maximum_alignment_error_ms}`, the take-level
measured `maximum_alignment_error_ms`, `validation_method` and `validation_result`.

`validation_result: "not_validated"` is an honest and common answer when streams share one
host clock but no independent common-mode event exists. It is far better than a pass that was
never measured — but it *is* a `warn`, so a clip without an independently validated
alignment cannot reach grade A.

**`maximum_alignment_error_ms` is composed, not copied.** It is the maximum over three
measured components, and is therefore `>=` every non-null `streams[].maximum_alignment_error_ms`:

```
max( clock_fit_se_worst_ms,                                   # the anchor fit's uncertainty
     |estimated_drift_ppm| * 1e-6 * duration_s * 1000,        # rate error over the take
     container-timeline divergence from real arrival times )  # measured off frame_times.csv
```

Component (a) is the **standard error of the fit**, not the scatter of the anchors about it.
A single anchor stamp says when the host was handed the bytes, not when the device sampled,
so it is quantised by transport burst arrival; what places a sample on the reference clock is
the fitted *line* through all the anchors, and the uncertainty of a line is its standard
error. On a 40–135-anchor take the two differ by roughly `sqrt(n)` — one real corpus
published **34.45 ms** for data whose fit is uncertain to about **3 ms**, which put it past
one video frame and read as "not frame-synchronised" for data that was.

The per-anchor residual still ships, as `clock_fit_residual_ms`, labelled as the transport
jitter the fit averaged out. It is deliberately **not** a lower bound on the headline:
requiring the headline to exceed it is exactly what forced the overstatement above.

Averaging that scatter is only legitimate when it *is* scatter. A producer quoting an SE
must also publish the lag-1 autocorrelation of the residuals: quantisation noise is
non-positive (measured −0.32 to −0.39 on real tactile streams), whereas a clock that curves
over the take gives a positive value — and there a straight line is the wrong model and its
standard error is meaningless. Where the autocorrelation is positive the ingest falls back to
the residual for that stream and says so in `sync.notes`.

The remaining components still bound the headline, and they routinely dominate: a 4.2 ms fit
SE sitting next to `estimated_drift_ppm: 1379.9` over an 11.6 s take implies 16.0 ms from
drift alone. A buyer will do that subtraction, so the build does it first — `catalog-ingest
validate` re-derives the inequality and **fails the build** when the headline is smaller than
any bound the record itself implies.

---

## 6. Hard-requirement conformance map

| # | requirement | where it lives |
|---|---|---|
| **H1** | measured max inter-stream skew, auto-flag > 33 ms | `sync.maximum_alignment_error_ms` (composed from the fit STANDARD ERROR, per-stream drift over the take and container-timeline divergence — see §5.3), `sync.clock_fit_se_worst_ms`, `sync.clock_fit_residual_ms` (jitter diagnostic, not a bound), `sync.streams[].maximum_alignment_error_ms`, checks `sync_max_skew_ms` (`threshold: 33.0`, acceptance 66.0) and `sync_independent_validation` |
| **H2** | frame count == timestamp count; SHA-256 manifest; dropout > 1% alerts | `qa.video_frames_delivered` / `qa.video_timestamps` / `qa.frame_count_matches_timestamps`; `package_contents[].sha256`; `qa.checksums_verified`; check `video_frame_dropout` with `threshold: 0.01` |
| **H3** | per-episode measured sync fields, sign convention stated | `sync.*` in full; no boolean `synced` field exists |
| **H4** | exactly one disposition; every check carries id/category/result/measured/threshold | `qa.disposition` (4-value enum); `qa.checks[]` with all five keys `required` |
| **H5** | per-clip rights, four separate permission enums | `rights.{model_training, commercial_use, redistribution, derived_model}` in **both** schemas; no null, fails closed to `denied` |
| **H6** | notice, retention + deletion, redaction record with policy version and reviewer, no re-identification | `privacy.{notice_given, retention, redaction{policy_version, targets, method, reviewer, reviewed_utc, items_redacted}, consent, reidentification_prohibited}` |
| **H7** | fisheye intrinsics, cam-IMU extrinsics + time offset, IMU noise density / random walk, image readout time | `calibration.camera.{model, cameras[].distortion, readout_time_ms, shutter}`, `calibration.cam_imu.{R,T,time_offset_s,time_offset_convention}`, `calibration.imu.{accel,gyro}_{noise_density,random_walk}` |
| **H9** | machine-readable units, or raw counts + bit depth + pedestal + ceiling | `tactile_preview.{units, adc_bits, pedestal_counts, ceiling_counts}`, `imu_preview.units` |
| **H10** | published train/val/test split; normalisation constants scoped to train | `ClipSummary.split` and `clip.split` (`train`/`val`/`test`/null); `collection.splits.{policy, buckets, normalization}`; check `split_assigned`. `normalization.scope` must read `train`, and `catalog-ingest validate` recomputes the constants from the clips the manifest itself assigns to train and fails on a mismatch. |

H8 and H11 concern MCAP structure and the ROS2 delivery path. Neither is expressible in a
catalog manifest and neither is claimed here. H10 partly is: the **split assignment** and the
**scope of the normalisation constants** are both plain manifest fields, and the earlier
claim that H10 was inexpressible was half wrong. What a manifest still cannot carry is the
per-taxel constant array itself; `tactile_pedestal_counts` and `tactile_scale_counts` are the
scalar summary, and the per-taxel form ships in the package.

---

## 7. Worked example — the real take

Source: `.context/pkg/out/egotac-16A260-20260823-000821/` (`egotac-1.0`, 84.6 s, 159,312,184 B).
`take_id` `ego_20260823_000821_16A260` → `id` `ego-20260823-000821-16a260`.
Both documents below validate; long arrays are abridged with `...`.

### `catalog.json` (abridged)

```json
{
 "schema": "6s-catalog/1.0",
 "generated_utc": "2026-08-23T18:00:00Z",
 "collection": {
  "id": "nervous-1",
  "name": "nervous-1",
  "version": "0.1.0-eval",
  "description": "One 84.6 s bimanual take: two 22x22 tactile gloves at 246.5 Hz on the same clock as a calibrated egocentric stereo camera at 30.06 fps. This is a capability sample, not a corpus: 0.023 hours, one subject, one session, one environment.",
  "vendor": { "name": "6thSense", "url": "https://6thsense.dev", "contact": "data@6thsense.dev" },
  "license": {
   "id": "6S-EVAL-NO-LICENCE",
   "name": "Evaluation sample - no licence granted",
   "url": "media/ego-20260823-000821-16a260/LICENSE.txt",
   "summary": "Shared for technical evaluation by the named recipient only. Per-clip rights in each clip's rights object override this and are authoritative."
  },
  "totals": { "clips": 1, "hours": 0.0235, "duration_unit": "minutes",
              "tactile_hours": 0.0235, "tactile_usable_hours": 0.0135,
              "subjects": 1, "sessions": 1,
              "bytes": 159312184, "countries": ["CN", "HK"], "categories": ["manipulation"],
              "date_range": ["2026-08", "2026-08"] },
  "paths": { "detail": "clips/{id}.json", "poster": "media/{id}/poster.jpg",
             "preview": "media/{id}/preview.mp4" },
  "splits": {
   "policy": "Assigned by capture device, so no device appears in two splits.",
   "buckets": [{ "value": "train", "label": "Train", "clips": 1, "hours": 0.0235, "usable_hours": 0.0135 }],
   "normalization": { "scope": "train", "computed_from_clips": 1,
                      "statement": "Fitted on the train split only. Val and test clips contributed nothing.",
                      "tactile_pedestal_counts": 21.3, "tactile_scale_counts": 600.0 }
  },
  "sample_archive": null,
  "notice": "Evaluation sample: no licence granted. Consent, ethics review and redaction are not in place."
 },
 "facets": {
  "category": [{ "value": "manipulation", "label": "Manipulation", "clips": 1, "hours": 0.0235, "usable_hours": 0.0135 }],
  "country":  [{ "value": "CN", "label": "China", "clips": 1, "hours": 0.0235, "usable_hours": 0.0135 }],
  "capture":  [{ "value": "stereo_egocentric", "label": "Stereo", "clips": 1, "hours": 0.0235, "usable_hours": 0.0135 }],
  "split":    [{ "value": "train", "label": "Train", "clips": 1, "hours": 0.0235, "usable_hours": 0.0135 }],
  "qa_grade": [{ "value": "C", "label": "Grade C", "clips": 1, "hours": 0.0235, "usable_hours": 0.0135 }]
 },
 "benchmark": {
  "unit": "minutes",
  "series": [{ "id": "egotac_eval", "label": "EGO-TAC evaluation sample", "color": "#14120c" }],
  "tasks":  [{ "label": "Bimanual bin-picking", "values": { "egotac_eval": 1.41 }, "clips": 1 }],
  "categories": [{ "value": "manipulation", "label": "Manipulation",
                   "values": { "egotac_eval": 1.41 }, "clips": 1 }],
  "note": null
 },
 "clips": [{
  "id": "ego-20260823-000821-16a260",
  "slug": "bimanual-bin-picking-16a260",
  "split": "train",
  "title": "Bimanual industrial bin-picking",
  "description_short": "Operator sorts and transfers small components between plastic trays and bins, both hands instrumented at 246.5 Hz.",
  "category": "manipulation",
  "subcategory": "bin_picking",
  "country": "CN",
  "recorded_month": "2026-08",
  "capture": "stereo_egocentric",
  "duration_s": 84.6,
  "resolution": [1920, 600],
  "fps": 30.06,
  "modalities": ["calibration", "tactile", "video"],
  "hands": ["left", "right"],
  "subjects": 1,
  "bytes": 159312184,
  "rights": { "model_training": "denied", "commercial_use": "denied",
              "redistribution": "denied", "derived_model": "denied" },
  "privacy": { "faces_redacted": false, "consent_on_file": false, "pii_review": "pending" },
  "qa": { "grade": "C", "video_frames_dropped": 0, "tactile_crc_pass_rate": 1.0,
          "usable_channels": { "left": 278, "right": 308 }, "tactile_coverage": 0.5744 }
 }]
}
```

Note what is **not** there: no `poster`, no `preview`, no `detail` — all three come from
`collection.paths`. That is 125 bytes saved on every clip. Note also `country: "CN"`, which
the ingest **cannot** infer: `metadata.json` carries only a `+08:00` offset, and +08:00 spans
nine countries — including both of the two this collection uses, `CN` and `HK`, which is
exactly why it cannot be guessed. It came from the operator's `take.yaml` (see `INTAKE.md`).

### `clips/ego-20260823-000821-16a260.json` (abridged)

```json
{
 "schema": "6s-clip/1.0",
 "id": "ego-20260823-000821-16a260",
 "split": "train",
 "...": "all ClipSummary fields repeat here, identically",
 "poster": "media/ego-20260823-000821-16a260/poster.jpg",
 "preview": "media/ego-20260823-000821-16a260/preview.mp4",

 "rights": {
  "model_training": "denied", "commercial_use": "denied",
  "redistribution": "denied", "derived_model": "denied",
  "license_id": "6S-EVAL-NO-LICENCE",
  "license_name": "Evaluation sample - no licence granted",
  "license_url": "media/ego-20260823-000821-16a260/LICENSE.txt",
  "restrictions": [
   "Named recipient only; shared solely for technical evaluation.",
   "No publication of frames containing the operator or the premises.",
   "A permissive licence (CC BY 4.0 or similar) is intended for a full release, gated on subject consent, ethics review and a redaction policy - none of which exist yet."
  ],
  "attribution_required": true,
  "holder": "6thSense",
  "determined_utc": "2026-08-23T17:31:00Z",
  "notes": "All four permissions are denied because human-subject consent does not exist. This is the current state, not a negotiating position."
 },

 "privacy": {
  "faces_redacted": false, "consent_on_file": false, "pii_review": "pending",
  "notice_given": true, "identifiable_persons": 1, "identifiable_premises": true,
  "redaction": null,
  "_note": "faces_redacted is false, not true, so the null redaction record is consistent. `faces_redacted: true` alongside `redaction: null` FAILS privacy_redaction_record and quarantines the clip: it claims an outcome the schema defines as never having happened.",
  "retention": { "policy": "Source material is retained until licence terms are agreed or the evaluation closes.",
                 "delete_after_utc": null, "deletion_request_contact": "data@6thsense.dev" },
  "consent": { "subjects_consented": 0, "covers_model_training": false,
               "covers_redistribution": false, "document_ref": null },
  "reidentification_prohibited": true
 },

 "qa": {
  "grade": "C", "disposition": "accepted",
  "video_frames_dropped": 0, "video_frames_delivered": 2544, "video_timestamps": 2544,
  "frame_count_matches_timestamps": true,
  "tactile_crc_pass_rate": 1.0,
  "tactile_crc_pass_rate_by_hand": { "left": 1.0, "right": 1.0 },
  "tactile_frames_lost": { "left": 0, "right": 0 },
  "usable_channels": { "left": 278, "right": 308 },
  "checksums_verified": true,
  "checks": [
   { "check_id": "video_frame_timestamp_parity", "category": "integrity", "result": "pass",
     "measured_value": 2544, "threshold": 2544, "units": "count",
     "note": "2544 container frames against 2544 rows in frame_times.csv." },
   { "check_id": "video_frame_dropout", "category": "media", "result": "pass",
     "measured_value": 0.0, "threshold": 0.01, "units": "fraction" },
   { "check_id": "tactile_channel_coverage", "category": "coverage", "result": "pass",
     "measured_value": 0.574, "threshold": 0.40, "units": "fraction",
     "note": "Worst hand: 278 live-and-stable of 484 readout sites. Below the 0.60 bound for grade A. Acceptance bound 25%; below it the glove is broken hardware." },
   { "check_id": "sync_max_skew_ms", "category": "sync", "result": "warn",
     "measured_value": 33.3, "threshold": 33.0, "units": "ms",
     "note": "USB burst delivery quantises arrival stamps, so per-frame alignment is +/-1 video frame. Acceptance bound 66 ms (two camera frames); above it the clip is quarantined." },
   { "check_id": "sync_independent_validation", "category": "sync", "result": "warn",
     "measured_value": "not_validated", "threshold": "pass", "units": null,
     "note": "No common-mode event (clap) in this take, so alignment rests on the shared host clock." },
   { "check_id": "calibration_rectification_residual_px", "category": "calibration", "result": "pass",
     "measured_value": 0.2, "threshold": 0.5, "units": "px",
     "note": "Median |dy| over ~380 ORB matches using calibration_delivered.json. The raw solve with a 0.5x scale only gives 19.62 px." },
   { "check_id": "privacy_consent_covers_granted_rights", "category": "privacy", "result": "pass",
     "measured_value": "no permissions granted",
     "threshold": "consent must cover every granted permission", "units": null,
     "note": "No consent is on file and correspondingly nothing is granted. Any move to granted re-runs this check and it will fail." },
   { "check_id": "privacy_pii_review", "category": "privacy", "result": "warn",
     "measured_value": "pending", "threshold": "passed", "units": null }
  ],
  "notes": "Grade C: worst-case alignment is 33.3 ms, above the 33.0 ms H1 bound that BOTH A and B require, and left-hand channel coverage is 57.4%, below the 0.60 needed for A. It is accepted, and both exceedances are named verbatim in known_limitations — which is exactly what grade C means. It is inside the 66.0 ms acceptance bound, so it is not quarantined."
 },

 "media": {
  "video": {
   "stereo_sbs": "media/ego-20260823-000821-16a260/video/stereo_upright.mp4",
   "left": null, "right": null, "mono": null,
   "frame_times": "media/ego-20260823-000821-16a260/video/frame_times.csv",
   "layout": "side_by_side_lr",
   "codec": "h264 (from sensor MJPEG, one re-encode)",
   "source_resolution": [4000, 1200], "frames": 2544, "constant_frame_rate": true,
   "timing_note": "Container PTS diverges from true time by mean -16.3 ms and up to 38.0 ms (9.4 tactile samples). ALWAYS index by frame_idx and look the time up in frame_times.csv; NEVER seek the container by timestamp.",
   "orientation_note": "The module is mounted INVERTED, so each eye is cropped and rotated 180 deg individually. The mount also swaps which sensor is physically left: cam0 is the LEFT eye here. Verified by disparity sign."
  },
  "imu": null,
  "tactile": {
   "left": "media/ego-20260823-000821-16a260/tactile/left.npz",
   "right": "media/ego-20260823-000821-16a260/tactile/right.npz",
   "preview_png": ["media/ego-20260823-000821-16a260/preview/p50_frame2046_peak156_t068.1s.png", "..."],
   "layout": "media/ego-20260823-000821-16a260/sensor_layout.json"
  },
  "segcap": null,
  "calibration": { "raw": "media/.../calibration.json", "delivered": "media/.../calibration_delivered.json" },
  "docs": { "readme": "media/.../README.md", "datasheet": "media/.../DATASHEET.md",
            "license": "media/.../LICENSE.txt", "sync_protocol": "media/.../SYNC_PROTOCOL.md",
            "checksums": "media/.../checksums.sha256" },
  "archive": null
 },

 "imu_preview": null,

 "tactile_preview": {
  "grid": [22, 22], "readout_sites": 484,
  "usable_channels": { "left": 278, "right": 308 },
  "units": "raw_adc_counts", "adc_bits": 16, "pedestal_counts": null,
  "ceiling_counts": 600, "display_full_scale_counts": 300,
  "census": {
   "left": { "readout_sites": 484, "silent": 164, "over_ceiling": 18, "intermittent": 24,
             "live": 302, "stable": 278,
             "rules": { "silent": "counts.std(axis=0) == 0 over the whole take.",
                        "over_ceiling": "delta exceeds 600 counts anywhere. The good population tops out at 575 while faulty channels jump straight past 2000; the gap is empty, so the threshold is unambiguous.",
                        "intermittent": "|diff(counts)| > 150 counts in one 4.06 ms sample on more than 0.1% of samples." },
             "damage_note": "10 of 40 THUMB and 7 of 40 PINKY taxels are rejected, in contiguous runs at the two extreme grid rows. A contiguous run at an array edge is a flex-trace or connector fault and is expected to progress." },
   "right": { "readout_sites": 484, "silent": 165, "over_ceiling": 1, "intermittent": 10,
              "live": 318, "stable": 308, "rules": null,
              "damage_note": "1 palm taxel rejected; fingers fully intact." }
  },
  "peak_series": null,
  "frames": [
   { "t_s": 68.1, "hand": "both", "peak_counts": 156, "png": "media/.../preview/p50_frame2046_peak156_t068.1s.png", "label": "p50" },
   { "t_s": 42.1, "hand": "both", "peak_counts": 561, "png": "media/.../preview/max_frame1265_peak561_t042.1s.png", "label": "max" }
  ],
  "index_rule": "i = row*22 + P[col]; P differs per hand and ships in the layout sidecar.",
  "derive_delta": "delta = clip(counts.astype('f4') - baseline, 0, None); delta[:, ~taxel_stable] = 0",
  "note": "Median per-frame peak is 99 (left) / 144 (right) counts, so heatmaps use 0-300."
 },

 "segments": [],

 "package_contents": [
  { "path": "video/stereo_upright.mp4", "url": "media/.../video/stereo_upright.mp4",
    "bytes": 123485818, "sha256": "…64 hex…", "role": "video" },
  { "path": "video/frame_times.csv", "url": "media/.../video/frame_times.csv",
    "bytes": 54876, "sha256": "…64 hex…", "role": "video_index" },
  "… 28 more entries …"
 ],

 "sync": {
  "reference_clock_id": "host CLOCK_REALTIME, Unix wall-clock epoch microseconds; not monotonic; no NTP step occurred during the take",
  "offset_sign_convention": "offset_ns = t_reference - t_stream; a positive value means the stream's own timestamps run EARLY relative to the reference clock.",
  "streams": [
   { "stream_id": "video", "clock_id": "capture.egoc per-frame ts_us (host receive time)",
     "offset_ns": 0, "estimated_drift_ppm": 0.0, "interpolation_policy": "none",
     "maximum_alignment_error_ms": 33.3 },
   { "stream_id": "tactile_right", "clock_id": "glove device_us, mapped to host_us by a linear fit over per-250-frame anchors",
     "offset_ns": -9410000, "estimated_drift_ppm": -17.0, "interpolation_policy": "next",
     "maximum_alignment_error_ms": 32.1 }
  ],
  "maximum_alignment_error_ms": 33.3,
  "clock_fit_residual_ms": 12.4,
  "validation_method": "None. Both clocks come from one host process, so alignment is arithmetic rather than measured. A common-mode bimanual clap is committed for every pilot take.",
  "validation_result": "not_validated",
  "cross_hand_offset_ms": 9.41, "cross_hand_drift_ppm": -17.0,
  "samples_per_video_frame": 8.2,
  "notes": ["The gloves started 9.41 ms apart and the right ran 65 frames longer, so end-minus-start offset is ~263 ms. That is a length difference, not clock drift.",
            "maximum_alignment_error_ms is the maximum over three measured components, not the clock-fit residual alone: clock_fit_residual_ms = 12.4 ms, the per-stream rate error carried over the take, and the constant-rate container timeline's divergence from the real per-frame arrival times (33.3 ms)."]
 },

 "calibration": {
  "camera": {
   "model": "kannala_brandt", "image_size": [960, 600],
   "cameras": [
    { "id": "cam0", "role": "left", "fx": 411.4799, "fy": 410.8500, "cx": 466.1133, "cy": 288.3972,
      "distortion": [-0.03313077, -0.00705949, 0.00121990, -0.00052306] },
    { "id": "cam1", "role": "right", "fx": 412.2338, "fy": 411.5798, "cx": 458.6687, "cy": 293.9624,
      "distortion": [-0.03299875, -0.00753286, 0.00143694, -0.00054064] }
   ],
   "stereo": { "R": [[0.99999209, -0.00011035, 0.00397680], "…"], "T": [-0.06035864, 0.00027147, 0.00007873],
               "baseline_m": 0.06035930 },
   "rms_reprojection_px": 0.8438887, "rectification_residual_px": 0.2,
   "shutter": null, "readout_time_ms": null,
   "note": "These values are calibration_delivered.json: already de-rotated and scaled for the 960x600 panes. Applying the raw solve with a 0.5x scale only gives 19.62 px against 0.20 px here."
  },
  "imu": {
   "model": "BNO086", "status": "failed", "rate_hz": null,
   "accel_noise_density": null, "accel_random_walk": null,
   "gyro_noise_density": null, "gyro_random_walk": null,
   "units_note": "No values are quoted because the part emits nothing on this rig. It is declared with status 'failed' rather than omitted so a buyer finds it in the schema and not after integration."
  },
  "cam_imu": null,
  "tactile": { "grid": [22, 22], "index_rule": "i = row*22 + P[col]",
               "taxel_pitch_mm": 10.0, "force_calibration": null }
 },

 "provenance": {
  "take_id": "ego_20260823_000821_16A260", "device_id": "16A260", "firmware": "1.3.15.glove",
  "operator": "op-01", "recorded_local": "2026-08-23T00:08:21.770883+08:00",
  "packaged_utc": "2026-08-23T09:26:23Z", "pipeline_version": "egotac-pkg/1.0",
  "session_id": "ses-20260823-16a260", "environment": "indoor workshop / parts-staging area",
  "note": "Device wall clock with its UTC offset (+08:00). NTP was not stepped during the take."
 },

 "metadata": { "schema": "egotac-1.0", "take_id": "ego_20260823_000821_16A260",
               "…": "the entire source metadata.json, verbatim, 19,979 bytes" },

 "known_limitations": [
  "Force is in raw ADC counts; there is no calibration to newtons or kPa.",
  "The glove IMU (BNO086) is dead in hardware and emits nothing; no glove-side kinematics.",
  "No object, action, grasp or language annotation.",
  "Single subject, single session, single environment.",
  "There is no independent physical sync event in this take, so video-tactile alignment rests on the shared host clock rather than on a measured common-mode event.",
  "Peak-over-taxels traces are an ENVELOPE, not a sensor: the argmax channel changes between adjacent samples on 25% of this take.",
  "Rolling-shutter image readout time has not been measured, so H7 rolling-shutter compensation is not possible from the shipped calibration.",
  "QA check `sync_max_skew_ms` misses its bound: measured 33.3 ms against 33.0 ms. Acceptance bound 66 ms (two camera frames); above it the clip is quarantined.",
  "QA check `sync_independent_validation` misses its bound: measured not_validated against pass. No independent common-mode event (a clap visible in video and sharp on both gloves) validates the alignment; it rests on the shared host clock.",
  "tactile_crc_pass_rate is vendor-reported: it counts the `crc_ok` flag column the capture daemon wrote into the delivered array. The on-wire bytes are not shipped, so no consumer -- and no part of this ingest -- can recompute it independently."
 ]
}
```

### What the example demonstrates

- `imu_preview: null` and `imu` absent from `modalities` — the BNO086 is present in hardware
  and dead. It is declared in `calibration.imu.status = "failed"` so a buyer finds it in the
  schema, not after integration. Listing a dead sensor as a modality is the easiest way to
  lose a buyer's trust.
- `segments: []` with a matching entry in `known_limitations`. Empty is a determined answer.
- All four permissions `denied`, and the privacy check still **passes** — because nothing is
  granted, there is nothing for consent to cover. Flip any permission to `granted` and that
  check fails, unless the consent record covers it, `license_url` names a document and
  `determined_utc` records a human review.
- Grade **C**, not B, because 33.3 ms is over the H1 bound that both A and B require — and
  every measured miss is restated verbatim in `known_limitations`, quoting the measurement,
  the bound and the units. Grade C is "accepted with a NAMED caveat", so the caveat is named
  where a buyer reads it rather than left as a `warn` in the fourth tab.
- `split: "train"` and `collection.splits.normalization.scope: "train"` — the partition is
  published and the constants say which part of it they were fitted on (H10).

---

## 8. Keeping the two schemas in sync

`clip.schema.json` intentionally **duplicates** the shared `$defs` (`AssetUrl`, `ExternalUrl`,
`LicenseUrl`, `ClipId`, `Slug`, `CountryCode`, `YearMonth`, `Capture`, `Modality`, `Hand`,
`Resolution`, `Grade`, `Permission`, `Split`) rather than `$ref`-ing across files. The trade
is deliberate: a buyer's engineer can validate either file with zero registry wiring, at the
cost of a drift risk we close with an assertion that is **run**, not just printed —
`tests/test_schema_sync.py`, i.e. `make test`.

```python
import json
a = json.load(open("catalog.schema.json"))["$defs"]
b = json.load(open("clip.schema.json"))["$defs"]
SHARED = ["AssetUrl","ExternalUrl","LicenseUrl","ClipId","Slug","CountryCode","YearMonth",
          "Capture","Modality","Hand","Resolution","Grade","Permission","Split"]
for k in SHARED:
    # .get, not []: LicenseUrl is an `anyOf` with no `type` of its own, and the
    # earlier version of this snippet raised KeyError on it — a CI assertion that
    # cannot run is the same kind of claim as a threshold that cannot fail.
    for facet in ("type", "enum", "pattern", "anyOf", "const", "minLength", "maxLength"):
        assert a[k].get(facet) == b[k].get(facet), (k, facet)
```

`title` and `description` are allowed to differ (each file describes the def in its own
context); **type, `enum` and `pattern` must not.**

`$id` appears once per document, as the specification intends. Putting `$id` on every
subschema would create new base URIs and break `#/$defs/...` resolution, so every *property*
instead carries `title` and `description`, which is what a reader actually needs.

---

## 9. Versioning

| change | version |
|---|---|
| new optional property, new enum member, relaxed constraint | minor — `6s-catalog/1.1` |
| removed property, retyped property, removed enum member, tightened `required` | **major** — `6s-catalog/2.0` |

The `schema` const is checked before anything else is parsed. A consumer that sees an
unrecognised **major** must refuse to render rather than degrade silently: a rights field it
does not understand is a legal problem, not a display problem.

### Changes made to `1.0` before it was published

`6s-catalog/1.0` has not been handed to anyone: no bundle built against it has left this
repository, and `site-patch/` is written but deliberately not applied. So the changes below
were made **in place** rather than by burning a major version. Three of them would be a major
bump the moment 1.0 ships, and they are named here rather than folded quietly into a minor:

| change | under the table above |
|---|---|
| `Modality` loses `audio`, `hand_pose`, `depth` — none had a `media` slot or a quality block, so a clip could claim one, filter on it and add its full duration to `facets.modality[].hours` while resolving to no file | **major** (removed enum member) |
| `split` added to the `required` list of `ClipSummary` and of the clip record | **major** (tightened `required`) |
| `qa.tactile_coverage`, `totals.tactile_hours`, `totals.tactile_usable_hours`, `FacetBucket.usable_hours`, `collection.splits`, `collection.sample_archive` added as required-and-nullable, per R3 | **major** (tightened `required`) |
| `sync.clock_fit_residual_ms` added as optional; `split` facet added; descriptions sharpened | minor |
| `collection.totals.{sync_clips_measured, sync_max_alignment_error_ms, sync_p95_alignment_error_ms, sync_clips_over_one_frame}` added as required — the H1 aggregate the header quotes | **major** (tightened `required`) |
| `collection.totals.sync_clips_independently_validated` added as required — the figure that says what the alignment error is worth (§3.1.0) | **major** (tightened `required`) |
| `qa.sync_validated` added as required on `ClipSummary` and on the clip record | **major** (tightened `required`) |
| `collection.standfirst` added as optional-and-nullable — the authored promoted line (§3.1.0) | minor |
| `collection.provenance_class` added as required; `provenance.media_class` added as required on the clip record | **major** (tightened `required`) |
| `qa.{disposition, checks_warn, checks_fail}` added as required on `ClipSummary`; `qa.{checks_warn, checks_fail}` added as required on the clip record | **major** (tightened `required`) |
| `benchmark.tasks[].clips` added as required-and-nullable | **major** (tightened `required`) |
| `benchmark.categories[]` added as required — the coarse roll-up the chart actually draws, emitted by the producer because the consumer holds no clip-to-category map (§3.1.1) | **major** (tightened `required`) |
| `media.video.{overview, closeup}` added as optional-and-nullable — the two rendered clips every package already ships, the overlay composite and the force close-up, were pointed at by nothing and so were invisible to a buyer | minor |
| `qa.checks[].result` gains `not_applicable` (§4.2.1) — without it there is no way to say "there was nothing here to check", so a flawless camera-only package was structurally incapable of reaching grade A and a buyer reading the raw record could not tell an inapplicable check from one we skipped | minor (new enum member) |
| `facets.hands` gains the conventional value `none` for `hands: []` — a camera-only clip previously fell into no bucket, so it could not be filtered for, counted or priced | minor (no schema constraint changed; `FacetBucket.value` is a free string) |

Anything after the first published bundle follows the table strictly. The reason to say this
out loud is that a contract which quietly rewrites its own `1.0` is worth exactly as much as a
grade rule that cannot fail.
