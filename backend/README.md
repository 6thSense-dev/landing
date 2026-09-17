# 6thSense backend

FastAPI service for `/health` and the lead-capture endpoint backing the hero-finale form.

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r ../requirements-backend-dev.txt
```

Bring up Postgres (any local instance works):

```bash
docker run --rm -d --name 6th-pg -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres alembic upgrade head
```

Run the API:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \
SENSEPROBE_CORS_ORIGINS=http://localhost:5173 \
uvicorn app.main:app --reload --port 8000
```

- `GET /health` → `{"status":"ok"}`
- `POST /api/leads` → see `app/schemas/lead.py`

## Tests

```bash
cd backend && pytest -v
```

Tests use [testcontainers-python](https://testcontainers-python.readthedocs.io/) which boots an ephemeral Postgres in Docker. The Docker daemon must be running.
Alternatively, set `TEST_DATABASE_URL` to a disposable PostgreSQL database whose name ends in `_test`, using a `postgresql+asyncpg://` URL. The fixtures create and drop application tables; do not point them at a development or production ledger. See the [mobile pilot test command](../docs/CONTRIBUTOR-MOBILE-PILOT.md#deployment-and-validation).
Run the contributor-deletion regressions and real migration checks in separate invocations, with migration checks starting from an empty disposable schema. See the [deletion validation commands](../docs/CONTRIBUTOR-DELETION.md#local-validation), including migration 0018's preservation and downgrade-refusal tests.

## Raw processing queue

In `/portal/ops`, **Scan bucket** refreshes the `raw_inventory_v1` snapshot of media keys, sizes, ETags, and delivery prefixes. Raw uses that snapshot to show pending footage separately from the permanent episode and payment ledger. After an upload, cleanup, or clean import, scan again to refresh the queue.

`raw_source_receipts_v1` records verified source fingerprints. A receipt only marks an object processed when it matches a source bucket, key, version, SHA-256, and size in an imported clean manifest; the current raw object must also match the receipt's key, ETag, and size. Scanning can create original-source receipts by reading the exact manifest-pinned S3 version and checking its size and ETag. Missing or inaccessible source versions leave unverified files pending.

Copies in another delivery folder require operator-audited receipts backed by independently verified source/copy hashes. Cameras do not supply these receipts. A shared recording name, upload date, or file size alone does not prove processing, so additional segments and unverified copies remain visible.

The Raw UI labels `awaiting_verification` as **Checking source match**: Clean has been imported, but exact current source coverage still needs reconciliation. This state displays **In Clean** only when `raw.status == "processed"` and `raw.pending_files === 0`; an imported run ID, missing count or additional files cannot complete it. Other explicit processing states and holds are preserved, and deleted recordings remain rejected. Recognized diagnostics get specific cause badges and recovery guidance without changing the backend state or original reason; unknown causes keep a generic state label. See the [Raw status guide](../docs/OPS-WORKFLOW.md#raw-status-and-recovery-guidance).

Rows displayed as **In Clean** or **Rejected** are hidden by default; enable **Show completed / rejected** to include them. Completed rows preserve their earlier diagnostic under **Recorded status message**. Playback re-lists all known delivery prefixes and omits verified processed copies and empty files. Raw displays pending-file counts and uploaded megabytes; **Pending sources** counts non-deleted recordings with outstanding files. Accepted hours and hourly estimates are in [Clean](../docs/OPS-CLEAN.md). Queue classification does not delete episodes or alter ownership, approvals, or payment history.

Sieve inherits versioned MP4, validated metadata with its provenance, and calibration from imported Clean recordings through a separate worker. Metadata may be an original or an explicitly disclosed reconstruction; [the validation contract](../docs/SIEVE-CLEAN-INHERITANCE.md#metadata-validation) distinguishes their evidence and unknown capture fields. The [Sieve operations guide](../docs/SIEVE-CLEAN-INHERITANCE.md#railway-operation) covers enabling it, retry behavior and the temporary Ops dashboard. The contract ends September 22, 2026; the dashboard remains visible through September 25 in Los Angeles time.

## Contributor browser uploads

`/upload` accepts original episode folders from contributor Cognito accounts. Users sign in with their verified international phone number and password; password reset and token refresh use the same contributor app client. The Korean [Google Form register flow](../docs/contributors/google-form-register.md) adds website signup and links a current signed contract to the provider-verified phone. Upload access still requires an enrolled, active account, current consent and an approved assignment for the episode's camera. See the [participant instructions](../docs/CONTRIBUTOR-MOBILE-PILOT.md#browser-upload-from-an-sd-card) for folder selection and recovery.

The authenticated `/api/uploads` control plane provides `GET /info`, `POST /batches`, `POST /batches/{batch_id}/files/{file_id}/{start|parts|complete}` and `POST /batches/{batch_id}/complete`. Files go directly to private S3 through 15-minute, SHA-256-bound multipart grants: 16 MiB parts, up to three concurrent transfers. Limits are 100 GiB per file, 2,000 files per episode and 500 GiB / 500 new episode batches per account per rolling 24 hours; registering a batch reserves its declared bytes. Resuming the same manifest reuses that reservation.

Migration `0019` adds `upload_batches`, `upload_files` and `upload_parts` for durable uploader attribution and resumable receipts. It refuses downgrade once any upload batch exists. Keep these tables during an application rollback. The uploader is recorded separately from capture-time ownership, QC approval and payment eligibility; an ended camera assignment permits completion only when verified capture time attributes the recording to that contributor.

The server stores originals under `s3://6thsense-raw/sessions/web-{batch_id}/{recording}/` and verifies stored object versions before writing `_upload_complete.json`. Raw ignores browser delivery prefixes without that server-written receipt. After completion, **Scan bucket** refreshes Raw. Conflicting completed delivery locations for the same recording block worker claims, results, retries and Clean import; an operator must resolve the source locations and rescan before processing continues. Keep originals when a delivery needs attention.

Keep bucket versioning enabled; the default accelerated upload path also requires S3 Transfer Acceleration. In addition to existing Ops read permissions, the configured Ops AWS identity needs `s3:PutObject`, `s3:AbortMultipartUpload` and `s3:ListMultipartUploadParts` scoped to `arn:aws:s3:::6thsense-raw/sessions/web-*`. The bucket CORS rule must allow `PUT` from `https://6thsense.dev`, allow `content-type` and `x-amz-checksum-sha256`, and expose `ETag`. Retain the existing seven-day abort-incomplete-multipart lifecycle rule; after it expires an unfinished file, selecting the same originals restarts that file while preserving completed files. Browser clients receive short-lived part grants; AWS credentials stay on the backend.

## Environment

| name | required | purpose |
|---|---|---|
| `DATABASE_URL` | yes | Postgres connection string. SQLAlchemy async (`postgresql+asyncpg://`) is preferred but plain `postgresql://` and `postgres://` are normalised. |
| `SENSEPROBE_CORS_ORIGINS` | no | Comma-separated allowed origins. Default covers local Vite (5173/4173). |
| `SENSEPROBE_RATE_LIMIT` | no | slowapi limit applied to `POST /api/leads`. Default `5/minute`. |
| `PORT` | no | Auto-injected by Railway in production. |
| `OPS_PAYMENT_CALCULATION_ENABLED` | no | Defaults to `false`; `true` starts independent Sunday 23:59 Asia/Seoul Clean import and calculation. It does not reserve, transfer or fund payments. |
| `OPS_PAYMENT_CALCULATION_START_AT` | when calculation enabled | First cutoff: `2026-09-20T14:59:00Z`. Must include a timezone and resolve to Sunday 23:59:00 Asia/Seoul. |
| `OPS_PAYOUT_AUTOMATION_ENABLED` / `OPS_WISE_AUTO_FUND` | no | Keep both `false` for calculation-only operation. Payout execution and funding remain separately gated. |
| `OPS_SIEVE_ENABLED` | no | Defaults to `false`; `true` starts the independent five-minute Clean → Sieve inheritance loop. |
| `OPS_SIEVE_ROLE_ARN` | for Sieve inheritance | Dedicated scoped AWS role assumed by the worker. See the [Sieve guide](../docs/SIEVE-CLEAN-INHERITANCE.md#railway-operation) and checked-in `infra/sieve/` policies. |
| `OPS_BROWSER_UPLOAD_ENABLED` | for browser uploads | Set to `true` to enable authenticated upload APIs after migration `0019` and storage setup. Defaults to disabled. |
| `OPS_UPLOAD_ACCELERATE` | no | Defaults to `true`; uses the S3 Transfer Acceleration endpoint for browser multipart uploads. Set to `false` to use the regional endpoint. |
| `CONTRIBUTOR_COGNITO_POOL` / `CONTRIBUTOR_COGNITO_CLIENT` | for contributor accounts | Separate contributor pool and public app-client identifiers; both are required for mobile and browser-upload token acceptance. |
| `CONTRIBUTOR_COGNITO_REGION` | no | Contributor Cognito region; defaults to `us-west-2`. |
| `CONTRIBUTOR_TERMS_FOUNDER_EMAILS` | for terms publication | Comma-separated exact authenticated staff emails authorized by company founders; whitespace/case normalized. Empty or absent denies publication, including staff with the `founder` role. Do not infer identities or configure without founder direction. |
| `CONTRIBUTOR_SIGNUP_MODE` | no | Public configuration label; defaults to `closed`. The Cognito signup gate remains the authority for who can register. |
| `CONTRIBUTOR_FORM_ENABLED` | for Form activation | Exact value `true` enables the Korean Form configuration, signed-register sync and activation routes after migration `0020`. Defaults to disabled. |
| `CONTRIBUTOR_FORM_BUNDLE` | for Form activation | JSON containing the released `form_id`, `version`, `terms_sha256`, timezone-aware `effective_at`, Google respondent `url` and `rate_krw_hour: 11000`. See the [release procedure](../docs/contributors/google-form-register.md#release-procedure). |
| `CONTRIBUTOR_FORM_PHONE_KEY` | for Form activation/preapproval | Separate random secret of at least 32 characters for verified-phone HMAC matching. Changing it requires an explicit digest migration. Never store it in the register. |
| `CONTRIBUTOR_FORM_SYNC_SECRET` | for Form sync | Separate random secret of at least 32 characters, matching Apps Script's `CONTRACT_SYNC_SECRET`; authenticates timestamped request bytes. |

The [contributor pilot guide](../docs/CONTRIBUTOR-MOBILE-PILOT.md) documents `/api/contributor/*`, staff supervision in `/api/ops/contributors/*`, migration `0016`, versioned agreement storage and recipient recovery. Terms use the configured `OPS_AWS_ACCESS_KEY_ID` / `OPS_AWS_SECRET_ACCESS_KEY` pair and `OPS_S3_REGION`; credentials need the relevant terms read and consent-export write permissions. Wise configuration remains server-only and follows the [Ops payment workflow](../docs/OPS-WORKFLOW.md#payment-policy-and-operation).
The [Form register guide](../docs/contributors/google-form-register.md) covers `/api/form-contracts/*`, staff camera preapproval, withdrawal and additive migration `0020`. Keep its contract mirror and preapproval/consumption audits during rollback; a populated contract table refuses downgrade. Disabling the Form feature can restore legacy consent fallback, so it is not an appropriate way to withdraw a contributor's contract.
Weekly calculation imports verified Clean manifests and saves immutable snapshots in existing Ops settings; it adds no schema migration and does not move or delete S3 objects. The [Ops payment workflow](../docs/OPS-WORKFLOW.md#payment-policy-and-operation) explains the inclusive four-hour threshold, cutoff-limited review timestamps, retry behavior and live manual approval, which can include later reviews without changing earlier snapshots or reservations.
The [deletion release contract](../docs/CONTRIBUTOR-DELETION.md#deployment-and-rollback) adds migrations `0017` and `0018`. Cognito deletion uses the default AWS credential chain (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` on Railway) with permission limited to `cognito-idp:AdminDeleteUser` for the contributor pool. Preserve both the receipt schema and original/retry lookup code during an application rollback.

## Deploy (Railway)

This service is deployed as a new service in the same Railway project that already hosts the frontend and Postgres.

1. Add a new service from this repo. **Leave the Root Directory at the repository root** (do NOT set it to `backend/`). Railway reads `backend/railway.toml` automatically and that file points at `backend/Dockerfile` with the repo root as build context.
2. Set service variables:
   - `DATABASE_URL` → reference variable `${{Postgres.DATABASE_URL}}`
   - `SENSEPROBE_CORS_ORIGINS` → `https://<frontend-domain>,http://localhost:5173,http://127.0.0.1:5173`
   - `SENSEPROBE_RATE_LIMIT` → `5/minute` (optional)
3. Deploy. The container runs `alembic upgrade head` before starting uvicorn, so the schema migrates on first deploy.
4. Note the public Railway domain assigned to the backend.
5. On the **frontend** service, set `VITE_API_URL` to that public domain and redeploy.

The backend reaches Postgres over Railway's private network (`postgres.railway.internal`); Postgres has no public IP.
