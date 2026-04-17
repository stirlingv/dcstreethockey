#!/usr/bin/env bash
# push_local_to_render.sh — Overwrite the Render production database with your
# local database.
#
# THIS IS DESTRUCTIVE AND IRREVERSIBLE. Production data will be replaced with
# your local database. Use only after deliberate, intentional testing.
#
# Usage:
#   ./scripts/push_local_to_render.sh --confirm
#
# The --confirm flag is required. Without it the script exits immediately.
# You will also be prompted to type a confirmation phrase interactively.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_NAME="${DB_NAME:-dcstreethockey}"
DB_USER="${DB_USER:-dcstreethockey}"

# ---------------------------------------------------------------------------
# Require --confirm flag
# ---------------------------------------------------------------------------
CONFIRMED=0
for arg in "$@"; do
    if [[ "$arg" == "--confirm" ]]; then
        CONFIRMED=1
    fi
done

if [[ "$CONFIRMED" -eq 0 ]]; then
    echo ""
    echo "  ERROR: --confirm flag is required."
    echo ""
    echo "  This script overwrites the Render PRODUCTION database with your"
    echo "  local database. It is destructive and cannot be undone."
    echo ""
    echo "  If you are sure, run:"
    echo "    ./scripts/push_local_to_render.sh --confirm"
    echo ""
    exit 1
fi

# ---------------------------------------------------------------------------
# Require RENDER_EXTERNAL_DATABASE_URL
# ---------------------------------------------------------------------------
if [[ -z "${RENDER_EXTERNAL_DATABASE_URL:-}" ]]; then
    echo "ERROR: RENDER_EXTERNAL_DATABASE_URL is not set."
    echo "  It should be exported in ~/.zshrc."
    exit 1
fi

# ---------------------------------------------------------------------------
# Loud warning banner
# ---------------------------------------------------------------------------
echo ""
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║       WARNING: YOU ARE ABOUT TO OVERWRITE PRODUCTION        ║"
echo "  ║                                                              ║"
echo "  ║  Local database  →  Render production database              ║"
echo "  ║                                                              ║"
echo "  ║  ALL production data will be PERMANENTLY REPLACED with      ║"
echo "  ║  your local database. This cannot be undone.                ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo ""

# ---------------------------------------------------------------------------
# Interactive confirmation — must type exact phrase
# ---------------------------------------------------------------------------
REQUIRED_PHRASE="overwrite production"
echo "  Type exactly:  overwrite production"
echo "  (anything else aborts)"
echo ""
read -r -p "  > " USER_INPUT

if [[ "$USER_INPUT" != "$REQUIRED_PHRASE" ]]; then
    echo ""
    echo "  Aborted. Nothing was changed."
    exit 1
fi

echo ""

# ---------------------------------------------------------------------------
# Step 1: Backup local database first
# ---------------------------------------------------------------------------
echo "=== Step 1: Backing up local database ==="
"$SCRIPT_DIR/backup_db.sh"

# ---------------------------------------------------------------------------
# Step 2: Dump local database
# ---------------------------------------------------------------------------
LOCAL_DUMP="/tmp/local_push_$(date +%Y%m%d_%H%M%S).sql"
echo ""
echo "=== Step 2: Dumping local database '$DB_NAME' ==="
pg_dump --no-acl --no-owner -U "$DB_USER" "$DB_NAME" > "$LOCAL_DUMP"
echo "  Done. $(du -sh "$LOCAL_DUMP" | cut -f1) written to $LOCAL_DUMP"

# ---------------------------------------------------------------------------
# Step 3: Wipe and restore production
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: Overwriting Render production database ==="
psql "$RENDER_EXTERNAL_DATABASE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
psql "$RENDER_EXTERNAL_DATABASE_URL" < "$LOCAL_DUMP"
echo "  Done."

# ---------------------------------------------------------------------------
# Step 4: Run migrations on production
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 4: Running migrations on production ==="
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    if [[ -x "$(pwd)/venv/bin/python" ]]; then
        PYTHON_BIN="$(pwd)/venv/bin/python"
    else
        PYTHON_BIN="python"
    fi
fi
DATABASE_URL="$RENDER_EXTERNAL_DATABASE_URL" \
    "$PYTHON_BIN" manage.py migrate --settings=dcstreethockey.settings.production
echo "  Done."

echo ""
echo "=== Production database has been replaced with your local database. ==="
echo "  Local dump saved at: $LOCAL_DUMP"
