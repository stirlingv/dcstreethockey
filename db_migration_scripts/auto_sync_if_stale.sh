#!/usr/bin/env bash
# Called by Claude Code's UserPromptSubmit hook.
# Syncs production DB from Render at most once per 24 hours,
# only when you are actively working in Claude Code.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STAMP_FILE="$REPO_ROOT/database_dumps/.last_db_sync"
LOG_FILE="$REPO_ROOT/database_dumps/auto_sync.log"
SYNC_SCRIPT="$SCRIPT_DIR/sync_render_to_local.sh"
MAX_AGE_SECONDS=86400  # 24 hours

# Require the Render URL to be set — never prompt interactively from a hook
if [ -z "${RENDER_EXTERNAL_DATABASE_URL:-}" ]; then
    exit 0
fi

# Check if a sync has already happened within the last 24 hours
if [ -f "$STAMP_FILE" ]; then
    last_sync=$(cat "$STAMP_FILE")
    now=$(date +%s)
    age=$((now - last_sync))
    if [ "$age" -lt "$MAX_AGE_SECONDS" ]; then
        exit 0
    fi
fi

# Write timestamp now so a second Claude Code window doesn't double-trigger
date +%s > "$STAMP_FILE"

echo "Production DB sync started in background. Tail $LOG_FILE for progress."

# Run sync in background, detached from this shell so Claude Code isn't blocked
nohup "$SYNC_SCRIPT" > "$LOG_FILE" 2>&1 &
