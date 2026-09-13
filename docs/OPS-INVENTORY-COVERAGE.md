# Raw inventory coverage check

In Operations → Raw, expand **Which recordings does this board cover?** and choose **Check inventory coverage**. This performs a read-only census of the configured Operations bucket. Recognition uses the existing scanner's folder parser; recognition does not establish that an episode exists in the database.

The endpoint `GET /api/ops/inventory-coverage` requires the existing Operations role gate. It uses the configured raw bucket and credential selection, with no request-selected bucket, object downloads, database writes, approvals or payment changes. It does not modify Clean review.

## Interpreting results

- A completed listing counts current objects observed during pagination, not object versions or a transactionally frozen snapshot.
- Matching recording folders are counted separately. Repeated recording names in different folders are flagged; no deduplication or identity decision is inferred.
- Metadata counts mean file presence only. No media decoding, content validation, camera-quality assessment or usable-hour calculation occurs.
- Partial counts are observations, not full totals. Missing metadata on a partial listing means not yet observed.
- Failed storage access is unknown, even when zero entries were observed. It is not evidence of an empty bucket.
- Examples may include object names. They are available only to Operations-authorized users and are rendered as text.

The check lists from the bucket root, so credentials allowing only `sessions/` listing may return incomplete coverage. This feature does not grant additional storage permissions. Limits are 10,000 objects, 20 requests and 20 examples per category. Each S3 request uses a 3-second connection timeout, 5-second read timeout and one SDK attempt. These are request bounds, not a guaranteed total wall-clock deadline.

## Review evidence

Synthetic backend tests cover denied versus empty, pagination, caps, malformed responses, folder collisions, missing metadata, credential configuration and auth gates. Browser tests intercept every API call and verify explicit loading, partial wording, escaped names, stale-result removal after failed refresh and absence of writes at three viewport sizes.

Run:

```sh
python -m pytest backend/tests/test_ops_inventory.py backend/tests/test_ops_inventory_routes.py -q
cd frontend
E2E_PORT=4279 npx playwright test tests/e2e/ops-inventory.spec.js
```

These tests do not establish production bucket access or real inventory totals. No production deployment is included.
