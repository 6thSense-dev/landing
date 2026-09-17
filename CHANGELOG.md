# Changelog

## [0.2.1.1] - 2026-09-17

### Fixed

- Describe Synapse's configured camera fleet reports, their separation from optional analytics, contributor bank fields and commercial footage licensing in its public privacy policy.

## [0.2.1.0] - 2026-09-17

### Fixed

- Show specific Raw processing causes and recovery guidance, while preserving the original diagnostic message.
- Explain imported results as “Checking source match” until verified receipts cover the current Raw files. Keep status badges, filters and completed-history visibility consistent after reconciliation.

## [0.2.0.0] - 2026-09-16

### Added

- Calculate eligible contributor amounts every Sunday at 23:59 Korea time from verified clean results, with a durable weekly record and operator approval before payment.

### Changed

- Include exactly four accumulated unpaid approved hours in payment eligibility, including fractional recording durations. Keep late reviews pending for the next weekly snapshot and preserve existing approved payouts.

## [0.1.4.0] - 2026-09-16

### Fixed

- Limit account-deletion receipt retries to 20 per account per rolling day across server workers, with a Retry-After response. Previously issued receipts and deletion status remain available.

## [0.1.3.0] - 2026-09-16

### Fixed

- Keep every issued account-deletion receipt valid across retries and after the login is removed, including receipts issued before this release.
- Preserve receipt hashes with additive migration 0018 and refuse a downgrade that would revoke issued receipts.

## [0.1.2.0] - 2026-09-16

### Fixed

- Identify recordings from configured business upload destinations automatically, so PSDN uploads appear under PSDN in Ops instead of Unassigned.
- Preserve source attribution through rescans and Raw retirement, support registered nested delivery folders in Clean, and keep business footage outside individual earnings.
- Release resolved attribution holds while preserving processing holds for changed source files.

## [0.1.1.0] - 2026-09-16

### Fixed

- Play new Clean batches in Chrome with verified H.264 stereo previews, including recording review and link reloads.
- Keep browser playback on preview files between recordings and require a complete preview before publishing future Clean batches.

## [0.1.0.0] - 2026-09-15

### Added

- Track Sieve collected and inherited hours, diversity, intake dates, and blocked recordings in a temporary Operations tab through September 25.
- Inherit versioned Clean MP4, original metadata and calibration into Sieve with retryable copies and a role that cannot read Raw.

## [0.0.8.0] - 2026-09-15

### Fixed

- Attribute contracted factory footage to its business and country in Raw and Clean, keeping it separate from individual contributors and payouts.
- Preserve confirmed business ownership during camera assignment and processing; refuse Clean imports with mismatched business, source session, or region.
- Use the source country's collection date for business footage reviews and keep its hours in regional totals without an individual payment estimate.

## [0.0.7.1] - 2026-09-15

### Fixed

- Import existing segmented EGO footage into Clean with its original episode identity and camera-matched calibration. Source-location checks and duplicate-earnings protection remain in effect.

## [0.0.7.0] - 2026-09-15

### Changed

- Start Clean with region selection and collected, accepted, excluded hours, acceptance rate, and recording/contributor/camera counts.
- Browse contributors, combined footage and review ledgers within the selected region, keeping each region's totals visible while filtering people.
- Derive collection geography from preserved source records and hold missing or conflicting batches under Needs region review. Joined videos do not duplicate hours.

## [0.0.6.0] - 2026-09-15

### Fixed

- Record externally paid Clean footage against exact existing earnings, preserving rates and accepted time while keeping incentives separate.
- Show external payment reports and incentive breakdowns in Payment, with recipient delivery explicitly unverified until provider evidence is available.
- Keep versioned private receipts and prevent duplicate transfer imports or payment of already reserved footage.

## [0.0.5.0] - 2026-09-15

### Fixed

- Require each new retained Clean recording to include versioned, camera-matched calibration alongside stereo video, frames, IMU and timing.
- Verify calibration file contents, image geometry and hashes before importing a new result. Historical Clean playback and existing earnings remain readable without rewriting payment records.

## [0.0.4.1] - 2026-09-14

### Fixed

- Allocate each Clean run's rounded KRW total consistently across recordings so splitting reviews or payouts cannot change the final amount.
- Backfill confirmed camera ownership for historical IDs with mixed case or surrounding spaces. Existing owners, paid sources and Clean/payment records remain unchanged.

## [0.0.4.0] - 2026-09-14

Prepared release. This entry records the implementation, not a completed deployment.

### Added

- Separate Raw processing, Clean review, Payment and Users workflows. Raw monitors pending, recoverable and rejected sources; approval and payment controls move to the contributor ledgers.
- Durable processing claims, expiring worker leases and exact source receipt reconciliation. Missing data requires recovery or a recorded rejection reason; matching episode names alone cannot clear Raw.
- Clean v2 requires separate left/right videos, every retained frame for both eyes, measured IMU, a frame index and a shared sensor timeline. Both eyes use the same accepted intervals, and accepted time is counted once.
- Recording-specific footage review, collection-date confirmation, exclusion breakdowns and immutable payout reservations. Korean payouts use KRW 11,000/hour, strictly more than four accumulated unpaid reviewed hours and Friday 18:00 Korea scheduling for completed collection weeks.
- Contributor contact, workplace, location, camera assignments and decoded-time summaries, with the four confirmed Korean camera contributors seeded by migration `0014`.
- Registration integration contracts for `Korea666`, `China666`, `Vietnam666` and `India666`, country-specific phone verification, private contributor document storage and upload-region attribution. Mobile onboarding and account linking remain a separate integration.

### Fixed

- New Clean batches require a confirmed owner for every decoded recording and a single contributor across the batch. The current camera holder cannot silently replace missing historical ownership.
- Payment approval is bound to the exact recipient details shown to the operator. Recipient changes require a refreshed review; refreshing clears previous payment confirmation.
- Automated scans and payout execution have separate controls. `OPS_PAYOUT_AUTOMATION_ENABLED` defaults to `false`, independently of scan scheduling and Wise balance funding.
- Existing Clean footage, contributor attribution, rate snapshots and historical payment values remain unchanged. Legacy video-only results remain viewable and are identified as historical exports.

### Rollout requirements

- Apply migration `0014` before releasing the new API and Ops UI.
- Companion catalog changes prepare AWS on-demand extraction from trusted, reviewed plans and publication of verified Clean artifacts. This is not an automatic activity-QC planner; that planner and the complete mobile trial remain pending. No deployed worker or completed backfill is claimed here.
- Validate Wise credentials, recipient requirements, retries, returned transfers and settlement reconciliation before enabling production payouts. A sent transfer remains distinct from confirmed payment; this release does not itself initiate a payout.

## [0.0.3.0] - 2026-09-14

### Fixed

- Clean now shows one section per contributor with combined playback, retained time, and the total unpaid estimate. Batch details, individual videos, and review notes remain expandable within that section.

## [0.0.2.0] - 2026-09-13

### Fixed

- Clean can show one verified video joining a contributor’s existing batches in recording-date order, without counting earnings twice.
- Raw labels partially processed episodes clearly and explains why additional or failed files remain.

## [0.0.1.0] - 2026-09-13

### Fixed

- Raw now shows pending footage separately from processed collections and unavailable media, while preserving episode and payment history.
- Re-uploaded processed copies no longer obscure new segments in the same recording. Playback finds pending files across delivery folders.
- Raw storage reflects pending files; recording metadata minutes are clearly distinguished from accepted hours in Clean.
