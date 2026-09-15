# Operations intake integration — author receipt, 2026-09-15

## Delivery state

Local candidate on `intake/operations-integration-20260915`, based on current main `1f8e8cc93bc4b7c88fbad5d88249c613ca4ef15a`.
Implementation/test freeze: `3dc0c7e6d03cdffec248d1d16d9537c98d69045f`. Subsequent receipt/ledger commit is documentation only.

**Independent different-model review remains pending in the runner's later phase.** This receipt reports author implementation and executed tests, not independent review. No push or PR creation has occurred. Older PRs and other worktrees remain untouched.

Reserved draft PR title: **Integrate intake review and inventory with current Operations**.

## Integrated behavior

- Raw has an explicit bounded inventory check and server-configured source selector. Opening the selector does not LIST storage. Observations are scoped; partial, denied, nested/out-of-scope metadata and unknown states remain distinct. Source changes cancel older UI requests. No import, raw mutation or automatic source migration is added.
- Current contributor-grouped Clean retains collection and batch viewing. Batch details show actual policy, saved rate/estimate and historical paid-flag labels. QC retention, task usability, agreement credit, settlement, annotation quality and dataset acceptance remain separate. No new thresholds or production totals are inferred.
- Contextual interval playback requires an explicit clean offset. Recording-level payment playback starts at zero. Historical previews and current stereo videos stay supported; missing/ambiguous sources fail closed, contextual lists exclude other recordings, and contextual playback never auto-advances. Play/renewal/close/file-switch races are fenced, and renewals preserve key/recording/role/version/digest identity.
- Task reviews remain append-only complete snapshots keyed by run/task/revision and bound to manifest, source pins, criteria and server-derived reviewer. Exact integer-nanosecond unions count same-judgment overlaps once; contradictory overlaps reject. Missing/uncovered time remains unknown. No physical-hour, payment, annotation or dataset inference is added.
- Migration `0016_activity_reviews.py` follows main's `0015`; existing `0014` workflow and `0015` normalized-camera migrations are unchanged. Task reviews coexist with `FootageReview` and the Payment ledger.

## Candidate provenance

| Candidate | Original exact SHA | Integration |
|---|---|---|
| C01 inventory | `fb837020027f6c1688afa19a785e0faac5e266d2` | Combined with C07, add-only endpoints/panel on current Raw/Payment navigation |
| C07 source registry | `a0f9af5f1ea1d3401321a6e91f8d1175c8266c49` | Registry, bounded source selection, current scope/provenance and tests reused |
| C02 evidence labels | `132c5b3ba92634b449e7cb286461014a1af4d6b7` | Adapted to current grouped batch details; historical flags separated from current Payment |
| C03 timeline bounds | `5b161da937dd56009679cc93bb7e87a9fb57a869` | Combined with main's multimodal schema, duplicate-output and format validation |
| C04 contextual playback | `e1b5606b43c820b05e0b8d591a250e1e0e17db45` | Adapted to collection/stereo paths; strict contextual playlists and pinned renewals |
| C05 task reviews | `69cd9b27f50980bc91b1e9919e97b3b33b1a3d36` | Additive backend/model/route/form; migration renumbered to 0016 |
| Seed fixture fix | `a15bd3d7360028b2dd0e03783f1d8029f076f49a` | Main already implements the actual-0002 fixture correction; preserve main's version, reverify tests |

Main safeguards read before integration: contributor workflow `010f34b`, stereo/frame/IMU requirement `454a775`, attribution/recipient fencing `7428dc4`, split-payout rounding `5eb7b99`, and their merge head above. No candidate replaces main's whole UI.

The current payment route, Clean import/attribution route, ledger arithmetic, artifact validator, automation, existing workflow/camera migrations, `FootageReview`, `OpsPayments` and seed fixture are byte-identical to base. The shared manifest validator incorporates bounds/shape checks while retaining main's format requirements.

## Implementation commits

| Exact SHA | Logical unit |
|---|---|
| `9b44199e311e7c7f6a62a2e2914039fa03d66383` | Integrate bounded configured source inventory alongside current Operations |
| `055277a99765e1a6782c48329c2036f807600aad` | Validate decoded interval bounds while retaining multimodal Clean contracts |
| `8fb4b2b4843e1d22c7409eef774a1d2db143bebd` | Add append-only source and task reviews after current workflow migrations |
| `3d92437a38d66963bd7e9d366669ae3557059ddb` | Integrate task review and contextual playback into contributor Clean groups |
| `bee166139e1ed46feca686f90862e3b05615c590` | Verify task review isolation against current contributor and split payout ledgers |
| `3acc81c98e4bf9bb66da80151e4785bc4a1c5902` | Exercise stereo and collection playback races without inferring physical time |
| `a8a91f571829fcda17d30f3cc013c43afc876ff8` | Verify decoded synthetic playback and preserve grouped Clean browser coverage |
| `959ad8654906111220b538c916194540ffd0c0bf` | Prove additive review migration preserves historical and reserved workflow rows |
| `87a179d02214de8bff50fe7c174e53d08fdef062` | Document current workflow compatibility and evidence boundaries |
| `3dc0c7e6d03cdffec248d1d16d9537c98d69045f` | Model seekable byte-range media responses in contextual playback test |

## Verification

All heavy jobs acquired `flock -w 45 /tmp/intake-night-heavy-20260915.lock`; each command had a 120–600 second outer timeout. One heavy job ran at a time; browser workers=1, retries=0 on the final run. Existing dependencies were reused without upgrades. Database work used disposable Postgres testcontainers only.

- Final complete backend suite at the implementation/test freeze: **606 passed**, 219 dependency warnings, 138.09 seconds. Current ledger safeguards and the new task-review integration/migration tests ran together in this revision.

- Production build plus all Operations Playwright specs: **66 passed**, three viewports (375/768/1280), at implementation/test freeze above. Includes existing grouped Clean and Payment tests, inventory, exact task draft/conflict behavior, fail-closed matching, stereo, renewal/collection races, and actual synthetic media decode/seek/play. Served the production build on loopback port 4187; test server exits with Playwright.
- Node unit suite: **13 passed**, including contributor grouping/totals and workspace request races.
- Additional migration/review gate: **4 passed**, including populated `0015 → 0016 → 0015` round trip, preservation of historical Raw and reserved payout/recipient/attestation rows, and task-save isolation from current split-payout allocations and confirmed attribution.
- Earlier combined backend gate: 189 passed. Earlier full backend run: 605 passed before the additional populated migration test was added.
- `git diff --check`: passed.

Commands (from the indicated directory):

```sh
# backend/
flock -w 45 /tmp/intake-night-heavy-20260915.lock timeout 600 env PYTHONPATH=.:.. /tmp/landing-e08-venv/bin/python -m pytest -q

# frontend/; Playwright builds and serves this worktree's production bundle
flock -w 45 /tmp/intake-night-heavy-20260915.lock timeout 480 env E2E_PORT=4187 CI=1 node node_modules/@playwright/test/cli.js test 'ops-.*spec.js' --workers=1 --retries=0
node --test tests/*.test.mjs
```

Local runner logs: `/tmp/operations-integration-backend-final.log`, `/tmp/operations-integration-browser-final.log`, `/tmp/operations-integration-migration-final.log`. Playwright screenshots are in this worktree's ignored `frontend/test-results/` (synthetic media, collapsed Clean, and Payment for each viewport).

### Resolved validation setup issues

1. Running full pytest from `backend/` without the repository root on `PYTHONPATH` failed collection of existing `tests/test_catalog_upload_bundle.py` (`No module named scripts`). Corrected only the invocation to `PYTHONPATH=.:..`; no test was removed or weakened. No baseline assertion failures remained in the full suite.
2. The added media test initially modeled a nonseekable whole-body response. All 63 other browser cases passed; the 3 synthetic seek checks stayed at zero. The mock now implements byte ranges like the pinned object server. The exact decode/seek/play assertions pass without a player workaround.
3. The existing grouped Clean test asserted a playlist index of 1. Contextual lists intentionally exclude the joined/other recording; it now asserts the exact recording URL and a single contextual option, retaining its other grouping/collection/interval checks.

Existing warnings: large Vite chunk, Node color settings, and dependency deprecations (testcontainers/httpx). These are not production validation.

## Limits and next runner phase

- No AWS calls, credential reads, login, deployment, production DB migration, main merge, raw deletion/move, payments, dataset publication, or Research/paid experiments were performed. Provider behavior is mocked; known cloud-auth gaps were not retried.
- Source integrity, current cloud access/configuration, physical-clock synchronization, real media mapping, historical agreement terms and settlement evidence remain unknown/unverified. Synthetic totals are test fixtures only.
- The API supports historical task revisions; the UI edits the latest revision. Unknown evidence is not filled from current rate/contributor snapshots.
- Different-model review is required next. After any review fixes, the runner should rerun affected safeguards and only then decide whether to push/create the reserved draft PR. Existing older PRs stay open. This author did not complete or claim that review.

## Local log fingerprints

- `operations-integration-backend-final.log` SHA-256: `7769797064a5f19b2ff1b48d6ddf1146ca2a0c04b7579a241a0b53fff5fb7856`.
- `operations-integration-browser-final.log` SHA-256: `8849f430a86a0f0a77311aefaf04d6e132a21ee713c213f681432cbe6230a223`.
- `operations-integration-migration-final.log` SHA-256: `61d468bbdb1faa5b6629bf2df9770f84de77ef2b9b01003f79d0ebc5ece32bb2`.
