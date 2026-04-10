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
| Draft league views & state machine | `leagues/test_draft.py` |
| Project-level views | `dcstreethockey/tests.py` |

### PostgreSQL-specific queries in tests

The test database is SQLite. If a view uses a PostgreSQL-only feature (e.g., `.distinct("field")`), mock that queryset in the test rather than calling it directly. See `core/tests/test_cancellation.py` for an example using `unittest.mock.patch`.

### Performance tests

`core/tests/test_performance.py` maintains query-count ceilings for key views. If a legitimate change increases the query count:

1. Update the ceiling constant at the top of the file.
2. Add a comment explaining why it changed.
3. Never raise a ceiling without understanding _why_ the count increased.

---

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

### Score aggregation (`core/views/schedule.py` — `add_goals_for_matchups`)

Goals are annotated from `Stat` rows joined via the home/away team FK.
Tests live in `core/tests/test_schedule_views.py`.

---

## Terminology — floor hockey, not ice hockey

DC Street Hockey is a **floor hockey** league. It plays just like ice hockey — same positions, same rules — except players run instead of skate, and a ball is used instead of a puck. Use the correct vocabulary everywhere: code, comments, templates, and test fixtures.

| Never use | Use instead |
| --- | --- |
| skater | player, or their specific position |
| skating | running |
| field player | player, non-goalie, or their specific position |

Acceptable position terms: **player** (generic), **center**, **wing**, **defense**, **goalie**, **forward** (center or wing). When the distinction matters, prefer the specific position.

This applies to:

- Python docstrings and inline comments
- Template copy visible to users
- Test fixture names and test method names (e.g. `_player()`, not `_skater()`)

---

## Common gotchas

- `Team` requires `team_color` and `is_active` — both have no default in the model, so always supply them in test fixtures.
- `Roster.save()` calls `full_clean()`, which enforces the one-primary-goalie-per-team constraint. Creating a second `is_primary_goalie=True` roster entry for the same team will raise `ValidationError`.
- `MatchUp.clean()` rejects `goalie_status=2` (Sub Needed) when an explicit goalie is set. The view handles this by nulling out the goalie before saving.
- Division integers map to display names: 1=Sunday D1, 2=Sunday D2, 3=Wednesday Draft, 4=Monday A, 5=Monday B.
