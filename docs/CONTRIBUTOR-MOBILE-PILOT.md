# Contributor mobile pilot

The mobile API connects verified Cognito subjects to new Ops wearer records. It never infers an account from an existing name or a camera. Existing business-source attribution, raw/clean ledgers and payout approval remain authoritative.

## Trial flow

1. The private Synapse build signs up with the public regional selector `Korea666`, the user's verified test mobile number and a password. Cognito sends the confirmation code. Signup is restricted to the already verified AWS SMS sandbox destination; it does not open general registration. No account or recording is precreated.
2. The user names their account. `/api/contributor/enrollment` creates its wearer once. The immutable routing version comes from verified Cognito attributes, never from an app-supplied bucket.
3. An operator publishes the approved participation, privacy and collection documents, each in a versioned S3 object with a SHA-256 digest. The user reads and accepts all three in their chosen language. Until actual documents are published, camera and bank registration remain unavailable.
4. Hotspot detection identifies the camera. The user reconnects to the internet and sends a registration request. Ops → Users → Mobile contributor requests requires an operator's physical ownership confirmation, an active contributor and current consent. Assignments begin at approval time; earlier footage is never claimed automatically.
5. Use the existing camera controls to record. The first pilot retains manual SD-card offload into the existing `6thsense-raw/sessions/` layout. Upload every original and sidecar. No contractor destination changes are required by this integration. Only completed recordings with trusted NTP capture time fully inside a confirmed assignment are automatically attributed. Unknown time, pre-assignment recordings, or handovers need explicit Ops source attribution.
6. The existing raw scan and QC pipeline ingest and review footage. Ronak controls QC; the phone cannot approve duration. The dashboard reads the signed-in contributor's actual source/QC/payment records. Unknown approval stays pending.
7. The app retrieves current KRW/INR bank requirements from Wise and submits the user's details only after consent and explicit bank ownership/sharing acknowledgments. Raw bank details are never persisted by this integration. In Ops → Users → Mobile contributor requests, review the contributor name/ID, masked summary and known Wise recipient ID, check the ownership confirmation, then select **Verify and link recipient**. Payment linking currently accepts KRW recipients only.
8. Existing payment approval reserves reviewed work exactly once. Korea pays ₩11,000 per accepted hour after **more than** four accumulated unpaid approved hours. India has no agreed rate and no INR payment execution in this pilot. Friday scheduling covers previous completed weeks. Funding/sending is not settlement. Automatic payment funding remains off.

## API and supervision

All `/api/contributor/*` account routes require a Cognito access token. The server restricts issuer/client/token kind, then calls Cognito GetUser to verify the token and current phone/routing attributes. Staff cookie auth does not grant mobile access. `/configuration` is public and contains only mobile client configuration and pilot mode.

The `/api/ops/contributors` routes use the existing staff role gate and CSRF origin check. Operators can list requests, approve physical camera assignments, publish verified terms, export immutable consent receipts, and reconcile recipient attempts. The user-facing account cannot call these routes.

| Route | Purpose |
| --- | --- |
| `GET /api/contributor/configuration` | Public identity-client and pilot-mode configuration; the Cognito signup gate enforces registration eligibility. |
| `POST /api/contributor/enrollment` | Create the authenticated subject's wearer once, using a nonempty `name`. |
| `GET /api/contributor/terms?locale=en` | Published document versions and signed URLs; `en` and `ko` are supported. |
| `POST /api/contributor/consent` | Accept the current three agreement hashes for the supplied `locale`. |
| `POST /api/contributor/cameras` | Request supervised registration using `device_id`; discovery alone creates no assignment. |
| `GET /api/contributor/dashboard` | The account's source/approved totals, recording status, claims, masked bank state and payouts. |
| `POST /api/contributor/bank/requirements` / `POST /api/contributor/bank` | Live recipient requirements and durable submission; both require current consent. Submission also requires a unique `operation_id` and ownership/sharing confirmations. |
| `GET /api/ops/contributors` | Staff request queue; loading it or the Users panel does not call Wise. |
| `POST /api/ops/contributors/cameras/{claim_id}/approve` | Approve an active contributor's request with `physically_verified: true`; conflicting assignments are refused. |
| `POST /api/ops/contributors/recipients/{attempt_id}/resolve` | Record `found` or `not_created` evidence without approving a payout. |
| `POST /api/ops/payments/recipient` | Existing separate Wise verification/link operation; requires `wearer_id`, `recipient_id` and `confirm_recipient: true`. |

`POST /api/ops/contributors/terms/{routing_version}` accepts:

```json
{
  "approved_for_publication": true,
  "documents": [
    {"agreement":"participation","locale":"en","version":"APPROVED_VERSION","key":"terms/korea/participation/APPROVED_VERSION/en.pdf","object_version":"S3_VERSION_ID","sha256":"ACTUAL_SHA256"},
    {"agreement":"privacy","locale":"en","version":"APPROVED_VERSION","key":"terms/korea/privacy/APPROVED_VERSION/en.pdf","object_version":"S3_VERSION_ID","sha256":"ACTUAL_SHA256"},
    {"agreement":"collection","locale":"en","version":"APPROVED_VERSION","key":"terms/korea/collection/APPROVED_VERSION/en.pdf","object_version":"S3_VERSION_ID","sha256":"ACTUAL_SHA256"}
  ]
}
```

Include all three agreement IDs for each published language. Both English and Korean should be provided for the trial. The endpoint verifies the actual versioned bytes before publication; this example is not a terms document or legal approval. Documents are read through short-lived signed URLs. Consent receipts are durable database records; `POST /api/ops/contributors/consents/export` exports original receipts idempotently to private S3. Automatic export is not yet scheduled.

A recipient submission is committed before its provider request. Unknown outcomes remain held, including after a process crash. Never release a hold merely because the app timed out. In Ops, resolve it only after confirming a specific recipient or confirming that no recipient was created. Resolution records operator, timestamp, provider profile/environment and a note without bank details. A confirmed no-create outcome permits a new submission with a new operation ID. Payout linking/approval remain separate.

For an unknown outcome, select **Recipient found** or **No recipient was created** in the Users panel. Enter a verification note of 10–500 characters without bank details and check the corresponding confirmation. A found recipient also requires its ID and verified ownership; the backend checks its active state, ID, currency, profile and hash before returning it to review. Confirmed no-create changes the attempt to `retry_allowed`; the old operation ID cannot be reused. A `submitting` attempt must be at least five minutes old before reconciliation, and age alone never proves that creation failed. The audit is written once under `contributor_bank_audit_<attempt-id>` and cannot be replaced by a conflicting resolution. Refreshing requests clears approval checkboxes, and the read-only workspace preview has no request controls.

## Deployment and validation

Migration 0016 is additive. Empty installations can downgrade; populated mobile audit tables deliberately block destructive schema rollback. Roll back application code while retaining these tables if needed.

Configure `CONTRIBUTOR_COGNITO_POOL` and `CONTRIBUTOR_COGNITO_CLIENT`; the region defaults to `us-west-2` through `CONTRIBUTOR_COGNITO_REGION`. `CONTRIBUTOR_SIGNUP_MODE` labels the public configuration and defaults to `closed`; it does not replace the Cognito signup gate. S3 access uses the configured `OPS_AWS_ACCESS_KEY_ID` / `OPS_AWS_SECRET_ACCESS_KEY` pair and `OPS_S3_REGION` for versioned terms reads and consent exports. Cognito GetUser authenticates with the caller's access token, and Wise uses existing server-only credentials. No AWS or Wise credentials go into the app.

From the repository root, run backend tests with a disposable PostgreSQL database ending in `_test`; fixtures create and drop application tables:

```sh
PYTHONPATH=.:backend TEST_DATABASE_URL=postgresql+asyncpg://USER@localhost:PORT/contributor_test python -m pytest -c backend/pytest.ini backend/tests
```

Validation on 2026-09-15 included a 572-test backend run, later focused payment/metadata checks, the frontend production build and 15 Playwright checks across 375, 768 and 1280-pixel widths. Browser checks cover separate camera/bank confirmations, recipient recovery, failed loading, and the existing Raw → Clean → Payment workflow. These are local tests with provider calls mocked where appropriate.

External acceptance still requires real approved regional documents, a user-created verified account, a physical camera, actual SD-card offload, Ronak's QC and eligible operator-approved payout. Terms are absent, SMS remains restricted to one verified Korean sandbox destination, and the full account/hardware/payment trial is not complete. Tests do not manufacture any of these or send production money. See the [shared contract](CONTRIBUTOR-CONTRACT.md), [registration policy](CONTRIBUTOR-REGISTRATION.md), [storage contract](CONTRIBUTOR-STORAGE.md) and [Ops workflow](OPS-WORKFLOW.md) for the adjoining responsibilities.
