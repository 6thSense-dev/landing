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

Do not add package-specific credentials. `catalog-media-reader` already has the
required read access and both tiers reuse the existing catalog credentials and
region.

## Verify after deploy

1. Authenticate as a catalog user and `GET /api/catalog`; confirm the manifest is
   returned successfully and preview URLs point at `6thsense-catalog`.
2. Open one published clip through `/api/catalog/clips/<clip_id>`.
3. Copy one returned URL whose bundle-relative source is under `media/`, request it,
   and confirm HTTP 200 with a `6thsense-processed.s3.<region>.amazonaws.com` host and
   an `imported/2026-08-24_nervous-1/<clip_id>/...` key.

## Roll back

Set the two catalog variables back to the previous catalog location and redeploy:

```dotenv
CATALOG_S3_BUCKET=6thsense-catalog-media
CATALOG_S3_PREFIX=v2/
```

Leave the package variables recorded so a forward switch can be reapplied without
reconstructing the cohort path.
