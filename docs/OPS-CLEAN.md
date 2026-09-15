# Clean footage in Collector operations

`/portal/ops` separates Raw, Clean, Payment, and Users. These routes remain restricted to ops, founder, and admin accounts. The read-only learning preview does not expose Clean.

In Users, record a contributor's workplace, location, contact, and optional KRW hourly rate, and explicitly assign their camera. The optional checkbox also assigns existing unassigned, unpaid raw recordings. It does not change existing ownership or payment history.

## Browse by region

Clean opens with **Korea**, **China**, **Vietnam**, and **India**, including empty countries. **Needs region review** and **Test footage** appear when the stored runs require them. Select a region to browse its contributors and footage; use **All regions** or the Region selector to navigate back or switch regions.

The overview and selected-region totals show **all-time** collected/decoded, accepted-after-QC, and excluded time, plus acceptance rate and recording, contributor, and camera counts. Time comes from the original Clean source runs, including paid history. It is not the pending Raw inventory, and adding a joined viewing copy adds no hours. Acceptance rate is retained seconds divided by decoded source seconds; empty regions show no rate.

Within a region, the contributor filter appears when more than one contributor is present. It narrows the displayed footage sections; **region totals still include everyone**. Each contributor section includes only that region's runs, with decoded, retained, and excluded time. Review entries are matched by run, so a contributor's footage in another region does not enter the selected region's review list. Review and payment approval remain separate actions.

## Region attribution

`GET /api/ops/clean/state` adds a `{key, label, status}` region classification to each run. Classification uses its preserved manifest: explicit `region` or `country` fields, or those fields in `tags`, at the manifest, recording, or source level. It recognizes the four country names and `KR`, `CN`, `VN`, and `IN`, case-insensitively. Historical `sessions/<session>/...` source keys also supply country tokens delimited by underscores or hyphens; `trial` and `flowtest` tokens identify test footage when the evidence is otherwise unambiguous.

The whole batch stays in **Needs region review** if source attribution is missing, unsupported, or conflicting, including batches spanning multiple countries. Its hours remain counted there until the evidence is resolved. The classifier does not guess from a contributor's name, current profile location, camera owner, or rate. Preserved source provenance remains available after Raw cleanup, and editing a person's profile does not move historical hours between regions.

Future processing manifests must carry the verified capture-region metadata or source tags forward. This display classifier reads stored manifests; it does not fetch missing S3 tags or establish attribution for a new upload. Region grouping creates no regional S3 buckets, moves no objects, and changes no payments.

## Imports, playback, and review

Refresh clean footage imports completed QC collections from `6thsense-processed/qc-results/`. Each `_SUCCESS.json` pins its sibling `result.json` by S3 version and SHA-256. Historical `6thsense-clean-qc/1` results remain readable; new imports use `6thsense-clean-qc/2` and the required [Raw → Clean artifacts](RAW-TO-CLEAN-ARTIFACTS.md). Results carry decoded source durations, a complete keep/reject interval partition, versioned source hashes, and versioned clean outputs under `clean/<run_id>/`. The server checks the manifest digest and output size/hash metadata before importing. Invalid or incomplete runs do not create earnings; refresh reports skipped results while importing unrelated valid collections. Recording labels must match their source S3 paths and camera IDs.

The contributor and hourly rate are captured at import time. Estimated KRW is retained seconds × hourly rate / 3600, rounded once to the nearest won. Unknown rates remain blank. A re-import does not replace the rate or create another estimate; overlapping recordings or identical source content require explicit reconciliation. Sources already paid in the raw ledger cannot become a new unpaid clean estimate.

Retained time is the outcome of the stated QC rule, not a guarantee that every retained moment is productive. Other idle footage remains subject to review. Importing and watching a clean collection do not send money or mark payment complete. Review and payout approval follow the separate [Ops workflow](OPS-WORKFLOW.md); region browsing preserves historical payment records.

Clean shows one section per contributor within the selected region. Expand **Batch details & source recordings** for individual batch playback, retained/excluded time, QC notes, and source recordings, or **Flagged footage to review** to open review intervals. Use the recording-specific review controls before approving a payout in Payment.

Combined viewing collections appear only when all their referenced runs are known and belong to the same region. A collection spanning regions or referencing a missing run is omitted from region playback; its individual batches remain available in their own regions. When one collection covers every batch in that contributor's region section, select **Watch all clean footage** to watch retained recordings in recording-date order. A collection covering only some batches is labeled **Watch combined footage**; if several collections are available, each button uses its collection label. Combined playback is a non-payable viewing convenience: accepted time and earnings still come only from the original clean runs, so grouping adds no earnings and changes no payment status.

A one-off operator publisher prepares and fully decodes the joined preview before registering its verified metadata in the JSON-list setting `ops_clean_collections_v1`. These entries use schema `6thsense-clean-collection/1` with `payable: false`; they are not new QC imports. The entry pins at least two distinct source runs by run ID and manifest SHA-256, requires the same contributor on every run, and must list each retained recording exactly once in date order. Its retained duration must match the source-run total. The output carries an immutable S3 version, SHA-256, byte count, and successful full-decode evidence.

`GET /api/ops/clean/state` returns verified viewing collections separately from payable runs and reports invalid entries through `collection_errors`. `GET /api/ops/clean/collections/{collection_id}/files` revalidates the source-run hashes and contributor attribution, checks the pinned output's size and hash metadata, and returns a short-lived playback URL. A missing collection or changed source ledger returns 404; an output verification or signing failure returns 502. Invalid combined entries leave the original batches and estimates available. **Reload video link** also renews combined playback at the current position.

Raw's **Partly processed** label means a recording has a clean result but still has files awaiting processing, such as additional uploads or failed files. Completed footage is available in Clean. Fully processed and unavailable recordings appear only when **show processed / unavailable** is enabled; neither a combined viewing collection nor this filter deletes raw media. See the [Raw processing queue](../backend/README.md#raw-processing-queue) for receipt matching and scan behavior.

Playback uses short-lived presigned URLs for the exact output versions. Browser previews and original-resolution stereo files may both be included. Use Reload video link to renew an expired URL while preserving the playback position. Raw source objects remain in place. The API needs only ListBucket for `sessions/` in raw and `qc-results/`, `clean/` in processed, plus GetObject/GetObjectVersion for those prefixes. Configure its dedicated read-only credentials through `OPS_AWS_ACCESS_KEY_ID` and `OPS_AWS_SECRET_ACCESS_KEY`; `OPS_CLEAN_S3_BUCKET` defaults to `6thsense-processed`.

Migration `0013` adds contributor details, camera assignments, and the clean collection ledger. The deployment starts with `alembic upgrade head`.

## Region-view validation checkpoint

For version `0.0.7.0`, validation passed 65 unique backend checks across the original 64-check suite and the added API regression, seven Node tests, 18 Playwright tests, and the frontend build. Coverage includes preserved-source attribution, missing/mixed batches, region-contained playback and review, unchanged region totals while filtering contributors, and unchanged ownership/rate/payment fields. API deployment `1a2ba928-2532-40e0-bdad-3b43d9c1a677` succeeded: live source hashes match `cd3172f`, existing records classify correctly, and the complete Clean database row hash is unchanged, including payments, manifests, and rates. Frontend deployment remains pending at this checkpoint; the complete live UI rollout is not yet verified.
