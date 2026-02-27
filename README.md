# dcstreethockey

## Development Setup (Recommended)

**🏒 Quick Start for New Developers:**

1. **Clone and setup:**

   ```bash
   git clone https://github.com/[your-username]/dcstreethockey.git
   cd dcstreethockey
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Automated setup (does everything for you):**

   ```bash
   ./setup-dev.sh
   ```

   This script will:
   - Install all Python dependencies
   - Install pre-commit hooks
   - Run Django system checks
   - Check for migrations
   - Run all tests to verify setup
   - Format existing code

3. **Start developing! 🚀**

   ```bash
   python manage.py runserver
   ```

### 🛡️ Pre-commit Quality Assurance

**Automatic checks before every commit:**

- ✅ **Django system checks** - No configuration errors
- ✅ **Full test suite** - All tests must pass (including standings logic)
- ✅ **Migration checks** - No uncommitted database changes
- ✅ **Code formatting** - Auto-formatted with Black (88 chars)
- ✅ **Code linting** - Flake8 quality checks
- ✅ **File cleanup** - No trailing whitespace, proper line endings

**Manual commands:**

```bash
# Run pre-commit on all files
pre-commit run --all-files

# Run specific test suites
python manage.py test core.tests.test_standings -v 2  # Standings logic
python manage.py test leagues.tests                   # League functionality

# Test just the setup
./test-precommit.sh
```

### 🧪 Test Coverage

The standings logic includes comprehensive tests for:

- **2-team tiebreakers:** regulation wins, goal differential, head-to-head
- **3-team tiebreakers:** complex scenarios with mixed metrics
- **4-team tiebreakers:** all teams tied with different regulation wins
- **Edge cases:** identical metrics, integration tests

### 📋 Development Workflow

1. **Make changes** to code
2. **Add/commit** - pre-commit automatically runs all checks
3. **If checks fail** - fix issues and commit again
4. **Push** - GitHub Actions runs same checks
5. **Create PR** - All quality gates must pass

---

## Alternative Setup Methods

### Docker Setup (Alternative)

**Note:** The development setup above is recommended for active development. Use Docker for quick testing or if you prefer containerization.

1. [install_docker](https://docs.docker.com/engine/installation/)
1. [install_docker-compose](https://docs.docker.com/compose/install/)
1. [fork](https://help.github.com/articles/fork-a-repo/) and [clone](https://help.github.com/articles/cloning-a-repository/) repo
1. docker-compose up
1. Stop that process Ctrl+c
1. Download test data set
1. docker-compose run --rm web python manage.py loaddata working-herokudump.json
1. docker-compose up

### Manual Localhost Setup (Alternative)

**Note:** Use the **Development Setup** above instead for the best experience with pre-commit hooks and quality assurance.

1. **Install PostgreSQL:**

   ```bash
   # Using Homebrew (macOS)
   brew install postgresql

   # Or download from: https://www.postgresql.org/download/
   ```

1. **Clone and setup environment:**

   ```bash
   git clone [repo-url]
   cd dcstreethockey
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

1. **Setup database:**

1. Make sure postgres is running and Database exists
   - ```brew services start postgresql```
   - ```psql -l```
      - if dcstreethockey doesn't exist continue
   - ```createdb dcstreethockey```
   - ```createuser user```
1. ```uvicorn dcstreethockey.asgi:application --host 0.0.0.0 --port 8000```

## Deploy - keeps dev and  in sync

1. ```./manage.py makemigrations```
1. ```./manage.py migrate```
1. ```git push origin main```

## [OUTDATED] Ensure DJANGO_SETTINGS_MODULE is set for production deployments

1. ```heroku config:set DJANGO_SETTINGS_MODULE=dcstreethockey.settings.production```

## Create backup of render database and restore in local postgres instance

1. Run pg_dump to generate an export of the database on render:

    ```bash
    pg_dump --no-owner --no-privileges -d <<external render DB connection>> > ~/Downloads/<<file_name>>.sql
    ```

1. Delete local postgres db.

    ```bash
    dropdb dcstreethockey
    ```

1. Create local db.

    ```bash
    createdb dcstreethockey
    ```

1. Run restore using your app DB role so new objects are owned by `dcstreethockey`.

    ```bash
    psql -U dcstreethockey -d dcstreethockey < ~/Downloads/<<file_name>>.sql
    ```

1. If you restored with a different role, find the current owner role and reassign ownership to `dcstreethockey` (run as a local superuser role, e.g. `stirling`):

    ```bash
    psql -d dcstreethockey -c "select distinct tableowner from pg_tables where schemaname='public';"
    psql -d dcstreethockey -c 'REASSIGN OWNED BY "<restore_role>" TO dcstreethockey;'
    ```

1. Grant privileges and set default privileges for the app role:

   ```sql
   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO dcstreethockey;
   GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO dcstreethockey;
   GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO dcstreethockey;
   ALTER DEFAULT PRIVILEGES FOR ROLE dcstreethockey IN SCHEMA public GRANT ALL ON TABLES TO dcstreethockey;
   ALTER DEFAULT PRIVILEGES FOR ROLE dcstreethockey IN SCHEMA public GRANT ALL ON SEQUENCES TO dcstreethockey;
   ALTER DEFAULT PRIVILEGES FOR ROLE dcstreethockey IN SCHEMA public GRANT ALL ON FUNCTIONS TO dcstreethockey;
   ```

1. Verify ownership (all rows should show `dcstreethockey`):

   ```bash
   psql -d dcstreethockey -c "select relkind, pg_get_userbyid(relowner) as owner, count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname='public' and relkind in ('r','S') group by relkind, owner order by relkind, owner;"
   ```

1. Run migrations:

   ```bash
   ./venv/bin/python manage.py migrate
   ./venv/bin/python manage.py migrate --plan
   ```

## Run local database to render

1. Get Connection Details:
   - Log in to your Render dashboard and navigate to your PostgreSQL service. Copy the connection string provided, which will be in the format:

    ```sql
    postgres://<username>:<password>@<host>:<port>/<database>
    ```

1. Save your SQL script locally, e.g., db_migration_scripts/insert_matchup.sql.
1. Run the following command in your terminal, replacing <connection_string> with the actual connection string and path/to/your/script.sql with the path to your SQL script:

    ```bash
    psql postgres://<username>:<password>@<host>:<port>/<database> -f path/to/your/script.sql
    ```

---

## 🛠️ Development Reference

### Configuration Files Created

The development setup creates these important files:

- **`.pre-commit-config.yaml`** - Pre-commit hook configuration
- **`.flake8`** - Python linting rules (compatible with Black)
- **`pyproject.toml`** - Black formatter and isort configuration
- **`setup-dev.sh`** - Automated development environment setup
- **`test-precommit.sh`** - Test script to verify pre-commit setup
- **`.github/workflows/ci.yml`** - GitHub Actions for CI/CD
- **`PRE-COMMIT-SETUP.md`** - Detailed pre-commit documentation

### Key Testing Files

- **`core/tests/test_standings.py`** - Comprehensive standings logic tests
- **`core/tests/__init__.py`** - Makes tests directory a Python package

### Troubleshooting

**Pre-commit issues:**

```bash
# Reinstall hooks
pre-commit uninstall
pre-commit install

# Update hooks to latest versions
pre-commit autoupdate

# Skip hooks temporarily (not recommended)
git commit -m "message" --no-verify
```

**Test issues:**

```bash
# Run specific test with verbose output
python manage.py test core.tests.test_standings -v 2

# Run with keepdb to speed up repeated runs
python manage.py test --keepdb

# Debug test discovery issues
python manage.py test --debug-mode
```

**Environment issues:**

```bash
# Recreate virtual environment
deactivate
rm -rf venv
python3 -m venv venv
source venv/bin/activate
./setup-dev.sh
```

### Contributing

1. **Make sure pre-commit is working:** `pre-commit run --all-files`
2. **Run tests:** `python manage.py test core.tests.test_standings`
3. **Make changes and commit** - hooks will run automatically
4. **Push and create PR** - GitHub Actions will validate

All commits must pass the pre-commit quality gates! 🏒
