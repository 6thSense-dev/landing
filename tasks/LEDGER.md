# Task ledger

## 2026-08-04 — Conference mobile conversion audit

- Audited the production React source and rendered mobile experience for the AI4 conference referral use case.
- Added `tasks/SITE-AUDIT.md` with the current claim inventory, defensibility assessment, Eye1/prohibited-claim sweep, brand-mark mismatch, mobile-first findings, weakest first-screen issue, and ten ranked fixes with effort estimates.
- Found conference blockers: Eye2 is not the first-screen offer; a 3.8-second opener delays first paint; the contact path is at the end of an approximately 9.4-screen mobile journey; live/legacy/prerendered routes publish claims beyond Eye2 at 30 fps; and public routes offer Skin/Hand despite the Eye2-only constraint.
- Made no site or style changes; this task was audit-only and safe claim cleanup spans several coupled routes.
- Verification: `npm ci`; `npm run build` (passed); headless Chromium checks of `/` and `/products` at 390px.

## 2026-09-03 — Catalog and processed storage tiers

- Routed bundle-relative `media/` assets to the configured processed-package bucket and prefix while retaining catalog documents and previews on the catalog tier.
- Added a package-file refusal guard to the catalog preview uploader, rollout documentation, and routing/presigning tests.
- Verification and mutation evidence: `tasks/CATALOG-TIER-BUCKETS-2026-09-03.md`.
- 2026-09-03 round-1 fixes: corrected v2 rollout/rollback docs, safe tier defaults, CSP hosts, package health probe, archive routing, blank env handling, and cache invalidation coverage (`tasks/REVIEW-CATALOG-TIERS-1-RESPONSE.md`).

## 2026-09-16 — Cloud pipeline import boundary

- Added the dedicated-token pipeline API review fixes and regression coverage.
- New imports now require exact current Raw media coverage, matching delivery identity, current and pinned S3 versions and sizes, a pinned completed conversion receipt with full source hashes, and byte-identical versioned Raw metadata provenance.
- Clean metadata provenance requires its schema, byte-exact copy mode, unique exact media identities, and verified Clean metadata content. Repeat imports still work after Raw archival because Raw-dependent checks apply only before the first import.
- Contributor/business ownership and country must match authoritative source facts; paid cash facts carry into Clean, B2B unknown amounts remain `null`, and no payout rows are created.
- The coordinator status endpoint can no longer assert `clean`; deleted recordings remain blocked.
- Verification: `tests/test_ops_pipeline.py` (7 passed); pipeline/Sieve/source/artifact suite (107 passed).

## 2026-09-16 — Immutable originals archive worker

- Added `infra/raw_lifecycle/archive_worker.py`: accepts a SHA256-bound, version-pinned `TASK_PLAN_REF`; archives every planned Raw original, including media, metadata, calibration, and sidecars; performs no Raw deletion or job/database mutation.
- Copies use pinned source versions and conditional multipart completion, including objects over 5 GiB. Streaming SHA256 and full destination readback verify exact bytes; conflicting destinations and receipts fail closed; 403 is never interpreted as absence. Two default workers (maximum four) bound copy/read concurrency.
- Publishes version-pinned `6thsense-archive-receipt/1` receipts and immutable `6thsense-archive-source/1` resolver entries. Resolver identity is SHA256 of UTF-8 compact sorted JSON `{bucket,key,version_id}`; original keys use `originals/<identity>/<basename>`. Archive bucket versioning must be enabled; role credentials are supplied by boto3 without persistence.
- Verification: `/data/projects/6thsense/pipeline-takeover-20260916/venv/bin/python -m pytest tests/raw_lifecycle/test_archive_worker.py -q` — 14 passed. Covered exact full-file preservation, retries, pinned versions despite latest changes, corruption, unauthorized lookup, immutable conflicts, conditional creation races, empty objects, and multipart ranges above 5 GiB. No live archive writes were performed by these tests.

## 2026-09-16 — Raw lifecycle adversarial safety tests

- Added retirement regression coverage proving every planned archive version is verified before the first Raw deletion, missing receipt members and changed archive metadata fail closed, a newly uploaded current version blocks all cleanup, and a partial retry deletes only exact version IDs safely.
- Added coordinator coverage proving retirement cannot run while archive verification is pending, stale historical cloud jobs cannot be adopted for different Raw versions, and an uncertain Batch submission is held for reconciliation instead of blindly duplicated.
- The review caught the archive metadata contract mismatch (`source-sha256`) and required source-bound historical job adoption and conversion receipt validation. The coordinator and retirement implementations were corrected in the shared branch.
- Verification: `AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-west-2 /data/projects/6thsense/pipeline-takeover-20260916/venv/bin/python -m pytest -q tests/raw_lifecycle/test_archive_worker.py tests/raw_lifecycle/test_retirement.py tests/raw_lifecycle/test_coordinator.py` — 23 passed; mocks only, no AWS mutations.
