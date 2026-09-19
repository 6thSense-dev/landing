# Contributor storage — deployed 2026-09-14

- Bucket: `s3://6thsense-contributor-records`
- AWS account: `194680606079` (`6thsense-production`)
- Region: `us-west-2`
- CloudFormation stack: `sixthsense-contributor-records`

The bucket is live. CloudFormation completed, all four public-access blocks are enabled, ACLs are disabled (`BucketOwnerEnforced`), default encryption is SSE-S3 (`AES256`), versioning is enabled, and its bucket policy denies non-HTTPS access. The bucket is retained on stack deletion/replacement. No object-expiration policy has been added.

Seven initial objects were written and read back: `_meta/README.md`, `_meta/layout.json`, and five empty prefix markers. Encryption and non-null S3 version IDs were verified on every object. Anonymous HTTPS access to the layout returns HTTP 403. Current IAM simulation for `egocam-korea` and `egocam-china` explicitly denies both GetObject and PutObject in this bucket.

## Storage responsibilities

| Information | Authority / location |
| --- | --- |
| Login passwords, MFA, account recovery, access/refresh tokens | Separate contributor Cognito pool; see [identity resources](CONTRIBUTOR-REGISTRATION.md#aws-identity-resources). Staff identity and portal authentication remain separate. Bucket provisioning did not change a login configuration. |
| Current contributor profile, account link, contact, camera assignment, collection and payment ledger | Application database. Resolve the verified identity-provider issuer + subject to a stable contributor ID. |
| Approved agreement documents | S3 `terms/<region>/<agreement>/<version>/<locale>.<ext>` |
| Founder publication approval | Insert-only application `OpsSetting` records at `contributor_terms_audit_<publication-id>`, preserving authenticated founder identity, time, routing and exact document versions/hashes. An upload alone does not publish terms. |
| Durable consent evidence | Original immutable snapshot in `contributor_consents`; staff export writes S3 `consent-receipts/<account-subject>/<receipt-id>.json` without replacing an existing object. |
| Interim Korean Google Form contracts | Linked Google Sheet is the contractor register; restricted Drive stores frozen source/Form shape and signed receipts; `contributor_form_contracts` mirrors the authenticated evidence and verified account link. See the [Form register guide](contributors/google-form-register.md). This does not move existing app consent receipts out of S3. |
| Korean website bank registration | Full account holder, bank and account number in the private workbook's **Bank details** tab, keyed by contributor ID. The application database stores only a masked `sheet_saved` receipt and consent evidence. See [bank spreadsheet storage and deletion](contributors/bank-spreadsheet.md). Registration creates no Wise recipient. |
| Contributor/account metadata exports | S3 `profile-exports/<contributor-id>/<export-id>.json` |
| Camera details and assignment-history exports | S3 `camera-exports/<device-id>/<assignment-id>/<export-id>.json` |
| Payout approval and provider reconciliation evidence | S3 `payment-receipts/<contributor-id>/<payout-id>/<event-id>.json` |

S3 exports are evidence and document storage, not the mutable authority for ownership or payable balances. Never store passwords/password hashes, session cookies, access/refresh tokens, AWS keys or Wise secrets in this bucket. Avoid personal names, phone numbers and emails in object keys.

## App/backend integration

Use a backend-only, least-privilege IAM identity. The existing camera upload identities cannot be reused. Contributor-facing downloads must authenticate the account, verify the database relationship, and sign access only to that contributor's specific object/version. No permanent AWS credentials belong in the phone app. No new backend IAM grant or cross-account grant was made during bucket provisioning.

The [mobile pilot](CONTRIBUTOR-MOBILE-PILOT.md) persists account links and server-timestamped consent snapshots in the database. Publication requires an explicitly allowlisted founder and four complete documents per language: `participation`, `privacy`, `collection`, and `international_transfer`. Consent pins all four versions, hashes and the selected locale. `POST /api/ops/contributors/consents/export` retries those original snapshots with stable receipt IDs and conditional S3 writes. An S3 interruption leaves the originals available; automatic export scheduling remains pending. Camera ownership remains a verified, effective-dated database assignment; writing a camera JSON file cannot claim a device. Payment evidence does not initiate or mark a payout as settled.

At the 2026-09-14 provisioning checkpoint, only infrastructure and the layout were created. The subsequent mobile API implements authenticated agreement downloads, version/hash verification and explicit consent export using the configured Ops AWS credentials. Production agreements and real pilot consent are still absent, and profile/camera export jobs remain unimplemented. The app preview's agreement text remains unapproved.

## Source and verification

Catalog repo source: `infra/contributor-records.yaml` and `infra/contributor-records-layout.json`. Local deployment evidence: `.context/contributor-records-2026-09-14/verification.json`. The CloudFormation change set contained only the new bucket and its HTTPS policy; existing video buckets, camera destinations and identity pools were unchanged.

[Amazon Cognito user pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html) provide application authentication. [S3 security guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html) describes the bucket controls used here.
