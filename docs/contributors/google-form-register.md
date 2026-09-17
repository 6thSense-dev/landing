# Google Form contract register (prepared, not released)

As requested on 2026-09-18, the final published Google Form is the company's offer. The participant's required acknowledgments, typed legal name and successful submission form the contract. The linked Sheet is the interim authoritative contractor register. No later countersignature is required. Phone verification, camera handover and filming permissions remain prerequisites to recording/uploading.

Confirmed commercial decisions: KRW 11,000 per accepted, non-overlapping footage hour; identifiable accepted footage retained no more than three years from recording; non-onboarded applications deleted within 30 days of submission. External robotics-training licensing is authorized subject to privacy permissions.

Company: 6thSense AI, Inc., Delaware file 10635916. Registered office: c/o Corporation Service Company, 251 Little Falls Drive, Wilmington, New Castle County, Delaware 19808, USA. Contact: Alex Noh, alex@6thsense.dev.

## Artifacts and status

- Contract draft: https://docs.google.com/forms/d/1I5L9JSi4IgRLN_AqtJNaqO7bc7LjDuCeueePVdAEm6g/edit
- Register workbook: https://docs.google.com/spreadsheets/d/1ZJZ_H4ZIWRl_c6QngmsDTfcAhQnbN6vrLbUnpPd_CPg/edit
- Apps Script: https://script.google.com/home/projects/1VxvnIq02VKmRhqENhv3sejahCX2Wjg-Zpbx4mR5pVUwniSvYfyifu8Ol/edit
- Local spec: `scripts/google-contracts/contract-spec.review.json`.
- The older application form already has a response. Its acknowledgments do not constitute the new contract. Preserve its original purpose, timestamps and 30-day retention rule.
- Read-back at 01:01 KST verified 16 questions, zero responses, no password question, private source saved and the contractor register created (zero signed contractors). The new form remains unpublished. Production API/frontend are unchanged. No contract-sync secret or bundle has been enabled.

## Identity and evidence

Never collect passwords or SMS codes in Forms, Sheets, receipts or this API. The upload website sends the password directly to Cognito. After SMS verification and sign-in, the API obtains the verified phone from Cognito and matches an HMAC phone digest to exactly one signed record. Browser-supplied phone/name cannot select the contractor.

Keep the full signed snapshot, contract source and exact Form shape in restricted Drive files. `Contractors` records immutable response/receipt IDs plus staff-managed status, legacy Ops ID and camera handover fields. Staff must explicitly resolve duplicate names/phones or link a legacy record. Never merge by camera alone. Activation preserves existing contributor IDs, rates, episodes and payment history.

Cameras need physical handover and capture-time assignment intervals in Ops. The Sheet is a register, not an automatic override of capture ownership. Upload completion, file moves and copies must not create extra payment. The payment ledger remains in Ops; the Sheet points to the same contributor.

The submit trigger records the contract before calling the API. The five-minute reconciliation recovers missing events and retries failed syncs. The API verifies a timestamped HMAC of the exact bytes, freezes signed fields, rejects stale/unsigned submissions and treats retries idempotently. Withdrawal cannot reactivate the same signature. A retained minimal ledger/contract receipt is distinct from footage and must never extend footage's three-year period.

## Release prerequisites

1. Finish the exact provider-country and backup-deletion disclosures for Google Workspace/Forms, AWS/Cognito/SNS and Railway. Google Forms' data-region coverage includes storage but does not establish that all processing is in the US. Do not promise a location or deletion period based only on headquarters or hosting region.
2. Obtain company review of the concrete payment deadlines and five-year minimal contract/payment evidence schedule in the draft. Rate and footage/application retention were explicitly confirmed; these other terms are proposals.
3. Finalize text, version and terms hash. Freeze the Form shape and private source. Verify respondent flow without creating a false signature or contractor.
4. Configure matching `CONTRIBUTOR_FORM_BUNDLE` (form_id, version, terms_sha256, effective_at, URL, rate_krw_hour=11000), `CONTRIBUTOR_FORM_PHONE_KEY`, `CONTRIBUTOR_FORM_SYNC_SECRET`, and `CONTRIBUTOR_FORM_ENABLED`. Keys must be separate random secrets, at least 32 characters, stored in Railway and Apps Script properties only. Set `CONTRACT_SYNC_URL=https://api.6thsense.dev/api/form-contracts/sync` and the matching secret in Script Properties. Never commit keys.
5. Deploy migration 0020 and API first, frontend next; verify rollout before opening the Form. Run `releaseReviewedContractForm` only with zero review issues. This installs the submit/retry triggers and publishes the final Form.
6. Monitor sync errors. Plan retention operations across original Forms responses, linked Sheets, Drive receipts, API mirrors, footage copies and providers. Expiry automation is not implemented by this change; do not claim it is. A retention deadline alone is not evidence of deletion.

## Validation

- 36 backend tests passed (signed evidence, verified phone, existing accounts, deletion/withdrawal, upload and contributor regressions).
- 18 Playwright cases passed across mobile/tablet/desktop (12 upload regressions plus six signup/recovery cases).
- Eight Node tests passed (four Apps Script evidence tests and four upload/auth tests).
- Production frontend build passed; migration 0020 upgrade, empty downgrade and re-upgrade passed on isolated Postgres.

## Primary references checked

- Electronic Signature Act, Article 3: https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0003&lsiSeq=236201&urlMode=lsScJoRltInfoR
- PIPA overseas transfers: https://law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1033215841
- Google data-region coverage: https://knowledge.workspace.google.com/admin/compliance/data-covered-by-data-regions
- Google processors: https://workspace.google.com/terms/subprocessors/
- Railway DPA: https://railway.com/legal/dpa
- Cognito signup: https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SignUp.html

Current access blocker: the Google Admin page at `https://admin.google.com/ac/companyprofile/legal` requires owner re-authentication. The open preview tab `tab_f` is at that Google sign-in prompt. Do not retrieve or request the password; the owner signs in directly.
