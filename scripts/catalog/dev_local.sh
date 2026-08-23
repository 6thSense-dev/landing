#!/usr/bin/env bash
#
# Run the WHOLE catalog locally -- the real site, not a prototype.
#
#     ./scripts/catalog/dev_local.sh
#
# Brings up Postgres, migrates it, seeds the guest account, serves the catalog
# bundle off local disk, and starts the Vite dev server. Then prints one URL.
# Ctrl-C tears everything down.
#
# Nothing here needs AWS. The catalog's storage sits behind one interface with
# two drivers; this runs the `local` one. Going live is an env-var change, not
# a rewrite:
#
#     local  : CATALOG_SOURCE=local  CATALOG_LOCAL_DIR=<bundle>
#     s3     : CATALOG_SOURCE=s3     CATALOG_S3_BUCKET/REGION/PREFIX + a reader key
#
# Flags:
#   CATALOG_LOCAL_DIR=<dir>   serve that bundle instead of the fixture one
#
#   --s3             read the catalog from the real S3 bucket instead of local disk
#                    (needs scripts/catalog/.env.local -- see the S3 block below)
#   --rebuild        regenerate fixtures + re-ingest the bundle before starting
#   --with-gaps      build the corpus that exercises missing-modality UI paths
#   --port N         Vite port (default 5173)
#   --api-port N     uvicorn port (default 8000)
#   --no-open        don't open a browser
#   --stop           tear down a previous run and exit

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
# Which bundle to serve. Defaults to the generated fixture corpus; point
# CATALOG_LOCAL_DIR at a real one (e.g. an ingest of your own takes) to review
# it in the actual product before it goes anywhere near S3.
BUNDLE="${CATALOG_LOCAL_DIR:-$HERE/sample/bundle}"
RUN="$HERE/.dev"
PGNAME="nervous1-pg"
PGPORT=55432

WEB_PORT=5173
API_PORT=8000
REBUILD=0
WITH_GAPS=0
OPEN=1
USE_S3=0

# The local guest password. Deliberately NOT the production one: this repo is
# public, so a real shared credential must never be a literal in it. Override
# per-machine by exporting CATALOG_GUEST_PASSWORD, or by putting it in the
# gitignored scripts/catalog/.env.local (sourced just below).
GUEST_PW_DEFAULT="local-dev-guest"

while [ $# -gt 0 ]; do
  case "$1" in
    --s3)        USE_S3=1 ;;
    --rebuild)   REBUILD=1 ;;
    --with-gaps) WITH_GAPS=1; REBUILD=1 ;;
    --port)      WEB_PORT="$2"; shift ;;
    --api-port)  API_PORT="$2"; shift ;;
    --no-open)   OPEN=0 ;;
    --stop)      STOP_ONLY=1 ;;
    -h|--help)   sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

# Per-machine overrides, if you keep any. Gitignored; may hold
# CATALOG_GUEST_PASSWORD and the S3 reader key.
if [ -f "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.env.local" ]; then
  set -a; . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.env.local"; set +a
fi
GUEST_PW="${CATALOG_GUEST_PASSWORD:-$GUEST_PW_DEFAULT}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
step() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "$RUN"

teardown() {
  echo
  step "shutting down"
  for f in "$RUN"/*.pid; do
    [ -e "$f" ] || continue
    pid="$(cat "$f" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      # give it a moment, then insist
      for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$f"
  done
  docker rm -f "$PGNAME" >/dev/null 2>&1 || true
  echo "   done."
}

if [ "${STOP_ONLY:-0}" = "1" ]; then teardown; exit 0; fi
trap teardown EXIT INT TERM
teardown >/dev/null 2>&1 || true   # clear a previous run before we start

# ------------------------------------------------------------ prerequisites --
step "checking prerequisites"
command -v docker  >/dev/null || die "docker is required (it hosts Postgres). Start Docker Desktop."
docker info >/dev/null 2>&1     || die "docker is installed but not running. Start Docker Desktop."
command -v node    >/dev/null || die "node is required"
command -v python3 >/dev/null || die "python3 is required"
command -v ffmpeg  >/dev/null || warn "ffmpeg not found -- only needed with --rebuild"

PY="$(command -v python3)"
if [ -x "$REPO/.venv/bin/python3" ]; then PY="$REPO/.venv/bin/python3"; fi
"$PY" -c "import fastapi, sqlalchemy, alembic, asyncpg, argon2" 2>/dev/null \
  || die "backend deps missing. Run:
    python3 -m pip install -r $REPO/requirements-backend-dev.txt
  (or create $REPO/.venv and install there)"

[ -d "$REPO/frontend/node_modules" ] || {
  step "installing frontend deps (first run only)"
  (cd "$REPO/frontend" && npm install --silent)
}

# ------------------------------------------------------------------ bundle --
if [ "$REBUILD" = "1" ] && [ -n "${CATALOG_LOCAL_DIR:-}" ]; then
  die "--rebuild regenerates the FIXTURE corpus into $HERE/sample/bundle, but
  CATALOG_LOCAL_DIR points at $CATALOG_LOCAL_DIR. Pick one: drop --rebuild to serve
  your bundle, or unset CATALOG_LOCAL_DIR to rebuild the fixtures."
fi
if [ "$REBUILD" = "1" ] || [ ! -f "$BUNDLE/catalog.json" ]; then
  step "building the catalog bundle"
  if [ "$WITH_GAPS" = "1" ]; then
    make -C "$HERE" clean fixtures ingest validate FIXTURE_FLAGS=--with-gaps
  else
    make -C "$HERE" clean fixtures ingest validate
  fi
else
  step "using the existing bundle ($(ls "$BUNDLE/clips" | wc -l | tr -d ' ') clips)"
  echo "     rebuild it with: $0 --rebuild"
fi
[ -f "$BUNDLE/catalog.json" ] || die "no bundle at $BUNDLE -- run with --rebuild"

# ---------------------------------------------------------------- postgres --
step "starting Postgres on :$PGPORT"
docker run -d --rm --name "$PGNAME" \
  -e POSTGRES_PASSWORD=nervous1 -e POSTGRES_USER=nervous1 -e POSTGRES_DB=nervous1 \
  -p "$PGPORT:5432" postgres:16-alpine >/dev/null
DB_URL="postgresql+asyncpg://nervous1:nervous1@127.0.0.1:$PGPORT/nervous1"

printf '     waiting for it'
for i in $(seq 1 60); do
  if docker exec "$PGNAME" pg_isready -U nervous1 -q 2>/dev/null; then echo " ok"; break; fi
  printf '.'; sleep 0.5
  [ "$i" = 60 ] && die "Postgres did not come up"
done

# --------------------------------------------------------- migrate + seed  --
export DATABASE_URL="$DB_URL"
export SENSEPROBE_COOKIE_SECURE=false          # we are on http://localhost
export SENSEPROBE_CORS_ORIGINS="http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT"
# HOST matters, not just the port. The session cookie is SameSite=Lax, and Chromium
# treats `localhost` and `127.0.0.1` as DIFFERENT SITES -- so a page served from
# localhost:5173 talking to an API on 127.0.0.1:8000 silently never sends the
# cookie and every catalog request 401s while login appears to succeed. Both ends
# use the same hostname; ports do not affect same-site.
HOSTNAME_DEV=localhost
export SENSEPROBE_LOGIN_RATE_LIMIT="200/minute"  # so a QA pass doesn't lock you out

step "running migrations"
(cd "$REPO/backend" && "$PY" -m alembic upgrade head >"$RUN/alembic.log" 2>&1) \
  || { tail -20 "$RUN/alembic.log"; die "alembic failed -- see $RUN/alembic.log"; }
echo "     $(grep -c 'Running upgrade' "$RUN/alembic.log" || echo 0) migration(s) applied"

step "seeding the guest account"
(cd "$REPO/backend" && CATALOG_GUEST_PASSWORD="$GUEST_PW" "$PY" -m app.cli seed-guest \
  >"$RUN/seed.log" 2>&1) || { tail -20 "$RUN/seed.log"; die "seed-guest failed"; }

# --------------------------------------------------------------- backend  --
# Two storage drivers behind one interface. `local` is the default because it
# needs nothing; `--s3` proves the exact code path production will run, against
# the real bucket, before anything is deployed.
ENVFILE="$HERE/.env.local"
if [ "$USE_S3" = "1" ]; then
  [ -f "$ENVFILE" ] || die "--s3 needs $ENVFILE. Create it (it is gitignored):

    CATALOG_S3_BUCKET=6thsense-catalog-media
    CATALOG_S3_REGION=us-west-2
    CATALOG_S3_PREFIX=v1/
    CATALOG_AWS_ACCESS_KEY_ID=<the catalog-media-reader AccessKeyId>
    CATALOG_AWS_SECRET_ACCESS_KEY=<its secret>

  Use the READ-ONLY reader identity here, never the writer."
  # shellcheck disable=SC1090
  set -a; . "$ENVFILE"; set +a
  : "${CATALOG_S3_BUCKET:?CATALOG_S3_BUCKET missing from $ENVFILE}"
  : "${CATALOG_AWS_ACCESS_KEY_ID:?CATALOG_AWS_ACCESS_KEY_ID missing from $ENVFILE}"
  : "${CATALOG_AWS_SECRET_ACCESS_KEY:?CATALOG_AWS_SECRET_ACCESS_KEY missing from $ENVFILE}"
  step "starting the API on :$API_PORT  (catalog source: s3://$CATALOG_S3_BUCKET/${CATALOG_S3_PREFIX:-v1/})"
  (
    cd "$REPO/backend"
    CATALOG_SOURCE=s3 \
    CATALOG_PRESIGN_TTL=900 \
    "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
      >"$RUN/api.log" 2>&1 &
    echo $! > "$RUN/api.pid"
  )
else
  step "starting the API on :$API_PORT  (catalog source: local disk)"
  (
    cd "$REPO/backend"
    CATALOG_SOURCE=local \
    CATALOG_LOCAL_DIR="$BUNDLE" \
    CATALOG_LOCAL_SIGNING_KEY="dev-local-not-a-secret" \
    CATALOG_PRESIGN_TTL=900 \
    "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
      >"$RUN/api.log" 2>&1 &
    echo $! > "$RUN/api.pid"
  )
fi
printf '     waiting for it'
for i in $(seq 1 60); do
  if curl -fsS "http://$HOSTNAME_DEV:$API_PORT/health" >/dev/null 2>&1; then echo " ok"; break; fi
  printf '.'; sleep 0.5
  [ "$i" = 60 ] && { tail -30 "$RUN/api.log"; die "API did not come up -- see $RUN/api.log"; }
done

# -------------------------------------------------------------- frontend  --
step "starting the site on :$WEB_PORT"
(
  cd "$REPO/frontend"
  VITE_API_URL="http://$HOSTNAME_DEV:$API_PORT" \
  npm run dev -- --port "$WEB_PORT" --host "$HOSTNAME_DEV" --strictPort \
    >"$RUN/web.log" 2>&1 &
  echo $! > "$RUN/web.pid"
)
printf '     waiting for it'
for i in $(seq 1 90); do
  if curl -fsS "http://$HOSTNAME_DEV:$WEB_PORT/" >/dev/null 2>&1; then echo " ok"; break; fi
  printf '.'; sleep 0.5
  [ "$i" = 90 ] && { tail -30 "$RUN/web.log"; die "Vite did not come up -- see $RUN/web.log"; }
done

# ------------------------------------------------------------------ ready  --
CLIPS=$("$PY" -c "import json;print(len(json.load(open('$BUNDLE/catalog.json'))['clips']))" 2>/dev/null || echo '?')
echo
bold "  nervous-1 is running"
echo
echo "    http://localhost:$WEB_PORT/login          sign in:  guest / $GUEST_PW"
echo "    http://localhost:$WEB_PORT/portal/catalog $CLIPS clips, served from local disk"
echo
echo "    API      http://$HOSTNAME_DEV:$API_PORT   logs: $RUN/api.log"
echo "    site     logs: $RUN/web.log"
echo "    bundle   $BUNDLE"
echo
echo "    Edit anything under frontend/src/catalog/ and it hot-reloads."
echo "    Rebuild the data with:  $0 --rebuild"
echo
echo "    Ctrl-C to stop everything."
echo

if [ "$OPEN" = "1" ] && command -v open >/dev/null; then
  open "http://localhost:$WEB_PORT/login" 2>/dev/null || true
fi

# Hold the terminal, and die loudly if either server exits on its own.
while true; do
  for name in api web; do
    pid="$(cat "$RUN/$name.pid" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && ! kill -0 "$pid" 2>/dev/null; then
      warn "$name exited unexpectedly -- last lines of $RUN/$name.log:"
      tail -20 "$RUN/$name.log"
      exit 1
    fi
  done
  sleep 2
done
