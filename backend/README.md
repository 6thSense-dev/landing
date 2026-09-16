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

**Partly processed** means the recording has an imported clean result but still has files awaiting processing. The label shows the pending file count; its tooltip explains that additional uploads and failed files remain in Raw while completed footage is in Clean.

Fully processed recordings and recordings without nonempty raw media are hidden by default; enable **show processed / unavailable** to see their history. Playback re-lists all known delivery prefixes and omits verified processed copies and empty files. **Pending raw** reports pending bytes, while **Ledger minutes** remain recording metadata estimates. Accepted hours and hourly estimates are in [Clean](../docs/OPS-CLEAN.md). Queue classification does not delete episodes or alter ownership, approvals, or payment history.

Sieve inherits versioned MP4, original metadata and calibration from imported Clean recordings through a separate worker. The [Sieve operations guide](../docs/SIEVE-CLEAN-INHERITANCE.md#railway-operation) covers enabling it, retry behavior and the temporary Ops dashboard. The contract ends September 22, 2026; the dashboard remains visible through September 25 in Los Angeles time.

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
| `CONTRIBUTOR_COGNITO_POOL` / `CONTRIBUTOR_COGNITO_CLIENT` | for mobile accounts | Separate contributor pool and public app-client identifiers; both are required for token acceptance. |
| `CONTRIBUTOR_COGNITO_REGION` | no | Contributor Cognito region; defaults to `us-west-2`. |
| `CONTRIBUTOR_TERMS_FOUNDER_EMAILS` | for terms publication | Comma-separated exact authenticated staff emails authorized by company founders; whitespace/case normalized. Empty or absent denies publication, including staff with the `founder` role. Do not infer identities or configure without founder direction. |
| `CONTRIBUTOR_SIGNUP_MODE` | no | Public configuration label; defaults to `closed`. The Cognito signup gate remains the authority for who can register. |

The [contributor pilot guide](../docs/CONTRIBUTOR-MOBILE-PILOT.md) documents `/api/contributor/*`, staff supervision in `/api/ops/contributors/*`, migration `0016`, versioned agreement storage and recipient recovery. Terms use the configured `OPS_AWS_ACCESS_KEY_ID` / `OPS_AWS_SECRET_ACCESS_KEY` pair and `OPS_S3_REGION`; credentials need the relevant terms read and consent-export write permissions. Wise configuration remains server-only and follows the [Ops payment workflow](../docs/OPS-WORKFLOW.md#payment-policy-and-operation).
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
