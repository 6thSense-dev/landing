# Clean tab evidence labels

The contributor-grouped Clean view and Payment workflow are preserved. Batch details now display the imported run's actual QC policy, saved rate and retained-time estimate.

- QC-retained time is separate from task-specific usable time, annotation quality and dataset acceptance.
- Actual `policy` is rendered as escaped JSON. Missing, null or empty policy remains unknown; no threshold is substituted.
- The displayed estimate comes from the existing run snapshot. Current Payment eligibility and split-payout allocations continue to use the existing contributor ledger.
- The historical run paid flag is labeled as a flag, without claiming a transfer. Current payout status is in Payment.
- Current contributor details and saved run rates do not prove historical agreement terms.
- Batch totals remain the current arithmetic sum. Unique physical-clock time across recordings or camera views is unknown.

Task activity review is available inside each batch's details. It saves a separate task declaration; it does not mark the payment attestation reviewed, approve a payout, change recipient approval fencing, or reprice an agreement.

Synthetic browser tests cover policy variation/escaping, unknown policy and rate, displayed durations/estimates, and explicit refresh. Current payment and grouped-footage tests run alongside these tests. See [integration receipt](OPS-INTAKE-INTEGRATION-20260915.md) for revision-specific results and limitations.
