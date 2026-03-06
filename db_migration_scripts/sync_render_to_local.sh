#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: db_migration_scripts/sync_render_to_local.sh [options]

Pull a Render PostgreSQL dump into ./database_dumps, restore it locally,
fix ownership/privileges, and run Django migrations.

Options:
  --render-url URL         Render external PostgreSQL URL.
                           Falls back to $RENDER_EXTERNAL_DATABASE_URL.
  --local-db NAME          Local database name (default: dcstreethockey).
  --local-app-role ROLE    Local app role to own objects (default: dcstreethockey).
  --local-admin-db NAME    DB used for role checks (default: postgres).
  --dump-dir PATH          Dump output directory (default: ./database_dumps).
  --skip-migrate           Skip Django migrate + migrate --plan.
  -h, --help               Show this help.

Environment:
  RENDER_EXTERNAL_DATABASE_URL   Render external DB URL.
  LOCAL_DB_NAME                  Same as --local-db.
  LOCAL_APP_ROLE                 Same as --local-app-role.
  LOCAL_ADMIN_DB                 Same as --local-admin-db.
  PYTHON_BIN                     Python executable for manage.py.

Examples:
  db_migration_scripts/sync_render_to_local.sh
  db_migration_scripts/sync_render_to_local.sh --local-db dcstreethockey_test
  db_migration_scripts/sync_render_to_local.sh --render-url "postgresql://..."
EOF
}

log() {
    printf '[sync-render-db] %s\n' "$*"
}

die() {
    printf '[sync-render-db] ERROR: %s\n' "$*" >&2
    exit 1
}

ensure_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

ensure_sslmode_require() {
    local url="$1"
    if [[ "$url" == *"sslmode="* ]]; then
        printf '%s' "$url"
        return
    fi
    if [[ "$url" == *"?"* ]]; then
        printf '%s&sslmode=require' "$url"
    else
        printf '%s?sslmode=require' "$url"
    fi
}

next_dump_path() {
    local dump_dir="$1"
    local last_id next_id ts

    last_id="$(
        find "$dump_dir" -maxdepth 1 -type f -name 'render_dump_*.sql' -print \
        | sed -E 's/.*render_dump_([0-9]+)_.*/\1/' \
        | sort -n \
        | tail -1
    )"

    if [[ -z "$last_id" ]]; then
        next_id=1
    else
        next_id=$((10#$last_id + 1))
    fi

    ts="$(date +"%Y%m%d_%H%M%S")"
    printf '%s/render_dump_%04d_%s.sql' "$dump_dir" "$next_id" "$ts"
}

role_exists() {
    local role_name="$1"
    local admin_db="$2"
    local escaped_role
    escaped_role="${role_name//\'/\'\'}"
    psql -d "$admin_db" -Atqc \
        "SELECT 1 FROM pg_roles WHERE rolname='${escaped_role}'" | grep -q '^1$'
}

can_connect_as_role() {
    local role_name="$1"
    local db_name="$2"
    psql -U "$role_name" -d "$db_name" -Atqc 'SELECT 1' >/dev/null 2>&1
}

fix_public_schema_ownership() {
    local db_name="$1"
    local role_name="$2"
    psql -v ON_ERROR_STOP=1 -v target_role="$role_name" -d "$db_name" <<'SQL' >/dev/null
SELECT set_config('sync.target_role', :'target_role', false);

DO $$
DECLARE
    target_role text := current_setting('sync.target_role');
    r record;
BEGIN
    FOR r IN
        SELECT
            n.nspname AS schema_name,
            c.relname AS relation_name,
            c.relkind AS relation_kind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND pg_get_userbyid(c.relowner) <> target_role
    LOOP
        IF r.relation_kind IN ('r', 'p') THEN
            EXECUTE format(
                'ALTER TABLE %I.%I OWNER TO %I',
                r.schema_name,
                r.relation_name,
                target_role
            );
        ELSIF r.relation_kind = 'S' THEN
            EXECUTE format(
                'ALTER SEQUENCE %I.%I OWNER TO %I',
                r.schema_name,
                r.relation_name,
                target_role
            );
        ELSIF r.relation_kind = 'v' THEN
            EXECUTE format(
                'ALTER VIEW %I.%I OWNER TO %I',
                r.schema_name,
                r.relation_name,
                target_role
            );
        ELSIF r.relation_kind = 'm' THEN
            EXECUTE format(
                'ALTER MATERIALIZED VIEW %I.%I OWNER TO %I',
                r.schema_name,
                r.relation_name,
                target_role
            );
        ELSIF r.relation_kind = 'f' THEN
            EXECUTE format(
                'ALTER FOREIGN TABLE %I.%I OWNER TO %I',
                r.schema_name,
                r.relation_name,
                target_role
            );
        END IF;
    END LOOP;
END $$;
SQL
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RENDER_URL="${RENDER_EXTERNAL_DATABASE_URL:-}"
LOCAL_DB_NAME="${LOCAL_DB_NAME:-dcstreethockey}"
LOCAL_APP_ROLE="${LOCAL_APP_ROLE:-dcstreethockey}"
LOCAL_ADMIN_DB="${LOCAL_ADMIN_DB:-postgres}"
DUMP_DIR="${PROJECT_ROOT}/database_dumps"
SKIP_MIGRATE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render-url)
            [[ $# -ge 2 ]] || die "--render-url requires a value"
            RENDER_URL="$2"
            shift 2
            ;;
        --local-db)
            [[ $# -ge 2 ]] || die "--local-db requires a value"
            LOCAL_DB_NAME="$2"
            shift 2
            ;;
        --local-app-role)
            [[ $# -ge 2 ]] || die "--local-app-role requires a value"
            LOCAL_APP_ROLE="$2"
            shift 2
            ;;
        --local-admin-db)
            [[ $# -ge 2 ]] || die "--local-admin-db requires a value"
            LOCAL_ADMIN_DB="$2"
            shift 2
            ;;
        --dump-dir)
            [[ $# -ge 2 ]] || die "--dump-dir requires a value"
            DUMP_DIR="$2"
            shift 2
            ;;
        --skip-migrate)
            SKIP_MIGRATE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
done

ensure_command pg_dump
ensure_command psql
ensure_command dropdb
ensure_command createdb

if [[ -z "$RENDER_URL" ]]; then
    read -r -s -p "Render external DB URL: " RENDER_URL
    echo
fi

[[ -n "$RENDER_URL" ]] || die "Render URL is required."
[[ "$RENDER_URL" == postgres://* || "$RENDER_URL" == postgresql://* ]] \
    || die "Render URL must start with postgres:// or postgresql://"

RENDER_URL="$(ensure_sslmode_require "$RENDER_URL")"

mkdir -p "$DUMP_DIR"
DUMP_PATH="$(next_dump_path "$DUMP_DIR")"

log "Dumping Render database to: $DUMP_PATH"
pg_dump \
    --no-owner \
    --no-privileges \
    --file "$DUMP_PATH" \
    "$RENDER_URL"

log "Recreating local database: $LOCAL_DB_NAME"
dropdb --if-exists "$LOCAL_DB_NAME"

if role_exists "$LOCAL_APP_ROLE" "$LOCAL_ADMIN_DB"; then
    createdb -O "$LOCAL_APP_ROLE" "$LOCAL_DB_NAME"
else
    log "Role '$LOCAL_APP_ROLE' not found; creating DB owned by current role."
    createdb "$LOCAL_DB_NAME"
fi

log "Restoring dump into local database"
if role_exists "$LOCAL_APP_ROLE" "$LOCAL_ADMIN_DB" \
    && can_connect_as_role "$LOCAL_APP_ROLE" "$LOCAL_DB_NAME"; then
    log "Restoring as role '$LOCAL_APP_ROLE'"
    psql -v ON_ERROR_STOP=1 -U "$LOCAL_APP_ROLE" -d "$LOCAL_DB_NAME" -f "$DUMP_PATH" >/dev/null
else
    if role_exists "$LOCAL_APP_ROLE" "$LOCAL_ADMIN_DB"; then
        log "Could not connect as '$LOCAL_APP_ROLE'; restoring as current role."
    fi
    psql -v ON_ERROR_STOP=1 -d "$LOCAL_DB_NAME" -f "$DUMP_PATH" >/dev/null
fi

if role_exists "$LOCAL_APP_ROLE" "$LOCAL_ADMIN_DB"; then
    log "Normalizing public schema object ownership to '$LOCAL_APP_ROLE'"
    fix_public_schema_ownership "$LOCAL_DB_NAME" "$LOCAL_APP_ROLE"

    log "Applying grants/default privileges for role: $LOCAL_APP_ROLE"
    psql -v ON_ERROR_STOP=1 -d "$LOCAL_DB_NAME" <<SQL >/dev/null
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "$LOCAL_APP_ROLE";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "$LOCAL_APP_ROLE";
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO "$LOCAL_APP_ROLE";
ALTER DEFAULT PRIVILEGES FOR ROLE "$LOCAL_APP_ROLE" IN SCHEMA public GRANT ALL ON TABLES TO "$LOCAL_APP_ROLE";
ALTER DEFAULT PRIVILEGES FOR ROLE "$LOCAL_APP_ROLE" IN SCHEMA public GRANT ALL ON SEQUENCES TO "$LOCAL_APP_ROLE";
ALTER DEFAULT PRIVILEGES FOR ROLE "$LOCAL_APP_ROLE" IN SCHEMA public GRANT ALL ON FUNCTIONS TO "$LOCAL_APP_ROLE";
SQL
else
    log "Skipping ownership/grants because role '$LOCAL_APP_ROLE' does not exist."
fi

if [[ "$SKIP_MIGRATE" -eq 0 ]]; then
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        python_cmd="$PYTHON_BIN"
    elif [[ -x "${PROJECT_ROOT}/venv/bin/python" ]]; then
        python_cmd="${PROJECT_ROOT}/venv/bin/python"
    else
        python_cmd="python"
    fi

    log "Running Django migrations with: $python_cmd"
    (
        cd "$PROJECT_ROOT"
        "$python_cmd" manage.py migrate
        "$python_cmd" manage.py migrate --plan
    )
fi

log "Done. Local DB '$LOCAL_DB_NAME' restored from $DUMP_PATH"
