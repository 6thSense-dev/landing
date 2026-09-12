# Clean footage in Collector operations

`/portal/ops` has Raw, Clean, and Users tabs. These routes remain restricted to ops, founder, and admin accounts. The read-only learning preview does not expose Clean.

In Users, record a contributor's workplace, location, contact, and optional KRW hourly rate. In Clean, explicitly assign a camera to that contributor. The optional checkbox also assigns existing unassigned, unpaid raw recordings. It does not change existing ownership or payment history.

Refresh clean footage imports completed QC collections from `6thsense-processed/qc-results/`. Each `_SUCCESS.json` pins its sibling `result.json` by S3 version and SHA-256. The result uses schema `6thsense-clean-qc/1`, with decoded source durations, a complete keep/reject interval partition, versioned source hashes, and versioned clean outputs under `clean/<run_id>/`. The server checks the manifest digest and output size/hash metadata before importing. Invalid or incomplete runs do not create earnings.

The contributor and hourly rate are captured at import time. Estimated KRW is retained seconds × hourly rate / 3600, rounded once to the nearest won. Unknown rates remain blank. A re-import does not replace the rate or create another estimate; overlapping recordings or identical source content require explicit reconciliation. Sources already paid in the raw ledger cannot become a new unpaid clean estimate.

Retained time is the outcome of the stated QC rule, not a guarantee that every retained moment is productive. Other idle footage remains subject to review. Importing and watching a clean collection do not send money or mark payment complete. The existing raw ledger's per-episode payment mechanism is unchanged.

Playback uses short-lived presigned URLs for the exact output versions. Browser previews and original-resolution stereo files may both be included. Raw source objects remain in place. The API needs only ListBucket for `sessions/` in raw and `qc-results/`, `clean/` in processed, plus GetObject/GetObjectVersion for those prefixes. Configure its dedicated read-only credentials through `OPS_AWS_ACCESS_KEY_ID` and `OPS_AWS_SECRET_ACCESS_KEY`; `OPS_CLEAN_S3_BUCKET` defaults to `6thsense-processed`.

Migration `0013` adds contributor details, camera assignments, and the clean collection ledger. The deployment starts with `alembic upgrade head`.
