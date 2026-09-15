# External payment records

Operators can record a payment made outside the payout workflow against exact,
whole Clean runs. The maintenance helper
[`record_external_payment`](../backend/app/core/ops_external_payments.py) has no
HTTP import endpoint and makes no Wise API calls. It records bookkeeping from an
operator report; it does not send money or independently verify recipient delivery.

## Evidence and reconciliation

The event schema is `6thsense-external-payment/1`. Each event includes:

- A canonical Wise transfer ID: a string of 1–20 decimal digits, starting with
  1–9. Leading-zero aliases are rejected.
- The contributor ID and a timezone-aware `reported_at` timestamp.
- Exact distinct run IDs, each pinned to its manifest SHA-256, retained seconds,
  recording count, and expected earnings amount.
- Positive footage earnings, a nonnegative incentive, and their exact total,
  all in whole KRW.
- Separate `document` and `audit_receipt` references in the private
  `6thsense-contributor-records/payment-receipts/` namespace, each pinned by S3
  version and SHA-256.

The privileged caller must verify and preserve the actual payment document and
audit bytes before import. This helper validates the reference shape and pinned
identities; it does not fetch S3 objects or prove what the document establishes.
Keep documents, bank information, and private event payloads outside tracked docs.

The only accepted provenance is `payment_basis: operator_reported_paid` with
`provider_delivery_status: unverified`. An operator's report or a funding
instruction sheet does not establish that Wise delivered funds to the recipient.
A request to record confirmed provider delivery through this importer is rejected.

## Privileged import procedure

1. Prepare the private event from verified evidence and the current Clean ledger.
   Select whole runs; partial-run allocation is not supported.
2. In a privileged database session, call
   `record_external_payment(db, event)` to validate without writing.
3. Review the returned earnings, incentive, total, and recording count. Publish
   with `record_external_payment(db, event, publish=True)` inside the caller's
   transaction, then commit only after the helper succeeds. The helper flushes
   changes but does not commit the transaction itself.
4. Verify the exact event record and affected Clean runs after commit. An
   identical retry is idempotent; do not create an alternate transfer ID to retry.

The importer takes transaction advisory locks shared with the ledger/payment
workflow and row locks on the selected Clean runs. It recomputes each run's
earnings using the existing retained time, hourly rate, and per-run rounding,
then checks contributor ownership, manifest hash, amount, time, and recording
coverage against the event.

Missing runs, changed ownership/QC/earnings, already-paid footage, existing payout
reservations, duplicate run IDs, and transfer IDs already used by the normal
payout ledger are rejected. Events are stored canonically in `OpsSetting` under
`external_payment:wise:<id>`. Reusing that key with different event content is
rejected; an identical existing event returns without another write.

## Bookkeeping and history

Publication sets each selected `CleanRun.paid` to true, `paid_at` to the operator's
report time, and `amount_krw` to that run's footage earnings. In this path, “paid”
means **operator-reported bookkeeping**, not confirmed provider settlement.
QC, retained/rejected time, hourly rates, and source ownership remain unchanged.

The incentive remains separate in the audit event and payment history. It is not
additional earned footage, a rate increase, or time added to the Clean ledger.
No `Payout` or `PayoutItem` is created by this importer.

The existing payment-state response appends history read from the
`external_payment:wise:<id>` settings. The Payments page displays the total and
its footage/incentive breakdown, labels it **paid (operator reported)**, and shows
**Recipient delivery unverified**. History includes the transfer ID and
bookkeeping fields; it does not expose bank details or private document URLs.

## Validation and rollout checkpoint

The release's 62 backend tests, frontend build, and three responsive Ops workflow
tests passed. Coverage includes exact-run
reconciliation, unchanged time/rate/QC, separate incentive accounting, idempotent
retries, and rejection of ambiguous evidence or unsupported settlement claims.

The API and frontend were deployed on 2026-09-15 from code commit
`c6bd555a411bf9b4c4db30090c1a3d2e4eeadee2`. Both Railway deployments succeeded.
Live verification matched deployed API source hashes, reconciled the payment
history with the covered Clean ledger, and confirmed the public frontend bundle
contains the incentive breakdown and unverified-delivery label. Private evidence
and reconciliation results remain outside tracked documentation.
