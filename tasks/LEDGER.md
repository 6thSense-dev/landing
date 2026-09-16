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
- Verification: `AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-west-2 /data/projects/6thsense/pipeline-takeover-20260916/venv/bin/python -m pytest -q tests/raw_lifecycle/test_archive_worker.py tests/raw_lifecycle/test_retirement.py tests/raw_lifecycle/test_coordinator.py` — 24 passed; mocks only, no AWS mutations. Clean coverage must come from one complete imported run rather than a union of partial historical runs.

## 2026-09-16 — Reserved automatic Clean imports

- Generic operator and scheduled Clean scans now skip `raw-clean-auto-*` results, reserving them for the pipeline bridge's stricter source, metadata, country, ownership, and payment checks.
- Regression coverage proves a committed automatic result cannot create a `CleanRun` through the weaker generic scanner and is not misreported as an invalid scan.
- Verification: Clean/pipeline/workflow/artifact suite — 94 passed. Coordinator/API review found one remaining interface gap: coordinator `.h265`/`.hevc` media are not classified as media by the portal Raw scanner; hold those native streams until both sides support them consistently.

## 2026-09-16 — Durable AWS Raw lifecycle rollout (initial checkpoint; superseded below)

- User authorized dinner-time autonomous work, tested pipeline publication, original preservation, and India/Korea-only Sieve. Production account 194680606079/us-west-2; no GPU quota increase; $100 initial additional-compute ceiling and stop at 12:09:22 UTC.
- Production API deployment `33021b93-9ab3-49c9-af54-cab06913af9d` serves the authenticated pipeline bridge and reserves `raw-clean-auto-*` imports. Sieve eligibility is deployed. Eight China deliveries/48 versioned objects were withdrawn from Sieve only after confirming their Clean originals; 27 eligible deliveries remain. Audit: `s3://6thsense-processed/raw-lifecycle/v1/audit/sieve-china-withdrawal-20260916.json`.
- Created `6thsense-archive-194680606079`, versioned/private/encrypted/no expiry. Live archive canary `8a0b324f-24a9-43e5-94d9-3b96ecadba26` succeeded with full destination hash readback; retry `fe13d792-8ca8-4421-a570-cd29cc91785c` reused the same immutable receipt version. An earlier canary correctly rejected a receipt path outside its recording/fingerprint contract before copying.
- Armed EventBridge two-minute coordinator and five-minute budget watchdog. Source inventory: 44 eligible recording groups, 1,876 current objects, 237.28 GiB; operator-deleted groups excluded. Existing Alex jobs are adopted by pinned source identities. Retired the five old task-specific Batch definition revisions to prevent stale laptop submissions, preserving queued/running work and separate new compute environments.
- Live scheduler exposed a missing `batch:TagResource` permission on owned definitions. Fixed exact-scoped IAM, captured explicit CloudTrail denials plus all-status empty Batch searches, and immutably audited/reconciled all 44 refused intents before resubmission. Corrected tick at 04:14:53 UTC advanced 42 groups and held two missing-original-metadata groups; accepted job IDs are durable in S3.
- Code pushed to branch `feat/aws-raw-lifecycle-20260916`; PR https://github.com/6thSense-dev/landing/pull/67 is stacked on the already deployed feature history. `main` has not been changed. Independent model review and relevant tests passed. Raw retirement remains disabled pending full-recording archive validation and crash-recovery integration checks; do not describe temporary Raw cleanup as enabled yet.

## 2026-09-16 — Archive receipt commits resolver completion

- Addressed PR #67's archive publication-order finding: the worker now publishes and verifies every source-index entry before creating the final verified archive receipt. Partial indexes remain reusable if a job fails before commit.
- Added regressions for a middle index's write failure and readback failure: neither emits a completion receipt, retries preserve all existing original/index versions, and a successful receipt is the final write. Both regressions failed against the previous ordering before the fix.
- Verification: archive worker suite — 16 passed. Initial combined lifecycle run — 30 passed, 3 unrelated retirement-test failures because a concurrent discovery guard needed an updated paginator mock; reported to the coordinating owner. No cloud changes or modifications to existing pinned jobs.

## 2026-09-16 — Verified autonomous pipeline release

- All 44 eligible groups have complete archive receipts; 33 groups completed independent Clean/archive validation and exact-version Raw retirement at 04:40 UTC. Six additional Clean jobs were running/queued; missing original metadata (two), PSDN legacy timing/calibration/documents, one China IMU conflict and one recoverable container-clock failure remained held. Original uploads remain archived even for held recordings.
- Independent post-retirement verification re-read every archive file for a six-file 9.1 GiB recording, matched each full SHA256 and confirmed its Raw versions absent. Evidence: `s3://6thsense-processed/raw-lifecycle/v1/audit/post-retirement-verification-20260916.json`. Empty final camera placeholders explained six former holds; they stay archived and verified, with only nonempty media required in Clean.
- Active Sieve country audit: 27 Korea recordings; India/Korea allowlist enforced; eight China deliveries/48 versions withdrawn with Clean originals retained. Audit: `raw-lifecycle/v1/audit/sieve-country-audit-20260916.json` in processed.
- Reviewed runtime recovery widens only container-header/presentation guards for an observed 1 fps header. The 901-frame problematic chunk fully decoded with valid embedded barcodes, zero IMU conflicts and 3.334 ms maximum IMU gap. Source timestamps remain unchanged; final Clean still requires measured exposure/IMU coverage. Explicit retries preserve failed-attempt evidence and require unchanged sources, no existing outputs and a new immutable worker definition.
- Validation: 641 backend tests; fresh and 0015→0016 Postgres migrations; API startup/health; 19 frontend unit tests, build and 48 Playwright checks across three viewports; final 63 lifecycle tests. Backend/frontend trees match tested efe3227. Different-model implementation review approved. Registry corruption intentionally fails closed to prevent B2B attribution being treated as individual contributor ownership.
- Release: PR68 consolidates the already deployed production feature stack and pipeline into main atomically; PR67 provides the focused pipeline review. Both Railway services watch main. This avoids intermediate deployments that would remove currently deployed behavior. Exact release/deployment receipts live in `/data/projects/6thsense/pipeline-takeover-20260916/TAKEOVER.md`.
- AWS EventBridge and Batch continue without this chat. Initial additional-compute ceiling is $100; watchdog deadline remains 2026-09-16 12:09:22 UTC. Future source-specific recovery is distinct from indefinitely extending compute. No camera/Synapse changes or payout creation. Dashboard walkthrough: `tasks/PIPELINE-ONBOARDING-2026-09-16.md`.
