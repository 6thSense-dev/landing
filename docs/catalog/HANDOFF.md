# nervous-1 catalog — handoff

**Last updated:** 2026-08-24 · **Branch:** `feat/data-catalog` (off `origin/main` @ `cd998b0`)
**Status:** built, tested, running locally against real S3. **Nothing is committed. Nothing is deployed.**

Read this first when you come back. It says what exists, what is decided, what is waiting on
you, and exactly what to do when the real clips are ready.

---

## 1. TL;DR

| | |
|---|---|
| What it is | A buyer-facing data catalog behind `6thsense.dev/login`. Guest credential → read-only browse of clips: stereo video, IMU, tactile, segment captions, calibration, QA. |
| Collection name | **nervous-1** |
| Where the code is | `feat/data-catalog` in the **landing** repo. Worktree: `~/conductor/workspaces/landing/catalog` |
| Where the media is | Catalog documents/previews: `s3://6thsense-catalog/v2/`; packages: `s3://6thsense-processed/imported/2026-08-24_nervous-1/` (us-west-2, AWS account **194680606079**) |
| What is live | Nothing. Production `6thsense.dev` still runs `main`, which has none of this. |
| Corpus today | 30 **synthetic** clips (ffmpeg colour bars), 30–45 s each, ~19 min total, CN + HK, all stereo + tactile |
| Blocking the launch | Real clips → then a production deploy → then 4 decisions in §6 |

---

## 2. Where everything is

```
~/conductor/workspaces/landing/catalog          git worktree, branch feat/data-catalog
├── frontend/src/catalog/                       the catalog UI (18 files, code-split chunk)
│   ├── CatalogPage.jsx   CatalogTopBar.jsx   CollectionHeader.jsx
│   ├── FilterBar.jsx     CatalogGrid.jsx     ClipCard.jsx
│   ├── ClipDetail.jsx    tabs/*.jsx          TaskDistribution.jsx
│   ├── useCatalog.js     format.js
│   └── catalog.css + parts.{header,grid,detail,chart}.css
├── frontend/public/fonts/PretendardVariable.subset.{71,79,91}.woff2
├── backend/app/api/routes/catalog.py           the API
├── backend/app/core/catalog_{store,redact}.py  S3 + local drivers, role redaction
├── backend/migrations/versions/0007_add_guest_role.py
├── scripts/catalog/
│   ├── dev_local.sh        ← run the whole thing locally
│   ├── provision_s3.sh     ← already run; idempotent
│   ├── upload_bundle.py    ← bundle → S3
│   ├── ingest/             ← takes → bundle
│   ├── fixtures/           ← synthetic corpus generator
│   ├── schema/             ← the two JSON Schemas (the contract)
│   ├── tests/              ← 136 tests
│   ├── e2e/                ← catalog_e2e.cjs (105 checks), catalog_visual.cjs (54)
│   ├── .env.local          ← S3 reader key. GITIGNORED, 0600. Not in git.
│   └── sample/             ← generated corpus + bundle. GITIGNORED (273 MB).
└── docs/catalog/
    ├── HANDOFF.md          ← this file
    ├── INTAKE.md           ← what a capture operator must hand over  ★ read before encoding
    ├── CONTRACT.md         ← field-by-field spec of both schemas
    ├── DEPLOY.md           ← the ordered production runbook
    ├── README.md           ← the pipeline in one page
    └── screenshots/        ← 39 PNGs at 360 / 768 / 1440
```

**Do not touch** `~/conductor/workspaces/landing/gwangju` — a different workspace on
`add-eye-camera-products`.

---

## 3. What works today — verified, not assumed

Run it: `make -C scripts/catalog dev` → <http://localhost:5173/login>. The script prints the
guest password it seeded (default `local-dev-guest`; override with `CATALOG_GUEST_PASSWORD`
or a line in the gitignored `scripts/catalog/.env.local`).

| Check | Evidence |
|---|---|
| Backend suite | **289 passed** |
| Catalog tooling suite | **136 passed** |
| Bundle validation | **17/17 rows PASS** |
| End-to-end (headless) | **105/105** |
| Visual assertions | **54/54** |
| Frontend build | exit 0, catalog is its own lazy chunk |
| Video from real S3 | `readyState 4`, 1920 px, `currentTime 1.79`, playing |
| Range requests | `206 Partial Content`, `Content-Range: bytes 0-99999/1871773` |
| Guest redaction over S3 | `media.tactile.{left,right,layout}` → `null`, and **no presigned URL is minted** for them |
| Reader key least privilege | `PutObject` / `DeleteObject` / `ListBucket` → all `AccessDenied` |
| Responsive | 0 horizontal overflow at 360 / 768 / 1440; 0 console errors |

### AWS, as provisioned

```
bucket   s3://6thsense-catalog-media   us-west-2   account 194680606079
         public access blocked · AES256 · versioned · CORS for Range · 30-day noncurrent expiry
         1084 objects, 273 MB under v1/  (the synthetic corpus)

IAM      catalog-media          read+write   → ~/.aws/credentials [catalog-upload]   workstation ONLY
         catalog-media-reader   GetObject    → scripts/catalog/.env.local + Railway   the app
```

The account is **not** 537124957922, which holds the firmware bucket
`6thsense-prod-camera-updates`. See §6.4.

---

## 4. ★ The next thing: uploading real clips

This is the path you came back for.

### 4.1 Encode and lay out the takes

Read **[`INTAKE.md`](./INTAKE.md)** — it has the copy-pasteable directory tree and the exact
`take.toml` fields. The short version, one directory per clip:

```
takes/
├── collection.toml
└── <take_id>/
    ├── take.toml                       title, category, country (CN|HK), rights, privacy
    ├── video/stereo_upright.mp4        [left | right] side-by-side, the web mp4
    ├── video/frame_times.csv           frame_idx,host_us
    ├── tactile/{left,right}.npz
    ├── imu/imu.csv                     t_s,ax,ay,az,gx,gy,gz
    ├── segcap/segments.csv             t0_s,t1_s,label,verb,objects,description
    └── calibration/calibration.json
```

**The directory name becomes the clip id.** Rename later and you break every link a buyer holds.

Three things that will bite:
- `rights` has **no "unknown"**. If legal review hasn't happened, the honest value is `denied`,
  and the ingest will fail a clip that claims `granted` with no consent record behind it.
- `country` must be `CN` or `HK`, uppercase. A code with no display label fails the build.
- `operator` must be a pseudonym. Never a name, email or initials.

### 4.2 Build and check

```bash
cd ~/conductor/workspaces/landing/catalog/scripts/catalog

python3 -m ingest.catalog_ingest build \
  --takes <your-takes-dir> --out /tmp/nervous1-real --posters --previews
python3 -m ingest.catalog_ingest validate --out /tmp/nervous1-real
cat /tmp/nervous1-real/INGEST_REPORT.md     # read this — it names every skipped take and why
```

`validate` must be 17/17. Anything that fails names the take and the reason.

**Expect some clips to be quarantined.** The QA gate drops takes whose measured inter-stream
skew exceeds the acceptance bound. That is the gate working — the alternative is shipping a
clip whose tactile and video disagree about when contact happened. The report lists them.

### 4.3 Look at it before anyone else does

```bash
CATALOG_LOCAL_DIR=/tmp/nervous1-real ./scripts/catalog/dev_local.sh
```

Check: posters look right, video plays, the Tactile tab shows real contact, Segcap segments
line up with the video, and the header numbers are ones you'd defend to a buyer.

### 4.4 Upload

```bash
AWS_PROFILE=catalog-upload python3 scripts/catalog/upload_bundle.py \
  --bundle /tmp/nervous1-real --prefix v2/ --dry-run
```

**No `--allow-synthetic` this time.** Real takes declare `media_class: recorded`, the
collection rolls up to `provenance_class: recorded`, the guard passes on its own, and the
SYNTHETIC banner disappears from the page by itself. If the guard still fires, a take is
mis-declared — fix the take, don't add the flag.

Use **`--prefix v2/`**, not `v1/`. Prefixes are immutable versions: upload to `v2/`, verify,
then flip `CATALOG_S3_PREFIX` to switch atomically. Nobody browsing `v1/` sees a half-uploaded
`v2/`. Keep `v1/` until you're sure, then delete it.

```bash
AWS_PROFILE=catalog-upload python3 scripts/catalog/upload_bundle.py \
  --bundle /tmp/nervous1-real --prefix v2/
```

### 4.5 Prove the real path

```bash
# point .env.local at v2/, then:
./scripts/catalog/dev_local.sh --s3
```

Same site, real bucket, real presigned URLs. If a video plays here, production is env vars.

---

## 5. Deploying to 6thsense.dev

The domain is **already wired** — `6thsense.dev` and the API at
`https://api-production-0649.up.railway.app` are live on Railway. There is no DNS work. What's
missing is that production runs `main`, and `main` doesn't have the catalog:

```
prod /api/catalog                       → 404   (router not deployed)
prod login {"identifier":"guest"}       → 422   {"email":"Field required"}
```

Ordered runbook is in **[`DEPLOY.md`](./DEPLOY.md)**. The shape:

1. **Railway → Postgres → snapshot.** Do this first. Step 5 does live DDL on the `users` table.
2. Commit + push `feat/data-catalog`, open a PR.
3. Merge to `main`.
4. Set on the **backend** service:
   ```
   CATALOG_SOURCE=s3
   CATALOG_S3_BUCKET=6thsense-catalog
   CATALOG_S3_REGION=us-west-2
   CATALOG_S3_PREFIX=v2/
   CATALOG_PACKAGE_BUCKET=6thsense-processed
   CATALOG_PACKAGE_PREFIX=imported/2026-08-24_nervous-1/
   CATALOG_AWS_ACCESS_KEY_ID=<catalog-media-reader>
   CATALOG_AWS_SECRET_ACCESS_KEY=<its secret>
   CATALOG_PRESIGN_TTL=900
   CATALOG_GUEST_PASSWORD=<see §6.1>
   ```
5. Deploy runs `alembic upgrade head` automatically (`backend/railway.toml` `startCommand`),
   which applies `0007` and adds `guest` to the `users_role_check` constraint.
6. **Seed the account** — the migration creates the *role*, not the *user*:
   ```
   railway run --service <backend> python -m app.cli seed-guest
   ```
   This is the step everyone forgets.
7. Verify: `/api/catalog` → **401** (not 404) · log in as guest · a video plays ·
   **log in as yourself** — the auth change touches every role's login path.

**Rollback:** revert the merge and redeploy. The DB migration has a working `downgrade()`, but
the snapshot from step 1 is the real safety net.

---

## 6. Decisions waiting on you

### 6.1 The guest password
**Not yet chosen.** The repo (`alnosarus/6thSense`) is **public**, so the production value is
never a literal anywhere in it — it lives only in Railway's `CATALOG_GUEST_PASSWORD`. The
value used during development was written into `DEPLOY.md` and four other files by an earlier
pass; it was purged, and `git log -S` confirms it never entered history — but it has lived in
a working tree on disk, so treat it as burned.

**Pick one before the branch is pushed.** Set it as `CATALOG_GUEST_PASSWORD` on the Railway
backend service and run `seed-guest` (§5 step 6). Minimum 8 characters — `cli.py` enforces a
12-character floor for every other account and makes a narrow, documented exception for this
one, because it is a shared read-only demo credential and not a login to anything.

### 6.2 Synthetic vs real before going live
Deploying today puts colour bars at a buyer-facing URL — honestly bannered, but still colour
bars. **Recommendation: wait for the real clips.** If you want it live sooner as a plumbing
check, that's defensible, just decide it deliberately.

### 6.3 How the corpus is described
30 clips × 30–45 s ≈ **19 minutes**, two adjacent cities, five operators, four rigs. That is a
**pilot sample**, and the page says so. Two things to hold the line on:
- Nothing gets denominated in *hours*. The ingest picks minutes below a 2-hour total.
- "Countries: 2" over China and Hong Kong is technically true and reads as more geographic
  diversity than we have. The header says `Locale (declared)`; keep it honest.

### 6.4 Which AWS account owns this
The bucket is in **194680606079**; the firmware bucket is in **537124957922**. If 194680606079
is your personal account, this is infrastructure only you can administer. Worth raising with
Ronak — moving it later means re-creating the bucket and re-uploading, which is cheap now and
annoying once a buyer holds links.

---

## 7. Gotchas that will waste your time

**`localhost` ≠ `127.0.0.1` for cookies.** The session cookie is `SameSite=Lax` and Chromium
treats those as *different sites*. Serve the page from one and the API from the other and login
appears to succeed while every catalog request 401s, silently. `dev_local.sh` uses one hostname
for both — don't "fix" it.

**A missing S3 object reads as 503, not 404.** The reader deliberately lacks `s3:ListBucket`,
so S3 returns 403 for absent keys (it refuses to confirm existence — that's what we want), and
the store maps that to `CatalogUnavailable`. A wrong `CATALOG_S3_PREFIX` or an un-uploaded
bundle presents as *"service unavailable"*, not *"not found"*.

**Presigned URLs must use the regional virtual-hosted host.** botocore signs against the
*global* `<bucket>.s3.amazonaws.com` even when the client endpoint is regional; S3 307s that to
another host, SigV4 binds the signature to Host, and **all media 403s**. Fixed with
`Config(s3={"addressing_style": "virtual"})` in `catalog_store._build_client`. Measured:
global → 403, virtual → 200. Guarded by
`test_presigned_urls_use_the_regional_virtual_hosted_endpoint`, which was confirmed to fail
with the fix removed. **Unit tests never caught this** — it only surfaced by fetching a real
presigned URL from the real bucket. Keep doing the S3 dry run.

**Renaming the collection is two files.** The ingest reads `sample/takes/collection.yaml`,
which is *generated from* `fixtures/collection.toml`. Editing the TOML alone does nothing until
you re-run `make fixtures` (re-encodes 30 videos, ~10 min) or patch the yaml and re-run
`make ingest`.

**`make fixtures` re-encodes everything.** ~10 minutes. Use `make ingest` alone when only
metadata changed.

---

## 8. Known gaps

- **Nothing is committed.** 128 new files, 19 modified, sitting in the worktree.
- The **task-distribution chart is a picket fence** on the synthetic corpus — ten category bars
  between 1.80 and 2.03 min, because the generator spreads clips evenly. Real data will vary.
  If it still looks flat with real clips, the chart is the wrong visual and should be cut.
- The **sticky filter panel is too tall to be sticky** — six rows, ~280 px, and it covers a card
  thumbnail on scroll. It should collapse to search + active filters once pinned.
- **Three stacked notice banners** in the masthead. All three earned their place; they could be
  one block with three lines.
- **No comparison datasets in the chart.** We have no per-task hour breakdowns for Ego4D /
  EgoDex / Xperience-10M / Egocentric-100K, and inventing numbers for a buyer who knows the real
  ones is a credibility loss. `collection.toml` has a `[[benchmark.comparison]]` slot that the
  ingest refuses to render without a `source_url`. Fill it if you get sourced figures.
- **IMU is not on the reference clock.** It ships with the package but is not placed on the
  video timeline; the UI says so on the IMU tab and in the sync table. Fixing that is a capture
  change, not a catalog change.
- **CSP is Report-Only** and hardcodes the S3 origin in `frontend/Caddyfile`. If the bucket or
  region ever changes, that string must change with it.

---

## 9. Command reference

```bash
cd ~/conductor/workspaces/landing/catalog

# run the whole product locally (Postgres + API + site), local disk
make -C scripts/catalog dev
./scripts/catalog/dev_local.sh --rebuild        # regenerate the corpus first
./scripts/catalog/dev_local.sh --with-gaps      # missing-modality corpus, for UI edge paths
./scripts/catalog/dev_local.sh --s3             # same site, real S3 bucket
make -C scripts/catalog dev-stop                # clean up after a hard kill

# data pipeline
make -C scripts/catalog fixtures ingest validate stats

# upload  (writer identity, workstation only)
AWS_PROFILE=catalog-upload python3 scripts/catalog/upload_bundle.py \
  --bundle <dir> --prefix v2/ [--dry-run]

# tests
cd backend && python3 -m pytest -q                      # 289
python3 -m pytest scripts/catalog/tests -q              # 136
node scripts/catalog/e2e/catalog_e2e.cjs                # 105  (needs CATALOG_E2E_PW)
node scripts/catalog/e2e/catalog_visual.cjs             # 54
cd frontend && npm run build
```

**Local sign-in:** user `guest`; the password is whatever `dev_local.sh` prints on startup.

---

## 10. If you're picking this up cold

Read in this order: this file → [`INTAKE.md`](./INTAKE.md) (what to hand the pipeline) →
[`README.md`](./README.md) (how the pipeline works) → [`CONTRACT.md`](./CONTRACT.md) (the field
spec) → [`DEPLOY.md`](./DEPLOY.md) (shipping it).

The one idea that explains the rest: **the bundle is the contract.** Two JSON Schemas define
`catalog.json` and each `clips/<id>.json`. The ingest emits nothing outside them; the UI reads
nothing outside them; every asset URL is relative, so the same bundle works on a laptop, on S3
behind presigned URLs, and behind the portal — the host rewrites the base, the manifest never
moves. A value that cannot be measured is `null`, rendered as an em-dash, and named in
`INGEST_REPORT.md`.
