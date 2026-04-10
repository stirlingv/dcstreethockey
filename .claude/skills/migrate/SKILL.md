# Django Migration Skill

Use this skill when the user asks to create a migration, apply migrations, sync the database, check migration state, or do any database schema/data work.

## Project context

- **Production**: Render PostgreSQL (`postgresql-sinuous-75597`) at `dcstreethockey.com`
- **Local**: PostgreSQL database named `dcstreethockey`, role `dcstreethockey`
- **Migrations**: 95+ in `leagues/migrations/`, settings split into `base.py` / `local.py` / `production.py`
- **Sync script**: `db_migration_scripts/sync_render_to_local.sh` — pulls Render DB dump locally and runs migrations
- **Data scripts**: raw SQL files in `db_migration_scripts/` for one-off player/roster/stat updates

---

## Step-by-step workflows

### Creating a new migration

1. Make model changes in `leagues/models.py` (or `core/models.py`)
2. Preview what Django will generate — do NOT apply yet:
   ```bash
   python manage.py makemigrations --dry-run --verbosity=2
   ```
3. If the preview looks correct, generate it:
   ```bash
   python manage.py makemigrations
   ```
4. **Review the generated file** in `leagues/migrations/` before proceeding. Check for:
   - Unintended field removals or renames
   - Missing `on_delete` arguments
   - Data migrations that need a corresponding RunPython step
5. Run `python manage.py migrate --plan` to confirm the migration order locally
6. Apply locally:
   ```bash
   python manage.py migrate
   ```
7. Run the full test suite to catch breakage before pushing:
   ```bash
   python manage.py test
   ```
8. Commit the migration file alongside the model change — never commit one without the other.

### Checking migration state

```bash
# Show all migrations and whether they've been applied
python manage.py showmigrations

# Show what would be applied next
python manage.py migrate --plan
```

### Syncing production DB to local (for development/debugging)

```bash
db_migration_scripts/sync_render_to_local.sh
# Prompts for Render external DB URL if RENDER_EXTERNAL_DATABASE_URL is not set
# Dumps Render DB → restores locally → runs Django migrations
```

### Applying a data migration (SQL script)

Raw SQL scripts in `db_migration_scripts/` handle one-off data fixes (player merges, gender updates, stat corrections). Before running any of them:
1. Sync local DB from production first so you're testing against real data
2. Run the script against local DB and verify the result
3. Only then run against production via a Render shell or direct connection
4. Document what you ran and why in a git commit comment or the script itself

### Rolling back a migration (local only)

```bash
# Roll back to a specific migration number
python manage.py migrate leagues 0092_captain_draft_round
```

Never roll back migrations in production without a recovery plan — Render has no automatic rollback.

---

## Safety rules

- **Never run `makemigrations` on production** — migrations are always created locally and committed
- **Always run `python manage.py test` before pushing** — the pre-commit hook enforces this, but run it manually too when migrations are involved
- **Check for squash opportunities** every ~20 migrations to keep the history manageable
- **Data migrations that touch player PII** (emails, names) should use `RunPython` with a reverse function so they're reversible
- The `pre-commit` hook runs `makemigrations --check --dry-run` and will block commits if you have unapplied model changes without a migration file
