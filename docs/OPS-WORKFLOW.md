# Ops contributor workflow

Workflow foundation: `feat/ops-workflow-ledgers`; mobile extension: `feat/contributor-mobile-pilot-20260915`. This guide describes implementation behavior, not proof of a completed trial. See [the Synapse contract](CONTRIBUTOR-CONTRACT.md) and [mobile pilot](CONTRIBUTOR-MOBILE-PILOT.md) for registration, terms and remaining acceptance work.

## Screens and authority

- **Raw** monitors the current `6thsense-raw` inventory, outstanding source files, validation/recovery queue and rejected history. Current manifests plus exact source receipts determine whether files are represented in Clean. A matching episode name alone cannot clear the backlog. Old approve/pay/rate endpoints return HTTP 410; historical payment fields remain unchanged.
- **Clean** starts with region selection and all-time decoded, accepted, and excluded hours from the original Clean runs. Within a region it groups footage once per contributor or business, keeps playback and review inside that region, and records recording-specific review against the immutable manifest SHA-256. Filtering sources does not change region totals. Operators confirm collection dates when camera time is unreliable, review retained footage and flagged intervals, and can hold footage with a reason. See [Clean browsing and region attribution](OPS-CLEAN.md) for missing/mixed-region handling and the distinction from pending Raw footage.
- **Sieve** shows retained Clean hours, verified inherited hours, country/entity/activity diversity and per-recording copy status through September 25, 2026, Los Angeles time. Its independent worker copies only Clean MP4, validated metadata with its provenance, and calibration; customer acceptance remains separate. See [Sieve collection and inheritance](SIEVE-CLEAN-INHERITANCE.md).
- **Payment** shows exclusion reasons, review status, eligibility, the latest weekly calculation and import-error count, exact payout approval and transfer history. Approval reserves the displayed recordings and rate snapshots in one transaction. New footage is never added to an existing approval. Unique payout items prevent a recording from being reserved twice.
- **Users** manages contributor contact/workplace/location/rate, supervised camera assignments and time totals derived from decoded Clean intervals. Its **Mobile contributor requests** panel approves pending camera requests after physical verification and current consent, reviews masked bank submissions, and exposes audited recipient recovery. Each recipient link requires a separate ownership confirmation; payment approval stays in Payment. Manual roster entries do not establish app identity or consent.

## Raw status and recovery guidance

For **Blocked**, **Retry pending**, and **Recovery needed** rows, Raw shows a specific cause badge when the recorded diagnostic supports one, followed by the underlying processing state. The **Reason / next step** column preserves the original diagnostic and adds recovery guidance. Search by the cause label, source, camera, episode or diagnostic text; the **Processing status** filter still selects the underlying state, not the cause badge.

| Cause badge | Next step |
| --- | --- |
| Scene review required | Screening could not confidently retain footage; review the saved evidence before deciding. |
| Rejected by scene QA | No footage passed the current scene rules; inspect the reason. Processing ended without a Clean export. |
| Budget update interrupted | Parallel reservation updates conflicted; recovery retains the shared cap and reuses completed calls. |
| Cloud worker interrupted | AWS reclaimed the worker; preserve sources and check earlier outputs before retrying. |
| Model service interrupted | Recovery retries eligible failed requests within the shared budget and reuses valid saved responses. |
| Scene response invalid | Sample validation failed; recovery requests a separately validated response. |
| Metadata missing | Recover the recording's original metadata, then revalidate it. |
| Metadata unreadable | Check metadata access and recover a readable original. |
| Recording incomplete | Confirm completion and upload the final files and metadata. |
| Source files changed | Compare the new upload with the earlier processing attempt before retrying. |
| Job status uncertain | Confirm whether the cloud job exists or is running before submitting another. |
| IMU data conflict | Recover a consistent source sensor timeline. |
| Calibration missing | Recover calibration for the recording's camera. |
| Calibration mismatch | Verify that the calibration belongs to the camera and matches the recording. |
| Source attribution needed | Confirm the contributor or business and capture country. |
| Account deletion pending | Resolve the contributor deletion request before processing. |
| Retry limit reached | Inspect the recorded failure and fix its cause before retrying. |
| No valid segments | Review timing and quality exclusions to assess source recovery. |
| Model budget reached | Review remaining work and the processing budget before resuming. |
| Run window ended | Review remaining work and renew the cloud run window to resume. |
| Conversion failed | Inspect the conversion job's error before retrying. |
| Clean processing failed | Inspect the Clean job's error before retrying. |

An unknown cause retains the generic state label and asks the operator to review the recorded reason; the UI does not invent a metadata, sensor or scene diagnosis. Specific evidence takes precedence over a generic failed-job wrapper. An old failure message does not relabel an active or completed job. These labels and instructions do not themselves retry work or change backend state.

**Scene review required** and **Rejected by scene QA** distinguish a completed screening disposition with no retained output from a technical worker failure. They are cause badges on the underlying held state, not **In Clean**, customer acceptance or a deletion instruction. Model-service failures, invalid responses, interrupted workers and budget-update conflicts remain technical recovery causes. The displayed guidance describes the configured recovery path; a frontend deployment alone does not activate that worker or prove a retry succeeded.

**Checking source match** means a Clean result has been imported and automatic scans are verifying that it covers the exact current Raw files. A result run ID alone is insufficient. An `awaiting_verification` row displays **In Clean** only when `raw.status` is `processed` and `raw.pending_files` is the number `0`; missing counts, additional files or unmatched receipts leave it checking. Other explicit processing states and holds remain unchanged, and deleted recordings stay **Rejected**. See the [receipt-matching contract](../backend/README.md#raw-processing-queue).

**In Clean** confirms coverage of the current Raw source files. Its original diagnostic remains available under **Recorded status message**. Completed and rejected rows are hidden by default; select **Show completed / rejected** to include them. A Clean result's source coverage does not establish human quality approval, customer acceptance or payment.

## Payment policy and operation

Registered [business sources](OPS-BUSINESS-SOURCES.md) keep quality reviews and regional hours but have no individual owner, rate or payout eligibility. Their source-country collection dates and `b2b_contract` ledger status do not establish contract settlement. Operators configure dedicated upload channels through controlled maintenance; Raw scans then preserve per-recording business attribution before filling individual owners, so PSDN uploads display under PSDN. Attribution survives Raw retirement. Invoice handling and self-service onboarding are outside this release.

The Korean pilot uses KRW 11,000/hour. Eligibility requires **at least 14,400 seconds** of accumulated unpaid, reviewed retained footage with confirmed collection dates. Exactly four hours qualifies; 14,399.99 seconds does not. Decimal arithmetic preserves this boundary when intervals and recordings have fractional durations. The API fixes the threshold basis to accumulated unpaid time for this pilot.

Weekly calculation uses **Sunday 23:59:00 Asia/Seoul**. The collection window runs from Monday through that Sunday, with the following Monday excluded; earlier unpaid eligible balances carry forward. The first configured cutoff is **20 September 2026 at 23:59 Korea time**, or `2026-09-20T14:59:00Z`.

The independent calculation loop checks every 30 seconds, imports verified Clean manifests through the existing scanner, then saves one durable record per completed Sunday in `payment_calculation_YYYY-MM-DD` plus a `payment_calculation_latest` pointer in Ops settings. Invalid individual imports are counted and excluded; a scan exception leaves the weekly record absent for retry. PostgreSQL advisory locks prevent competing replicas from scanning/calculating the same week concurrently. A restart can catch up the latest completed cutoff; it does not replay every missed historical week. Once saved, the weekly record is not replaced by later ticks. No schema migration is added.

The weekly snapshot includes only active contributors' qualifying entries with `reviewed_at` **at or before the cutoff**. Post-cutoff reviews wait for a later weekly snapshot, even if a delayed job runs after the review. Unreviewed, already-paid/reserved, business-owned, uncertain-date or unreconciled entries remain excluded. Calculation writes **no `Payout` or `PayoutItem` records**, creates no reservations, and does not create or fund Wise transfers. Scanning imports verified ledger evidence; it does not move or delete S3 objects or perform QC itself.

The Payment screen and **Approve Payment** independently recalculate the live ledger against the latest completed Sunday collection window. They can include a review completed after the weekly snapshot cutoff when its collection date and other eligibility checks qualify. They do not approve the saved snapshot verbatim. Refresh and review the current exact recording/manifest references, amount and recipient; changed eligibility or amounts reject approval until refreshed. The calculation start flag gates the background snapshots, not this live approval path. Existing approved reservations, rate/recipient snapshots and scheduled timestamps remain unchanged.

Recipient verification checks the configured Wise profile, KRW currency, active state and recipient hash. Approval must match the recipient revision displayed to the operator, then snapshots recipient ID/hash, profile, environment, target amount and source currency. A recipient change requires a refreshed review; refreshing clears the prior approval checkbox. Transfer retries use the payout UUID as `customerTransactionId`.

`approved` → `quoted` → `awaiting_funding` / `processing` → `sent`. A returned/cancelled transfer becomes `needs_attention` and its footage stays reserved. Funding completion is not recipient receipt. `sent` remains distinct from `paid`. A verified settlement/delivery reconciliation is still needed before implementing the final paid transition. No manual unreserve/reissue shortcut is provided for an uncertain transfer outcome.

Configuration uses server-side environment variables; never enter a token into an Ops form or commit it:

| Variable | Default / purpose |
| --- | --- |
| `OPS_PAYMENT_CALCULATION_ENABLED` | `false`; `true` starts the independent weekly calculation loop, without enabling payout execution |
| `OPS_PAYMENT_CALCULATION_START_AT` | Required when calculation is enabled; use `2026-09-20T14:59:00Z` for the first cutoff. Must include a timezone and resolve to Sunday 23:59:00 Asia/Seoul |
| `OPS_AUTOMATION_ENABLED` | `false`; enables the five-minute automation loop and scans |
| `OPS_PAYOUT_AUTOMATION_ENABLED` | `false`; separate opt-in required for payout reconciliation/creation inside the automation loop |
| `OPS_PROCESSOR_TOKEN` | unset; bearer credential for a separate recovery/QC worker |
| `WISE_API_TOKEN` | unset; server-side Wise credential |
| `WISE_PROFILE_ID` | unset; verify the actual account/profile before use |
| `WISE_ENVIRONMENT` | `sandbox`; explicit `production` required for real transfers |
| `WISE_SOURCE_CURRENCY` | `USD`; proposed funding default; recipient amount remains fixed KRW |
| `OPS_WISE_AUTO_FUND` | `false`; must be explicitly enabled for balance funding after approval |

For calculation-only operation, set `OPS_PAYMENT_CALCULATION_ENABLED=true` with the start timestamp above and keep **`OPS_PAYOUT_AUTOMATION_ENABLED=false` and `OPS_WISE_AUTO_FUND=false`**. Calculation does not depend on `OPS_AUTOMATION_ENABLED`; that flag separately controls the existing scan/payment automation loop. Wise credentials alone do not enable payment execution. The separate payout worker requires both `OPS_AUTOMATION_ENABLED` and `OPS_PAYOUT_AUTOMATION_ENABLED` to process approved, due reservations, and uses PostgreSQL advisory locking across replicas. Interrupted attempts reconcile the same transfer identity on later ticks. The Sunday calculation cutoff is not a transfer-initiation or bank-receipt promise. Allow up to five business days after actual initiation in contributor copy, while showing provider progress. Live recipient requirements were checked for the mobile adapter, and local fake-provider tests cover retries; a real pilot recipient, funding, delivery and return trial is still pending.

`GET /api/ops/payments/state` exposes `latest_calculation`, `next_calculation_at`, the latest completed `scheduled_for` cutoff and calculation configuration. Inspect the latest record's `calculated_at`, `imported_runs` and `scan_error_count` before reviewing amounts. A zero error count does not substitute for operator footage or recipient approval. Local validation for this change passed 61 backend tests and the frontend production build, including the exact fractional threshold, cutoff/start gate, replica deduplication, immutable snapshots and absence of payout writes.

Official Wise references: [personal API tokens](https://docs.wise.com/guides/developer/auth-and-security/personal-api-token), [SMB payouts](https://docs.wise.com/guides/product/send-money/use-cases/payouts-smbs), [balance funding](https://docs.wise.com/guides/product/send-money/funding/fund-from-balance).

## Recovery/QC integration

This branch implements diagnosis, durable leases and result verification. **It does not deploy a media recovery or activity-QC worker.** A configured token indicates worker access configuration, not a running worker.

1. Scans wait for **10 minutes without new or updated source files** before proposing recovery/QC. An unknown latest-upload time keeps the recording waiting for verification. This replaces the six-hour delay; a quiet period alone does not prove complete capture or authorize metadata reconstruction.
2. Missing/malformed metadata, absent media, incomplete stereo pairs and truncated capture require recovery. Transient storage failures retry; exhausted infrastructure retries require operator attention. A worker must attempt recoverable source versions/alternate deliveries before returning `irrecoverable` with a reason.
3. Worker calls `POST /api/ops/processing/claim` with its bearer token and an allowed `Origin` header (the Ops CSRF middleware still applies). Claim returns recording, fingerprint, input inventory, lease token and expiry, plus the registered `counterparty` for business footage. Preserve that counterparty and country in the result; completion verifies attribution again. Send `outcome: heartbeat` to `/result` before the 30-minute lease expires. Stale source fingerprints or leases are refused.
4. The worker must pin source S3 versions and checksums, validate/decode source timelines, avoid double-counting stereo pairs and duplicate/repackaged sources, preserve available timing/sensor provenance, and apply the collection's approved QC policy. Future manifests must also preserve verified capture-region fields or source tags; a contributor's mutable profile is not collection provenance. Missing or mixed attribution keeps the whole batch under Needs region review. The region view does not fetch omitted tags, create region buckets, or change payment records. The ink-factory rule removes entire neither-hand-visible intervals longer than 30 seconds and excludes computer/phone work; do not silently apply that activity-specific exclusion to other work categories.
5. New results must satisfy `6thsense-clean-qc/2`: separate left/right videos, every retained frame for both eyes, measured IMU, frame index and shared sensor timeline. See [Raw → Clean artifacts](RAW-TO-CLEAN-ARTIFACTS.md) for the local extraction stage and output contract. Claims advertise this requirement; both new import and worker completion reject video-only evidence. Publish all pinned outputs before `_SUCCESS.json`. S3 writes belong to the external worker; these API routes do not move or delete objects. Worker completion references the imported run, then Raw reconciliation checks exact source receipts before clearing the backlog. Existing v1 ledger entries remain readable and are labelled as historical video exports; backfilling modalities must not create another payable run.
6. Existing paid sources, overlapping payable runs, mixed contributors and changed existing manifests are held. Additional source files attached to an already-processed recording require explicit non-overlapping segmentation/supersession; the current importer will not create another payable run for the same positive-duration recording.

Worker deployment and source-pinned integration verification remain separate from this API change. Container/stereo recovery quality, hands visibility and computer-work exclusion are not inferred from this queue's status. The UI and docs must not say an episode was cleaned until its committed output and source receipts are verified.

### Explicit metadata recovery

Recover original capture metadata when available. For missing originals, the
external worker can use a separate, version-pinned
`6thsense-source-metadata-recovery/1` authorization for the recording's available
MP4s. It must bind the recording and camera, exact source versions and sizes, the
recovery basis, and camera calibration with its applicability evidence. The
scope is `available_source_only`; a queue diagnosis or elapsed quiet period does
not grant that authorization. Original metadata or calibration must be reconciled
before taking the reconstruction path, and original files remain preserved.

Generated `6thsense-reconstructed-source-metadata/1` metadata is labelled
`metadata_origin: reconstructed`. Frame count and duration describe inspected
available media. Capture completeness is `unknown`; `complete`, `start_time`,
`clock_synced`, `stop_reason`, `received_frames`, `written_frames`,
`dropped_frames`, `fw`, `lossless` and `truncated` stay explicitly `null`.
Available-source counts do not establish original capture totals, missing final
chunks or absolute capture time. Source SHA-256, version and size, plus pinned
calibration provenance, remain attached to the generated artifact.

Clean import requires the `6thsense-clean-source-metadata/2` provenance
supplement. It rereads the immutable authorization and conversion receipt, checks
the generated bytes and measured observations, and rejects changed sources,
canary-only evidence or newly available original metadata. Existing Clean,
attribution and exact-source receipt checks still apply. Sieve checks the
disclosed reconstruction against committed Clean evidence before copying; see
[its metadata validation contract](SIEVE-CLEAN-INHERITANCE.md#metadata-validation).
Neither stage establishes complete capture or customer acceptance.

At the September 17 implementation checkpoint, 91 focused backend tests and
123 catalog tests passed, including 20 new recovery cases. Backend validation and
the 10-minute quiet-period check are deployed. A 900-frame conversion cloud canary
passed; Clean canary completion and cloud worker promotion remain pending.
Pipeline holds remain in place until promotion; this API update does not establish
a completed recording recovery.

## Rollout dependencies

- Apply migration `0014` before this API/UI version. It adds new ledgers and the four user-confirmed roster assignments, preserving non-null existing attribution and all historical payment values.
- Connect and verify the recovery/QC worker before describing intake as automatic processing. Archive buckets from the prior inventory remain a separate migration/triage concern; the Ops scanner targets the configured current raw bucket.
- Publish production agreements and exercise the implemented mobile account linking, consent receipts and supervised capture-time assignment history with a real account and camera. Apply additive migration `0016` before the mobile API/UI; its audit tables must be retained on rollback once populated.
- Validate Wise recipient requirements, funding, retry/return handling and settlement reconciliation in sandbox before enabling production funding.

Deploying this implementation does not itself pay anyone, delete originals, create an app account or record contributor consent. Those require the user's authenticated actions or the separate operator workflow.

### Weekly calculation error handling

Per-object S3 client errors keep the weekly calculation pending for retry; a partial storage read never writes the completion key. Invalid manifests remain visible as scan errors and are excluded from payable footage. The weekly snapshot stores `retained_seconds_exact` alongside display seconds; eligibility uses exact interval arithmetic from the versioned manifest, whose hash remains pinned in any payment reservation.
