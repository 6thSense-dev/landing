# Ops contributor workflow

Workflow foundation: `feat/ops-workflow-ledgers`; mobile extension: `feat/contributor-mobile-pilot-20260915`. This guide describes implementation behavior, not proof of a completed trial. See [the Synapse contract](CONTRIBUTOR-CONTRACT.md) and [mobile pilot](CONTRIBUTOR-MOBILE-PILOT.md) for registration, terms and remaining acceptance work.

## Screens and authority

- **Raw** monitors the current `6thsense-raw` inventory, outstanding source files, validation/recovery queue and rejected history. Current manifests plus exact source receipts determine whether files are represented in Clean. A matching episode name alone cannot clear the backlog. Old approve/pay/rate endpoints return HTTP 410; historical payment fields remain unchanged.
- **Clean** starts with region selection and all-time decoded, accepted, and excluded hours from the original Clean runs. Within a region it groups footage once per contributor or business, keeps playback and review inside that region, and records recording-specific review against the immutable manifest SHA-256. Filtering sources does not change region totals. Operators confirm collection dates when camera time is unreliable, review retained footage and flagged intervals, and can hold footage with a reason. See [Clean browsing and region attribution](OPS-CLEAN.md) for missing/mixed-region handling and the distinction from pending Raw footage.
- **Sieve** shows retained Clean hours, verified inherited hours, country/entity/activity diversity and per-recording copy status through September 25, 2026, Los Angeles time. Its independent worker copies only Clean MP4, original metadata and calibration; customer acceptance remains separate. See [Sieve collection and inheritance](SIEVE-CLEAN-INHERITANCE.md).
- **Payment** shows exclusion reasons, review status, eligibility, exact payout approval and transfer history. Approval reserves the displayed recordings and rate snapshots in one transaction. New footage is never added to an existing approval. Unique payout items prevent a recording from being reserved twice.
- **Users** manages contributor contact/workplace/location/rate, supervised camera assignments and time totals derived from decoded Clean intervals. Its **Mobile contributor requests** panel approves pending camera requests after physical verification and current consent, reviews masked bank submissions, and exposes audited recipient recovery. Each recipient link requires a separate ownership confirmation; payment approval stays in Payment. Manual roster entries do not establish app identity or consent.

## Payment policy and operation

Registered [business sources](OPS-BUSINESS-SOURCES.md) keep quality reviews and regional hours but have no individual owner, rate or payout eligibility. Their source-country collection dates and `b2b_contract` ledger status do not establish contract settlement. Operators configure dedicated upload channels through controlled maintenance; Raw scans then preserve per-recording business attribution before filling individual owners, so PSDN uploads display under PSDN. Attribution survives Raw retirement. Invoice handling and self-service onboarding are outside this release.

The Korean pilot uses KRW 11,000/hour. Eligibility requires strictly more than 14,400 seconds of accumulated unpaid, reviewed retained footage with confirmed collection dates. Friday scheduling defaults to 18:00 Asia/Seoul and includes completed Monday–Sunday collection weeks plus earlier unpaid balances. The API fixes the threshold basis to accumulated unpaid time for this pilot.

Recipient verification checks the configured Wise profile, KRW currency, active state and recipient hash. Approval must match the recipient revision displayed to the operator, then snapshots recipient ID/hash, profile, environment, target amount and source currency. A recipient change requires a refreshed review; refreshing clears the prior approval checkbox. Transfer retries use the payout UUID as `customerTransactionId`.

`approved` → `quoted` → `awaiting_funding` / `processing` → `sent`. A returned/cancelled transfer becomes `needs_attention` and its footage stays reserved. Funding completion is not recipient receipt. `sent` remains distinct from `paid`. A verified settlement/delivery reconciliation is still needed before implementing the final paid transition. No manual unreserve/reissue shortcut is provided for an uncertain transfer outcome.

Configuration uses server-side environment variables; never enter a token into an Ops form or commit it:

| Variable | Default / purpose |
| --- | --- |
| `OPS_AUTOMATION_ENABLED` | `false`; enables the five-minute automation loop and scans |
| `OPS_PAYOUT_AUTOMATION_ENABLED` | `false`; separate opt-in required for payout reconciliation/creation inside the automation loop |
| `OPS_PROCESSOR_TOKEN` | unset; bearer credential for a separate recovery/QC worker |
| `WISE_API_TOKEN` | unset; server-side Wise credential |
| `WISE_PROFILE_ID` | unset; verify the actual account/profile before use |
| `WISE_ENVIRONMENT` | `sandbox`; explicit `production` required for real transfers |
| `WISE_SOURCE_CURRENCY` | `USD`; proposed funding default; recipient amount remains fixed KRW |
| `OPS_WISE_AUTO_FUND` | `false`; must be explicitly enabled for balance funding after approval |

The scheduler uses a PostgreSQL advisory lock across API replicas. Scans can run while payout execution stays disabled, even when Wise credentials are configured. Both automation flags must be enabled to process approved, due reservations. If a Friday attempt is interrupted, subsequent ticks reconcile the same transfer identity; a retry may therefore occur after Friday. Allow up to five business days after initiation in contributor copy, while showing actual provider progress. Live recipient requirements were checked for the mobile adapter, and local fake-provider tests cover retries; a real pilot recipient, funding, delivery and return trial is still pending.

Official Wise references: [personal API tokens](https://docs.wise.com/guides/developer/auth-and-security/personal-api-token), [SMB payouts](https://docs.wise.com/guides/product/send-money/use-cases/payouts-smbs), [balance funding](https://docs.wise.com/guides/product/send-money/funding/fund-from-balance).

## Recovery/QC integration

This branch implements diagnosis, durable leases and result verification. **It does not deploy a media recovery or activity-QC worker.** A configured token indicates worker access configuration, not a running worker.

1. Scans wait for six hours of upload stability before proposing recovery/QC. This is a provisional rule for legacy camera deliveries; a verified completion manifest should replace the delay for the new app workflow.
2. Missing/malformed metadata, absent media, incomplete stereo pairs and truncated capture require recovery. Transient storage failures retry; exhausted infrastructure retries require operator attention. A worker must attempt recoverable source versions/alternate deliveries before returning `irrecoverable` with a reason.
3. Worker calls `POST /api/ops/processing/claim` with its bearer token and an allowed `Origin` header (the Ops CSRF middleware still applies). Claim returns recording, fingerprint, input inventory, lease token and expiry, plus the registered `counterparty` for business footage. Preserve that counterparty and country in the result; completion verifies attribution again. Send `outcome: heartbeat` to `/result` before the 30-minute lease expires. Stale source fingerprints or leases are refused.
4. The worker must pin source S3 versions and checksums, validate/decode source timelines, avoid double-counting stereo pairs and duplicate/repackaged sources, preserve available timing/sensor provenance, and apply the collection's approved QC policy. Future manifests must also preserve verified capture-region fields or source tags; a contributor's mutable profile is not collection provenance. Missing or mixed attribution keeps the whole batch under Needs region review. The region view does not fetch omitted tags, create region buckets, or change payment records. The ink-factory rule removes entire neither-hand-visible intervals longer than 30 seconds and excludes computer/phone work; do not silently apply that activity-specific exclusion to other work categories.
5. New results must satisfy `6thsense-clean-qc/2`: separate left/right videos, every retained frame for both eyes, measured IMU, frame index and shared sensor timeline. See [Raw → Clean artifacts](RAW-TO-CLEAN-ARTIFACTS.md) for the local extraction stage and output contract. Claims advertise this requirement; both new import and worker completion reject video-only evidence. Publish all pinned outputs before `_SUCCESS.json`. S3 writes belong to the external worker; these API routes do not move or delete objects. Worker completion references the imported run, then Raw reconciliation checks exact source receipts before clearing the backlog. Existing v1 ledger entries remain readable and are labelled as historical video exports; backfilling modalities must not create another payable run.
6. Existing paid sources, overlapping payable runs, mixed contributors and changed existing manifests are held. Additional source files attached to an already-processed recording require explicit non-overlapping segmentation/supersession; the current importer will not create another payable run for the same positive-duration recording.

The worker still needs implementation/deployment and source-pinned integration tests. Container/stereo recovery quality, hands visibility and computer-work exclusion are not inferred from this queue's status. The UI and docs must not say an episode was cleaned until its committed output and source receipts are verified.

## Rollout dependencies

- Apply migration `0014` before this API/UI version. It adds new ledgers and the four user-confirmed roster assignments, preserving non-null existing attribution and all historical payment values.
- Connect and verify the recovery/QC worker before describing intake as automatic processing. Archive buckets from the prior inventory remain a separate migration/triage concern; the Ops scanner targets the configured current raw bucket.
- Publish production agreements and exercise the implemented mobile account linking, consent receipts and supervised capture-time assignment history with a real account and camera. Apply additive migration `0016` before the mobile API/UI; its audit tables must be retained on rollback once populated.
- Validate Wise recipient requirements, funding, retry/return handling and settlement reconciliation in sandbox before enabling production funding.

Deploying this implementation does not itself pay anyone, delete originals, create an app account or record contributor consent. Those require the user's authenticated actions or the separate operator workflow.
