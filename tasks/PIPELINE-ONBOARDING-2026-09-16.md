# Ronak's pipeline walkthrough

## What Alex handed over

Alex had already built the GPU conversion and CPU Clean workers and queued the current batch. At the September 16 03:06 UTC handoff, 4 of 11 current recordings were imported, two Clean jobs were running, one was queued, and four waited for conversion. Those are historical handoff counts, not current progress.

`monitor.py` watched the first conversion jobs and checked their receipts. `controller.py` waited for those results, submitted eligible Clean jobs, verified original metadata, imported results, and cleaned up temporary compute. They were the traffic controllers, not the video-processing engines. Their copies were on Alex's Mac and were absent from the ZIP. The ZIP's `check_pipeline.py` only reads status.

AWS keeps a submitted worker running without a laptop. It only advances the whole sequence automatically when something is installed to coordinate the stages. That role is now a scheduled AWS coordinator with durable S3 state. Chat can operate and inspect it; the running AWS service does not depend on this conversation staying open. We recovered and pinned Alex's actual worker runtime from deployment storage. We cannot verify that his Mac processes stopped; their old task-specific submission definitions were fenced to prevent new duplicate jobs.

## Follow one recording

1. **Upload:** files arrive in temporary `6thsense-raw`. The coordinator waits for the same settled source versions on separate checks. A file arriving later cannot silently replace an in-flight source.
2. **Preserve:** Archive gets the complete original files, including metadata, calibration, sidecars, and relevant old versions. Every file is hashed before copying and after reading it back. An immutable receipt records its location and version.
3. **Convert:** GPU workers decode the video, separate the calibrated eyes, and extract measured camera timing and sensor data. This can run alongside archival. Output existing in a bucket does not mean it has passed verification.
4. **Clean:** CPU workers reject invalid intervals and produce eye videos, frame archives, a timeline, IMU, calibration and unchanged original metadata. Missing measurements are not guessed.
5. **Verify and register:** committed manifests, source hashes, outputs, metadata, country and ownership must agree. Registration means the portal records the verified Clean result; it does not create another copy, approve content, or pay anyone.
6. **Keep company Clean:** `6thsense-processed` holds usable company footage from all confirmed countries, including China, organized in the portal by region/source. Technically blocked recordings remain held with their originals preserved.
7. **Deliver to Sieve:** its inheritance worker copies eligible Clean files into `6thsense-sieve`. The contract allows India and Korea only. China, unknown countries, and deleted recordings are excluded. Both eyes count as one recording's duration.
8. **Empty temporary Raw:** a separate verifier checks Archive, one complete imported Clean run, and worker completion before removing only the exact archived source versions. New uploads stop cleanup. Empty camera placeholder files also remain preserved in Archive.

The original upload survives in `6thsense-archive-194680606079`; it does not have to stay in temporary Raw. A held recording can have both copies while its processing issue is unresolved.

## Open the dashboard

Sign in at <https://6thsense.dev/login>, then open <https://6thsense.dev/portal/ops>. Your account's role determines which tabs appear. An account/workspace home after login is normal; use the direct Ops link for this workflow.

| Tab | What it means | First action |
| --- | --- | --- |
| Raw | Upload inventory and processing status; pending, processing and needs-attention totals. | Search a recording/camera/source, read its status and reason, then preview if useful. A bucket scan refreshes inventory; it does not launch a duplicate conversion. |
| Clean | Verified company footage, organized by region and contributor/business. | Choose a region, open a source card, watch its footage, expand batch/source details and inspect flagged intervals. Technical acceptance and your content review are separate. |
| Sieve | The eligible customer subset and copy progress. | Compare eligible Clean hours with inherited hours; filter by country/status and read blocked rows. A newly imported recording can wait for the next copy pass. |
| Payment | Existing payment and review facts. | Inspect history; processing completion does not authorize a new payout. The pipeline preserves paid facts and leaves payment automation disabled. |
| Users | Contributor and source administration. | Inspect identity/assignment; a camera folder alone does not prove who owns a historical recording. |

Useful bookmarks: [Raw](https://6thsense.dev/portal/ops?tab=ops), [Clean](https://6thsense.dev/portal/ops?tab=clean), [Sieve](https://6thsense.dev/portal/ops?tab=sieve), [Payment](https://6thsense.dev/portal/ops?tab=payment), [Users](https://6thsense.dev/portal/ops?tab=users).

Archive is storage infrastructure, not a new dashboard tab. Do not interpret a Raw row disappearing after verified cleanup as loss of its original. The archive receipt is the preservation evidence. The current Sieve page is temporary and displays its contract/dashboard dates; those are separate from the scheduler's initial run deadline.

## What still needs attention

Ordinary complete uploads should advance automatically. Actual source defects (missing original metadata, calibration or exposure timing, conflicting IMU, damaged video) require evidence-based recovery; the system preserves them rather than pretending they are usable. PSDN also retains its document-review hold. Content review and business rights remain human work.

The first autonomous run has a $100 additional-compute ceiling and an eight-hour window ending September 16 at 12:09 UTC. Its watchdog stops this workflow's compute at that deadline; original Alex jobs are separate. The infrastructure persists, but this initial run is not indefinite spending authorization. Current operational evidence and instructions are in `infra/raw_lifecycle/README.md` and the task ledger.
