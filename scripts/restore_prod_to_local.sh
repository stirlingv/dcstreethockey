#!/usr/bin/env bash
# restore_prod_to_local.sh — Pull the Render production database into your local
# dcstreethockey database, after first backing up the current local state.
#
# Usage:
#   PROD_DB_URL="postgresql://user:pass@host/dbname" ./scripts/restore_prod_to_local.sh
#
# Get PROD_DB_URL from: Render dashboard → postgresql-sinuous-75597 → Connect → External
set -euo pipefail

DB_NAME="${DB_NAME:-dcstreethockey}"
DB_USER="${DB_USER:-dcstreethockey}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "${PROD_DB_URL:-}" ]]; then
    echo "Error: PROD_DB_URL is not set."
    echo "  Export it first:"
    echo "  export PROD_DB_URL='postgresql://...'"
    echo "  (Find it in the Render dashboard → postgresql-sinuous-75597 → Connect → External)"
    exit 1
fi

# Step 1: Backup local database
echo "=== Step 1: Backing up local database ==="
"$SCRIPT_DIR/backup_db.sh"

# Step 2: Dump production
DUMP_FILE="/tmp/prod_dump_$(date +%Y%m%d_%H%M%S).sql"
echo ""
echo "=== Step 2: Dumping production database ==="
echo "  Source: $PROD_DB_URL"
echo "  Destination: $DUMP_FILE"
pg_dump --no-acl --no-owner "$PROD_DB_URL" > "$DUMP_FILE"
echo "  Done. $(du -sh "$DUMP_FILE" | cut -f1) dumped."

# Step 3: Drop and recreate local database
# Note: drop/create run as the system superuser (no -U flag) because the
# app user (dcstreethockey) does not have CREATEDB privilege.
# After restore, grant privileges back to the app user.
echo ""
echo "=== Step 3: Resetting local database '$DB_NAME' ==="
dropdb "$DB_NAME"
createdb "$DB_NAME"
psql "$DB_NAME" -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER; GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;" > /dev/null

# Step 4: Load dump
echo ""
echo "=== Step 4: Loading production dump into local ==="
psql -U "$DB_USER" "$DB_NAME" < "$DUMP_FILE"
echo "  Done."

# Step 5: Apply any pending local migrations
echo ""
echo "=== Step 5: Applying pending migrations ==="
cd "$SCRIPT_DIR/.."
venv/bin/python manage.py migrate

echo ""
echo "=== Done. Local database now mirrors production. ==="
echo ""
echo "Next steps — re-import ADP history if prod doesn't have it:"
echo ""
echo "  # Check what season IDs are available:"
echo "  venv/bin/python manage.py shell -c \\"
echo "    \"from leagues.models import Season, DraftSession; [print(s.pk, s) for s in Season.objects.filter(year=2025) if not DraftSession.objects.filter(season=s).exists()]\""
echo ""
echo "  # Then import each historical CSV with the right --season-id:"
echo "  venv/bin/python manage.py import_draft_results \\"
echo "    --csv 'docs/2025 Fall Draft Board - Draft Board.csv' \\"
echo "    --roster-csv 'docs/2025 Fall Draft League Registration (Responses) - Form Responses 1.csv' \\"
echo "    --season-id <ID>"
echo ""
echo "  venv/bin/python manage.py import_draft_results \\"
echo "    --csv 'docs/2025 Spring Draft Board - Draft Board.csv' \\"
echo "    --roster-csv 'docs/2025 Spring Draft League Registration (Responses) - Form Responses 1.csv' \\"
echo "    --season-id <ID>"
