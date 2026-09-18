# Google Form contract register

As requested on 2026-09-18, the final published Google Form is the company's offer. The participant's required acknowledgments, typed legal name and successful submission form the contract. The linked Sheet is the interim authoritative contractor register. No later countersignature is required. Phone verification, camera handover and filming permissions remain prerequisites to recording/uploading.

Confirmed commercial decisions: KRW 11,000 per accepted, non-overlapping footage hour; identifiable accepted footage retained no more than three years from recording; non-onboarded applications deleted within 30 days of submission. External robotics-training licensing is authorized subject to privacy permissions.

Company: 6thSense AI, Inc., Delaware file 10635916. Registered office: c/o Corporation Service Company, 251 Little Falls Drive, Wilmington, New Castle County, Delaware 19808, USA. Contact: Alex Noh, alex@6thsense.dev.

## Artifacts and release evidence

- Contract editor: https://docs.google.com/forms/d/1I5L9JSi4IgRLN_AqtJNaqO7bc7LjDuCeueePVdAEm6g/edit
- Published respondent URL: https://docs.google.com/forms/d/e/1FAIpQLSeampbT4_nIhAdxxiIt145QRSqHWLGAoY-hVuGXgkr1aX3Fzw/viewform
- Register workbook: https://docs.google.com/spreadsheets/d/1ZJZ_H4ZIWRl_c6QngmsDTfcAhQnbN6vrLbUnpPd_CPg/edit
- Apps Script: https://script.google.com/home/projects/1VxvnIq02VKmRhqENhv3sejahCX2Wjg-Zpbx4mR5pVUwniSvYfyifu8Ol/edit
- Final source: [`contract-spec.review.json`](../../scripts/google-contracts/contract-spec.review.json), version `KR-FORM-2026-09-18-1`, terms SHA-256 `556d32d8d0dd07f1e75f32530ad0b473103ac16371db6d5a4406e74cfca5e15e`. The matching generated Apps Script source is [`ContractSpec.gs`](../../scripts/google-contracts/ContractSpec.gs). The filename does not establish publication or external legal review.
- The older application form already has a response. Its acknowledgments do not constitute the new contract. Preserve its original purpose, timestamps and 30-day retention rule.
- [`google-artifacts.json`](../../scripts/google-contracts/google-artifacts.json) records the latest timestamped live read-back. Final source and passing local tests alone do not establish publication, deployment, a real signed contract, SMS verification or a completed upload. Update that record only from observed production evidence.
- The earlier Google Admin sign-in blocker was resolved. The Workspace Cloud Data Processing Addendum was accepted and the covered-data storage policy was saved as United States. Saving that policy does not prove completed migration or US-only processing.
- On 2026-09-18, the published respondent page returned HTTP 200 anonymously. Parsed public HTML exactly matched the final source's 17 legal text sections, 16 questions and contract metadata. This verifies the public offer; participant signing, SMS verification and a real upload remain separate acceptance steps.
- Railway verified the API follow-up at commit `f42f0d3` as deployed successfully; live `/api/form-contracts/configuration` returned HTTP 200 with the final Form URL, version and rate. The frontend remains at `48c27db`, with no subsequent frontend source changes. Commit-specific deployment evidence belongs in `google-artifacts.json`.

## Signup infrastructure verified 2026-09-18

Production SMS in `us-west-2` reports `IsInSandbox=false` and `MonthlySpendLimit=50` USD. The contributor signup gate has `SIGNUP_ENABLED=true`, `SIGNUP_MODE=aws_sms` and the Korean route open. The public app client supports `USER_PASSWORD_AUTH` and the required signup attributes. These live observations supersede the older closed-signup and sandbox checkpoints in the [registration guide](../CONTRIBUTOR-REGISTRATION.md).

A direct Lambda probe exposed a cold invocation timing out at 5,000 ms with 128 MB memory; later invocations took 4,319.71 ms and 258.83 ms. CloudFormation change set `signup-cold-start-readiness-20260918` preserved the deployed template and changed only `SignupGate.MemorySize` from 128 to 512 MB. The stack reached `UPDATE_COMPLETE` and the function code hash remained unchanged. After the change, the cold probe took 1,364.35 ms plus 96.77 ms initialization (1,461.12 ms total), and a warm probe took 85.91 ms. Both successful responses left `autoConfirmUser`, `autoVerifyPhone` and `autoVerifyEmail` false.

Cognito's synchronous trigger response limit is five seconds; increasing a function timeout cannot extend it. Lambda allocates more CPU with higher configured memory. Future identity-infrastructure deployments must preserve at least 512 MB for this gate and verify cold invocation latency within that response budget; the deployed CloudFormation template already includes the correction. These synthetic invocations created no Cognito account and sent no SMS. They verify the gate's behavior and measured latency, not real participant signup or message delivery. See [Cognito trigger constraints](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-working-with-lambda-triggers.html) and [Lambda memory configuration](https://docs.aws.amazon.com/lambda/latest/dg/configuration-memory.html).

## Participant and operator flow

1. Keep the original application as an application. `finishContractRegisterDraft` imports legacy applications into the register without manufacturing a contract or signature.
2. The participant reads the final published contract, completes each required acknowledgment, types their own legal name and submits it. An operator must not sign for them. The register receives the signed response and private receipt before attempting API sync.
3. On `https://6thsense.dev/upload`, the participant creates their password directly with Cognito, verifies the SMS code, and signs in with the same phone number. The API matches the provider-verified phone to one current signed contract. Duplicate eligible contracts require staff identity review.
4. Use the verified preapproval below for an already handed-over camera, or the existing supervised camera-request workflow. Record the same stable Ops contributor ID and camera in the Sheet. Application contact fields or a matching name alone cannot establish an account link.
5. Upload complete original episode folders from the SD card. Follow the [browser upload instructions](../CONTRIBUTOR-MOBILE-PILOT.md#browser-upload-from-an-sd-card). Server receipt, QC acceptance and payment remain separate stages. Do not delete originals on a spinner or merely after files appear in the bucket.

The Sheet tracks contractors, signed evidence and staff fields. Ops remains the source for approved capture intervals, accepted seconds, reserved amounts and payments. A `Login linked` sync status confirms account linking; it is not evidence that filming, a bank recipient or a payout was approved. Contributors enter payment details themselves at [Payment details](https://6thsense.dev/upload#payment-details) after signing in. This is available before camera approval and does not block uploads. Finance reviews the masked submission in Ops and verifies the Wise recipient. Do not collect bank details by email or add them to the contractor Sheet.
After linking, sync returns the authoritative Ops `wearer_id`. Apps Script fills a blank `Existing Ops contributor ID` only when the returned contract ID matches that row's receipt, `linked` is true and the ID is a positive integer. Existing staff-entered IDs are preserved; names and camera IDs do not select the account.

## Identity and evidence

Never collect passwords or SMS codes in Forms, Sheets, receipts or this API. The upload website sends the password directly to Cognito. After SMS verification and sign-in, the API obtains the verified phone from Cognito and matches an HMAC phone digest to exactly one signed record. Browser-supplied phone/name cannot select the contractor.

Keep the full signed snapshot, contract source and exact Form shape in restricted Drive files. Release freezes the complete spec, Form/item IDs and rendered question/section shape in a hashed source file. Later submissions use that frozen release, not mutable editor text. `Contractors` records immutable response/receipt IDs plus staff-managed status, legacy Ops ID and camera handover fields. Sync binds contract, response, Form, version and signing timestamp to the correct receipt before reading staff fields. Staff must explicitly resolve duplicate names/phones or link a legacy record. Never merge by camera alone. Activation preserves existing contributor IDs, rates, episodes and payment history.

Cameras need physical handover and capture-time assignment intervals in Ops. The Sheet is a register, not an automatic override of capture ownership. Upload completion, file moves and copies must not create extra payment. The payment ledger remains in Ops; the Sheet points to the same contributor.

The five-minute reconciliation recovers missing events and retries failed syncs. A malformed response is counted/quarantined without stopping unrelated imports or withdrawals. The API verifies a timestamped HMAC of the exact bytes, freezes signed fields, rejects stale/unsigned submissions and treats retries idempotently. Set the signed register row's status to `Withdrawn` to synchronize withdrawal; the same signature cannot be reactivated. A withdrawn or stale Form record also blocks legacy-consent fallback before first account linking when matched through the provider-verified phone. Valid legacy accounts with no matching Form record retain their existing consent path.

## Verified camera preapproval

`POST /api/ops/contributors/camera-preapprovals` uses the existing authenticated staff session and CSRF origin check. It requires an existing active Ops contributor and configured `CONTRIBUTOR_FORM_PHONE_KEY`; a Form submission is not required yet.

| Field | Value |
| --- | --- |
| `preapproval_id` | New lowercase UUID, reused unchanged for retries. |
| `phone` | Verified handover contact in Korean international mobile format, `+8210` followed by eight digits. Never place the real value in source control. |
| `wearer_id` | Explicit existing Ops contributor ID. |
| `device_id` | Six uppercase hexadecimal characters. |
| `physically_verified`, `camera_owner_verified`, `permissions_verified` | All must be `true`, backed by the actual handover/permission evidence. |
| `note` | 10–500 characters describing verification, without bank details or credentials. |

The response returns the approval ID, camera, contributor, approval timestamp and seven-day expiry. The reservation is immutable, checks conflicting assignments and records the staff identity. Its phone index stores an HMAC digest. On activation, the signed account must still match the reserved contributor and unchanged camera; the approved interval starts at the later of staff approval and contract signature. Earlier handover or recording time is not invented.

Consumption is recorded separately, so retrying cannot recreate a returned or reassigned claim. `camera_preapproval_expired` requires renewed staff verification; `camera_preapproval_changed` requires resolving the changed camera assignment. Do not clear either error by editing immutable audit rows. Delayed SD-card footage after an assignment ends still needs trusted capture time wholly inside that contributor's approved interval; a current holder cannot inherit old payable footage.

## API reference

| Route | Authentication and result |
| --- | --- |
| `GET /api/form-contracts/configuration` | Public; returns only respondent URL, version and rate when configured. Invalid/disabled setup returns `contract_setup_pending`. |
| `POST /api/form-contracts/sync` | Apps Script only; `x-form-timestamp` and `x-form-signature` authenticate `timestamp + "." + exact body` with SHA-256 HMAC and a five-minute freshness window. Limit: 120/minute. |
| `POST /api/form-contracts/activate` | Contributor Cognito bearer token; provider-verified Korean phone and exactly one current signed contract required. Limit: 10/minute. |
| `POST /api/ops/contributors/camera-preapprovals` | Staff authentication and CSRF checks; verified pending handover reservation as described above. |

The sync payload includes immutable `response_id`, `form_id`, `version`, `terms_sha256`, `receipt_sha256`, `phone`, `name`, `signature`, timezone-aware `signed_at`, and five true `accepted` values: `participation`, `collection`, `privacy`, `international_transfer`, `adult`. Only staff-managed `wearer_id` and `state` (`signed` or `withdrawn`) may change. Phone/name/signature must come from the signed receipt, not edited display cells. Unknown fields and invalid payloads receive fixed error messages without echoing submitted personal data.

## Release procedure

1. Confirm the final spec and exact provider disclosures still match the operating setup. The current source identifies 6thSense, Google Workspace storage/maintenance, AWS hosting and SMS delivery, and Railway hosting. Identifiable customer disclosure requires a specific recipient notice and lawful basis; the general robotics license does not supply blanket consent for unnamed customers.
2. Check the offered payment deadlines and minimal five-year contract/payment evidence schedule against the operating process. The final source also covers payment of small balances and termination. The existing four-hour payment eligibility automation does not implement those exceptions; an operator must track and fulfill them.
3. Save the final `ContractSpec.gs` and `ContractRegister.gs` in Apps Script, run `finishContractRegisterDraft`, then `auditContractDraft`. Verify the respondent flow without creating a false signature or contractor. The finisher resolves saved question IDs before title fallback and distinguishes questions from section headings; it refuses released/responded Forms. Never alter an already released source/version to change a signed agreement.
4. Configure matching `CONTRIBUTOR_FORM_BUNDLE` (form_id, version, terms_sha256, effective_at, URL, rate_krw_hour=11000), `CONTRIBUTOR_FORM_PHONE_KEY`, `CONTRIBUTOR_FORM_SYNC_SECRET`, and `CONTRIBUTOR_FORM_ENABLED`. Keys must be separate random secrets, at least 32 characters, stored in Railway and Apps Script properties only. Set `CONTRACT_SYNC_URL=https://api.6thsense.dev/api/form-contracts/sync` and the matching secret in Script Properties. Never commit keys.
5. Deploy migration `0020` and API first, frontend next; verify rollout before opening the Form. Run `releaseReviewedContractForm` only with zero review issues. This freezes the source and Form shape, installs submit/retry triggers and publishes the final Form. `ensureContractResponderAccess` verifies or creates the Drive permission `{type: "anyone", view: "published", role: "reader"}` without notification emails; it grants the published respondent view, not editable-file or response access. Read back the public configuration, anonymous respondent view and installed triggers, and record their timestamps in `google-artifacts.json`.
6. Monitor the register's `Last sync` and `Sync issue` columns and recover missed submissions. Preserve `contributor_form_contracts` and preapproval/consumption audits during an application rollback. Migration `0020` refuses downgrade while any contract evidence exists. Disabling the feature flag restores the existing consent path; use a synchronized withdrawal to revoke a Form contract instead.

## Retention operations and provider limits

This release does not implement scheduled erasure. Assign an operator and track due dates across original Form responses, every linked Sheet copy/export, private Drive receipts, API mirrors, raw/clean footage versions, derived datasets, customer copies and provider backups. Record verified disposition rather than treating a deadline, disabled account or hidden row as deletion evidence. Follow the existing [deletion fulfillment procedure](../CONTRIBUTOR-DELETION.md#operator-fulfillment) when a contributor requests erasure.

The final source sets accepted identifiable footage to three years from recording and unonboarded applications to 30 days from submission. Minimal contract/payment evidence has a separate five-year schedule; retaining that evidence must not extend footage retention or retain unnecessary contact/bank fields. The provider disclosure separately states Google's residual deletion window of up to 180 additional days after working-copy deletion. A US data-region setting does not constrain every support, SMS or service-processing location. Provider notices and routing should be checked again when providers change.

## Validation

- 63 targeted backend tests passed, covering signed evidence, verified phone, legacy accounts, withdrawal, immutable handovers, delayed uploads and contributor regressions. The linked-ID follow-up passed 32 related backend tests.
- 15 Form activation Playwright cases passed across mobile/tablet/desktop; the prior upload suite passed 12 cases. Provider calls in these browser tests are controlled fixtures.
- 14 Apps Script Node tests passed, including frozen release evidence, receipt binding, retry isolation, published responder access and guarded Ops-ID reconciliation.
- Frontend production build passed. On isolated Postgres, migration `0020` refused downgrade to `0019` with a populated contract table and preserved both the evidence and schema version; empty downgrade and re-upgrade passed.
- A live Apps Script → API HMAC probe authenticated an empty JSON payload and received the expected HTTP 422 `invalid_form_submission`. This verifies bridge authentication without creating a false contract.
- A real participant still needs to sign, complete their own SMS/password steps, and upload actual footage. Local tests and a staff reservation are not substitutes for those actions or evidence of a completed payout.

## Primary references checked

- Electronic Signature Act, Article 3: https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0003&lsiSeq=236201&urlMode=lsScJoRltInfoR
- PIPA overseas transfers: https://law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1029331979
- Google data-region coverage: https://knowledge.workspace.google.com/admin/compliance/data-covered-by-data-regions
- Google processors: https://workspace.google.com/terms/subprocessors/
- Google Cloud Data Processing Addendum: https://cloud.google.com/terms/data-processing-addendum/
- AWS subprocessors: https://aws.amazon.com/compliance/sub-processors/
- Railway DPA: https://railway.com/legal/dpa
- Cognito signup: https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SignUp.html
