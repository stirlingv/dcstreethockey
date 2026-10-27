# DC Street Hockey — Claude Code Guidelines

## Tech stack

- **Backend**: Django 4.2, Python 3.11+
- **Real-time**: Django Channels 4 (WebSockets)
- **Database**: PostgreSQL (production), SQLite (tests)
- **Code style**: Black (88-char line length), enforced via pre-commit

## Running tests

```bash
# Full suite
python manage.py test

# Single module (faster during development)
python manage.py test core.tests.test_standings

# With verbose output
python manage.py test --verbosity=2
```

All tests must pass before committing. The pre-commit hook runs the full suite automatically.

---

## Testing standards

### Rule: every new function and every code change must include tests

- **New view?** Add an integration test that hits the URL with a `Client()` and asserts status code, context keys, and key rendered content.
- **New model method or helper function?** Add unit tests covering the happy path, edge cases (empty queryset, None values), and any error conditions.
- **New API/AJAX endpoint?** Test all response codes (200, 400, 403, 404, 405) and verify the JSON payload structure.
- **Bug fix?** Add a regression test that reproduces the bug _before_ the fix passes, so the bug can never silently return.

### Test file locations

| What you're testing | Where to put the test |
| --- | --- |
| `core/views/schedule.py` helpers & views | `core/tests/test_schedule_views.py` |
| `core/views/standings.py` | `core/tests/test_standings.py` |
| `core/views/players.py` | `core/tests/test_player_stats.py` |
| `core/views/home.py` cancellation logic | `core/tests/test_cancellation.py` |
| Performance / query count regressions | `core/tests/test_performance.py` |
| `leagues/views.py` goalie views & helpers | `leagues/test_goalie_views.py` |
| `leagues/models.py` validation | `leagues/tests.py` |
| `leagues/seasons.py` (which season each division is playing) | `leagues/test_seasons.py` |
| `leagues/results.py` and `leagues/signals.py` (game results → standings) | `leagues/test_results.py` |
| Admin pages in `leagues/admin.py` (matchup, week, team, season) | `leagues/tests_matchup_admin.py` |
| Dashboard widgets (`leagues/templatetags/admin_quick_cancel.py`) | `leagues/tests.py` |
| Draft league views & state machine | `leagues/test_draft.py` |
| Project-level views | `dcstreethockey/tests.py` |
| Every admin page and public URL (smoke sweep) | `dcstreethockey/test_smoke.py` |
| `requirements.txt` hygiene and security floors | `dcstreethockey/test_dependencies.py` |

### PostgreSQL-specific queries in tests

The test database is SQLite. If a view uses a PostgreSQL-only feature (e.g., `.distinct("field")`), mock that queryset in the test rather than calling it directly. See `core/tests/test_cancellation.py` for an example using `unittest.mock.patch`.

### Smoke tests and new pages

`dcstreethockey/test_smoke.py` opens every admin page and every public URL. It fails when a new admin model, custom admin URL, or public URL isn't covered, so when you add one:

- New model registered in the admin? Add a row for it in `dcstreethockey/smoke_data.py`.
- New public URL? Add its name to `PublicUrlSmokeTest.EXPECTED` with the statuses a GET should return.
- New custom admin URL? Add it to `_custom_admin_urls` (safe to GET) or `STATE_CHANGING_ADMIN_URLS`.

Views that change data must reject GET (`@require_POST`), so links, crawlers and chat-app link previews can't trigger them.

### Production smoke test

CI also boots the site with the production settings under uvicorn, against an empty Postgres database seeded by `manage.py seed_smoke_data`, and crawls every page including the admin. To run it locally:

```bash
createdb dcsh_smoke
DATABASE_URL=postgres://dcstreethockey:dcstreethockey@localhost/dcsh_smoke \
    scripts/run_production_smoke.sh
dropdb dcsh_smoke
```

`scripts/smoke_crawl.py` can also crawl any running copy of the site, for example a local server on a copy of production data. Use `--snapshot-dir` to save each page's HTML for a before-and-after diff.

### Performance tests

`core/tests/test_performance.py` maintains query-count ceilings for key views. If a legitimate change increases the query count:

1. Update the ceiling constant at the top of the file.
2. Add a comment explaining why it changed.
3. Never raise a ceiling without understanding _why_ the count increased.

---

## Dependencies

- `requirements.txt` holds production packages only. Development and CI tools go in `requirements-dev.txt`, which includes it. Install locally with `pip install -r requirements-dev.txt`.
- `dcstreethockey/test_dependencies.py` fails if a pin isn't needed, or if the code imports a package `requirements.txt` doesn't install. A package production needs but never imports directly belongs in `INDIRECT_RUNTIME_PINS` with the reason.
- Never pin a package below its entry in `PATCHED_DEPENDENCY_FLOORS`. Add an entry whenever a security advisory is fixed.
- Before removing a dependency, run the full suite and the production smoke test. Removing a Django app from `INSTALLED_APPS` also removes its templates, template tags and static files.

## Pre-commit hooks (run automatically on every commit)

| Hook | What it does |
| --- | --- |
| `trailing-whitespace` | Strips trailing whitespace |
| `end-of-file-fixer` | Ensures files end with a newline |
| `check-yaml` / `check-json` | Validates YAML and JSON syntax |
| `black` | Auto-formats Python (88-char limit) |
| `django-check` | Runs `manage.py check` |
| **`django-test`** | **Runs the full test suite** |
| `django-migrations-check` | Ensures no pending migrations are uncommitted |

If a hook fails, fix the underlying issue — do not bypass hooks with `--no-verify`.

---

## Key business logic to protect with tests

### Standings tiebreakers (`core/views/standings.py`)

Three-tier tiebreaker: regulation wins → head-to-head → goal differential.
Tests live in `core/tests/test_standings.py`. Always add a case when changing tiebreaker logic.

### Goalie status (`leagues/views.py`)

- `get_roster_goalie()` — primary goalie flag takes precedence; substitutes are excluded.
- `update_goalie_status()` — status 2 (Sub Needed) must always clear the explicit goalie field.
- Tests live in `leagues/test_goalie_views.py`.

### Draft state machine (`leagues/models.py`, `leagues/draft_views.py`)

Valid transitions: `SETUP → DRAW → ACTIVE ↔ PAUSED → COMPLETE`.
Tests live in `leagues/test_draft.py`.

### Standings computed from game results (`leagues/results.py`)

For a season with `standings_from_games` (every season created since Fall 2026),
`Team_Stat` is a cache rebuilt from the games: score from `Stat` goals, `went_to_overtime`
and `shootout_winner_is_home` from the game. A tied score with no shootout winner is
undecided and the admin refuses to save it. Signals on `Stat` and `MatchUp` keep the cache
fresh; `Week.save()` and the admin's bulk `update()` calls recompute explicitly. Seasons
before Fall 2026 have `standings_from_games=False` and keep their hand-entered records:
never backfill them. Tests live in `leagues/test_results.py`.

### Which season is current (`leagues/seasons.py`)

Nothing reads `Season.is_current_season` any more. A division's current season is the
oldest season that still has an unplayed, uncancelled game in it (so a rain-delayed
championship keeps its season current), otherwise the newest season it has played in.
`active_season_ids()` adds any newer season that already has teams or games, for admin
filters. Tests live in `leagues/test_seasons.py`.

### Teams carry their division and season (`MatchUp.clean()`)

A game's week must agree with its teams' division and season. The check runs for new or
re-pointed games and for any game in an active season; historical mismatches (Monday A/B
before the 2022 split, a few Sunday crossover games) are left alone. The matchup page shows
a banner with a one-click "move to the right division" fix when it finds one.

### Score aggregation (`core/views/schedule.py` — `add_goals_for_matchups`)

Goals are annotated from `Stat` rows joined via the home/away team FK.
Tests live in `core/tests/test_schedule_views.py`.

---

## User-friendly and intuitive design — required for all enhancements

Every feature and UI change must be immediately understandable to a non-technical user with no training. Clarity and simplicity are non-negotiable.

- **Zero learning curve**: users should know what to do without instructions. Use plain, familiar language for labels and actions (e.g. "View Draft Board" not "Open Session").
- **Progressive disclosure**: show the most important information first; hide advanced or rarely-needed controls until needed. Don't crowd the primary UI with edge-case options.
- **Consistent patterns**: match the visual language and interaction patterns already used on the site. New UI elements should feel like they belong.
- **Clear feedback**: every user action must produce visible feedback — button states, success/error messages, loading indicators where appropriate.
- **Accessible defaults**: meaningful contrast ratios, readable font sizes (≥ 14px body copy), and clear focus states for keyboard navigation.

---

## Mobile-friendly UI — required for all changes

Every UI change must work well on both desktop and mobile devices. This is not optional polish — it is a hard requirement for all templates, pages, and interactive features.

- Use responsive layouts (flexbox/CSS grid) that reflow naturally at narrow widths.
- Touch targets (buttons, links) must be at least 44px tall on mobile.
- Text must be readable without zooming (minimum ~14px font size in body copy).
- Avoid fixed widths that overflow on small screens; use `min-width` with `overflow: auto` for tables/grids that cannot reflow.
- Test at ≤ 600px viewport width for phone-sized screens and at ≥ 1024px for desktop.
- Use `@media (max-width: 767px)` as the primary breakpoint for mobile overrides.

---

## Terminology — street hockey (a.k.a. ball hockey)

DC Street Hockey is a **street hockey** league — also called **ball hockey**. It shares the same positions and rules as ice hockey, but it is neither ice hockey nor floor hockey: players run instead of skate, and a ball is used instead of a puck. Never call the sport "ice hockey" or "floor hockey". Use the correct vocabulary everywhere: code, comments, templates, and test fixtures.

| Never use | Use instead |
| --- | --- |
| skater | player, or their specific position |
| skating | running |
| field player | player, non-goalie, or their specific position |
| floor hockey / ice hockey | street hockey, or ball hockey |

Acceptable position terms: **player** (generic), **center**, **wing**, **defense**, **goalie**, **forward** (center or wing). When the distinction matters, prefer the specific position.

This applies to:

- Python docstrings and inline comments
- Template copy visible to users
- Test fixture names and test method names (e.g. `_player()`, not `_skater()`)

---

## Environment variables and credentials

- **`RENDER_EXTERNAL_DATABASE_URL`** — production Postgres connection string, already exported in `~/.zshrc`. Use this directly; do not ask the user to fetch it from the Render dashboard.
- **`RENDER_API_KEY`** and **`RENDER_POSTGRES_ID`** — also in `~/.zshrc` and `.env`.
- **Python / venv** — the project venv is at `venv/bin/python`. Git commits require `PATH="$(pwd)/venv/bin:$PATH"` so pre-commit hooks can find `python`.
- **Local DB** — `DB_NAME=dcstreethockey`, `DB_USER=dcstreethockey`, `DB_PASSWORD=dcstreethockey` (in `.env`).
- **`GOALIE_CZAR_NAME`** / **`GOALIE_CZAR_EMAIL`** — the league's goalie coordinator, shown on the Goalie Status Board and captain pages. When the email is set and an email backend is configured, new "Sub Needed" reports and "I can sub" offers are emailed there. Defaults: name "John Romps", no email.

### Pushing local → production

**This is destructive and rare.** Use only when you intentionally want to overwrite production data (e.g. after a data migration or seeding exercise that you fully tested locally).

```bash
./scripts/push_local_to_render.sh --confirm
```

The script requires `--confirm` AND an interactive confirmation phrase. **Never run the underlying `psql` commands directly** — always go through this script so the safeguards are enforced.

### Pulling production → local

This happens automatically at the start of each Claude Code session (at most once per 24 hours via the `UserPromptSubmit` hook). To trigger it manually:

```bash
db_migration_scripts/sync_render_to_local.sh
```

---

## Committing changes

Only run the `/commit` skill when the user explicitly asks to commit or push changes. Do not commit automatically after completing a feature or fix.

---

## Common gotchas

- `Team` requires `team_color` and `is_active` — both have no default in the model, so always supply them in test fixtures.
- `Roster.save()` calls `full_clean()`, which enforces the one-primary-goalie-per-team constraint. Creating a second `is_primary_goalie=True` roster entry for the same team will raise `ValidationError`.
- `MatchUp.clean()` rejects `goalie_status=2` (Sub Needed) when an explicit goalie is set. The view handles this by nulling out the goalie before saving.
- Division integers map to display names: 1=Sunday D1, 2=Sunday D2, 3=Wednesday Draft, 4=Monday A, 5=Monday B.
