## Verdict: REJECT as drafted

The routing core is sound and well defended — I could not break `sign()`. The blockers are in the two things a human actually executes: the rollout runbook prescribes the **wrong bucket and wrong prefix**, and the documented **rollback path breaks all package media**. Fix those plus the CSP and this is a merge.

---

## [B] blockers

**[B] confidence 9/10 — `/tmp/landing-rev/tasks/CATALOG-TIER-BUCKETS-2026-09-03.md:12-18`, `docs/catalog/README.md:174-178`**
WHAT: The runbook tells the operator to set `CATALOG_S3_BUCKET=6thsense-catalog-media` and `CATALOG_S3_PREFIX=v1/`. The corpus this PR exists to serve is at `s3://6thsense-catalog/v2/`.
BREAK: Apply the runbook verbatim -> (a) the live catalog swaps from the 10-clip nervous-1 corpus to `6thsense-catalog-media/v1/`, a 30-clip 2025 corpus (verified: `ego-20251130-000121-16a260`, `ego-20251210-165921-17c902`, …); (b) every v1 clip doc references `media/ego-20251130-.../video/stereo_upright.mp4` (verified), which the new code presigns as `s3://6thsense-processed/imported/2026-08-24_nervous-1/ego-20251130-000121-16a260/...` — verified absent. `catalog-media-ro` has no `s3:ListBucket`, so S3 answers a missing key with **403 AccessDenied XML**, not 404. Buyer sees every download and full-res video fail.
FIX: `CATALOG_S3_BUCKET=6thsense-catalog`, `CATALOG_S3_PREFIX=v2/` in both the runbook and the README block.

**[B] confidence 9/10 — `tasks/CATALOG-TIER-BUCKETS-2026-09-03.md:36-40` ("Roll back")**
WHAT: "Redeploy the preceding application revision… the package variables may remain recorded… because the preceding revision ignores them." It never says to revert `CATALOG_S3_BUCKET`/`PREFIX`.
BREAK: Rollback happens *after* the env is flipped to `6thsense-catalog`. Old code has no package tier, so it signs `media/...` as `s3://6thsense-catalog/v2/media/...`. Verified: `6thsense-catalog/v2/` has no `media/` prefix at all. Every package asset 403s — on the rollback path, mid-incident, while the runbook says you are safe.
FIX: rollback = revert env to `6thsense-catalog-media` + `v2/` **first** (that bucket still has `v2/media/` and `v2/archives/`, verified), then redeploy the previous revision.

---

## [M] findings

**[M] confidence 9/10 — `frontend/Caddyfile:59` (not touched by this PR)**
WHAT: `img-src`/`media-src`/`connect-src` allowlist only `6thsense-catalog-media.s3[.us-west-2].amazonaws.com`. Post-flip the browser fetches from `6thsense-catalog.s3.us-west-2...` and `6thsense-processed.s3.us-west-2...`.
BREAK: Header is `Content-Security-Policy-Report-Only`, so nothing breaks today — but every poster/preview/video now emits a violation report, and the Caddyfile's own comment states the consequence: "the day someone flips this header to enforcing every clip in the catalog goes blank at once." `catalog_store.py:337` still claims the signed URL "produces exactly the origin the Caddyfile CSP allowlists" — now false for both tiers.
FIX: add both new hosts (regional + global forms) to all three directives in the same PR.

**[M] confidence 8/10 — `backend/app/core/config.py:180-190`**
WHAT: `package_bucket`/`package_prefix` default to `6thsense-processed` / `imported/2026-08-24_nervous-1/` instead of to the catalog tier. Code-only deploy is therefore **not** a no-op.
BREAK: The instant the new code deploys with the current env untouched, every `media/` path stops resolving to `6thsense-catalog-media/v2/media/` and starts resolving to a cohort string baked into application source. It happens to work (same 10 clip ids; live `catalog-media-ro` policy does grant `6thsense-processed/imported/*` — I read it) but it is an unrequested behaviour change on a deploy that changed no configuration, and the next import silently mis-routes until someone edits Python.
FIX: default `package_bucket` to `bucket` and `package_prefix` to `f"{prefix}media/"`. That makes "deploy code first" genuinely safe.

**[M] confidence 8/10 — `backend/app/api/routes/catalog.py:195-235` + `catalog_store.py:257-265`**
WHAT: No readback or health signal for the new tier. `probe()` only reads the manifest; staff `/health` returns `bucket`/`prefix`/`region` and nothing about the package tier.
BREAK: Presigning is offline HMAC, so a wrong `CATALOG_PACKAGE_*` or lost IAM on processed never surfaces server-side. `/api/catalog/health` reports `ok: true`, the manifest and posters load, and every full-package download 403s in the buyer's browser. The runbook's step 1 can pass while the thing this PR adds is broken.
FIX: add `package_bucket`/`package_prefix` to the staff health body; ideally one `head_object` against a known package key.

**[M] confidence 8/10 — `catalog_redact.py:163` vs `upload_bundle.py:292-306` vs `catalog_store.py:371-376`**
WHAT: `archives/` is now unroutable *and* unuploadable, while `("media","archive","url")` is still a signed field.
BREAK: A bundle that populates `media.archive.url = "archives/<id>.tar.gz"` presigns `6thsense-catalog/v2/archives/...`. `_package_tier_guard` now refuses `archives/` into the catalog tier, so nothing is permitted to put it there; the real archives live at `imported/<cohort>/_archives/<id>.tar.gz` (verified) and `sign()` only reroutes `media/`. Dormant today — `media.archive` is `null` in all 10 clip docs (verified) — so latent, not live. No test covers the field.
FIX: route `archives/` to the package tier as `_archives/`, or drop the field from the redact allowlist.

---

## [L] findings

**[L] 8/10 — `config.py:166-170` + `:180`.** The new `bool(self.package_bucket)` term in `configured` is near-dead: `os.environ.get(...) or "6thsense-processed"` runs *before* `.strip()`, so unset and empty-string both yield the default. Probe-verified: `""` -> `'6thsense-processed'`, `configured=True`; only `"   "` -> `''`, `configured=False`. Untested branch. The task doc claims "an empty package bucket" was attacked; the only new config test asserting `configured is False` (`test_catalog_store.py:57-65`) does it via half-credentials, and its name `test_package_tier_reuses_the_catalog_credential_pair` describes an assertion it does not make.

**[L] 8/10 — `config.py:185-190`.** `CATALOG_PACKAGE_PREFIX` set to blank yields `""` (the `os.environ.get(name, default)` form only defaults when *absent*). Probe-verified: `sign("media/other-cohort/secret.zip")` -> `6thsense-processed/other-cohort/secret.zip`, i.e. the whole bucket, confined only by IAM (`imported/*` + `packages/*`), not by code — and `configured` stays `True`. Realistic form: operator blanks the var to "unset" it and gets a silent 403 on every package asset with a green health check.

**[L] 6/10 — `catalog_store.py:370-385`.** No `CATALOG_PACKAGE_REGION`; the package bucket is presigned by a client pinned to `cfg.region`. All three buckets are `us-west-2` today (verified via `get-bucket-location`), so it holds — but the file's own comment explains SigV4 binds the signature to the host, so a cross-region package bucket would 403 with no config escape.

**[L] 7/10 — `catalog_store.py:475-486`.** The `_signature_of` addition **survives mutation**: deleting both `cfg.package_bucket` and `cfg.package_prefix` leaves `test_catalog_store.py` at 55 passed. The task doc's claim that "package configuration participates in store-cache invalidation" is asserted, not tested.

**[L] 7/10 — docs not updated.** `docs/catalog/DEPLOY.md:224` and `:342` still give literal verification URLs on `6thsense-catalog-media/v1/...`, including `v1/media/<id>/tactile/left.npz` — exactly the path this PR moves. README was updated; DEPLOY.md and HANDOFF.md were not. Separately, `README.md:218`'s table documents `GET /api/catalog/media/{path}` which does not exist (only `/health`, `""`, `/`, `/clips/{id}` and the local streaming route) — pre-existing, but the diff edits that table without fixing it.

**SMELL — `scripts/catalog/upload_bundle.py:292-296`.** `path.relative_to(bundle)` is called unguarded (and twice per file). Safe from `main()` because every path comes from `bundle.rglob`, but a caller passing a path outside `bundle` gets a `ValueError` traceback instead of exit 2, and `parts[0]` would `IndexError` on a path equal to `bundle`.

**Nits.** The guard also blocks `--dry-run`, so you cannot dry-run a legacy bundle to see what would move. The `media/` match is case-sensitive, so `Media/...` silently lands on the catalog tier. The stripped media path gets 33 segments of `MAX_SEGMENTS` budget vs 32 for catalog paths.

---

## Verified (what I tried to break and it held)

**Routing on the real corpus — held.** Simulated `sign()` with the *new* env over all 10 clip docs from `s3://6thsense-catalog/v2/clips/`: **459 unique bucket+key pairs, 0 misroutes, 0 `head_object` failures.** Covered poster, preview, detail, `media.video.*`, `media.imu.{csv,f32}`, `media.tactile.{left,right,layout,preview_png[]}`, `media.calibration.*`, `media.docs.*`, `rights.license_url`, `imu_preview.sidecar.url`, `tactile_preview.peak_series.sidecar.url`, `tactile_preview.frames[].png`, all 36 `package_contents[].url`. The subtle split is handled correctly: `media.imu.f32` = `imu/<id>.f32` -> catalog tier, `media.imu.csv` = `media/<id>/imu/imu.csv` -> processed tier; `media/<id>/preview/*.png` -> processed while `stills/<id>/*.png` -> catalog. `segments` is `[]` and `collection.sample_archive` is `null`, so nothing there to sign.

**Traversal on both tiers — held.** 26 hostile strings + 4 non-str, all `UnsafeAssetPath`, zero presigns: `media/../../x`, `media//x`, `media/`, `media/../x`, `media/a/../other/x`, `media/./x`, `media/.hidden/x`, `media/%2e%2e/x`, `media/x%2f..%2fy`, `/media/x`, `media/x/`, `"  media/x"`, `"media/x "`, `media\/x`, `https://evil.example/media/x`, `media/../../../../etc/passwd`, `""`, `.`, `..`, 41 segments, 600 chars, NUL, U+2024 one-dot-leader, plus `None`/`int`/`bytes`/`dict`. The three that do sign — `media`, `medias/x`, `MEDIA/x` — correctly go to the catalog tier. Stripping `media/` *before* validation is safe because `resolve_key` rejects empty and dot segments unconditionally.

**Credentials — held.** Single `_client()`; the package presign uses the same `CATALOG_AWS_*` pair, asserted with a real botocore SigV4 URL in `test_presigning_uses_the_catalog_key_and_not_the_ambient_one` (`AKIACATALOGREADER00000` in both hosts). Half-configured refusal still fires (`configured=False`).

**LocalCatalogStore — unchanged.** No package tier in local mode; `media/...` still served from the bundle dir via HMAC URLs. `CATALOG_SOURCE=local` bundles containing `media/` keep working.

**Tests.** `backend/tests/test_catalog_store.py` + `test_catalog_upload_bundle.py`: **59 passed** (venv from `requirements-backend-dev.txt`). Full suite: `143 passed, 157 errors` — all errors are `docker.errors.DockerException` from testcontainers/Postgres, i.e. environment, not code. `test_catalog_api.py` is docker-gated: `1 passed, 37 errors` -> **unverified: sandbox-blocked**.

**Mutations re-planted.** M1 `media/` -> `self.settings.bucket`: **2 failures** (`test_s3_signs_media_against_the_processed_package_tier`, `test_presigning_uses_the_catalog_key_and_not_the_ambient_one`). M2 drop `.removeprefix("media/")`: **2 failures**. M3 package key built with catalog `prefix`: **2 failures**. M4 drop `package_bucket`/`package_prefix` from `_signature_of`: **survives, 55 passed**. Source restored after each; `git diff --stat` clean.

**Diff hygiene — clean.** 9 files, all inside the allowlist, `--diff-filter=D` empty, zero unrelated deletions.

**Theory that fell.** My best shot was privilege escalation: the new `package_prefix` contains 13 clip dirs plus `_archives/*.tar.gz` while only 10 clips are published, so it widens what a signable path could reach versus the old `catalog-media/v2/media/` (published clips only). But there is **no route that signs a client-supplied path** in the S3 driver — only `/health`, `""`, `/`, `/clips/{id}`. Not reachable. The `_published_ids` invariant ("if its id is not in catalog.json, it does not exist") simply loses its storage-layer backstop for the package tier.

---

## Safe rollout order

1. **Fix the runbook first**: `CATALOG_S3_BUCKET=6thsense-catalog`, `CATALOG_S3_PREFIX=v2/`, `CATALOG_PACKAGE_BUCKET=6thsense-processed`, `CATALOG_PACKAGE_PREFIX=imported/2026-08-24_nervous-1/`. Do not deploy against the doc as written.
2. **Frontend first**: add `6thsense-catalog.s3.us-west-2.amazonaws.com` and `6thsense-processed.s3.us-west-2.amazonaws.com` (plus global forms) to `img-src`/`media-src`/`connect-src` in `frontend/Caddyfile` and ship. No-op today (Report-Only), but the enforcing flip must never be what discovers this.
3. **Backend code, env unchanged.** Confirm `/api/catalog` still serves and one `media/` URL now points at processed. This is where the default-driven tier switch (finding 6) is exercised; it works only because IAM already grants `imported/*`. If you fix finding 6 first, this step is a true no-op.
4. **Flip all four env vars in one Railway update**, then redeploy. Never flip `CATALOG_S3_BUCKET`/`PREFIX` without the code; never flip a subset of the four.
5. **Verify**: staff `GET /api/catalog/health` (`bucket=6thsense-catalog`, `prefix=v2/`); `GET /api/catalog/clips/ego-20260823-000821-16a260`; curl one `posters/` URL -> `6thsense-catalog.s3.us-west-2...` 200; curl one `media/.../video/left.mp4` URL -> `6thsense-processed.s3.us-west-2.../imported/2026-08-24_nervous-1/...` 200.
6. **Rollback**: env back to `6thsense-catalog-media` + `v2/` **first**, then redeploy the previous backend revision.

## Residual open items

- **Unconfirmed**: I could not read Railway. The briefing says prod is on `6thsense-catalog-media` + `v2/`; the PR's runbook says `v1/`. Confirm the actual live values before touching anything — steps 3 and 6 both depend on it.
- `catalog-media-ro` also grants `6thsense-processed/packages/*`, which this PR does not need. Given finding 8, consider dropping it to shrink blast radius.
- No API-level test asserts that a full clip document's media URLs carry the processed host; `test_catalog_api.py` was not touched and is docker-gated here.
- The hardcoded cohort default (`imported/2026-08-24_nervous-1/`) will need a code change, not a config change, at the next import unless finding 6 is fixed.
