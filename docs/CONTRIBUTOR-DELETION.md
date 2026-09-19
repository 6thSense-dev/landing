# Contributor deletion release contract

Receipt preservation is live. The retry-issuance limit documented below is a
follow-up awaiting deployment. Neither release publishes regional agreements,
enables signup, or establishes a legal retention period. No real user has been deleted.

## Mobile API

- Authenticated `GET /api/contributor/account-deletion` works before enrollment.
- Authenticated `POST /api/contributor/account-deletion` with `{"confirmed":true}`
  creates one durable request per Cognito subject, independent of enrollment.
- Both return `status` (`none`, `requested`, `processing`, `completed`),
  `request_id`, `requested_at`, and `expected_completion` (nullable text configured
  with `CONTRIBUTOR_DELETION_EXPECTED_COMPLETION`). Do not invent an estimate.
- POST additionally returns a 64-character random `receipt_token`. Store it in
  secure storage before clearing the login session. A repeated POST preserves the
  request and, within the retry limit below, issues another token. The original and
  every retry token remain valid, even when responses arrive out of order. If the
  response is lost, retry while signed in.
- `GET /api/contributor/account-deletion/receipt` accepts that token as a Bearer
  credential independently of Cognito. It reveals only the public request status.
  The database stores only SHA-256 hashes of tokens, never the raw tokens. All issued
  receipts permit completion confirmation after Cognito removes the login. Keep a
  receipt across contributor logout.

The follow-up limits additional receipt tokens to **20 per authenticated subject per
rolling 24 hours**. The first valid authenticated deletion request and its original
receipt are always accepted by this limiter and do not consume a retry slot. The API
counts stored retry timestamps under the shared database advisory transaction lock,
so the limit holds across workers, restarts, concurrent requests, and changing IPs.

Once all retry slots are used, POST returns HTTP `429` with
`{"detail":"deletion_receipt_retry_limited"}` and a `Retry-After` header containing
the number of seconds to wait before trying again. Keep any saved receipt and honor
that delay. The limit affects only new receipt issuance: the existing deletion
request, authenticated status lookup, and every original/retry receipt remain valid.
Slots reopen as issuance timestamps leave the rolling window; receipt rows are retained.

Request acceptance immediately deactivates the contributor, closes assignment
intervals, and clears camera ownership. A shared transaction fence blocks new
mobile actions and operator camera, recipient, review, and payment approvals.
Local camera control is a separate app feature and does not require an account.

## Operator fulfillment

Existing staff authentication and CSRF checks protect these endpoints:

1. `GET /api/ops/contributors/deletions` lists requests and their audit state.
2. Reconcile every in-flight/unknown Wise submission through the existing recipient
   recovery workflow. Unknown outcomes prevent fulfillment; never assume a failed
   request created no recipient. Also reconcile already-approved payouts and
   outstanding Wise transfers before attesting processor cleanup. Existing payout
   automation can continue paying money already owed; this request blocks new
   approvals and does not cancel owed payments. Record any retained processor
   payment records and their legal reason in the retention evidence.
3. Perform and verify applicable source, versioned-object, backup, derived dataset,
   exported consent, downstream recipient, and processor cleanup using the
   company's approved process. This API does not enumerate or delete those external
   stores automatically. Identify the subject's records before scrubbing profile
   fields. Record evidence references, not raw bank details or footage.
4. Identify the exact legal/payment records that must be retained, their scope,
   legal reason, and review date. The service retains consent, assignment, payment,
   and deletion audit rows; operator evidence must account for those retained
   records and any external retention. This is not permission to retain unrelated
   profile data indefinitely.
5. POST `/api/ops/contributors/deletions/{request_id}/fulfill` with:

```json
{
  "footage_cleanup": "Verified source and derived footage removal; evidence reference ...",
  "processor_cleanup": "Verified processor and exported-record disposition; evidence reference ...",
  "retained_records": [{
    "scope": "Precisely identified consent, payment, assignment and deletion audit records",
    "reason": "Applicable obligation requiring these records",
    "review_at": "2027-01-01"
  }]
}
```

The date above is a payload example, not a retention policy. Evidence is recorded
once and is immutable across retries. The operator is attesting verified cleanup;
accepting text is not an automated check of external evidence.

The service durably records processing. For an enrolled contributor, it first
removes their **Bank details** spreadsheet rows and records a contributor-ID
tombstone that prevents delayed submissions from recreating them, even when no
masked database receipt exists. A bridge failure returns HTTP `503` with
`payment_sheet_deletion_retry_required`; processing remains retryable and Cognito
deletion has not run. See the [bank spreadsheet guide](contributors/bank-spreadsheet.md)
for configuration and the separate handling of retained settlement evidence.

After spreadsheet cleanup, the service calls Cognito `AdminDeleteUser` using the
configured contributor pool and subject, then scrubs the profile and bank summaries
and removes the active payout-recipient link. `UserNotFoundException` is idempotent
success; other failures remain `processing` with `retry_required`, sanitized error
responses, and append-only attempt audits. Retry the same evidence. Completion is
never reported for deactivation alone. A crash after Cognito removal can be retried
through the staff endpoint; the receipt still reports processing until DB completion.

## Deployment and rollback

Apply migrations 0017 and 0018 before serving the updated API (`alembic upgrade head`
from `backend/`). Migration 0018 adds the append-only `contributor_deletion_receipts`
table for retry hashes and leaves the original `contributor_deletions.receipt_hash`
untouched, including the hash retained from a pre-0018 request. Receipt lookup checks
both locations; retries and fulfillment do not revoke those receipts.

Migration 0018 refuses downgrade when any retry receipt rows exist. For an application
rollback, keep both the receipt schema and the code that looks up original and retry
hashes. Restoring code that only reads the original hash would strand retry receipts
even if the new table remained. Do not delete receipt rows to bypass the downgrade guard.

On 2026-09-16, the original receipt-preservation fix (PR 76, commit `93eae43`) was
deployed. Migration 0018 and IAM principal `sixthsense-contributor-deletion-prod`
were verified in the running API. Its `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
provide only `cognito-idp:AdminDeleteUser` on contributor pool `us-west-2_mZ3Sz9xvE`.
This runtime verification did not delete a real user or verify live erasure.

The 20-token retry-issuance follow-up is not deployed yet. It uses the existing
migration 0018 table and requires no new schema migration. Release acceptance still
requires a verified expected-completion policy, operator ownership and evidence
process, and app receipt persistence.

## Local validation

From the repository root, run the contributor regressions and migration checks in
separate invocations against a fresh, disposable PostgreSQL database whose name ends
in `_test`. Application fixtures create and drop tables; migration checks exercise
real Alembic upgrades and downgrades and must start with an empty schema.

```sh
export TEST_DATABASE_URL=postgresql+asyncpg://USER@localhost:PORT/contributor_test
PYTHONPATH=.:backend python -m pytest -q -c backend/pytest.ini \
  backend/tests/test_contributor_deletion.py backend/tests/test_contributor_mobile.py \
  backend/tests/test_contributor_terms.py backend/tests/test_contributor_recovery.py
PYTHONPATH=.:backend python -m pytest -q -c backend/pytest.ini \
  backend/tests/test_migrations.py backend/tests/test_contributor_deletion_migration.py \
  backend/tests/test_contributor_receipt_migration.py
```

On 2026-09-16 the follow-up passed 64 contributor regressions, including competing
requests for the final retry slot, the 429 response and `Retry-After`, continued
receipt/status access, separate subjects, and recovery at the 24-hour boundary.
The original receipt release passed 7 migration tests; the follow-up does not change
the schema. Existing coverage includes concurrent and legacy receipts, hash-only
storage, completion after authentication ends, preservation across upgrade, and
refusal to downgrade with issued retry receipts. Provider calls are mocked; these
results do not verify live erasure.

## Published pre-account notices

`GET /api/contributor/notice?routing_version=kr-2026-v1&locale=en` is public.
It returns the existing four-document terms schema only when all localized documents
match the immutable founder-publication audit. Unknown routing, unavailable locale
bundles, malformed or unaudited pointers return `not_published` with no links.
Presigned URLs pin the published S3 object version. No drafts are exposed.
