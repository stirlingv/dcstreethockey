#!/usr/bin/env bash
# backup_db.sh — Dump the local dcstreethockey database to a timestamped file.
# Usage:
#   ./scripts/backup_db.sh              # saves to backups/
#   ./scripts/backup_db.sh /tmp/out.sql # saves to a specific path
set -euo pipefail

DB_NAME="${DB_NAME:-dcstreethockey}"
DB_USER="${DB_USER:-dcstreethockey}"
BACKUP_DIR="$(dirname "$0")/../backups"

if [[ $# -ge 1 ]]; then
    OUTFILE="$1"
else
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
    OUTFILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql"
fi

echo "Backing up local database '$DB_NAME' → $OUTFILE"
pg_dump --no-acl --no-owner -U "$DB_USER" "$DB_NAME" > "$OUTFILE"
echo "Done. $(du -sh "$OUTFILE" | cut -f1) written."
