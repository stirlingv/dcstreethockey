# Wednesday Draft League Setup Skill

Use this skill for any work related to the Wednesday Draft League: setting up a new draft season, running the draft, fixing draft state, or finalizing picks into real teams.

## How the draft works (big picture)

Players sign up publicly → commissioner creates a `DraftSession` → captains are drawn for position order → live snake draft via WebSocket boards → commissioner finalizes, which converts draft picks into real `Team` and `Roster` records.

## State machine

```
SETUP → DRAW → ACTIVE ↔ PAUSED → COMPLETE
```

- **SETUP**: Commissioner configures teams/rounds; signups open/close here
- **DRAW**: Captains draw positions (randomized order assignment)
- **ACTIVE**: Live draft in progress; captains make picks on their boards
- **PAUSED**: Draft paused mid-session (break, dispute, etc.)
- **COMPLETE**: All picks made; ready for finalization
- Transitions are triggered via `draft/<session_pk>/advance/<commissioner_token>/`

## Key URLs (all require session PK)

| Role | URL pattern |
| --- | --- |
| Spectator (public) | `/draft/<session_pk>/` |
| Commissioner | `/draft/<session_pk>/commissioner/<commissioner_token>/` |
| Captain | `/draft/<session_pk>/captain/<captain_token>/` |
| Captain portal | `/draft/<session_pk>/captains/` |
| Signup form | `/draft/signup/<season_pk>/` |

## Pre-draft checklist (new season)

### 1. Create the Season
In Django admin: **Leagues → Seasons → Add Season**
- Set `year`, `season_type` (3 = Wednesday Draft), `is_current_season = True`
- Unmark the previous season's `is_current_season`

### 2. Open signups
In Django admin: **Draft → Draft Sessions → Add Draft Session**
- Link to the new season
- Set `signups_open = True`
- Share the signup URL: `/draft/signup/<season_pk>/`

### 3. Link signups to Player records
After signups close, match each `SeasonSignup` to an existing `Player`:
- Admin: **Draft → Season Signups** — set the `linked_player` FK for each
- New players need a `Player` record created first
- The `import_draft_signups` management command can bulk-import from a CSV:
  ```bash
  python manage.py import_draft_signups <csv_path>
  ```
- Use `link_draft_players` to auto-match by name:
  ```bash
  python manage.py link_draft_players
  ```

### 4. Configure the DraftSession
In admin: set `num_teams`, `num_rounds`, then add `DraftRound` objects for any rounds that should be **randomized** instead of snake (default is all snake).

### 5. Seed test data (local dev only)
```bash
python manage.py seed_draft_test
```
Creates fake signups, players, and a ready-to-draw session. Useful for testing the draft board without real data.

### 6. Run the draft

1. Commissioner opens `/draft/<session_pk>/commissioner/<token>/`
2. Advance to **DRAW** phase → captains draw positions
3. Advance to **ACTIVE** → live draft begins
4. Captains pick on their boards; commissioner can `undo` last pick or `swap` two picks
5. Auto-captain: if a captain's turn is skipped (they don't pick in time), the system can auto-draft them in — controlled in admin

### 7. Finalize the draft
After all picks are made, commissioner triggers **Finalize** at:
`/draft/<session_pk>/finalize/<commissioner_token>/`

This creates real `Team` and `Roster` records from the draft picks. **Irreversible** — only do this when all picks are confirmed correct.

### 8. Post-draft
- Verify teams in admin: **Leagues → Teams** — new teams for the season should appear
- Verify rosters: **Leagues → Rosters**
- Set up `Week` and `MatchUp` records for the season schedule
- Share captain access codes (goalie status URLs) via the captain URLs page: `/captain-urls/`

---

## Undo / fix mid-draft

- **Undo last pick**: `POST /draft/<session_pk>/undo/<commissioner_token>/`
- **Swap two picks**: `POST /draft/<session_pk>/swap/<commissioner_token>/` with `pick1_id` and `pick2_id`
- **Reset entire draft**: `POST /draft/<session_pk>/reset/<commissioner_token>/` — removes all picks and resets to SETUP; use only in emergencies

## Debugging draft state

```bash
# Check current session state
python manage.py shell -c "
from leagues.models import DraftSession
s = DraftSession.objects.latest('created_at')
print(s.state, s.current_pick, s.num_teams, s.num_rounds)
print('Picks made:', s.picks.count())
print('Teams:', [(t.team_name, t.draft_position) for t in s.teams.all()])
"
```

## Tests

Draft logic is tested in `leagues/test_draft.py`. Always run after any draft model/view changes:
```bash
python manage.py test leagues.test_draft --verbosity=2
```
