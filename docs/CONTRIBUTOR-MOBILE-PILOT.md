# Contributor mobile pilot

This page retains the original mobile-pilot procedure and dated verification results. The Korean website now also implements the [Google Form contract workflow](contributors/google-form-register.md), including secure password setup and supervised camera preapproval. Its release guide is the source for that workflow's current rollout checks; historical sandbox and unpublished-terms observations below are not fresh production measurements.

The mobile API connects verified Cognito subjects to new Ops wearer records. It never infers an account from an existing name or a camera. Existing business-source attribution, raw/clean ledgers and payout approval remain authoritative.

## Trial flow

1. The private Synapse build signs up with the public regional selector `Korea666`, the user's verified test mobile number and a password. Cognito sends the confirmation code. Signup is restricted to the already verified AWS SMS sandbox destination; it does not open general registration. No account or recording is precreated.
2. The user names their account. `/api/contributor/enrollment` creates its wearer once. The immutable routing version comes from verified Cognito attributes, never from an app-supplied bucket.
3. An explicitly authorized company founder publishes the approved participation, privacy, collection and international-transfer documents, each in a versioned S3 object with a SHA-256 digest. The user reads and separately accepts all four in their chosen language; every checkbox starts unselected. Until actual documents are published, camera and bank registration remain unavailable.
4. Hotspot detection identifies the camera. The user reconnects to the internet and sends a registration request. Ops → Users → Mobile contributor requests requires an operator's physical ownership confirmation, an active contributor and current consent. Assignments begin at approval time; earlier footage is never claimed automatically.
5. Use the existing camera controls to record, then manually offload the SD card through the [browser upload page](#browser-upload-from-an-sd-card) into the existing `6thsense-raw/sessions/` layout. Upload every original and sidecar. No contractor destination changes are required by this integration. Only completed recordings with trusted NTP capture time fully inside a confirmed assignment are automatically attributed. Unknown time, pre-assignment recordings, or handovers need explicit Ops source attribution.
6. The existing raw scan and QC pipeline ingest and review footage. Ronak controls QC; the phone cannot approve duration. The dashboard reads the signed-in contributor's actual source/QC/payment records. Unknown approval stays pending.
7. The app retrieves current KRW/INR bank requirements from Wise and submits the user's details only after consent and explicit bank ownership/sharing acknowledgments. Raw bank details are never persisted by this integration. In Ops → Users → Mobile contributor requests, review the contributor name/ID, masked summary and known Wise recipient ID, check the ownership confirmation, then select **Verify and link recipient**. Payment linking currently accepts KRW recipients only.
8. Existing payment approval reserves reviewed work exactly once. Korea's rate is ₩11,000 per accepted hour, with eligibility at **at least** four accumulated unpaid approved hours, including fractional recording durations. Sunday 23:59 Asia/Seoul calculation prepares a weekly snapshot from qualifying reviews completed by the cutoff; manual approval recalculates the live ledger and can include later reviews for eligible collection dates. India has no agreed rate and no INR payment execution in this pilot. Funding/sending is not settlement. `OPS_PAYOUT_AUTOMATION_ENABLED` and `OPS_WISE_AUTO_FUND` remain `false`. See the [calculation and approval workflow](OPS-WORKFLOW.md#payment-policy-and-operation).

## Browser upload from an SD card

Open `https://6thsense.dev/upload` on the computer with the SD card. Existing contributors use their established account. New Korean contributors follow the [final Form contract and website activation flow](contributors/google-form-register.md#participant-and-operator-flow) once released. The older application acknowledgment does not constitute that contract. The page supports Korean and English, and requires an active enrolled account with current consent and an approved camera assignment.

1. Sign in with the verified phone number including its country code and the account password. For a Korean number, use `+82` and omit the leading `0`. **Forgot password?** sends a reset code to the registered phone. The page refreshes access tokens during long uploads; if the session ends, sign in again.
2. Stop recording before removing the SD card. Drop a complete `ego_YYYYMMDD_HHMMSS_CAMERA` folder onto the page or use **Choose folders**; a parent folder containing several episodes also works. Keep original folder and file names, `metadata.json`, video or `.egoc` recordings, and sensor sidecars together.
3. Select **Upload episodes** and keep the tab open. Each file can be at most 100 GiB, each episode can contain at most 2,000 files, and each account can register up to 500 GiB and 500 new episodes in a rolling 24 hours. The displayed allowance includes registered unfinished uploads.
4. Use **Pause** / **Resume upload** as needed. After closing the tab or a network interruption, sign in and select the same unchanged folders to resume. Completed files and acknowledged parts are retained; an unfinished file may restart after S3 removes an abandoned multipart upload seven days later. Keep the originals until receipt and review are confirmed.
5. **Received** confirms that the server verified the delivery and wrote its completion receipt. An operator then scans Raw to refresh the queue. QC review and payment approval remain separate. Operations records the signed-in uploader without substituting that person for the recording's capture-time owner.

An ended camera assignment can still accept delayed footage, but finalization requires verified capture time wholly within that contributor's approved assignment. Contact 6thSense if agreements, camera approval, changed originals or an existing recording block upload. Conflicting completed source locations require operator source review and a rescan before processing can continue. Storage, permissions and API details are in the [backend upload guide](../backend/README.md#contributor-browser-uploads).

## API and supervision

### Website payment details

Korean individual contributors can use [Payment details](https://6thsense.dev/upload#payment-details) after signing in with a current contract. Camera approval is independent. They review the payment notice, separately confirm collection/use, financial-provider sharing, overseas transfer and account ownership, then enter the current Wise-required fields. Bank details never need to be emailed to staff. Payment setup remains optional for uploading.

`GET /api/contributor/bank/setup` returns only the caller's masked bank status and the versioned Korean/English notice. `POST /bank/web/requirements` and `POST /bank/web` require its exact version/hash, language and all four acknowledgments before contacting Wise. The submission freezes that notice and the acceptance time with the durable attempt. Raw bank numbers, birth dates and address/contact fields are forwarded to Wise without database persistence; responses prohibit caching. These website endpoints currently support Korean individual recipients only; the mobile endpoints remain compatible.

Finance reviews requests at **Ops → Users → Mobile contributor requests**, verifies ownership and selects **Verify and link recipient**. Existing manually linked recipients show as verified. Interrupted or ambiguous submissions remain held for operator reconciliation and never cause an automatic second recipient-creation request. The contributor can refresh status; requested corrections go through staff without emailing the account number. Recipient verification does not approve footage, calculate new earnings or send money.

The production Wise requirements route was checked read-only on 2026-09-18. Automated tests use simulated recipients; they do not create real recipients or send payments. See [Wise's KRW guide](https://wise.com/help/articles/2932331/guide-to-krw-transfers) for bank verification that PayGate may separately request when a payment is sent.

Validation for this change passed 64 focused backend tests and 60 browser checks across mobile, tablet and desktop. Coverage includes consent/version enforcement, account isolation, masked persistence, ambiguous writes, recovery after operator-confirmed non-creation, pre-camera setup, unchanged uploads and existing Ops recipient approval. The Korean notice and form were visually checked at 375 and 1280 pixels.

### Authenticated routes

Authenticated `/api/contributor/*` account routes require a Cognito access token. The server restricts issuer/client/token kind, then calls Cognito GetUser to verify the token and current phone/routing attributes. Staff cookie auth does not grant mobile access. `/configuration` is public and contains only mobile client configuration and pilot mode. The [deletion receipt endpoint](CONTRIBUTOR-DELETION.md#mobile-api) uses its own Bearer token so original and retry receipts remain usable after the login is removed; `/notice` serves published pre-account notices without authentication.

The `/api/ops/contributors` routes use the existing staff role gate and CSRF origin check. Operators can list requests, approve physical camera assignments, export immutable consent receipts, and reconcile recipient attempts. Terms publication additionally requires the authenticated staff email to appear in the server-only `CONTRIBUTOR_TERMS_FOUNDER_EMAILS` allowlist. A staff role, including `founder`, does not itself grant this authority; an empty or absent allowlist denies everyone. The user-facing account cannot call these routes.

| Route | Purpose |
| --- | --- |
| `GET /api/contributor/configuration` | Public identity-client/pilot configuration plus `threshold_seconds: 14400`, `threshold_comparison: at_least`, `calculation_schedule: Sunday 23:59` and `calculation_timezone: Asia/Seoul`; payment remains `operator_approved`. The Cognito signup gate enforces registration eligibility. |
| `POST /api/contributor/enrollment` | Create the authenticated subject's wearer once, using a nonempty `name`. |
| `GET /api/contributor/terms?locale=en` | Published document versions and signed URLs; `en` and `ko` are supported. |
| `POST /api/contributor/consent` | Accept all four displayed agreements using `documents` (agreement → SHA-256), `versions` (agreement → version), and the exact `locale`. Missing or stale hashes/versions fail closed. |
| `POST /api/contributor/cameras` | Request supervised registration using `device_id`; discovery alone creates no assignment. |
| `GET /api/contributor/dashboard` | The account's source/approved totals, recording status, claims, masked bank state and payouts. |
| `POST /api/contributor/bank/requirements` / `POST /api/contributor/bank` | Live recipient requirements and durable submission; both require current consent. Submission also requires a unique `operation_id` and ownership/sharing confirmations. |
| `GET /api/ops/contributors` | Staff request queue; loading it or the Users panel does not call Wise. |
| `POST /api/ops/contributors/cameras/{claim_id}/approve` | Approve an active contributor's request with `physically_verified: true`; conflicting assignments are refused. |
| `POST /api/ops/contributors/recipients/{attempt_id}/resolve` | Record `found` or `not_created` evidence without approving a payout. |
| `POST /api/ops/payments/recipient` | Existing separate Wise verification/link operation; requires `wearer_id`, `recipient_id` and `confirm_recipient: true`. |

Only an allowlisted founder with an active staff session and valid CSRF origin may call `POST /api/ops/contributors/terms/{routing_version}`. It accepts:

```json
{
  "approved_for_publication": true,
  "documents": [
    {"agreement":"participation","locale":"en","version":"APPROVED_VERSION","key":"terms/korea/participation/APPROVED_VERSION/en.pdf","object_version":"S3_VERSION_ID","sha256":"ACTUAL_SHA256"},
    {"agreement":"privacy","locale":"en","version":"APPROVED_VERSION","key":"terms/korea/privacy/APPROVED_VERSION/en.pdf","object_version":"S3_VERSION_ID","sha256":"ACTUAL_SHA256"},
    {"agreement":"collection","locale":"en","version":"APPROVED_VERSION","key":"terms/korea/collection/APPROVED_VERSION/en.pdf","object_version":"S3_VERSION_ID","sha256":"ACTUAL_SHA256"},
    {"agreement":"international_transfer","locale":"en","version":"APPROVED_VERSION","key":"terms/korea/international_transfer/APPROVED_VERSION/en.pdf","object_version":"S3_VERSION_ID","sha256":"ACTUAL_SHA256"}
  ]
}
```

Include all four agreement IDs for each published language. Old three-document bundles and receipts do not unlock the pilot. Both English and Korean should be provided for the trial. The endpoint verifies the actual versioned bytes before publication; this example is not a terms document or legal approval. Documents are read through short-lived signed URLs. Consent receipts are durable database records; `POST /api/ops/contributors/consents/export` exports original receipts idempotently to private S3. Automatic export is not yet scheduled.

Publication retains an insert-only `contributor_terms_audit_<publication-id>` record with founder email/user ID, approval time, routing version, payload hash and each document’s immutable version/hash/S3 reference. Retrying the same bundle preserves the original approval; replaying an older bundle cannot replace a newer current bundle. Rebinding a published document version to changed bytes or object references is rejected. Generic settings helpers reserve the entire `contributor_terms_*` namespace, and laptop imports cannot write settings. Runtime configuration, direct database access and staff-provisioning CLI access remain privileged infrastructure boundaries.

`CONTRIBUTOR_TERMS_FOUNDER_EMAILS` is a comma-separated list of exact authenticated staff emails, normalized for whitespace and case. Configure it only after the founders identify the authorized accounts; no live allowlist is configured by this change. Publication approval is never inferred from document upload, an Ops role, a code deployment or this example.

International-transfer consent is required separately throughout the private pilot because its infrastructure is in the US. It does not authorize third-party customer disclosure. Commercial customer licensing remains a separate legal and release gate until the actual recipients, purposes and applicable authorization basis are specified. No marketing consent or blanket waiver is bundled into these four agreements.

A recipient submission is committed before its provider request. Unknown outcomes remain held, including after a process crash. Never release a hold merely because the app timed out. In Ops, resolve it only after confirming a specific recipient or confirming that no recipient was created. Resolution records operator, timestamp, provider profile/environment and a note without bank details. A confirmed no-create outcome permits a new submission with a new operation ID. Payout linking/approval remain separate.

For an unknown outcome, select **Recipient found** or **No recipient was created** in the Users panel. Enter a verification note of 10–500 characters without bank details and check the corresponding confirmation. A found recipient also requires its ID and verified ownership; the backend checks its active state, ID, currency, profile and hash before returning it to review. Confirmed no-create changes the attempt to `retry_allowed`; the old operation ID cannot be reused. A `submitting` attempt must be at least five minutes old before reconciliation, and age alone never proves that creation failed. The audit is written once under `contributor_bank_audit_<attempt-id>` and cannot be replaced by a conflicting resolution. Refreshing requests clears approval checkboxes, and the read-only workspace preview has no request controls.

## Deployment and validation

Migration 0016 is additive. Empty installations can downgrade; populated mobile audit tables deliberately block destructive schema rollback. Roll back application code while retaining these tables if needed.
Account deletion also requires migrations 0017 and 0018. Retain the receipt schema and original/retry lookup code on application rollback; migration 0018 refuses downgrade once retry receipts exist. See the [deletion deployment and rollback guidance](CONTRIBUTOR-DELETION.md#deployment-and-rollback) and [separate regression and migration test commands](CONTRIBUTOR-DELETION.md#local-validation).

Browser upload requires additive migration `0019`, which adds three upload receipt tables and refuses downgrade once a batch exists. Preserve those tables during rollback. Enable `OPS_BROWSER_UPLOAD_ENABLED=true` only with the scoped S3 write grants, bucket CORS and versioning described in the [backend upload guide](../backend/README.md#contributor-browser-uploads). `OPS_UPLOAD_ACCELERATE=true` is the default and requires bucket acceleration.

Configure `CONTRIBUTOR_COGNITO_POOL` and `CONTRIBUTOR_COGNITO_CLIENT`; the region defaults to `us-west-2` through `CONTRIBUTOR_COGNITO_REGION`. `CONTRIBUTOR_SIGNUP_MODE` labels the public configuration and defaults to `closed`; it does not replace the Cognito signup gate. S3 access uses the configured `OPS_AWS_ACCESS_KEY_ID` / `OPS_AWS_SECRET_ACCESS_KEY` pair and `OPS_S3_REGION` for versioned terms reads and consent exports. Cognito GetUser authenticates with the caller's access token, and Wise uses existing server-only credentials. No AWS or Wise credentials go into the app.

From the repository root, run backend tests with a disposable PostgreSQL database ending in `_test`; fixtures create and drop application tables:

```sh
PYTHONPATH=.:backend TEST_DATABASE_URL=postgresql+asyncpg://USER@localhost:PORT/contributor_test python -m pytest -c backend/pytest.ini backend/tests
```

Validation on 2026-09-15 included a 572-test backend run, later focused payment/metadata checks, the frontend production build and 15 Playwright checks across 375, 768 and 1280-pixel widths. Browser checks cover separate camera/bank confirmations, recipient recovery, failed loading, and the existing Raw → Clean → Payment workflow. These are local tests with provider calls mocked where appropriate. The subsequent founder-publication/four-agreement update passed 150 targeted contributor, Ops, Clean, automation and source-attribution tests, including unauthorized publication, settings/import bypass attempts, concurrent approval retries, immutable audits and stale/missing agreement versions.

Browser-upload validation on 2026-09-17 passed 796 backend tests excluding migration tests, 38 Node tests and 15 Playwright checks (12 upload and three Raw). Migration `0019` upgrade and model checks passed separately. A real S3 smoke check verified presigned checksums, browser CORS preflight and multipart completion; its temporary objects were cleaned up.

External acceptance still requires real approved regional documents, a user-created verified account, a physical camera, actual SD-card offload, Ronak's QC and eligible operator-approved payout. The 2026-09-17 production check found one contributor account, no published terms and no approved camera claims, so onboarding still blocks participant uploads. SMS remains restricted to one verified Korean sandbox destination, and the full account/hardware/payment trial is not complete. Tests do not manufacture any of these or send production money. See the [shared contract](CONTRIBUTOR-CONTRACT.md), [registration policy](CONTRIBUTOR-REGISTRATION.md), [storage contract](CONTRIBUTOR-STORAGE.md) and [Ops workflow](OPS-WORKFLOW.md) for the adjoining responsibilities.
