# Raw → Clean media artifacts

September 14, 2026. **Local implementation, not a deployment or historical backfill record.**

The live `6thsense-processed/clean/` inventory inspected today contained 165 MP4
objects and one folder marker. The existing one-off ink-factory exports contain
native stereo and viewing previews; the QC v1 contract does not require separate
eyes, complete frame sequences or extracted IMU. Sampled sensor-clock audits and
QA images are not those deliverables.

## Required new result

New Clean imports and worker completion use `6thsense-clean-qc/2`, with media
profile `stereo-imu-frames/1`. For each retained recording:

| Artifact role | File | Required evidence |
| --- | --- | --- |
| `left_video`, `right_video` | `left.mp4`, `right.mp4` | Same retained frame count and presentation timeline |
| `left_frames`, `right_frames` | `frames/left-000000.tar`, `frames/right-000000.tar`, … | PNG for **every** retained frame, contiguous shard ranges |
| `frame_index` | `frame-index.csv` | Output index → source index/frame number, receive time if known, original PTS if present, sensor exposure, segment, clean PTS, frame archive/member/hash |
| `imu` | `imu.csv` | Actual measured accelerometer and gyro samples, sensor timestamp, segment and clean-time mapping |
| `timeline` | `timeline.json` | Eye geometry/orientation, sensor clock, segment mappings, counts, timing provenance and units |

An optional `joined_preview` remains a viewing convenience. It cannot substitute
for required artifacts. A fully rejected recording needs its source evidence,
partitioned QC timeline and reasons; it does not need fabricated media artifacts.

Extract the barcode/IMU **before cropping, rotating, resizing or re-encoding**.
The known native frame is 4000×1200: a 160-pixel sensor strip, cam0 at x=160,
cam1 at x=2080, each 1920×1200. Physical left/right depends on the declared mount.
The upright converter uses cam1 as left; the catalog's old inverted mount used
cam0. Do not split into equal 2000-pixel halves or silently use the catalog's
unregistered-rig fallback for a newly deployed camera. Supply a verified layout
declaration for the actual device. This extractor does not infer orientation or
claim rectification/calibration quality.

Use the same accepted source-frame intervals for both eyes, full frame sequences
and sensor samples. Sensor exposure and IMU share the camera's clock; host receive
time is a separate field, never relabelled as capture time. Counter rollover is
unwrapped, overlapping IMU samples are deduplicated, and conflicting samples fail.
Cuts retain their original sensor timestamps and explicit segment mappings.
Payment continues to count the one accepted timeline, never the sum of two eyes
or the number of artifacts.

## Local worker stage

Catalog implements `pipeline.clean_artifacts` using its existing bounded EGOC
reader and optical sensor decoder, Pillow and PyAV. Tested locally with PyAV
18.1, Pillow 12.1 and NumPy 2.4. It has no dependency on a sibling EGOCAM checkout.
Run from the catalog repository:

```sh
python3 -m pipeline.clean_artifacts --plan extraction-plan.json --out /new/path/bundle
python3 -m pytest tests/test_clean_artifacts.py -q
```

The plan identifies one source snapshot, an explicit layout, exact expected
decoded frame count, the final frame duration and its evidence, and QC intervals
in zero-based, half-open source-frame coordinates. All source frames must be
covered by keep/reject intervals; rejection requires a reason. Example (replace
the example identity, geometry, timing and digest with source evidence):

```json
{
  "schema": "6thsense-clean-extraction/1",
  "recording": "ego_20260914_120000_ABC123",
  "source": {
    "kind": "egoc",
    "media": {"path": "/snapshot/capture.egoc", "sha256": "<64 lowercase hex characters>"}
  },
  "source_frame_count": 900,
  "last_frame_duration_us": 33280,
  "last_frame_duration_basis": "Validated camera cadence from this source",
  "layout": {
    "width": 4000, "height": 1200,
    "left": [2080, 0, 1920, 1200], "right": [160, 0, 1920, 1200],
    "rotation_degrees": 0,
    "provenance": "Verified upright mount declaration for this source camera"
  },
  "intervals": [
    {"start_frame": 0, "end_frame": 300, "disposition": "keep"},
    {"start_frame": 300, "end_frame": 600, "disposition": "reject", "reason": "Computer work"},
    {"start_frame": 600, "end_frame": 900, "disposition": "keep"}
  ]
}
```

Supported sources:

- `egoc`: intact source container with decodable sensor strips.
- `stereo_video`: native video with a surviving sensor strip. An MP4 extension
  does not establish whether the strip survived; every frame is checked.
- `split_video`: `media` is already the left eye, with additional `right`, `frames`
  and `imu` `{path, sha256}` references and `sensor_sidecar_provenance`. Frame CSV
  requires `source_frame,exp_start_us,exp_end_us` in **unwrapped sensor microseconds**.
  IMU CSV requires `timestamp_us,ax_ms2,ay_ms2,az_ms2,gx_degs,gy_degs,gz_degs`.
  Left/right decoded counts and PTS must match. Missing sidecars cannot be recovered
  from already-cropped images alone.

PNG preserves decoded pixels without an additional lossy image encoding. Frames
are paired into bounded TAR shards (at most 100 pairs or approximately 256 MiB of
combined PNG payload per shard set). SQLite stages IMU deduplication on disk.
Videos use measured PTS/durations, with no fixed-frame-rate resampling. Both MP4s
are fully decoded again and compared frame-for-frame against the shared index.
The final frame's duration cannot be derived from a following exposure; its
explicit basis is retained instead of silently assuming 30 fps.

Invalid/missing barcode data, conflicting samples, missing IMU coverage, ambiguous
layout, corruption, changed source hashes, unexpected counts and timing
discontinuities fail the stage. No completed bundle is published on failure.
The recovery worker decides whether to recover original versions/sidecars, retry,
or reject with evidence. This stage alone does **not** decide irrecoverability.
Do not fabricate IMU or accept a preview as a substitute. A source with multiple
capture chunks or discontinuous clocks first needs source-aware normalization and
segmentation by that worker; this stage is not a chunk-discovery engine.

## Publication and Ops integration

`artifacts.json` is a **local bundle inventory**, not an S3 completion marker or a
payable run. The external worker still needs to connect recovery/activity QC,
the extraction stage and publication:

1. Pin and download the exact Raw source versions, including timing/IMU sidecars.
   Record S3 bucket, key, version, SHA-256 and byte size. Establish contributor,
   orientation and source-frame QC decisions from trusted evidence.
2. Run extraction and use the resulting measured `intervals` and `media` fields
   in the corresponding recording of a QC v2 document. Derive run time totals
   from those intervals once. Do not copy a fixed-30-fps v1 timeline and claim it
   is sensor time.
3. Upload every artifact under `clean/<run_id>/<recording>/`. Translate each
   artifact's relative `path` to `key`; preserve role, recording, counts, byte
   length and SHA-256; add its actual S3 `version_id`. Store SHA-256 in S3 metadata
   and verify uploaded contents. Never invent version IDs.
4. Publish the pinned `qc-results/<run_id>/result.json`, then `_SUCCESS.json`
   referencing the exact manifest key/version/SHA-256, only after all checks.
5. Ops verifies the manifest, every pinned output and its size/hash metadata.
   Import rejects new video-only results. A worker claim advertises the v2 output
   requirement, and `/result` refuses completion against v1 evidence.
6. Reconcile exact Raw source receipts before clearing backlog. Source deletion
   must remain a separate verified action; the stage and API never delete Raw.

The trusted worker is responsible for actual frame/archive/IMU content checks;
the API cannot infer CSV or TAR contents from S3 metadata alone. There is no new
deployed worker or S3 publisher in this change. The stage does not implement hand
visibility detection or computer-work classification; it consumes their reviewed
frame decisions. The ink-factory exclusions remain collection-specific.

## Historical footage and payment preservation

Existing v1 entries remain readable, with `artifact_status: legacy_video_only`.
Ops shows that separate eyes, full frames and IMU have not been verified. New v2
recordings can be reviewed using the left-eye video, with both eyes available in
the player. No payment values, reservations, approvals or historical manifests
are rewritten. Importing upgraded artifacts as another payable run is blocked by
the existing source-overlap guard. A future artifact-only backfill/supersession
path is required; this change does not duplicate earned time.

Read-only spot checks found readable barcodes in the first frames of three saved
native raw samples and the first five frames of one live native Clean MP4. This
establishes that **some** sources may be recoverable, not that every historical
frame survived. Previously deleted originals may limit recovery. Audit the entire
retained source before deciding; preserve available native files meanwhile.

## Validation evidence

Synthetic tests exercise actual EGOC/JPEG decode, native-video decode, measured
split-pair sidecars, left/right identity, identical QC cuts, frame counts,
microsecond timing, MP4 duration, counter rollover, IMU deduplication and missing
data failures. Ops tests reject missing modalities, incomplete shards, altered
timelines and video-only worker completion while retaining v1 reads.

A local 12-frame sample from saved native camera footage produced 9 retained
frame pairs, 85 IMU samples and all seven artifact roles, passing full MP4 decode
and the Ops v2 artifact validator. Its synthetic cuts and assumed upright layout
are a technical canary, **not activity QC, a payable episode or an upload**.
Local evidence is under catalog `.context/clean-artifacts-2026-09-14/`.

Completed checks: 84 extraction/container tests, 58 Ops artifact/ledger/worker
tests, and 12 browser tests across phone, tablet and desktop; the production
frontend build also passed. Docker did not respond, so the database tests used
a disposable local PostgreSQL 17 instance, stopped and removed after the run,
instead of the repository's PostgreSQL 16 testcontainer. No production database
was used. These checks do not establish deployed-worker or historical-backfill
readiness.

PyAV timing reference: https://pyav.org/docs/stable/api/time.html
