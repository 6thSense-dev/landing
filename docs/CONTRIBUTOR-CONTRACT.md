# Contributor contract: Synapse app and Ops

Coordinated 2026-09-14. This is an integration contract, not approved legal text or a claim of deployment. Both repositories carry this document; update both when the contract changes.

## Ownership and current implementation

- Synapse `src/lib/contributor/model.ts` and `ContributorPreview.tsx` own the app preview. Account sign-in, regional invitations, camera registration, consent and earnings are currently in-memory examples behind `EXPO_PUBLIC_CONTRIBUTOR_PREVIEW`.
- Landing Ops owns the existing `ops_wearers`, camera roster, raw inventory and committed Clean manifests. The workflow branch adds recording review, processing leases, payout reservations and a Wise adapter. These are operator APIs, not contributor-authenticated mobile APIs.
- Ronak's QC pipeline owns media validation/recovery, exclusions and committed Clean outputs. A queue or an S3 directory alone is not evidence that recovery/QC ran.
- Existing manually entered contributors must remain distinguishable from app accounts. Never infer a verified account, consent or bank ownership from a name, camera ID or an operator roster entry.

## Registration and terms

Use the app's three agreement identifiers: `participation`, `privacy`, `collection` (recording/payment guidelines). The current `KR-PREVIEW-1` / `US-CA-PREVIEW-1` texts are placeholders and must never be accepted as production consent.

Production terms configuration must resolve the collection/region to the required documents, each with an immutable version, locale, content SHA-256, and approved document URL. Until approved text is published, the production status is `terms_not_configured`; a preview checkbox cannot bypass it.

An authenticated acceptance receipt must contain the stable account subject, contributor ID, collection enrollment ID, each agreement ID/version/hash/locale, and a server timestamp. Record acceptance only after the contributor views and accepts the configured documents. New required versions or reenrollment in another collection require new acceptance. Do not manufacture receipts for existing contributors or use an Ops administrator's session as contributor consent.

Account → contributor is an explicit verified link. Preserve contributor, footage and payment history if login access is revoked. The mobile client reads its own ledger through authenticated server endpoints; it never supplies authoritative payable time, rate, recipient ownership or payout status.

## Camera and recording attribution

Normalize camera IDs to six uppercase hex characters internally; display `EGO-<id>`. Camera hotspot discovery proves reachability, not ownership. Claim a camera with supported device proof or supervised operator provisioning, reject conflicting assignments, and retain effective-dated assignment history.

Bind the upload receipt to the immutable capture-time assignment, recording ID and expected source objects/versions/checksums. Validate that assignment server-side. Current camera ownership, S3 folder names, SD-card swaps and an uploader-supplied contributor ID are insufficient to rewrite past attribution. Hold ambiguous history for operator resolution.

Confirmed Korean pilot roster:

| Camera | Contributor | Workplace |
| --- | --- | --- |
| EGO-16A4A5 | 한규태 | 한그라픽스 |
| EGO-16A2B6 | 최희웅 | 최희웅 |
| EGO-4A636A | 윤정원 | 아이픽스존 |
| EGO-1696C8 | 김명천 | 김명천 |

## Time and payment policy

- Korean rate: KRW 11,000 per accepted hour. Other countries require their own agreed local currency and rate; no invented production fallback.
- Keep uploaded/source duration, pending validation, QC-retained duration, excluded duration with reasons, operator-reviewed duration, reserved payouts, sent and confirmed paid separate. Decode measured duration; do not use file size or an unreliable camera clock as duration. Stereo pairs and joined previews do not add payable time.
- Eligibility is **strictly more than four hours of accumulated unpaid accepted time**. The payable subset must have operator review and confirmed collection dates. Carry earlier unpaid balances forward. Ops currently schedules Friday 18:00 Asia/Seoul using completed Monday–Sunday collection weeks; that hour is an implementation default, not a user-specified exact cutoff.
- Operators review all included footage and click **Approve Payment** for exact immutable recording/manifest references, recipient and amount. Approval never includes future uploads. Reserve each unit once; repeated approval, worker retries and provider events must not pay twice.
- Start approved payouts Friday. Contributor-facing timing: allow up to five business days after initiation, with actual progress shown from the provider. Do not promise a receipt date from a scheduler timestamp.
- Wise account is US-based; recipient receives KRW for Korea. USD is the proposed funding default, and sender fees must not reduce the approved recipient amount. Verify the configured profile, recipient, environment and quote. Sandbox transfers are not wages.
- Provider transfer creation/funding and `outgoing_payment_sent` are not independent evidence that the contributor received the funds. Keep `sent` separate from `paid`; mark paid only after verified provider settlement/delivery or documented operator reconciliation. Returned transfers keep their reservations until reconciled.

## Required integration before production app onboarding

1. Server-validated region enrollment, authenticated mobile account service and explicit account-to-contributor linking.
2. Approved regional agreement documents and durable versioned consent receipts.
3. Verified camera claims, assignment history and capture-time attribution receipts.
4. Idempotent complete-upload intake, a running QC/recovery worker, source-pinned results and reconciliation.
5. Contributor-scoped recording/earnings read APIs backed by the Ops ledger; retain all exclusion reasons and date confidence.
6. Verified Wise recipient onboarding, sandbox integration evidence, production configuration and settlement reconciliation before automated funding.

See Synapse `docs/storage/CONTRIBUTOR-PILOT-2026-09-14.md` for existing AWS findings and pilot constraints. No production terms, account, camera claim or payment is created by synchronizing this contract.

## Provisioned document storage

The private `6thsense-contributor-records` bucket is deployed. See [the storage integration contract](CONTRIBUTOR-STORAGE.md) for its prefixes and verified configuration. This storage provisioning does not activate app registration, record consent or move credentials into S3.

## Region codes and phone verification

See [the region and SMS integration](CONTRIBUTOR-REGISTRATION.md) for `Korea666`, `China666`, `Vietnam666`, and `India666`, the separate contributor Cognito pool, and signed upload tags. The old `ko2026` code is retired. Only Korea has an agreed rate (KRW 11,000/hour); the other rates remain unset. The region code is a public collection selector, not proof of camera ownership or an upload credential. Phone verification must come from Cognito and match the enrolled country. Registration remains closed pending production SMS access, per-country delivery setup and the real app/server onboarding integration.
