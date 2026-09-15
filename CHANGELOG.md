# Changelog

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
