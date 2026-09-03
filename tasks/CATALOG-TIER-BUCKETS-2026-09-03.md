# Catalog tier buckets — 2026-09-03

The buyer catalog now reads its manifest, clip documents and preview assets from
`s3://6thsense-catalog/v2/`. Bundle-relative paths beginning with `media/` are
presigned from the processed cohort at
`s3://6thsense-processed/imported/2026-08-24_nervous-1/`; the `media/` segment is
removed before the package key is formed. Both tiers share the catalog region and
`CATALOG_AWS_*` credentials.

## Railway backend variables

Apply these exact values to the backend service, then deploy through the normal
Railway workflow:

```dotenv
CATALOG_S3_BUCKET=6thsense-catalog
CATALOG_S3_PREFIX=v2/
CATALOG_PACKAGE_BUCKET=6thsense-processed
CATALOG_PACKAGE_PREFIX=imported/2026-08-24_nervous-1/
```

Do not add package-specific credentials. Both tiers reuse the existing catalog
credentials and region; ensure that identity has read access to the processed prefix.

## Safe rollout order

1. Ship the `frontend/Caddyfile` CSP additions first. They are a no-op while the
   policy is report-only and make both new S3 origins safe before the data switch.
2. Deploy the backend code with the environment unchanged. The package tier
   defaults to the current catalog tier, so this is a true no-op.
3. Apply all four catalog variables above in one Railway update, then redeploy.
   Never update only a subset of the four.
4. Complete every verification below before declaring the rollout healthy.
5. If rollback is needed, restore `CATALOG_S3_BUCKET=6thsense-catalog-media` and
   `CATALOG_S3_PREFIX=v2/` **first**, then redeploy the previous revision.

## Verify after deploy

1. Authenticate as a catalog user and `GET /api/catalog`; confirm the manifest is
   returned successfully and preview URLs point at `6thsense-catalog`.
2. Open one published clip through `/api/catalog/clips/<clip_id>`.
3. Copy one returned URL whose bundle-relative source is under `media/`, request it,
   and confirm HTTP 200 with a `6thsense-processed.s3.<region>.amazonaws.com` host and
   an `imported/2026-08-24_nervous-1/<clip_id>/...` key.

## Roll back

First restore `CATALOG_S3_BUCKET=6thsense-catalog-media` and
`CATALOG_S3_PREFIX=v2/`. Only after that environment rollback has completed, redeploy
the preceding application revision. The previous code ignores the package variables.

## Gate

Branch command:

```text
$ python3 -m pytest backend/tests/test_catalog_store.py backend/tests/test_catalog_upload_bundle.py backend/tests/test_catalog_api.py -q -p no:cacheprovider
104 passed, 58 warnings in 14.68s
```

Docker/testcontainers was available, so the API tests ran rather than being skipped or
reported as environment-blocked.

### Mutation proof

Planted unsafe hardcoded processed-tier defaults and blank handling. The targeted run went
red with the default case and both blank/whitespace cases:

```text
3 failed, 1 warning in 0.33s
```

Then planted three routing/health/cache regressions together: skipped the package
`head_object`, routed `archives/` with the catalog bucket, and removed package bucket/prefix
from `_signature_of`. All four guards went red:

```text
4 failed, 1 warning in 0.36s
```

After restoring the implementation, the combined targeted run returned:

```text
7 passed, 1 warning in 0.30s
```

### Adversarial review

Attacked empty and whitespace env vars, empty/odd manifests, null `package_contents`, package
head denial, archive traversal, local mode, cache invalidation, all regional/global CSP hosts,
and stale old-tier documentation. Found and fixed one stale README sentence that still named
the rollback bucket for previews. Path validation remains centralized in `resolve_key`; package
probe failures expose only the exception class to staff; local health remains successful. The
known cross-region limitation remains unchanged because both configured buckets are in
`us-west-2` and this task did not add a package-region setting.

### Demo

```text
code-only: 6thsense-catalog-media v2/media/
posters/clip.jpg -> 6thsense-catalog/v2/posters/clip.jpg
media/clip/video/left.mp4 -> 6thsense-processed/imported/2026-08-24_nervous-1/clip/video/left.mp4
archives/clip.tar.gz -> 6thsense-processed/imported/2026-08-24_nervous-1/_archives/clip.tar.gz
```

This was generated directly from `get_catalog_settings()` and
`S3CatalogStore._asset_location()` with the code-only environment followed by the four-variable
production environment. No network or AWS credentials were used.
