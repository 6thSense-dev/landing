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
| Login passwords, MFA, account recovery, access/refresh tokens | Authentication service. Existing company-account Cognito pools are integration candidates; no user pool or login configuration was changed here. Existing portal authentication stays unchanged. |
| Current contributor profile, account link, contact, camera assignment, collection and payment ledger | Application database. Resolve the verified identity-provider issuer + subject to a stable contributor ID. |
| Approved agreement documents | S3 `terms/<region>/<agreement>/<version>/<locale>.<ext>` |
| Durable consent evidence | S3 `consent-receipts/<contributor-id>/<receipt-id>.json`, referenced by the database |
| Contributor/account metadata exports | S3 `profile-exports/<contributor-id>/<export-id>.json` |
| Camera details and assignment-history exports | S3 `camera-exports/<device-id>/<assignment-id>/<export-id>.json` |
| Payout approval and provider reconciliation evidence | S3 `payment-receipts/<contributor-id>/<payout-id>/<event-id>.json` |

S3 exports are evidence and document storage, not the mutable authority for ownership or payable balances. Never store passwords/password hashes, session cookies, access/refresh tokens, AWS keys or Wise secrets in this bucket. Avoid personal names, phone numbers and emails in object keys.

## App/backend integration

Use a backend-only, least-privilege IAM identity. The existing camera upload identities cannot be reused. Contributor-facing downloads must authenticate the account, verify the database relationship, and sign access only to that contributor's specific object/version. No permanent AWS credentials belong in the phone app. No new backend IAM grant or cross-account grant was made during bucket provisioning.

On registration, the backend should persist the account/contributor link, approved agreement versions and server-recorded consent receipt, then create the corresponding S3 evidence with a stable receipt ID. Use a durable outbox/retry path so an S3 interruption cannot fabricate consent or lose an accepted registration event. Camera ownership remains a verified, effective-dated database assignment; writing a camera JSON file cannot claim a device. Payment evidence does not initiate or mark a payout as settled.

Only infrastructure and the layout are provisioned. No real contributor profile, camera assignment, payment receipt, production agreement or legal-consent receipt was uploaded. Login/registration, database export jobs and contributor-authorized download endpoints still require integration. The app preview's agreement text remains unapproved.

## Source and verification

Catalog repo source: `infra/contributor-records.yaml` and `infra/contributor-records-layout.json`. Local deployment evidence: `.context/contributor-records-2026-09-14/verification.json`. The CloudFormation change set contained only the new bucket and its HTTPS policy; existing video buckets, camera destinations and identity pools were unchanged.

[Amazon Cognito user pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html) provide application authentication. [S3 security guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html) describes the bucket controls used here.
