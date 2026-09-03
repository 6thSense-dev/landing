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
$ python3 -m pytest backend/tests -q -p no:cacheprovider
300 passed, 96 warnings in 72.06s (0:01:12)
```

Detached `origin/main` scratch-worktree baseline at
`4f47e70bc053f57808113bc3e23f336b8b4b358f`:

```text
$ python3 -m pytest backend/tests -q -p no:cacheprovider
291 passed, 96 warnings in 70.14s (0:01:10)
```

Failing-test name diff: empty. The branch adds nine passing tests.

### Mutation proof

Planted two bugs together: package `media/` URLs used `settings.bucket` instead of
`settings.package_bucket`, and the upload guard returned early unconditionally. The targeted
run went red with these failures:

```text
FAILED backend/tests/test_catalog_store.py::test_s3_signs_media_against_the_processed_package_tier
FAILED backend/tests/test_catalog_upload_bundle.py::test_package_directories_are_refused_without_override[media]
FAILED backend/tests/test_catalog_upload_bundle.py::test_package_directories_are_refused_without_override[archives]
3 failed, 2 passed, 1 warning in 0.52s
```

After restoring the implementation, the same targeted command returned:

```text
5 passed, 1 warning in 0.46s
```

### Adversarial review

Attacked `media/../secret` and `media/x/../../secret`, preview routing, an empty package bucket,
half-configured credentials, accidental `media/` and `archives/` uploads, and the explicit
emergency override. Path validation remains centralized in `resolve_key`; preview paths keep
the current catalog bucket and `v1/` prefix; package configuration participates in store-cache
invalidation. The override remains an intentional operational escape hatch and is called out
as requiring explicit review. No untested change outside the nine allowlisted files remains.

### Demo

The presigning test exercises botocore's real SigV4 URL generation and verifies that the same
catalog credential signs both hosts:

```text
$ python3 -m pytest backend/tests/test_catalog_store.py::test_presigning_uses_the_catalog_key_and_not_the_ambient_one -q -p no:cacheprovider
1 passed, 1 warning in 0.52s
```

It asserts preview output on `https://6thsense-catalog-media.s3.../v1/...` and package output
on `https://6thsense-processed.s3.../imported/2026-08-24_nervous-1/...`, with
`AKIACATALOGREADER00000` embedded in both signatures and the ambient firmware credential absent.
