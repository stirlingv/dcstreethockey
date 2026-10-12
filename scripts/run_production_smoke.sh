#!/usr/bin/env bash
# Boot the site the way Render does and crawl every page, including the admin.
#
# Runs with the production settings (DEBUG off, WhiteNoise manifest storage,
# HTTPS redirect, S3 media backend) under uvicorn, the production server,
# against a throwaway PostgreSQL database seeded with smoke-test data.
#
# Requirements:
#   - DATABASE_URL points at an EMPTY PostgreSQL database. seed_smoke_data
#     refuses to run against a database that already has league data.
#   - `python` has requirements.txt installed (production packages only, so
#     a missing runtime dependency fails here instead of on Render).
#
# Usage:
#   createdb dcsh_smoke
#   DATABASE_URL=postgres://user:pass@localhost/dcsh_smoke \
#       scripts/run_production_smoke.sh
#   dropdb dcsh_smoke
set -euo pipefail

cd "$(dirname "$0")/.."

: "${DATABASE_URL:?Set DATABASE_URL to an empty PostgreSQL database}"
PORT="${SMOKE_PORT:-8765}"
export DJANGO_SETTINGS_MODULE=dcstreethockey.settings.production
export SECRET_KEY="${SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(50))')}"
export DJANGO_SUPERUSER_USERNAME="${SMOKE_ADMIN_USER:-smoke-admin}"
export DJANGO_SUPERUSER_PASSWORD="${SMOKE_ADMIN_PASSWORD:-$(python -c 'import secrets; print(secrets.token_urlsafe(24))')}"
export DJANGO_SUPERUSER_EMAIL=smoke@example.com
export SMOKE_ADMIN_USER="$DJANGO_SUPERUSER_USERNAME"
export SMOKE_ADMIN_PASSWORD="$DJANGO_SUPERUSER_PASSWORD"

echo "==> Checking installed packages are consistent"
python -m pip check

echo "==> Django deploy checks (warnings are reported, errors fail)"
python manage.py check --deploy --fail-level ERROR

echo "==> Applying migrations to a fresh database"
python manage.py migrate --no-input

echo "==> Collecting static files with the production storage backend"
python manage.py collectstatic --no-input >/dev/null

echo "==> Seeding smoke-test data and an admin user"
python manage.py seed_smoke_data
python manage.py createsuperuser --no-input

echo "==> Starting uvicorn on port $PORT"
LOG="$(mktemp)"
python -m uvicorn dcstreethockey.asgi:application --host 127.0.0.1 --port "$PORT" \
    >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
    if curl -sf -o /dev/null -H "X-Forwarded-Proto: https" \
        "http://127.0.0.1:$PORT/admin/login/"; then
        break
    fi
    sleep 0.5
done

echo "==> Crawling the site"
status=0
python scripts/smoke_crawl.py --base-url "http://127.0.0.1:$PORT" --behind-proxy \
    || status=$?

if grep -qE "Traceback|Internal Server Error" "$LOG"; then
    echo "==> Server log shows errors:"
    cat "$LOG"
    status=1
fi
exit "$status"
