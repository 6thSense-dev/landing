# Configured recording sources

The existing Raw inventory panel can list configured recording locations across AWS accounts. Opening the panel reads the source registry; only **Check inventory coverage** performs S3 LIST calls. Changing source clears old results. Access errors remain incomplete/unknown, not empty inventory.

The default source `operations` retains the existing Operations bucket and credentials. Optional `OPS_INVENTORY_SOURCES` is a JSON array of at most10 additional sources. Each has `id`, `label`, `bucket`, `prefix`, and12-digit `expected_owner`. Extra fields, duplicate/reserved IDs and malformed values fail closed. No credentials or role names belong in this configuration.

Example locations for a reviewed deployment configuration—not applied by this PR:

```json
[
  {"id":"production-sessions","label":"Production recordings","bucket":"6thsense-raw","prefix":"sessions/","expected_owner":"194680606079"},
  {"id":"company-legacy","label":"Company legacy raw","bucket":"6thsense-dev-raw","prefix":"","expected_owner":"537124957922"}
]
```

All checks use existing Operations credentials and region. A successful additional-source request is constrained with S3 `ExpectedBucketOwner`; simply displaying the expected owner does not verify access. No roles, permissions, credentials, bucket policies or production environment variables are changed. Personal AWS Google/SSO login is separate from this server-side source configuration.

Registry: `GET /api/ops/inventory-sources`. Coverage: `GET /api/ops/inventory-coverage?source_id=production-sessions`. Both require Operations authorization. Clients cannot supply arbitrary buckets, owners, prefixes or profiles. Unknown IDs404; invalid configuration503; storage failures return incomplete evidence. Responses are not cached.

Coverage is limited to the selected prefix and bounded current-object listing. A prefix inside a recording may not include its parent metadata; that is reported separately as outside-scope/unknown, not missing. Only absent metadata keys inside the checked scope contribute to the missing count; incomplete listings still mean not yet observed. None of these counts prove recording quality, import status, unique hours or credit.

Tests use synthetic registries and mocked S3/browser responses. No real cross-account access or deployment is established here. Actual permissions and source registration remain deployment dependencies.
