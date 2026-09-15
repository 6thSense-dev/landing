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

## 2026-09-15 — Operations intake integration candidate

- Branch: `intake/operations-integration-20260915`; isolated worktree `/data/projects/6thsense/landing-operations-integration-20260915`; base main `1f8e8cc93bc4b7c88fbad5d88249c613ca4ef15a`.
- Implementation/test freeze: `3dc0c7e6d03cdffec248d1d16d9537c98d69045f`. Receipt/ledger commit above that freeze changes documentation only. Exact integration commits and C01/C02/C03/C04/C05/C07/fixture-fix provenance are recorded in `docs/OPS-INTAKE-INTEGRATION-20260915.md`.
- Integrated explicit bounded inventory/source selection, actual QC-policy/rate/flag labels, source-contextual playback and renewal race protection, and append-only task/criteria/source reviews with exact nanosecond unions.
- Preserved current contributor grouping, confirmed historical attribution, stereo/frame/IMU format requirements, Raw mutation fences, independent FootageReview attestations, payment recipient fencing, and split-payout rounding. No whole old UI transplant. Migration 0016 follows unchanged current 0015; main already contains the fixture-fix behavior.
- Validation: 606 full backend tests passed together at the frozen revision (138.09s); 66 Operations browser cases across 375/768/1280 plus production build; 13 Node unit tests; 4 focused migration/integration tests. Disposable migration cycle verifies existing historical Raw and reserved payout/recipient/attestation rows stay identical. Synthetic media actually decodes, seeks and plays. All heavy jobs used bounded `flock /tmp/intake-night-heavy-20260915.lock`, one at a time.
- Setup limitations resolved without weakened tests: full pytest needs `PYTHONPATH=.:..`; synthetic media mock needs byte-range support for seeking. Full results/logs, commands and remaining evidence limits are in the receipt.
- Outcome: local implementation complete; **different-model review pending in the later runner phase**. Author did not perform or claim independent review. No push/open PR. Reserved draft title: **Integrate intake review and inventory with current Operations**.
- Existing older PRs/worktrees and owner work preserved. No AWS/login/credential inspection, production changes, deployment, main merge, raw moves/deletion, payment, dataset publication or Research/paid experiment. Production integrity/clocks/mapping, agreement terms and settlements remain unknown.
