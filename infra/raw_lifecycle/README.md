# Raw lifecycle

This workflow replaces laptop coordination with a scheduled AWS Lambda and Batch workers. It preserves Alex's pinned conversion and Clean extraction runtime rather than reinterpreting capture timing.

## Buckets and stages

1. `6thsense-raw`: temporary upload intake. Wait for an unchanged, settled, versioned source set. Exclude operator-deleted recordings.
2. `6thsense-archive-194680606079`: byte-exact original files, metadata, calibration and sidecars, including older versions of present keys. Stream full SHA256 before copying and after reading the destination. Immutable receipts map original key/version to archive key/version. No expiration rule deletes archive objects.
3. Conversion: run on GPU Batch workers. Decode original video, extract measured optical timing and sensors, split calibrated eyes, and verify staging outputs. Archival and conversion can run concurrently.
4. Clean: CPU Batch workers produce calibrated videos, frame sequences, timeline and IMU; exclude technically invalid intervals. Pin and verify the output manifest, preserve original metadata, then import through the authenticated portal API. Existing paid facts are preserved; this workflow creates no payouts and does not approve content.
5. `6thsense-processed`: company Clean for every confirmed country. Missing completion, timing, calibration, attribution or conflicting IMU stays on hold. Unsupported legacy containers are archived but held, not given fabricated timing.
6. `6thsense-sieve`: the existing portal inheritance worker copies verified Clean only for **India and Korea**. China and unknown/other countries are excluded.
7. Retirement: a separate Lambda independently requires a complete archive receipt, every archive object version, one imported Clean run covering all nonempty current media, terminal source workers and no newer source versions. Only then can it delete the exact archived Raw versions. Empty camera placeholders are archived and verified too; they contain no frames for Clean. New uploads are never deleted by key.

## State and concurrency

- Production account: `194680606079`, region `us-west-2`. Use profile `ronak-catalog-sso`; the machine default profile is a different account.
- Coordinator/retirement/watchdog: `sixthsense-raw-lifecycle-v1-*`.
- Config: `s3://6thsense-deploy-artifacts/raw-lifecycle/v1/config.json`.
- State/status: `s3://6thsense-processed/raw-lifecycle/v1/`.
- Plans: `s3://6thsense-deploy-artifacts/clean-plans/raw-lifecycle-v1/`.
- Archive receipts: `receipts/<recording>/<fingerprint>.json`; per-object resolvers: `source-index/<sha256-of-original-identity>.json`; deletion audits: `retirement/`.
- EventBridge invokes one coordinator every two minutes; reserved concurrency is one. State is persisted before Batch submission. An uncertain submission is reconciled by its deterministic job name, never blindly repeated.
- Original job plans are adopted only if pinned source identities match. Existing CPU/GPU jobs continue on their original queues. The new queues and launch templates are separate.
- CPU maximum: 64 vCPU; GPU maximum: 8 vCPU (two g5.xlarge, shared regional GPU quota). Minimum zero; no GPU quota increase. Capacity scales with queued jobs within these bounds.
- Initial autonomous authorization: $100 additional compute, bounded eight-hour window. A five-minute watchdog disables new queues and terminates this workflow's active jobs at the deadline; the coordinator and retirement also enforce the deadline. This is a bounded initial run, not an indefinite spending authorization. S3 archive storage remains retained.

## Deploy and operate

Run `deploy.py prepare` with boto3 credentials for the production profile. It starts disabled and refuses to reset an enabled run. It downloads Alex's original runtime from the exact S3 version and SHA256 pinned in `SOURCE_RUNTIME`; no Mac or local extracted folder is needed. Re-run only after intentionally pausing the coordinator; job IDs and source states remain in S3. Set `RAW_LIFECYCLE_EVIDENCE_DIR` to choose local evidence output; the default is `.context/raw-lifecycle`.

For code fixes during a run, disable retirement and use `deploy.py update-code`; this preserves the budget, flags, jobs and worker definitions. `deploy.py update-archive` registers a new immutable archive worker for future jobs, extends only its exact submission permission, and preserves existing queued/running jobs and the spending deadline. Do not re-run `prepare` merely to update code.

The portal's `OPS_PIPELINE_TOKEN` must equal Secrets Manager `sixthsense-raw-lifecycle-v1-portal-token`. Transfer it through protected process input (`railway variable set OPS_PIPELINE_TOKEN --stdin --skip-deploys`), never in shell arguments, Git, logs or documentation. Deploy the backend router before enabling AWS. Bearer POST requests also require the allowed `Origin: https://6thsense.dev` header.

After unit/adversarial tests and a live archive canary, run `deploy.py enable` (processing and archive only). `deploy.py enable --retire` also enables independent retirement and adds only that role to the Raw bucket's deletion exception. Enabling explicitly re-enables this workflow's queues. Record the deadline returned by the command.

To pause: set config `enabled=false` and `retirement_enabled=false`; disable the tick EventBridge rule. Existing jobs do not stop automatically until the watchdog deadline. To stop this run immediately, shorten `run_deadline_epoch` to now and invoke the watchdog. Never stop unrelated queues or delete archive originals.

Failed or uncertain jobs are held for review; inspect CloudWatch and version-pinned state, then record an explicit replacement attempt. Do not remove durable submission intents merely to force a retry.

The retirement Lambda accepts `dry_run: true` with a recording and fingerprint for a production-role verification pass that performs zero deletions while retirement stays disabled. Interrupted cleanup retains its original snapshot and intent; subsequent ticks resume missing versions safely even if Raw is empty, or recover the existing immutable completion audit. Newly arrived keys or versions block unfinished cleanup.

## Limits

The original Mac coordinator scripts were not in the handoff ZIP. Cloud job/plan adoption is verified; their process liveness cannot be established from old S3 timestamps. Retiring a source requires all adopted workers to finish. Any old submission capability must be fenced before live retirement.

Current new conversions support complete calibrated side-by-side MP4 recordings. Native HEVC streams require portal inventory support; EGOC/legacy split recordings need format-specific measured timing recovery. Historical imported Clean can still be archived/retired when its full source hashes match. Holds preserve originals and remain visible; they are not silently treated as usable Clean.

Late metadata additions can begin a new observed source set after the earlier archive-only job finishes. Existing source identities, sizes and ETags must remain unchanged. Replaced/removed files or already started conversion/Clean require review; source changes never silently supersede an active processing run.
