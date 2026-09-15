# Contributor contract: Synapse app and Ops

Coordinated 2026-09-14; implementation status updated 2026-09-15. This is an integration contract, not approved legal text or evidence of a completed trial. Both repositories carry this document; keep shared requirements aligned. See the [mobile pilot guide](CONTRIBUTOR-MOBILE-PILOT.md) for the implemented flow and remaining acceptance work.

## Ownership and current implementation

- Synapse's `LiveContributor.tsx`, `registration.ts` and `live-client.ts` connect the pilot UI to Cognito and contributor APIs. The separate `ContributorPreview.tsx` remains a sample-data preview and cannot establish real consent, ownership or earnings.
- Landing Ops owns `ops_wearers`, the camera roster, raw inventory, Clean manifests and payment ledgers. `/api/contributor/*` adds account-scoped reads and enrollment; `/api/ops/contributors/*` adds staff supervision. Verified mobile enrollment creates a new wearer once and does not match an existing person by name.
- Ronak's QC pipeline owns media validation/recovery, exclusions and committed Clean outputs. A queue or an S3 directory alone is not evidence that recovery/QC ran.
- Existing manually entered contributors must remain distinguishable from app accounts. Never infer a verified account, consent or bank ownership from a name, camera ID or an operator roster entry.

## Registration and terms

Use the app's three agreement identifiers: `participation`, `privacy`, `collection` (recording/payment guidelines). The current `KR-PREVIEW-1` / `US-CA-PREVIEW-1` texts are placeholders and must never be accepted as production consent.

Production terms configuration must resolve the collection/region to the required documents, each with an immutable version, locale, content SHA-256, and approved document URL. Until approved text is published, the production status is `terms_not_configured`; a preview checkbox cannot bypass it.
The mobile terms endpoint returns `not_published` with an empty document list until all three agreements exist for the requested language. Current consent is required by camera requests, staff camera approval and both bank endpoints. The implementation stores receipts in the database and supports an explicit, idempotent staff export to private S3; export is not scheduled automatically.

An authenticated acceptance receipt must contain the stable account subject, contributor ID, collection enrollment ID, each agreement ID/version/hash/locale, and a server timestamp. Record acceptance only after the contributor views and accepts the configured documents. New required versions or reenrollment in another collection require new acceptance. Do not manufacture receipts for existing contributors or use an Ops administrator's session as contributor consent.

Account → contributor is an explicit verified link. Preserve contributor, footage and payment history if login access is revoked. The mobile client reads its own ledger through authenticated server endpoints; it never supplies authoritative payable time, rate, recipient ownership or payout status.

## Camera and recording attribution

Normalize camera IDs to six uppercase hex characters internally; display `EGO-<id>`. Camera hotspot discovery proves reachability, not ownership. Claim a camera with supported device proof or supervised operator provisioning, reject conflicting assignments, and retain effective-dated assignment history.

Bind the upload receipt to the immutable capture-time assignment, recording ID and expected source objects/versions/checksums. Validate that assignment server-side. Current camera ownership, S3 folder names, SD-card swaps and an uploader-supplied contributor ID are insufficient to rewrite past attribution. Hold ambiguous history for operator resolution.
For the manual SD-card pilot, Raw scanning assigns only new, complete recordings with trusted NTP start time and duration wholly inside one approved camera interval. Registered business sources are excluded, and existing episode ownership is preserved. Approval requires an active wearer, current consent and physical verification. Broker-issued capture-assignment receipts and firmware upload integration remain a later rollout step.

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

1. Validate the implemented region enrollment, mobile account service and account-to-contributor linking with a real user-created account.
2. Publish approved regional agreements and verify a real consent receipt and its export. Storage and API support exist; the legal text is still absent.
3. Exercise supervised camera claims, assignment history and delayed SD-card upload on real hardware. Capture-assignment receipts for broker/firmware uploads remain pending.
4. Idempotent complete-upload intake, a running QC/recovery worker, source-pinned results and reconciliation.
5. Verify the implemented contributor dashboard against real uploaded and reviewed footage. Detailed exclusion reasons and collection-date confidence remain available in Ops; the mobile dashboard currently exposes source and approved totals, recording status and payouts.
6. Complete a real Wise recipient and operator-approved payout trial. Live requirement retrieval, durable submission holds and audited operator recovery are implemented; funding, delivery and return evidence are still required before automated funding.

See Synapse `docs/storage/CONTRIBUTOR-PILOT-2026-09-14.md` for existing AWS findings and pilot constraints. No production terms, account, camera claim or payment is created by synchronizing this contract.

## Provisioned document storage

The private `6thsense-contributor-records` bucket is deployed. See [the storage integration contract](CONTRIBUTOR-STORAGE.md) for its prefixes and verified configuration. This storage provisioning does not activate app registration, record consent or move credentials into S3.

## Region codes and phone verification

See [the region and SMS integration](CONTRIBUTOR-REGISTRATION.md) for `Korea666`, `China666`, `Vietnam666`, and `India666`, the separate contributor Cognito pool, and signed upload tags. The old `ko2026` code is retired. Only Korea has an agreed rate (KRW 11,000/hour); the other rates remain unset. The region code is a public collection selector, not proof of camera ownership or an upload credential. Phone verification must come from Cognito and match the enrolled country. General registration remains closed; the prepared pilot is restricted to the already verified Korean SMS sandbox destination. Other countries still need production SMS access, delivery setup and end-to-end validation.
