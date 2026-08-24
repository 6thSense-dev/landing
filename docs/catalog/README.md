# The data catalog, end to end

A prospect logs in at `6thsense.dev/login` as `guest` and lands on a read-only catalog of
clips. This page is the whole path from a capture rig to that page, in order.

## Run the whole thing locally first

```bash
make -C scripts/catalog dev        # or: ./scripts/catalog/dev_local.sh
```

Postgres, migrations, the guest account, the API on the local-disk driver and the Vite dev
server — one command, no AWS, no domain. It prints
`http://localhost:5173/login` and you sign in as `guest`. Ctrl-C tears it all down;
`make -C scripts/catalog dev-stop` cleans up after a hard kill. `--rebuild` regenerates the
corpus first, `--with-gaps` builds the missing-modality corpus instead.

Going live is a change of environment, not of code — the storage layer has two drivers behind
one interface:

| | local (this script) | production |
|---|---|---|
| | `CATALOG_SOURCE=local` | `CATALOG_SOURCE=s3` |
| | `CATALOG_LOCAL_DIR=<bundle>` | `CATALOG_S3_BUCKET` / `_REGION` / `_PREFIX` + a read-only key |

**One gotcha the script handles for you:** the session cookie is `SameSite=Lax`, and Chromium
treats `localhost` and `127.0.0.1` as *different sites*. Serve the page from one and the API
from the other and login appears to succeed while every catalog request 401s. The script uses
the same hostname for both.

See [`DEPLOY.md`](./DEPLOY.md) for the ordered runbook to ship it.

```
capture rig ──► takes/ ──► catalog_ingest build ──► bundle/ ──► upload_bundle.py ──► s3://6thsense-catalog-media/v1/
                  │                                    │                                        │
             INTAKE.md                         catalog.json                          FastAPI reads the JSON,
             (§ what a take                    clips/<id>.json                       presigns the media, and
              must contain)                    posters/ previews/                    the BROWSER fetches bytes
                                               media/<id>/…                          straight from S3
```

Three ideas hold it together:

1. **The bundle is the contract.** Two JSON Schemas — `scripts/catalog/schema/` — define
   `catalog.json` and each `clips/<id>.json`. The ingest emits nothing that is not in them;
   the UI reads nothing that is not in them. `CONTRACT.md` is the prose half.
2. **Every asset URL in the bundle is relative to the directory holding `catalog.json`.**
   The same bundle therefore works unchanged on a laptop, on S3 behind presigned URLs, and
   behind the portal proxy. The host rewrites the base; the manifest never moves.
3. **Nothing is guessed.** A value the ingest cannot measure is `null`, the UI renders `null`
   as an em-dash, and `INGEST_REPORT.md` names the take that produced it.

| | |
|---|---|
| What a capture operator must hand over | [`INTAKE.md`](./INTAKE.md) |
| Field-by-field spec, grade rule, size budgets | [`CONTRACT.md`](./CONTRACT.md) |
| The CLI's own reference | [`../../scripts/catalog/ingest/README.md`](../../scripts/catalog/ingest/README.md) |
| The synthetic-take generator | [`../../scripts/catalog/fixtures/README.md`](../../scripts/catalog/fixtures/README.md) |

---

## 1. Where the data comes from

Real takes arrive from the capture rig as one directory per take, already encoded to web mp4.
The delivered corpus is **~30 clips of 30–45 s — about twenty minutes of runtime, not hours.**
Everything downstream is sized for that: the chart picks a minutes axis, the header quotes
minutes, and the whole bundle is a few hundred megabytes (the 30-take fixture bundle is
267 MB, almost all of it `media/`).

Until real takes land, `make fixtures` writes a synthetic `takes/` tree in exactly the shape
`INTAKE.md` describes — real playable h264, real tactile `.npz` with a realistic channel
census, real SHA-256s — so the pipeline is demoable and testable with no hardware. The ingest
has no fixture-only branch: it cannot tell the difference.

---

## 2. Build a bundle

```bash
python3 -m pip install -r scripts/catalog/requirements.txt   # jsonschema numpy pyyaml pytest boto3
# plus ffmpeg + ffprobe on PATH

# To run the API or its tests you also need the backend deps. boto3 is already in
# requirements-backend.txt; `requirements-backend-dev.txt` adds pytest and the
# Postgres testcontainer (Docker must be running for `cd backend && pytest`).
python3 -m pip install -r requirements-backend-dev.txt
# If the system Python refuses (externally-managed-environment):
#   python3 -m venv .venv && .venv/bin/pip install -r requirements-backend-dev.txt

make -C scripts/catalog            # fixtures + ingest + validate + test
                                   # ~45 min and ~250 MB from cold: 30 takes of 30-45 s
                                   # is 20 minutes of real h264 to encode. Use
                                   # `CLIPS=5` while iterating.
```

Or one step at a time:

| target | what it does | writes |
|---|---|---|
| `make -C scripts/catalog fixtures` | 30 synthetic takes at 30–45 s (~40 min, 223 MB) | `scripts/catalog/sample/takes/` |
| `make -C scripts/catalog ingest` | takes → bundle | `scripts/catalog/sample/bundle/` |
| `make -C scripts/catalog validate` | re-validate the emitted bundle | — |
| `make -C scripts/catalog stats` | totals and facet counts | — |
| `make -C scripts/catalog test` | 74 unit tests | — |
| `make -C scripts/catalog upload` | sync the bundle to S3 | `s3://…/v1/` |
| `make -C scripts/catalog clean` | delete `sample/` | — |

Override any of `CLIPS SEED MIN_S MAX_S TAKES BUNDLE PREFIX`:

```bash
make -C scripts/catalog fixtures CLIPS=5 MIN_S=30 MAX_S=45     # a fast loop
make -C scripts/catalog ingest   TAKES=/data/real/takes BUNDLE=/data/real/bundle
```

For a **real** drop, run the ingest by hand so you can pass `--strict` and `--media-mode copy`:

```bash
cd scripts/catalog
python3 -m ingest.catalog_ingest build --takes /data/real/takes --out /data/real/bundle \
        --media-mode copy --posters --previews --strict
python3 -m ingest.catalog_ingest validate --out /data/real/bundle     # must be all PASS
```

`--media-mode copy` hard-links within a filesystem and copies across devices, so the bundle is
self-contained. The default, `reference`, emits URLs for bytes it never materialised — fine
for a local schema check, useless to upload.

### What a bundle holds

```
bundle/
├── catalog.json              the manifest: collection, totals, facets, benchmark, clips[]
├── clips/<id>.json           one full record per clip
├── posters/<id>.jpg          grid thumbnails
├── previews/<id>.mp4         3 s silent hover loops
├── media/<id>/…              the take package: video/, tactile/, imu/, calibration/, docs/
├── imu/<id>.f32              full-rate IMU sidecar (streams over 2000 readings)
├── tactile/<id>.peak.f32     peak envelope
├── stills/<id>/*.png         tactile heatmaps
├── archives/<id>.tar.gz      only for takes marked publish_archive
├── INGEST_REPORT.md          every warning, named by take
└── .ingest-state.json        digest cache; safe to delete, costs a full rebuild
```

The ingest is **idempotent by content hash**: a rebuild from unchanged inputs rewrites nothing,
`catalog.json` keeps its previous `generated_utc`, and `upload_bundle.py` then skips every
object by ETag.

---

## 3. Provision S3 (once)

Media lives in a **private** bucket. It is never public-read; the only way in is a short-lived
presigned URL minted by the API.

```bash
AWS_PROFILE=6thsense-admin ./scripts/catalog/provision_s3.sh
```

Idempotent. It creates `6thsense-catalog-media` in `us-west-2`, blocks all public access,
turns on AES256 encryption and versioning, applies CORS that exposes `Content-Range` /
`Accept-Ranges` (this is what makes `<video>` seeking work), expires noncurrent versions after
30 days, and creates an IAM user `catalog-media` scoped to that one bucket. Then mint a key
once:

```bash
aws iam create-access-key --user-name catalog-media
```

Set these on the Railway **backend** service and in your local `.env`:

```
CATALOG_S3_BUCKET=6thsense-catalog-media
CATALOG_S3_REGION=us-west-2
CATALOG_S3_PREFIX=v1/
CATALOG_AWS_ACCESS_KEY_ID=…
CATALOG_AWS_SECRET_ACCESS_KEY=…
CATALOG_PRESIGN_TTL=900
```

Nothing in `scripts/catalog/` needs the secret key except `upload_bundle.py`, and it will also
take a plain `AWS_PROFILE`.

---

## 4. Upload

```bash
python3 scripts/catalog/upload_bundle.py --bundle /data/real/bundle --prefix v1/ --dry-run
python3 scripts/catalog/upload_bundle.py --bundle /data/real/bundle --prefix v1/
```

It mirrors the bundle tree under the prefix, key for key, so `clips/abc.json` in the bundle is
`v1/clips/abc.json` in the bucket. Content types are set explicitly — a `video/mp4` served as
`application/octet-stream` will not stream in Safari — and `Cache-Control` is `no-cache` for
JSON and one immutable year for everything else. Files already present with a matching ETag
are skipped, so a re-upload after a small re-cut moves only what changed.

---

## 5. How the API serves it

The API reads the **documents** and presigns the **bytes**. Media never passes through Railway.

| request | what the backend does |
|---|---|
| `GET /api/catalog` | fetch `<prefix>catalog.json` from S3, apply the role's redaction policy, return JSON |
| `GET /api/catalog/clips/{id}` | same for `<prefix>clips/{id}.json` |
| `GET /api/catalog/media/{path}` | check the role, then **302 to a presigned GET URL** valid for `CATALOG_PRESIGN_TTL` seconds |

Two consequences worth stating plainly:

- **Range requests, and therefore video seeking, come for free**, because the browser is
  talking to S3 directly and S3 speaks Range.
- **The role gate lives in the URL signing.** A `guest` gets presigned URLs for exactly the
  encoded mp4, the poster, the preview and the rendered heatmaps. Requests for originals, the
  `.npz`, the raw csv or `archives/` are refused before anything is signed — server-side, by
  role, not by hiding a button in the UI.
- **One clip is the exception, and it is the difference between a brochure and an
  evaluation.** The product's differentiator is time alignment; the withhold list took away
  `frame_times.csv` — the file the sync notes tell consumers to index the video by — the
  per-hand `.npz` and the geometry sidecar that makes it indexable, from every clip. Nothing
  on the page was then independently checkable: every figure vendor-asserted, on a corpus the
  page also says is synthetic. So the clip named by `collection.sample_archive.clip_id` ships
  those four things (plus its package archive) at preview level, and everything else stays
  exactly as shut, on that clip and on all the others. **Naming is not authorisation**:
  `catalog_redact.is_open_clip()` re-derives the commercial test from the clip's own `rights`
  — all four permissions `granted` — before it exempts a single path, so a hand-edited
  manifest pointing at a clip whose rights are anything less opens nothing. Costs ~7 MB.

Backend env: everything in §3, plus `CATALOG_SOURCE` (`s3`, the default) — see §6.

---

## 6. Run the site locally against a local bundle

No AWS credentials, no network, no bucket:

```bash
make -C scripts/catalog                     # build sample/bundle

# backend
export CATALOG_SOURCE=local
export CATALOG_LOCAL_DIR="$PWD/scripts/catalog/sample/bundle"
cd backend && uvicorn app.main:app --reload --port 8000

# frontend, in another shell
cd frontend && npm run dev
```

`CATALOG_SOURCE=local` swaps the S3 client for the filesystem and serves `media/**` directly
instead of redirecting. **The same redaction policy runs in both modes** — that is the point
of the switch being one flag rather than a separate code path. Log in as `guest` with the password you seeded
(`CATALOG_GUEST_PASSWORD=... python3 -m app.cli seed-guest`; locally, pick any throwaway of
8+ characters) and you are looking at the real thing.

Point it at a different bundle by changing `CATALOG_LOCAL_DIR`; nothing else moves.

---

## 7. Cutting a v2 and switching over

Prefixes exist so a re-cut is never a destructive overwrite of a bundle someone is browsing.

```bash
# 1. build the new corpus
python3 -m ingest.catalog_ingest build --takes /data/v2/takes --out /data/v2/bundle \
        --media-mode copy --posters --previews --strict
python3 -m ingest.catalog_ingest validate --out /data/v2/bundle

# 2. stage it alongside v1 — nothing live changes
python3 scripts/catalog/upload_bundle.py --bundle /data/v2/bundle --prefix v2/

# 3. verify against the staged prefix before anyone sees it
CATALOG_S3_PREFIX=v2/ uvicorn app.main:app --port 8001     # then browse localhost:8001

# 4. switch: set CATALOG_S3_PREFIX=v2/ on the Railway backend service and redeploy
# 5. roll back by setting it to v1/. v1 is still there, byte for byte.
```

Delete `v1/` only once you are sure — the bucket is versioned, but a delete is still a delete.

**Clip ids are the thing that must not churn across a re-cut.** They come from the take
directory name, so keep the directory names identical between `v1` and `v2` and every shared
`?clip=<id>` link, bookmark and download receipt survives the switch.

---

## 8. Two numbers that are easy to get wrong

**The corpus is minutes, not hours.** `benchmark.unit` and `collection.totals.duration_unit`
are chosen from the data — hours at or above a 2 h total, minutes below it — and published, so
the chart's axis and the header's stat tile cannot disagree. A consumer that renders `minutes`
values through an hours formatter is wrong by a factor of sixty.

**No third-party corpus appears on the chart.** We do not hold per-task hour breakdowns for
Ego4D, EgoDex, Xperience-10M or Egocentric-100K, and the buyers who would look at such a chart
know the real figures. The `[[benchmark.comparison]]` mechanism exists, requires a
`source_url` and a `retrieved` date, refuses to build without them, and prints the citation
under the bars — and it ships empty. See `INTAKE.md` §4.

---

## 9. Verified, and how

Everything below was run against a live stack — Postgres in Docker, migrations applied, the
guest seeded, uvicorn serving a real bundle, the Vite dev server, and headless Chrome driving
it — on **both** storage drivers.

| | |
|---|---|
| `make -C scripts/catalog clean fixtures ingest validate CLIPS=30` | exit 0, 15/15 `PASS`, **30 clips, 0 quarantined**, `benchmark.unit=minutes` |
| `scripts/catalog/tests` | 123 passed |
| `cd backend && pytest` | 286 passed |
| `alembic upgrade head` → `downgrade -1` → `upgrade head` | round-trips; `guest` deactivated, sessions dropped, role folded, then restored by `seed-guest` |
| `cd frontend && npm run build` | exit 0; Pretendard's three `@font-face` blocks land in the `CatalogPage` CSS chunk only, and the three `.woff2` subsets are emitted to `dist/fonts/` |
| `node scripts/catalog/e2e/catalog_e2e.cjs` | **105/105** on `CATALOG_SOURCE=local`; **75/75** previously on `CATALOG_SOURCE=s3` (MinIO with real SigV4 presigning) |
| `node scripts/catalog/e2e/catalog_visual.cjs` | **54/54** — see below |

`catalog_visual.cjs` is the measurement half of the 2026-08 design pass. It asserts, rather
than eyeballs: Pretendard loaded and computed at 200–800 with at least five distinct weights
in use; `.cat-figure` extralight at a display size and always one line; `.cat-label` semibold
and tracked; mono confined to machine strings; `scrollWidth <= clientWidth` at 360 / 768 /
1440; every mouse target over WCAG 2.5.8 AA's 24 px and every target over 44 px under an
emulated coarse pointer; the corpus CN + HK only and every clip stereo + tactile; no filter
chip that selects the whole corpus; the logo decoded in the top bar; a 44 px sign-out; and
that Pretendard has NOT leaked onto the marketing site.

Five of those assertions were added by the follow-up pass and each one guards a defect a
screenshot had already been taken of and nobody had spotted:

- **`v4b`** every card carries the `STEREO · TACTILE` mark and the grid says "Mono" nowhere.
  The card used to badge only the anomaly, so the grid never once stated the product — and a
  record with a missing `capture` stamped "Mono" on a card.
- **`v4c`** every card in a grid row puts its signal strip on ONE baseline. An unreserved
  two-line title clamp and a census that wrapped only on some cards moved the strip ~30 px
  between neighbours, on every row of a thirty-clip page.
- **`v4d` / `v4e`** the filter bar actually pins, and its elevation state tracks the pin line
  rather than `y = 0`. It was `position: sticky` inside a containing block exactly as tall as
  itself, so it had zero travel and scrolled away like static content.
- **`v4f`** every read-text rule on paper clears 7:1. The grid held itself to that with
  `--cat-ink-2` (7.6:1) while the header and the modal used `--muted` (6.25:1) for the same
  rank of copy.

`catalog_e2e.cjs` gained `c3b`/`c3c` (Tab and Shift+Tab cannot leave the clip modal from the
default Video tab — the roving-tabindex tab strip had broken the focus trap for every clip)
and `e6`–`e9` (the open evaluation clip: its rights are granted end to end, a guest can
actually fetch its package, timestamps, one hand and its geometry, everything the exemption
does not name is still null, and the record says so itself).

Screenshots at 360 / 768 / 1440 px are in [`screenshots/`](screenshots/): `header-*`,
`filters-*`, `chart-*` and full-page `page-*` from the visual harness, `grid-*` and
`modal-*-<tab>` from the acceptance harness. The runbook is [`DEPLOY.md`](DEPLOY.md).

Three bugs the end-to-end pass found and fixed, none of which any unit test could have seen:

1. **The header and chart rendered minutes as hours** — a 60x overstatement. `18.3 min`
   displayed as `0.31 h`. `TaskDistribution` mapped any non-`clips` unit to hours and
   `CollectionHeader` ignored `duration_unit` entirely.
2. **Hovering the selected tab erased its label.** `.cat-d-tab:hover:not(.is-off)` outscores
   `.cat-d-tab.is-on` by one class, so it repainted the label `var(--ink)` on the
   `var(--ink)` pill — and the pointer is always resting on the tab you just clicked.
3. **The IMU strip never scrolled.** The zero-specificity media reset
   (`:where(.cat-root) :where(img, video, svg) { max-width: 100% }`) clamped a deliberately
   4967 px-wide SVG to its 1101 px container. With a matching `viewBox` that scaled the whole
   coordinate space down, so 41 s of signal collapsed into the left third of a plot whose time
   axis still spanned the full width.

---

## 10. Known gaps

Real, understood, and not fixed. Nothing here blocks the ship.

**The category chart is flat, and that is the corpus, not the chart.** `benchmark.categories[]`
gives ten bars of three clips each, but the fixture apportions clips evenly, so every bar lands
between 1.80 and 2.03 minutes — a 13 % spread. The form rule the chart applies is clips-per-bar
(three earns bars; the 1.2-per-bar task fold falls back to a table), not magnitude spread, so it
draws them. The note under the plot now states both ratios out loud, so a reader is told the
shape rather than left to infer it from ten near-identical slabs. A real corpus will not be
apportioned this way. If a delivered corpus ever is, the honest response is a spread test on top
of the clips-per-bar one, not a taller y axis.

**The RIGHTS facet is six rows tall while its three neighbours are one.** The filter bar's
qualifier groups are one per grid column now (they used to balance by height and leave a whole
empty fourth column at 1440), and Rights has eleven buckets against Country's two. The result is
a tall column beside three short ones. Options if it starts to grate: collapse Rights to four
visible buckets, or let a group over N buckets span two tracks — both are content-keyed rules
and neither was worth the fragility today.

**Full-page screenshots show blank cards below the fold.** `.cat-card` carries
`content-visibility: auto`, so a card that has never been scrolled into view has no rendered
subtree for Chrome's full-page capture to composite. Real scrolling paints them — the acceptance
harness walks the whole grid and asserts all 31 `<img>` decode. Read `page-*.png` for layout,
not for card content.

**The masthead display line is three lines at 1440 for this collection's name.** `nervous-1`
was one line at `--cat-fs-4xl`; `EGO-TAC evaluation sample` is three, which pushes the SYNTHETIC
banner down and leaves the right column short of the left. It is legible and it does not
overflow, so it was left alone rather than clamped to a size that would be wrong for the short
name. A `text-wrap: balance` plus a name-length-aware step down is the fix if a longer name ever
ships.

**The burned-in camera labels in the fixture video duplicate the modal's own.** `LEFT CAMERA` /
`RIGHT CAMERA` appear twice on the Video tab: once as the modal's chrome and once rendered into
the synthetic frames by `generate_fixtures.py`. Real footage carries no such overlay, so this is
fixture noise, not a UI defect, and the chrome labels are the ones that must stay.

**The tactile map tells a guest the geometry sidecar does not exist.** `media.tactile.layout`
is withheld from preview roles on every clip but the open evaluation one, and `TactileTab` reports that as *"No per-taxel geometry
sidecar (`media.tactile.layout`), so the grid assumes the plain row-major rule"*. It is honest
about the consequence — it says to treat the arrangement as unverified — but it reads as
"absent" when the truth is "not shared at this access level". The clip payload carries
`access.withheld`, so the component could say so precisely. Copy change, one component.

**`media.docs.*` is readable by the guest, and now linked.** README, DATASHEET, LICENSE,
SYNC_PROTOCOL and checksums.sha256 are presigned for preview roles. This is a deliberate
reading of "the guest sees the encoded mp4 and the metadata": the withhold list names
originals, npz, raw csv and the archive, and per-clip documentation is what a buyer's
acceptance pipeline reads first. The Metadata tab has a Documentation block linking all five
— a deliberate grant that nothing surfaced was a grant with no effect. If you disagree it is
one entry in `WITHHELD_CLIP` in `backend/app/core/catalog_redact.py`.

**`privacy.redaction.record_url` is readable by the guest too.** It used to be withheld. A
redaction audit record is a RIGHTS artefact, not payload: withholding it withholds the only
evidence for the claim it exists to support, and counsel asks for it in their first reply.

**S3 mode is proven against MinIO, not AWS.** The driver, SigV4 presigning, content types,
Range playback and the private-bucket 403 were all exercised for real, but against a local
S3-compatible endpoint. Two things only real AWS can confirm: that `provision_s3.sh`'s CORS
rule admits the production origin (MinIO does not implement `PutBucketCors`, so the smoke test
ran permissive), and clock skew on presign expiry. `DEPLOY.md` §9 is the check.

**The prospect-facing copy has not been reviewed by a human.** The collection description,
`split_policy`, the licence summary and the preview notice all render verbatim from
`collection.toml` and the redaction layer. Nobody has read them as a *sales* document.

One class of inaccuracy is now caught by the build rather than by a reader: `validate`
FAILS a bundle whose collection or per-clip copy claims frame-level synchronisation while
the measured `sync.maximum_alignment_error_ms` says otherwise. That rule exists because the
copy did exactly that — "a contact event can be located to about one video frame", against a
measured 56.74 ms max with 20 of 29 clips over one 30 fps frame. The measured aggregate is
now a header stat tile (`totals.sync_max_alignment_error_ms`), so the number and the sentence
are on the same screen. The guard is narrow: it matches the shape of a precision CLAIM, never
a statement of the measured figure.

**`npx playwright test` still has 15 pre-existing failures** in `products-v2.spec.js` and
`products-reserve.spec.js`, on `origin/main`, unrelated to the catalog: they assert an
`a[href="/eye2-main-frame.stl"]` and a `#products-reserve-email` field that exist nowhere in
`src/`. The catalog harness is a separate entry point and does not touch those pages.

**`ruff check backend/` reports 6 errors**, all pre-existing on `origin/main` in
`tests/test_admin_leads.py`, `tests/test_cli.py` and `tests/test_password_hashing.py` — files
this change does not touch. Everything added or edited here is clean.
