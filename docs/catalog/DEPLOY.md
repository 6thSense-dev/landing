# Shipping the data catalog

The ordered runbook to put the buyer-facing catalog in front of a prospect at
<https://6thsense.dev/login>. Every step is a command you run, in this order, with the
check that tells you it worked before you move on.

Read [`README.md`](README.md) first for what the thing *is*. This file is the ship.

**Time**: ~40 minutes, of which ~25 is the upload.
**Blast radius**: steps 1–5 touch nothing live. The site changes at step 6 (deploy) and the
catalog becomes reachable at step 7 (seed). Rollback for every step is in §10.

---

> **Provisioned 2026-08-24.** The bucket is `6thsense-catalog-media` in **us-west-2**, in AWS
> account **194680606079** — deliberately *not* 537124957922, which holds the firmware bucket
> `6thsense-prod-camera-updates`. Two IAM identities: `catalog-media` (read+write, for
> `upload_bundle.py` from a workstation) and `catalog-media-reader` (GetObject only, the only
> one whose key belongs in Railway).

## 0. Before you start

| You need | Why |
|---|---|
| AWS credentials that can create a bucket and an IAM user | Step 1. **Not** the `alex-publisher` key — it is scoped to the firmware bucket. |
| Railway access to the backend service | Steps 3, 6 |
| A shell in this repo with `python3`, `ffmpeg`, `ffprobe`, `node`, `aws` | Steps 2, 4, 5 |
| The takes to publish, in intake shape | Step 4. See [`INTAKE.md`](INTAKE.md). |

Install the tooling once:

```bash
# ingest tooling (jsonschema, numpy, pyyaml, pytest, boto3)
python3 -m pip install -r scripts/catalog/requirements.txt

# backend, including boto3 for the S3 driver
python3 -m pip install -r requirements-backend.txt
```

> On a managed/system Python that refuses to install (`externally-managed-environment`),
> use a venv and prefix every later `python3` with `.venv/bin/`:
>
> ```bash
> python3 -m venv .venv && .venv/bin/pip install \
>   -r scripts/catalog/requirements.txt -r requirements-backend.txt
> ```

---

## 1. Provision S3 (once, ever)

```bash
AWS_PROFILE=6thsense-admin ./scripts/catalog/provision_s3.sh
```

Creates `s3://6thsense-catalog-media` in `us-west-2` with **all public access blocked**,
AES256 default encryption, versioning on, CORS for the site origins, a 30-day
noncurrent-version expiry, and **two** IAM users, each with an inline policy scoped to that
one bucket:

| User | Policy | Grants | Used by |
|---|---|---|---|
| `catalog-media` | `catalog-media-rw` | Get/Put/Delete/AbortMultipart | `upload_bundle.py`, from a workstation or CI |
| `catalog-media-reader` | `catalog-media-ro` | `s3:GetObject` only | the API on Railway |

The split is the point. The API only ever calls `get_object` and
`generate_presigned_url("get_object", …)`; it never writes. Putting the writer key in Railway
would give the public web app — the one fronting a credential we hand to prospects — the
ability to delete or silently replace every delivered clip, and (with `PutObject` on
`catalog.json`) to rewrite the manifest that the authenticated portal renders. Versioning
bounds the damage; it does not prevent it.

It is idempotent — re-running only re-applies the configuration.

**Check**: it prints `Bucket ready.` and

```bash
aws s3api get-public-access-block --bucket 6thsense-catalog-media
# all four flags true
```

---

## 2. Mint the access keys (once)

```bash
# The one that goes into Railway. Read-only.
aws iam create-access-key --user-name catalog-media-reader

# The one that stays on a workstation / in CI, as an AWS_PROFILE. Never in Railway.
aws iam create-access-key --user-name catalog-media
```

Copy `AccessKeyId` and `SecretAccessKey` **now** — AWS never shows the secret again.

The **reader** key is what step 3 puts in `CATALOG_AWS_ACCESS_KEY_ID` /
`CATALOG_AWS_SECRET_ACCESS_KEY`, and it goes nowhere else. The **writer** key goes in
`~/.aws/credentials` as a named profile for step 5 and must never reach the Railway
environment. Neither belongs in `.env`, a commit, or a Slack message.

---

## 3. Set the Railway env vars

On the **backend** service. Every variable the catalog reads, in full:

### Required

| Variable | Value | Notes |
|---|---|---|
| `CATALOG_SOURCE` | `s3` | The default. `local` is for `npm run dev` only. |
| `CATALOG_S3_BUCKET` | `6thsense-catalog-media` | |
| `CATALOG_S3_REGION` | `us-west-2` | |
| `CATALOG_S3_PREFIX` | `v1/` | The version prefix. Step 8 flips this. |
| `CATALOG_AWS_ACCESS_KEY_ID` | the **`catalog-media-reader`** key from step 2 | not the writer |
| `CATALOG_AWS_SECRET_ACCESS_KEY` | the **`catalog-media-reader`** secret from step 2 | not the writer |

`CATALOG_AWS_ACCESS_KEY_ID` and `CATALOG_AWS_SECRET_ACCESS_KEY` are **both or neither**.
Setting one alone is a hard startup error on purpose: falling through to the ambient AWS
credential chain would sign catalog URLs with whatever `AWS_*` key happens to be in the
environment, including the firmware publishing key.

### Optional, with the defaults that apply if you omit them

| Variable | Default | Notes |
|---|---|---|
| `CATALOG_PRESIGN_TTL` | `900` | Seconds a presigned URL lives (60…604800). Returned to the browser as `expires_at`; the UI refetches before it lapses. |
| `CATALOG_MANIFEST_TTL` | `60` | Seconds a parsed manifest is reused before revalidating against the object ETag. `0` disables. |
| `CATALOG_MANIFEST_KEY` | `catalog.json` | Manifest key, relative to the prefix. |
| `CATALOG_AWS_SESSION_TOKEN` | unset | Only for temporary credentials. |
| `CATALOG_S3_ENDPOINT_URL` | unset | S3-compatible endpoint (MinIO/LocalStack). Leave unset for real AWS. |
| `CATALOG_LOCAL_DIR` | unset | `CATALOG_SOURCE=local` only. |
| `CATALOG_LOCAL_SIGNING_KEY` | random per process | `CATALOG_SOURCE=local` only. |
| `SENSEPROBE_GUEST_LOGIN_RATE_LIMIT` | `60/minute` | Guest logins get their own bucket, keyed `guest-login:<ip>`, so a shared credential cannot exhaust the limit that protects real accounts. |

`DATABASE_URL`, `SENSEPROBE_SESSION_SECRET`, `SENSEPROBE_CORS_ORIGINS` and the existing
`SENSEPROBE_LOGIN_RATE_LIMIT` keep their current values.

### The two cookie variables the portal cannot log in without

Not catalog variables, but production is already set this way and a rebuild that omits them
breaks the catalog in a way that looks like a catalog bug:

| Variable | Value | Notes |
|---|---|---|
| `SENSEPROBE_COOKIE_SAMESITE` | `none` | Defaults to `lax`. |
| `SENSEPROBE_COOKIE_SECURE` | `true` | The default. `none` without it is a hard startup error — browsers silently drop that pairing. |

The SPA is served from `6thsense.dev` and the API from the Railway host: different registrable
domains, so every authenticated request is cross-site. A `lax` cookie is stored on login and
then never sent again — `POST /api/auth/login` returns 200 and `GET /api/catalog` 401s from the
same browser one second later. CSRF is not what `SameSite` defends here; `OriginCheckMiddleware`
rejects any unsafe method on `/api/auth/`, `/api/portal/` and `/api/admin/` whose `Origin` is
not in `SENSEPROBE_CORS_ORIGINS`.

**`none` is necessary but not sufficient, and this is the open issue.** A third-party cookie is
blocked outright — regardless of `SameSite` — by Safari's ITP, iOS in-app browsers (WeChat), and
Firefox/Brave/Chrome-incognito third-party cookie blocking. Those users get the 401 loop above
against a correctly configured server — reproduce it in a Chrome incognito window. The real fix
is to stop being cross-site: put the API on `api.6thsense.dev` (Railway custom domain + a
Porkbun CNAME) and rebuild the frontend with `VITE_API_URL=https://api.6thsense.dev`. That
origin is already in the `connect-src` of `frontend/Caddyfile`.

`SENSEPROBE_CORS_ORIGINS` does **not** change: it lists the origins of *pages* allowed to call
the API, and the page is still `https://6thsense.dev`. Adding the API's own origin to it would
do nothing. Once the cutover is verified, `SENSEPROBE_COOKIE_SAMESITE` can go back to `lax` --
`6thsense.dev` and `api.6thsense.dev` share a registrable domain, so the cookie is first-party
and no longer needs, or benefits from, `none`.

---

## 4. Build the bundle

```bash
make -C scripts/catalog clean fixtures ingest validate     # dry run on synthetic takes
```

For the real corpus, skip `fixtures` and point at the takes:

```bash
python3 -m ingest.catalog_ingest build \
  --takes /path/to/takes --out /path/to/bundle --posters --previews --strict
python3 -m ingest.catalog_ingest validate --out /path/to/bundle
```

(run from `scripts/catalog/`)

**Check**: `validate` exits 0 with eleven `PASS` rows and no `FAIL`. Then read the two
numbers that are easy to get wrong:

```bash
python3 -c "import json;d=json.load(open('/path/to/bundle/catalog.json'));\
print(d['benchmark']['unit'], d['collection']['totals']['duration_unit'], len(d['clips']))"
```

For a ~20 minute corpus this must print `minutes minutes 29` (or your clip count) — **not**
`hours`. The unit is resolved from the data and both consumers read it; see README §8.

Also read `INGEST_REPORT.md` in the bundle. Any take with a QA disposition other than
`accepted` is quarantined and does **not** appear in the catalog. That is intended — confirm
the count is the one you expect before uploading.

---

## 5. Upload

```bash
export CATALOG_S3_BUCKET=6thsense-catalog-media
export CATALOG_S3_REGION=us-west-2
export AWS_PROFILE=catalog-upload      # the catalog-media (writer) key — never the Railway one

python3 scripts/catalog/upload_bundle.py --bundle /path/to/bundle --prefix v1/ --dry-run
python3 scripts/catalog/upload_bundle.py --bundle /path/to/bundle --prefix v1/
```

Always `--dry-run` first and read the object count. The uploader sets content types
explicitly — an mp4 served as `application/octet-stream` will not stream in Safari.

**Check**:

```bash
aws s3 ls s3://6thsense-catalog-media/v1/ --recursive --summarize | tail -3
curl -s -o /dev/null -w '%{http_code}\n' \
  https://6thsense-catalog-media.s3.us-west-2.amazonaws.com/v1/catalog.json
# 403 — the bucket is private. A 200 here means step 1 did not take. Stop and fix it.
```

---

## 6. Migrate and deploy

Migration `0007` adds `guest` to the `users_role_check` constraint. It is DDL only — it seeds
no account and grants no privilege.

```bash
cd backend && python3 -m alembic upgrade head
```

**Check**:

```sql
SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'users_role_check';
-- ... ANY (ARRAY['admin','founder','customer','investor','guest'])
```

Then deploy the backend and the frontend.

---

## 7. Seed the guest account

The migration deliberately does not do this. A shared credential must be revocable **without
a deploy**, and a migration that recreated it on every `alembic upgrade head` would silently
undo a revocation.

> **The guest password is never a literal in this repository.** `6thSense-dev/landing` is a
> public repo: anything committed here is readable by GitHub code search, every fork, and
> every CI log, permanently. The value lives in the password manager (entry *catalog guest*)
> and reaches the process only through `$CATALOG_GUEST_PASSWORD` or the interactive prompt.
> The e2e harness likewise requires `$CATALOG_E2E_PW` and refuses to run with a default.
> If a password ever does land in a file here, treat it as public and rotate immediately with
> `seed-guest` (which also invalidates every live guest session).

```bash
# The password itself is NEVER written down in this repo. Read it out of the
# password manager entry "catalog guest" at the moment you run the command.
cd backend && CATALOG_GUEST_PASSWORD='<from password manager: catalog guest>' \
  python3 -m app.cli seed-guest
```

Creates `guest@6thsense.dev` with role `guest`, active. The login form also accepts the bare
username `guest`, resolved server-side through `RESERVED_USERNAMES`.

`seed-guest` is the only command that accepts a password shorter than `MIN_PASSWORD_LEN` (12),
it accepts a minimum of 8, and it refuses to run against any address but `guest@6thsense.dev`.

**Check**:

```bash
API=...   # the origin the frontend was built with as VITE_API_URL
curl -s -X POST "$API/api/auth/login" \
  -H 'Content-Type: application/json' -H 'Origin: https://6thsense.dev' \
  -d "{\"identifier\":\"guest\",\"password\":\"$CATALOG_GUEST_PASSWORD\"}" -i | head -3
# HTTP/1.1 200, and a Set-Cookie: sid=...
```

Rotating the password later re-runs the same command; it also deletes every live guest session,
which is what makes a rotation an actual revocation rather than a suggestion.

---

## 8. Flip the prefix (only when cutting a new corpus)

For a first launch `CATALOG_S3_PREFIX` is already `v1/` and there is nothing to flip. For a
re-cut:

```bash
python3 scripts/catalog/upload_bundle.py --bundle /path/to/new-bundle --prefix v2/
# verify against the staged prefix BEFORE anyone sees it (§9 with CATALOG_S3_PREFIX=v2/)
# then set CATALOG_S3_PREFIX=v2/ on Railway and redeploy
```

`v1/` stays on the bucket, byte for byte. Rollback is setting the variable back.

---

## 9. Verify in production

Log in at <https://6thsense.dev/login> as `guest` with the password from the manager
("catalog guest") and confirm:

1. You land on `/portal/catalog`. Every other portal route (`/portal/founder`,
   `/portal/admin`, `/portal/customer`, `/portal/investor`) bounces you straight back to it,
   and `/api/admin/*` returns 403 — the redirect is a convenience, the 403 is the control.
2. The grid renders every clip with a poster.
3. Opening a card shows the modal; Video, IMU, Tactile, Segcap, Calib & sync and Metadata
   all render. Calib & sync shows the camera model, per-camera intrinsics, the baseline and
   the per-stream sync table; Metadata shows the QA check table with thresholds, the full
   redaction review record, and links to the per-clip docs.
4. The video plays.
5. The header and task section read **minutes**, not hours, for a ~20 minute corpus.
6. The header carries a **Max sync error** tile with the measured figure, and the count of
   clips over one video frame beneath it. If the corpus is synthetic, a banner says so above
   the grid — if you are looking at a real drop and that banner is showing, stop: the wrong
   bundle is live.
7. Both notices are present: the producer's standing notice AND the preview-access one. If
   only one shows, the redaction layer has swallowed the other.
8. **Request full access** goes somewhere. It is a `mailto:` built from the collection's
   vendor contact, with the collection id in the subject.
9. Logging out and revisiting `/portal/catalog` bounces you to `/login`.

Then check the two things a click-through cannot show you:

```bash
# a. withheld assets are null in the guest's own JSON — enforced server-side, not hidden
curl -s -b cookies.txt "$API/api/catalog/clips/<id>" \
  | python3 -c "import json,sys;c=json.load(sys.stdin);print(c['media']['tactile'], c['media']['archive'], c['media']['imu'])"
# every value null

# b. a raw bucket key, without a signature, is refused
curl -s -o /dev/null -w '%{http_code}\n' \
  https://6thsense-catalog-media.s3.us-west-2.amazonaws.com/v1/media/<id>/tactile/left.npz
# 403
```

Or run all of it at once against a deployed stack:

```bash
CATALOG_E2E_SITE=https://6thsense.dev \
CATALOG_E2E_API="$API" \
CATALOG_E2E_PW="$CATALOG_GUEST_PASSWORD" \   # required; the harness refuses to run without it
node scripts/catalog/e2e/catalog_e2e.cjs
```

105 assertions covering login, the grid, all six tabs, real video playback, the measured
sync aggregate on the header, the synthetic-provenance banner, both collection notices, the
access CTA's destination, the H4 check table, the H6 review record, the documentation links,
withholding, signature stripping, the presign clock coming from the response rather than a
build-time constant, logout, and layout at 360 / 768 / 1440 px. Exit 0 is the gate.
Screenshots land in `docs/catalog/screenshots/`.

---

## 10. Rollback

Ordered from cheapest to most drastic. Prefer the earliest one that solves your problem.

### The catalog is wrong but the site is fine — revoke the credential

```bash
cd backend && python3 -m app.cli seed-guest --deactivate
```

Instant, no deploy. Sets `is_active = false` (enforced on every request by `current_user`
*and* the login route) and deletes every live guest session, so issued cookies die too.
Re-enable by running `seed-guest` with a password again.

### The new corpus is wrong — go back to the previous one

Set `CATALOG_S3_PREFIX` back to the previous prefix on Railway and redeploy. The old bundle
was never overwritten. One variable, no data movement.

### The catalog endpoints are misbehaving — turn the feature off

Unset `CATALOG_AWS_ACCESS_KEY_ID` / `CATALOG_AWS_SECRET_ACCESS_KEY`. The catalog routes fail
closed; nothing else on the site depends on them. Pair with `seed-guest --deactivate` so
prospects get a clean login refusal rather than an empty page.

### Roll the code back

Redeploy the previous build. **Do not downgrade the database to undo the frontend or API** —
`0007` is additive DDL and a forward-deployed backend is happy with it in place.

### Actually reverse the migration

Only if you are removing the `guest` role for good:

```bash
cd backend && python3 -m alembic downgrade -1
```

`downgrade()` does three things, in this order, and the order is the safety property:

1. Deactivates every guest row (`is_active = false`)
2. Deletes their sessions, so no issued cookie survives the role change
3. Only then folds the role to `customer`, so the narrower 0006-era CHECK can re-apply

It does **not** delete the rows — that would destroy data and break the FK'd session history.
It does not fold into a *more* privileged role while the credential is still live, which is
the failure a naive `UPDATE ... SET role='customer'` would ship: a password handed out in
sales emails silently promoted to an account that can reach customer data.

To restore afterwards:

```bash
cd backend && python3 -m alembic upgrade head
CATALOG_GUEST_PASSWORD='...' python3 -m app.cli seed-guest
```

`seed-guest` recognises the deactivated-and-folded row `downgrade()` left behind — that exact
pair (`role = 'customer'` **and** `is_active = false` at `guest@6thsense.dev`) is the
migration's artefact and nothing else, because a genuine customer would be active. It restores
the role in place and prints `(restored from a 0007 downgrade)`. Any other row at that address
still refuses, loudly.
