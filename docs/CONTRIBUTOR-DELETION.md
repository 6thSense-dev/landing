# Contributor deletion release contract

This implementation is staged. It does not publish regional agreements, enable signup,
perform production erasure, or establish a legal retention period.

## Mobile API

- Authenticated `GET /api/contributor/account-deletion` works before enrollment.
- Authenticated `POST /api/contributor/account-deletion` with `{"confirmed":true}`
  creates one durable request per Cognito subject, independent of enrollment.
- Both return `status` (`none`, `requested`, `processing`, `completed`),
  `request_id`, `requested_at`, and `expected_completion` (nullable text configured
  with `CONTRIBUTOR_DELETION_EXPECTED_COMPLETION`). Do not invent an estimate.
- POST additionally returns a 64-character random `receipt_token`. Store it in
  secure storage before clearing the login session. A repeated POST preserves the
  request but rotates the token. If the response is lost, retry while signed in.
- `GET /api/contributor/account-deletion/receipt` accepts that token as a Bearer
  credential independently of Cognito. It reveals only the public request status.
  The database stores its SHA-256 hash. It permits completion confirmation after
  Cognito removes the login. Keep this receipt across contributor logout.

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

The service durably records processing, calls Cognito `AdminDeleteUser` using the
configured contributor pool and subject, then scrubs the profile and bank summaries
and removes the active payout-recipient link. `UserNotFoundException` is idempotent
success; other failures remain `processing` with `retry_required`, sanitized error
responses, and append-only attempt audits. Retry the same evidence. Completion is
never reported for deactivation alone. A crash after Cognito removal can be retried
through the staff endpoint; the receipt still reports processing until DB completion.

Deployment needs migration 0017, a narrowly scoped IAM `cognito-idp:AdminDeleteUser`
permission for the contributor pool, a verified expected-completion policy, operator
ownership and evidence process, and app receipt persistence. These are release gates,
not actions taken by this change.

## Published pre-account notices

`GET /api/contributor/notice?routing_version=kr-2026-v1&locale=en` is public.
It returns the existing four-document terms schema only when all localized documents
match the immutable founder-publication audit. Unknown routing, unavailable locale
bundles, malformed or unaudited pointers return `not_published` with no links.
Presigned URLs pin the published S3 object version. No drafts are exposed.
