# Sieve collection dashboard and Clean inheritance

Sieve's active collection inherits **only from Clean**. The Ops tab at
`/portal/ops?tab=sieve` shows unique retained hours in Clean, hours copied into
Sieve, country and contributor/business diversity, operator task assignments,
cameras, Clean intake dates, and per-recording pending/blocked/inherited status.
Open an inherited episode for its media, sensor data and pipeline action labels. Customer
acceptance is separate and currently not recorded. Neither Clean import nor a
successful copy implies acceptance by Sieve.

The contract ends **September 22, 2026**. The temporary dashboard remains visible
through **September 25, 2026, America/Los_Angeles**, including that whole day. It
hides at September 26 midnight (07:00 UTC); the state API returns HTTP 410. The
availability endpoint remains available to Ops. This UI expiry does not delete
objects or stop Clean inheritance.

## Data contract

Source: `s3://6thsense-processed/clean/` and its committed `qc-results/` manifests.
Destination: `s3://6thsense-sieve/inherited/v1/`.

Only India and Korea recordings are eligible for Sieve, using the preserved
Clean country attribution. China, other countries, and unknown attribution are
excluded while remaining in the company's Clean inventory. The inventory filter
also excludes them from Sieve dashboard totals and the next published receipt
index; the copy function rejects them before any storage access. Previously
copied objects require a separate scoped storage withdrawal.

```text
inherited/v1/
  latest.json                              # current receipt index
  <clean-run>/<recording>/<fingerprint>/
    left.mp4 + right.mp4                    # split stereo, existing codec
    # or native.mp4 for historical native-stereo Clean recordings
    metadata.json                          # original or disclosed reconstructed metadata
    metadata-provenance.json                # source → Clean metadata evidence
    calibration.json                       # validated camera-specific calibration
    manifest.json                          # pinned Clean → Sieve handoff receipt
```

The worker copies the authoritative per-recording MP4s. It excludes combined
previews, per-recording preview duplicates, PNG frames, IMU, and frame-index CSVs
from this Sieve handoff. Those additional modalities remain in Clean. It does not
re-encode, split, rotate, or manufacture metadata. Original codecs and pixel
coordinates stay unchanged. Historical native-stereo recordings are labelled as
such, rather than claiming split-eye delivery.

## Episode inspection and labels

Open a verified recording in the Sieve tab to inspect its video, IMU, original
metadata, calibration JSON and pipeline task report together. Video and both
JSON documents come from the versioned Sieve receipt. IMU and task reports remain
in Clean and are read through the same pinned Clean manifest; each panel names
its storage source. A verified browser-compatible Clean preview is offered when
available, alongside the original Sieve videos. Opening the viewer never copies
or changes an object.

The IMU chart previews the first 200 samples, with a full CSV link. Task events
use source timestamps before Clean cuts. The viewer preserves each model's task
labels, environments, partial coverage and review status. It shows at most 200
events and links the full report. These annotations are not customer acceptance.

Pipeline annotations are linked by `policy.episode_tasks`, independently of the
manual `Episode.task_id` assignment. An unassigned operator task does not mean
pipeline labels are absent. The list reports whether a pipeline report is linked;
the viewer verifies its contents before showing labels. Read failures say
unavailable, rather than claiming no labels exist. Collection task-hour breakdowns
refer only to operator assignments, not model task coverage.

`GET /api/ops/sieve/episodes/{recording}` requires the existing Ops role. Only
active, currently inherited recordings can issue 15-minute, version-pinned links.
The endpoint rechecks eligibility after storage reads and returns `no-store`.
Deleted, stale, pending and blocked recordings cannot issue preview links. The
browser loads one expanded episode at a time and cancels requests on close.

Clean import and the internal Sieve copy are separate from upload to Sieve's
customer storage. The internal worker repeats after a five-minute wait following
each pass; it does not automatically perform customer delivery. Dashboard refresh
only reads status and does not start processing or copying.

Each source and destination file has a bucket, key, VersionId, SHA-256 and byte
count in the receipt. The Clean completion marker must still agree with the DB's
pinned manifest. Metadata must match the Clean metadata-provenance supplement
and source identities under the validation rules below. Calibration is read and
validated against the recording camera and, when available, the output layout. Canonical supplements
are supported alongside revised MP4 prefixes within the same Clean run.

S3 performs version-pinned server-side copies, including multipart copy for large
MP4s. Source and destination sizes and SHA metadata are checked; JSON bodies also
receive SHA-256 readback. This is not a new full decode or video SHA readback.
Receipt publication happens only after the complete recording's files verify.
Exact-prefix listing distinguishes absent keys from permission errors without granting access to other Sieve prefixes. Retries reuse matching destinations; conflicting provenance is blocked. Deleted
recordings and stale manifest/attribution revisions are excluded from the active
DB dashboard and next completed S3 index. Older immutable receipts remain audit
history; explicit media deletions must also purge Sieve versions and caches.

Hours come from Clean's retained intervals, once per recording. The inventory
suppresses repeated recording names and overlapping source hashes. Country comes
from preserved Clean provenance/business attribution, not inferred demographics.
Entity attribution comes from the Clean ledger; the task-hour breakdown uses the
operator task assignment for that Clean recording. Missing assignments display
as Not assigned. Pipeline action labels are inspected separately as described above.
Intake dates are Clean import dates in Los Angeles time, not assumed capture dates.

Legacy `prepared/`, `sources/`, and `reports/` content was produced by the old
Raw-fed CodeBuild process. It is retained separately as legacy history and is
excluded from this active inheritance index and its hour counts. Do not restart
that old preparation flow for new Sieve data.

## Metadata validation

Original capture metadata uses `6thsense-clean-source-metadata/1` provenance
with `copy_mode: byte_exact_from_versioned_source`. Its bytes must match the
pinned original references. Reconstructed metadata cannot pass as an original.

The recovery path uses `6thsense-clean-source-metadata/2` with
`copy_mode: reconstructed_from_verified_sources` and an empty `source_metadata`
list. Its `6thsense-reconstructed-source-metadata/1` artifact must disclose
`metadata_origin: reconstructed`, `capture_completeness: unknown` and inspection
of `all_available_sources`. The measured frame count covers available source
frames only. Completeness, wall-clock time and original capture totals remain
unknown: `complete`, `start_time`, `clock_synced`, `stop_reason`,
`received_frames`, `written_frames`, `dropped_frames`, `fw`, `lossless` and
`truncated` must all be explicitly `null`.

Sieve checks those disclosures, source versions/sizes/SHA-256, the pinned recovery
authorization reference, and calibration provenance against the committed Clean
recording. Clean import separately reads the explicit authorization and conversion
evidence and validates their measured observations. The Sieve worker reads Clean;
it does not inspect Raw or independently approve the recovery authorization. It
copies the generated artifact and provenance without changing their disclosures.
Original files remain preserved, and neither successful validation nor inheritance
establishes complete capture or customer acceptance.

As of the September 17 metadata-recovery implementation checkpoint, backend
validation is deployed and the conversion cloud canary passed 900 frames. Clean
canary completion and cloud worker promotion remain pending. This contract does
not establish completed recovery or delivery.

## Contributor delivery exclusions

Store Sieve-only contributor exclusions in `OpsSetting.sieve_delivery_exclusions_v1`
as a JSON object with `schema: "6thsense-sieve-delivery-exclusions/1"` and a
`wearers` object. Each `wearers` key must be a positive decimal contributor ID
without leading zeroes; its value must be an object containing a nonblank string
`reason`. Use IDs and operational reasons, not contributor names or other personal
information in repository examples. An absent setting or empty `wearers` object
adds no contributor exclusions; existing country and other eligibility rules still
apply. Invalid JSON, schema or entries fail closed and hold delivery.

Inventory excludes recordings owned by a listed contributor through either
`Episode.wearer_id` or `CleanRun.wearer_id`. The exclusion also covers historical
manifests with the same recording name and aliases sharing an excluded source
SHA-256, so relabelling a recording or using an older run cannot bypass it.
Excluded recordings leave Sieve dashboard totals, new delivery candidates and
the next published receipt index. Internal Raw/Clean records and payment history
remain unchanged. Previously copied Sieve objects require a separate scoped
withdrawal; changing this policy does not delete them or rewrite immutable audit
receipts.

Policy writers **must acquire `SELECT pg_advisory_xact_lock(61306135)` in the same
database transaction before updating the setting**, then retain the lock through
commit. This is the same lock key held by the inheritance worker and serializes
policy changes with active copies. Do not update the policy outside that locking
protocol. `sync_once` rechecks current inventory and revision before every copy,
before saving its result, and before publishing `latest.json`; an earlier
inventory snapshot cannot authorize a newly excluded recording. This policy uses
the existing settings table and requires no migration.

## Railway operation

The API's lifespan starts an independent worker when `OPS_SIEVE_ENABLED=true`.
Set `OPS_SIEVE_ROLE_ARN` to
`arn:aws:iam::194680606079:role/sixthsense-sieve-clean-inheritance`.

The existing portal credential may assume that dedicated role; it does not gain
Sieve write permission itself. Policies are checked into `infra/sieve/`: the role
can read only Clean/QC source objects and list/read/write `inherited/v1/` destinations,
with an explicit deny on Raw object reads. It cannot write Raw, Clean, or legacy
Sieve preparation prefixes. No new permanent access keys are created.

A PostgreSQL session advisory lock (`61306135`) elects one worker across API
replicas. It commits progress into `OpsSetting.sieve_clean_sync_v1` after each
recording, then publishes a current S3 receipt index and completion timestamp.
It retries on a five-minute loop, independently of the Raw/Clean processing
coordinator. API deployments can resume existing S3 copies. Copy cancellation
holds the worker lock until its current thread completes. Database outages do
not permanently terminate the retry loop. No database migration is required.

The dashboard polls the read-only Ops API every 30 seconds. It preserves the last
snapshot on refresh failure and warns when the latest verification is older than
15 minutes. `/api/ops/sieve/state` and `/availability` use the existing Ops role
gate. The learning preview, customers, and contributors cannot access this tab.
