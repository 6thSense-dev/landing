# Clean tab evidence labels

This change preserves Alex's cleaner backend, rate calculations, imports, camera assignments and playback. It changes how existing evidence is described.

- QC-retained time is a processing result, not task-specific usable time or accepted training data.
- The run's actual `policy` is rendered as escaped JSON. Missing, null or empty policy is explicitly unknown. No threshold is inferred from the software version or substituted from another run.
- Estimates still use the existing backend output and existing unpaid-filter aggregation. They do not establish collector credit under an agreement or verified payment settlement.
- A paid flag is displayed as a flag, without claiming transfer evidence.
- Run rates are saved snapshots; sidebar contributor rates and details are current records. Neither proves historical agreement terms.

Synthetic Playwright tests cover policy variation and escaping, absent policy, missing rate, differing current/snapshot rates, unchanged displayed durations and amounts, no mutations during loading, and unchanged explicit refresh action. Three configured viewports are 375, 768 and 1280 pixels. No production recordings, payments or cloud writes are exercised.

Outstanding: no task-validation, agreement reconciliation, settlement evidence, or unique-source deduplication is implemented here. Retained aggregates continue to use existing run arithmetic. Production QC policy correctness remains unverified.

## Validation

`E2E_PORT=4280 npx playwright test tests/e2e/ops-clean-evidence.spec.js --workers=2`: 12 passed, covering all three configured viewports. Playwright built the production Vite bundle successfully before serving it. Existing large-chunk and FORCE_COLOR warnings remain. Mocked API responses are explicitly synthetic; no real video playback or production API response is validated.
