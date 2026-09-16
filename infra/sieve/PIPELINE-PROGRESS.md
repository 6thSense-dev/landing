# Ops pipeline progress

`GET /api/ops/sieve/pipeline` is restricted to existing ops/founder/admin sessions.
It reads the lifecycle coordinator's state, customer delivery receipt, independent
validator reports, and private supplement summary through the existing Sieve role.
It caches a snapshot for 30 seconds and reports unavailable/stale sections rather
than substituting zero. It neither starts processing nor uploads customer data.

Apply `pipeline-progress-policy.json` as the separate `PipelineProgressReadOnly`
inline policy on `sixthsense-sieve-clean-inheritance`. Preserve the existing
`CleanOnlyInheritance` policy, including its explicit Raw-read denial. This new
policy grants no object writes and no reads of the private customer upload URL.

The current source selectors are:

- `OPS_PIPELINE_PROGRESS_BATCH_ID=sow1-20260915-batch-1`
- `OPS_PIPELINE_PROGRESS_VALIDATION_RUN=sow1-20260916-independent-v2`
- `OPS_PIPELINE_PROGRESS_SUPPLEMENT_RUN=sow1-20260916-supplement-v1`

Those are defaults. To show a future batch, update both the environment selectors
and the exact read/list resources in this policy. An unpermitted selector reports
unavailable; it cannot fall back to a different batch.

Company counts are source groups across all countries, not customer delivery
hours. Internal Clean-to-Sieve copies, prepared footage, customer-uploaded footage,
and the private supplement are separate quantities. Uploaded hours are exposed
only when the delivery receipt declares checksum-verified completion and its
positive recording/asset/file/byte totals reconcile. Validation report object
counts alone never declare PASS. Technical validation does not record human review
or customer acceptance.
