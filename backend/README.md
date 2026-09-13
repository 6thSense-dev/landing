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

## Raw processing queue

In `/portal/ops`, **Scan bucket** refreshes the `raw_inventory_v1` snapshot of media keys, sizes, ETags, and delivery prefixes. Raw uses that snapshot to show pending footage separately from the permanent episode and payment ledger. After an upload, cleanup, or clean import, scan again to refresh the queue.

`raw_source_receipts_v1` records verified source fingerprints. A receipt only marks an object processed when it matches a source bucket, key, version, SHA-256, and size in an imported clean manifest; the current raw object must also match the receipt's key, ETag, and size. Scanning can create original-source receipts by reading the exact manifest-pinned S3 version and checking its size and ETag. Missing or inaccessible source versions leave unverified files pending.

Copies in another delivery folder require operator-audited receipts backed by independently verified source/copy hashes. Cameras do not supply these receipts. A shared recording name, upload date, or file size alone does not prove processing, so additional segments and unverified copies remain visible.

Fully processed recordings and recordings without nonempty raw media are hidden by default; enable **show processed / unavailable** to see their history. Playback re-lists all known delivery prefixes and omits verified processed copies and empty files. **Pending raw** reports pending bytes, while **Ledger minutes** remain recording metadata estimates. Accepted hours and hourly estimates are in [Clean](../docs/OPS-CLEAN.md). Queue classification does not delete episodes or alter ownership, approvals, or payment history.

## Environment

| name | required | purpose |
|---|---|---|
| `DATABASE_URL` | yes | Postgres connection string. SQLAlchemy async (`postgresql+asyncpg://`) is preferred but plain `postgresql://` and `postgres://` are normalised. |
| `SENSEPROBE_CORS_ORIGINS` | no | Comma-separated allowed origins. Default covers local Vite (5173/4173). |
| `SENSEPROBE_RATE_LIMIT` | no | slowapi limit applied to `POST /api/leads`. Default `5/minute`. |
| `PORT` | no | Auto-injected by Railway in production. |

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
