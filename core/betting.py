"""
Betting lines computation for upcoming matchups.

Blends current-season team statistics with individual player recent form and
goalie goals-against average to produce spread, total (over/under), and
American-format moneyline odds.

Algorithm overview:
  1. Team offensive rating = 60% season goals-for/game + 40% recent player
     goals+assists/game (last RECENT_GAMES games across the roster).
  2. Team defensive proxy = season goals-against/game (lower is better).
  3. Expected goals for each side = (own offense + opponent defense) / 2.
  4. Goalie adjustment: if a confirmed goalie's career GAA differs from the
     team's season average, shift the opponent's expected goals proportionally
     (dampened by GOALIE_ADJ_WEIGHT).  A "Sub Needed" status adds a flat
     GOALIE_SUB_PENALTY to the opponent's expected goals.
  5. Moneyline derived from a logistic sigmoid on the expected goal differential.
  6. Spread = expected goal differential rounded to the nearest 0.5.
  7. Total = sum of both sides' expected goals rounded to the nearest 0.5.

All output is FOR ENTERTAINMENT PURPOSES ONLY.
"""

import datetime
from collections import defaultdict
from math import exp

from django.db.models import Q

from leagues.models import MatchUp, Roster, Stat, Team, Team_Stat

# ---------------------------------------------------------------------------
# Tuning constants — game lines
# ---------------------------------------------------------------------------

RECENT_GAMES = 5  # player-form window (most recent games)
FORM_WEIGHT = 0.4  # recent-form share of offensive estimate (vs season avg)
GOALIE_ADJ_WEIGHT = 0.5  # dampening on goalie GAA vs team-average adjustment
GOALIE_SUB_PENALTY = 1.5  # extra expected goals against when status is "Sub Needed"
LOGISTIC_SCALE = 0.7  # steepness of the win-probability sigmoid

# Minimum probability used for the regulation-draw outcome in the 3-way line.
# Ensures the draw market is always shown even when teams have no recorded OT
# games in the sample (which would otherwise imply a 0% draw probability).
THREEWAY_MIN_DRAW_PROB = 0.15

# Standard vig applied to spread and total legs (informational only)
VIG = -110

# ---------------------------------------------------------------------------
# Tuning constants — player props
# ---------------------------------------------------------------------------

# Minimum games played before a player prop is shown.
# 1 means any player with at least one recorded game qualifies; the shrinkage
# prior handles statistical uncertainty from small samples.
PROP_MIN_GAMES = 1

# How many of a player's most recent games (spanning seasons on the same team
# name) to use when computing scoring/point frequency for props.
PROP_HISTORY_GAMES = 10

# How much of the goalie quality factor flows through to scoring/point props.
# Goals are more directly goalie-dependent than assists, so the dampening
# differs between the two props.
PROP_GOAL_GOALIE_WEIGHT = 0.4
PROP_POINT_GOALIE_WEIGHT = 0.2

# Scoring probability multiplier when the opposing goalie status is "Sub Needed".
PROP_SUB_BOOST = 1.3

# Shrinkage prior for player props.
# We blend each player's observed scoring frequency with PROP_PRIOR_GAMES
# "phantom" games played at the baseline rate. This prevents small samples
# from producing extreme probabilities (e.g. 5-for-5 → raw 100% → -1900).
# A player going 5/5 on goals instead shows ~-167; 10/10 shows ~-300.
# The prior rates are conservative baselines for a high-scoring floor hockey
# league; goals are less frequent than points (assists inflate point rate).
PROP_PRIOR_GAMES = 5
PROP_PRIOR_GOAL_RATE = 0.25  # ~25% of games with ≥1 goal as baseline prior
PROP_PRIOR_POINT_RATE = 0.40  # ~40% of games with ≥1 point as baseline prior

# Wednesday Draft League division ID. Each draft season uses entirely new
# teams, so cross-season lookback must follow the player's roster history
# rather than spanning by team name.
_DRAFT_DIVISION = 3

# Position abbreviations for non-goalie positions.
_POS_LABELS = {1: "C", 2: "W", 3: "D"}


# ---------------------------------------------------------------------------
# Math / formatting helpers
# ---------------------------------------------------------------------------


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + exp(-x))


def _round_half(x: float) -> float:
    """Round to the nearest 0.5."""
    return round(x * 2) / 2


def win_prob_to_american(prob: float) -> int:
    """Convert a win probability in [0, 1] to an American moneyline integer."""
    prob = max(0.01, min(0.99, prob))
    if prob >= 0.5:
        return round(-100 * prob / (1.0 - prob))
    return round(100 * (1.0 - prob) / prob)


def fmt_american(odds: int) -> str:
    """Format an American moneyline for display (e.g. -150, +130)."""
    return f"+{odds}" if odds > 0 else str(odds)


def fmt_spread(value: float) -> str:
    """Format a spread value for display (e.g. -1.5, +1.5, PK)."""
    if value == 0.0:
        return "PK"
    if value > 0:
        return f"+{value:g}"
    return f"{value:g}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_betting_lines_for_matchups(matchup_ids: list) -> dict:
    """
    Given a list of MatchUp PKs for upcoming games, return a dict keyed by
    matchup ID.  Each value is either None (insufficient data) or a dict:

        {
            "away_spread":      "+1.5",
            "home_spread":      "-1.5",
            "total":            "7.5",
            "away_ml":          "+130",
            "home_ml":          "-150",
            "vig":              "-110",
            "home_is_favorite": True,
        }
    """
    if not matchup_ids:
        return {}

    matchups = list(
        MatchUp.objects.filter(id__in=matchup_ids).select_related(
            "hometeam",
            "awayteam",
            "home_goalie",
            "away_goalie",
        )
    )

    team_ids = set()
    for m in matchups:
        team_ids.add(m.hometeam_id)
        team_ids.add(m.awayteam_id)

    # ── 1. Team season stats (one query) ────────────────────────────────────
    # Team_Stat has one row per (team, season, division). Pick the most recent
    # season per team by ordering descending and taking the first per team.
    team_stats: dict[int, Team_Stat] = {}
    for ts in (
        Team_Stat.objects.filter(team_id__in=team_ids)
        .select_related("season")
        .order_by("team_id", "-season__year", "-season__season_type")
    ):
        if ts.team_id not in team_stats:
            team_stats[ts.team_id] = ts

    # ── 2. Rosters — non-substitute players (one query) ─────────────────────
    rosters_by_team: dict[int, list] = defaultdict(list)
    goalie_ids_by_team: dict[int, list] = defaultdict(list)
    all_player_ids: list = []

    for r in Roster.objects.filter(team_id__in=team_ids, is_substitute=False):
        rosters_by_team[r.team_id].append(r.player_id)
        if r.position1 == 4:  # Goalie position
            goalie_ids_by_team[r.team_id].append(r.player_id)
        all_player_ids.append(r.player_id)

    # ── 3. Recent player stats (one query) ───────────────────────────────────
    # Fetch all historical stat rows for these players on these teams, newest
    # first.  We'll cap each (player, team) pair to RECENT_GAMES in Python.
    raw_stats = list(
        Stat.objects.filter(
            player_id__in=all_player_ids,
            team_id__in=team_ids,
        )
        .values(
            "player_id",
            "team_id",
            "goals",
            "assists",
            "matchup__week__date",
        )
        .order_by("player_id", "team_id", "-matchup__week__date")
    )

    player_team_stats: dict[tuple, list] = defaultdict(list)
    for row in raw_stats:
        key = (row["player_id"], row["team_id"])
        if len(player_team_stats[key]) < RECENT_GAMES:
            player_team_stats[key].append(row)

    # ── 4. Goalie career stats for GAA (one query) ───────────────────────────
    all_goalie_ids = [gid for gids in goalie_ids_by_team.values() for gid in gids]
    goalie_ga: dict[int, int] = defaultdict(int)
    goalie_games: dict[int, int] = defaultdict(int)

    for row in Stat.objects.filter(player_id__in=all_goalie_ids).values(
        "player_id", "matchup_id", "goals_against"
    ):
        if row["matchup_id"] is not None and row["goals_against"] is not None:
            goalie_ga[row["player_id"]] += row["goals_against"]
            goalie_games[row["player_id"]] += 1

    # ── Helper: goalie GAA ────────────────────────────────────────────────────
    def _goalie_gaa(player_id) -> float | None:
        games = goalie_games.get(player_id, 0)
        if games == 0:
            return None
        return goalie_ga[player_id] / games

    # ── Helper: blended team offensive estimate ───────────────────────────────
    def _team_metrics(team_id: int):
        ts = team_stats.get(team_id)
        if ts is None:
            return None
        games = ts.win + ts.otw + ts.loss + ts.otl + ts.tie
        if games == 0:
            return None

        season_gf_pg = ts.goals_for / games
        season_ga_pg = ts.goals_against / games

        # Sum recent non-goalie points across roster, normalize to goals/game
        total_pts = 0
        total_game_slots = 0
        goalie_ids = set(goalie_ids_by_team[team_id])
        for pid in rosters_by_team[team_id]:
            if pid in goalie_ids:
                continue
            rows = player_team_stats.get((pid, team_id), [])
            if rows:
                total_pts += sum((r["goals"] or 0) + (r["assists"] or 0) for r in rows)
                total_game_slots += len(rows)

        recent_gf_pg = (
            total_pts / total_game_slots if total_game_slots else season_gf_pg
        )

        blended_gf = (1 - FORM_WEIGHT) * season_gf_pg + FORM_WEIGHT * recent_gf_pg

        return {
            "gf": blended_gf,
            "ga": season_ga_pg,
            "games": games,
        }

    # ── Helper: apply goalie adjustment to expected goals against ─────────────
    def _goalie_adjustment(
        goalie_status: int, goalie_id, team_id: int, exp_against: float
    ) -> float:
        if goalie_status == 2:  # Sub Needed
            return exp_against + GOALIE_SUB_PENALTY

        # Resolve which goalie to use
        gid = goalie_id
        if gid is None:
            gids = goalie_ids_by_team.get(team_id, [])
            gid = gids[0] if gids else None
        if gid is None:
            return exp_against

        gaa = _goalie_gaa(gid)
        if gaa is None:
            return exp_against

        ts = team_stats.get(team_id)
        if ts is None:
            return exp_against
        games = ts.win + ts.otw + ts.loss + ts.otl + ts.tie
        team_avg_ga = ts.goals_against / games if games else gaa

        # Positive adjustment: better-than-average goalie suppresses opponent scoring
        adj = (team_avg_ga - gaa) * GOALIE_ADJ_WEIGHT
        return max(0.0, exp_against - adj)

    # ── Compute lines per matchup ─────────────────────────────────────────────
    results: dict = {}

    for matchup in matchups:
        home_m = _team_metrics(matchup.hometeam_id)
        away_m = _team_metrics(matchup.awayteam_id)

        if home_m is None or away_m is None:
            results[matchup.id] = None
            continue

        # Expected goals: each team's blended offense vs opponent's season defense
        home_exp = (home_m["gf"] + away_m["ga"]) / 2.0
        away_exp = (away_m["gf"] + home_m["ga"]) / 2.0

        # Apply goalie adjustments (home goalie affects away's expected scoring)
        away_exp = _goalie_adjustment(
            matchup.home_goalie_status,
            matchup.home_goalie_id,
            matchup.hometeam_id,
            away_exp,
        )
        home_exp = _goalie_adjustment(
            matchup.away_goalie_status,
            matchup.away_goalie_id,
            matchup.awayteam_id,
            home_exp,
        )

        home_exp = max(0.0, home_exp)
        away_exp = max(0.0, away_exp)

        # Spread (home-team perspective: negative = home favored)
        diff = home_exp - away_exp
        home_spread = -_round_half(diff)
        away_spread = -home_spread

        # Total
        total_val = _round_half(home_exp + away_exp)

        # Moneyline
        home_win_prob = _sigmoid(diff * LOGISTIC_SCALE)
        home_ml = win_prob_to_american(home_win_prob)
        away_ml = win_prob_to_american(1.0 - home_win_prob)

        # 3-way (60-min) line: home win / draw (goes to OT) / away win, all
        # measured at the end of regulation only.
        #
        # P(draw at regulation) is estimated from each team's historical OT
        # rate — the fraction of games they played that went to extra time.
        # A floor (THREEWAY_MIN_DRAW_PROB) prevents a 0% draw market when a
        # team has no OT games in the sample.
        #
        # Relationship to the 2-way moneyline (which includes OT):
        #   P(home 2-way win) = P(home reg win) + P(draw) * 0.5
        # → P(home reg win) = home_win_prob − p_d / 2
        # → P(away reg win) = (1 − home_win_prob) − p_d / 2
        # After clamping negatives, the three values are renormalized to 1.
        home_ts = team_stats.get(matchup.hometeam_id)
        away_ts = team_stats.get(matchup.awayteam_id)
        home_ot_rate = (
            (home_ts.otw + home_ts.otl + home_ts.tie) / home_m["games"]
            if home_ts
            else 0.0
        )
        away_ot_rate = (
            (away_ts.otw + away_ts.otl + away_ts.tie) / away_m["games"]
            if away_ts
            else 0.0
        )
        p_d = max(THREEWAY_MIN_DRAW_PROB, (home_ot_rate + away_ot_rate) / 2)

        p_home_3 = max(0.05, home_win_prob - p_d / 2)
        p_away_3 = max(0.05, (1.0 - home_win_prob) - p_d / 2)
        total_3 = p_home_3 + p_away_3 + p_d
        p_home_3 /= total_3
        p_away_3 /= total_3
        p_d /= total_3

        results[matchup.id] = {
            "away_spread": fmt_spread(away_spread),
            "home_spread": fmt_spread(home_spread),
            "total": f"{total_val:g}",
            "away_ml": fmt_american(away_ml),
            "home_ml": fmt_american(home_ml),
            "vig": fmt_american(VIG),
            "home_is_favorite": home_win_prob > 0.5,
            "home_3way": fmt_american(win_prob_to_american(p_home_3)),
            "away_3way": fmt_american(win_prob_to_american(p_away_3)),
            "draw_3way": fmt_american(win_prob_to_american(p_d)),
        }

    return results


# ---------------------------------------------------------------------------
# Player props
# ---------------------------------------------------------------------------


def _team_abbr(team_name: str) -> str:
    """
    Derive a short team abbreviation for display in player prop rows.
    Single-word names: first 3 chars ('Fury' → 'FUR').
    Multi-word names: initials up to 3 chars ('Group Therapy' → 'GT').
    """
    words = team_name.split()
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words if w)[:3].upper()


def compute_player_props_for_matchups(matchup_ids: list) -> dict:
    """
    Compute anytime goal scorer and anytime point scorer props for every
    non-goalie, non-substitute rostered player in the given matchups.

    Base probabilities come from each player's full current-team history:
      p_goal  = games where player scored ≥1 goal  / games played
      p_point = games where player recorded ≥1 point / games played

    Both are adjusted for the opposing goalie's quality relative to their
    team's season average GA.  Goals are adjusted more aggressively than
    points because assists are less goalie-dependent.

    Players from both teams are merged into two flat lists — one per prop
    type — matching the DraftKings/FanDuel convention of organizing by bet
    type rather than by team.  Each list is independently sorted so the
    best candidates for that specific prop appear first.

    Returns a dict keyed by matchup_id:
        {
            "by_goal":  [               # sorted by p_goal descending
                {
                    "name":       "Jane Smith",
                    "pos":        "C",
                    "team_abbr":  "MAN",
                    "goal_odds":  "+320",
                    "point_odds": "-115",
                    "games":      9,
                },
                ...
            ],
            "by_point": [ ... ],        # same players, sorted by p_point descending
            "total":    14,             # total qualifying players across both teams
        }
    Returns None for a matchup if no qualifying players exist on either side.
    """
    if not matchup_ids:
        return {}

    matchups = list(
        MatchUp.objects.filter(id__in=matchup_ids).select_related(
            "hometeam", "awayteam", "home_goalie", "away_goalie"
        )
    )

    team_ids = set()
    for m in matchups:
        team_ids.add(m.hometeam_id)
        team_ids.add(m.awayteam_id)

    # ── 1. Rosters: non-sub players with names (one query) ───────────────────
    # Goalies tracked separately; non-goalie positions collected for props.
    goalie_ids_by_team: dict[int, list] = defaultdict(list)
    all_player_ids: list = []
    # (player_id, team_id, first_name, last_name, pos_label)
    roster_entries: list[tuple] = []

    for r in (
        Roster.objects.filter(team_id__in=team_ids, is_substitute=False)
        .select_related("player")
        .order_by("team_id", "player__last_name", "player__first_name")
    ):
        all_player_ids.append(r.player_id)
        if r.position1 == 4:
            goalie_ids_by_team[r.team_id].append(r.player_id)
        else:
            roster_entries.append(
                (
                    r.player_id,
                    r.team_id,
                    r.player.first_name,
                    r.player.last_name,
                    _POS_LABELS.get(r.position1, "?"),
                )
            )

    # ── 2. Team season stats for goalie baseline (one query) ─────────────────
    team_stats: dict[int, Team_Stat] = {}
    for ts in (
        Team_Stat.objects.filter(team_id__in=team_ids)
        .select_related("season")
        .order_by("team_id", "-season__year", "-season__season_type")
    ):
        if ts.team_id not in team_stats:
            team_stats[ts.team_id] = ts

    # ── 3a. Team division + name info ────────────────────────────────────────
    team_info = {
        t.id: {"name": t.team_name, "division": t.division_id}
        for t in Team.objects.filter(id__in=team_ids)
        .select_related("division")
        .only("id", "team_name", "division")
    }

    # ── 3b. Build a PROP_HISTORY_GAMES game window per (player, current_team).
    #
    # The denominator for scoring frequency is the number of games the *team*
    # played (not the number of games the player has a stat row), so that a
    # player who was absent for a game is correctly counted as 0 that night.
    #
    # Non-draft leagues: teams keep the same name across seasons, so we span
    # by team name (Iced Out 2025, Iced Out 2026 → same franchise window).
    #
    # Wednesday Draft League (division 3): teams are completely new each
    # season, so we follow each player's own roster history across seasons
    # and use whichever team they were on in each prior draft season.
    today = datetime.date.today()

    # game_window[current_team_id] = ordered list of last N matchup IDs
    # (used for non-draft teams; all players on that team share the window)
    game_window: dict[int, list] = {}

    # player_game_window[player_id] = ordered list of last N matchup IDs
    # (used for draft players; each player has their own cross-season window)
    player_game_window: dict[int, list] = {}

    # ── Non-draft: find all historical team IDs with the same name ───────────
    non_draft_ids = {
        tid for tid in team_ids if team_info[tid]["division"] != _DRAFT_DIVISION
    }
    non_draft_names = {team_info[tid]["name"] for tid in non_draft_ids}
    name_to_current_id = {team_info[tid]["name"]: tid for tid in non_draft_ids}

    current_to_historical: dict[int, set] = defaultdict(set)
    for ht in Team.objects.filter(team_name__in=non_draft_names).only(
        "id", "team_name"
    ):
        current_id = name_to_current_id.get(ht.team_name)
        if current_id:
            current_to_historical[current_id].add(ht.id)

    for current_id in non_draft_ids:
        hist_ids = current_to_historical[current_id]
        window = list(
            MatchUp.objects.filter(
                Q(hometeam_id__in=hist_ids) | Q(awayteam_id__in=hist_ids),
                week__date__lt=today,
            )
            .order_by("-week__date")
            .values_list("id", flat=True)[:PROP_HISTORY_GAMES]
        )
        game_window[current_id] = window

    # ── Draft: per-player window from roster history across seasons ──────────
    draft_player_ids = {
        pid
        for pid, tid, *_ in roster_entries
        if team_info.get(tid, {}).get("division") == _DRAFT_DIVISION
    }

    if draft_player_ids:
        # Find all draft rosters for these players across all seasons
        player_draft_teams: dict[int, list] = defaultdict(list)
        for r in (
            Roster.objects.filter(
                player_id__in=draft_player_ids,
                team__division__division=_DRAFT_DIVISION,
                is_substitute=False,
            )
            .select_related("team__season")
            .order_by("-team__season__year", "-team__season__season_type")
        ):
            player_draft_teams[r.player_id].append(r.team_id)

        # Fetch regular-season matchups for every draft team the players have
        # been on. Championships are excluded — they're a different format and
        # skew the scoring frequency (often against tougher opponents).
        all_draft_hist_ids = {
            tid for tids in player_draft_teams.values() for tid in tids
        }
        draft_matchups_by_team: dict[int, list] = defaultdict(list)
        for m in (
            MatchUp.objects.filter(
                Q(hometeam_id__in=all_draft_hist_ids)
                | Q(awayteam_id__in=all_draft_hist_ids),
                week__date__lt=today,
                is_championship=False,
            )
            .order_by("-week__date")
            .values("id", "hometeam_id", "awayteam_id")
        ):
            for side in ("hometeam_id", "awayteam_id"):
                tid = m[side]
                if tid in all_draft_hist_ids:
                    draft_matchups_by_team[tid].append(m["id"])

        for pid in draft_player_ids:
            window: list = []
            seen: set = set()
            for team_id in player_draft_teams.get(pid, []):
                for mid in draft_matchups_by_team.get(team_id, []):
                    if mid not in seen:
                        seen.add(mid)
                        window.append(mid)
                    if len(window) >= PROP_HISTORY_GAMES:
                        break
                if len(window) >= PROP_HISTORY_GAMES:
                    break
            player_game_window[pid] = window

    # ── 3c. Fetch player stats for all window matchups (one query) ────────────
    all_window_ids: set = set()
    for mids in game_window.values():
        all_window_ids.update(mids)
    for mids in player_game_window.values():
        all_window_ids.update(mids)

    # Index by (player_id, matchup_id) for O(1) lookup in _player_props
    player_had_goal: dict[tuple, bool] = {}
    player_had_point: dict[tuple, bool] = {}
    player_appeared: set = set()  # (player_id, matchup_id) pairs with any stat row

    if all_window_ids:
        for row in Stat.objects.filter(
            player_id__in=all_player_ids,
            matchup_id__in=all_window_ids,
        ).values("player_id", "matchup_id", "goals", "assists"):
            key = (row["player_id"], row["matchup_id"])
            goals = row["goals"] or 0
            assists = row["assists"] or 0
            player_appeared.add(key)
            player_had_goal[key] = goals > 0
            player_had_point[key] = goals > 0 or assists > 0

    # ── 4. Goalie career stats for GAA (one query) ───────────────────────────
    all_goalie_ids = [gid for gids in goalie_ids_by_team.values() for gid in gids]
    _prop_goalie_ga: dict[int, int] = defaultdict(int)
    _prop_goalie_games: dict[int, int] = defaultdict(int)

    for row in Stat.objects.filter(player_id__in=all_goalie_ids).values(
        "player_id", "matchup_id", "goals_against"
    ):
        if row["matchup_id"] is not None and row["goals_against"] is not None:
            _prop_goalie_ga[row["player_id"]] += row["goals_against"]
            _prop_goalie_games[row["player_id"]] += 1

    def _prop_goalie_gaa(gid) -> float | None:
        g = _prop_goalie_games.get(gid, 0)
        return _prop_goalie_ga[gid] / g if g else None

    # ── Helper: goalie quality factor relative to team average ───────────────
    # Returns >1 if goalie is worse than average (easier to score against),
    # <1 if better (harder to score against), 1.0 if unknown.
    def _goalie_factor(goalie_status: int, goalie_id, defending_team_id: int) -> float:
        if goalie_status == 2:  # Sub Needed
            return PROP_SUB_BOOST

        gid = goalie_id
        if gid is None:
            gids = goalie_ids_by_team.get(defending_team_id, [])
            gid = gids[0] if gids else None
        if gid is None:
            return 1.0

        gaa = _prop_goalie_gaa(gid)
        if gaa is None:
            return 1.0

        ts = team_stats.get(defending_team_id)
        if ts is None:
            return 1.0
        games = ts.win + ts.otw + ts.loss + ts.otl + ts.tie
        if games == 0:
            return 1.0
        team_avg_ga = ts.goals_against / games
        return gaa / team_avg_ga if team_avg_ga > 0 else 1.0

    # ── Helper: props for one player ─────────────────────────────────────────
    def _player_props(pid: int, team_id: int, opp_goalie_factor: float) -> dict | None:
        # Use draft-specific per-player window or shared non-draft team window.
        if team_info.get(team_id, {}).get("division") == _DRAFT_DIVISION:
            window = player_game_window.get(pid, [])
        else:
            window = game_window.get(team_id, [])

        # Denominator = games the *team* played in the window.
        # A game where the player was absent counts as 0 goals/assists.
        total = len(window)

        # Numerator = games where the player actually appeared (has a stat row).
        # Must meet minimum before showing a prop.
        appearances = sum(1 for mid in window if (pid, mid) in player_appeared)
        if appearances < PROP_MIN_GAMES:
            return None

        goal_count = sum(1 for mid in window if player_had_goal.get((pid, mid), False))
        point_count = sum(
            1 for mid in window if player_had_point.get((pid, mid), False)
        )

        # Shrinkage: blend observed rate with a conservative prior to prevent
        # extreme probabilities from small samples.
        smoothed_total = total + PROP_PRIOR_GAMES
        p_goal_raw = (
            goal_count + PROP_PRIOR_GAMES * PROP_PRIOR_GOAL_RATE
        ) / smoothed_total
        p_point_raw = (
            point_count + PROP_PRIOR_GAMES * PROP_PRIOR_POINT_RATE
        ) / smoothed_total

        # Dampen the goalie factor before applying.
        # Assists depend less on goalie quality than goals do.
        adj_goal = 1 + (opp_goalie_factor - 1) * PROP_GOAL_GOALIE_WEIGHT
        adj_point = 1 + (opp_goalie_factor - 1) * PROP_POINT_GOALIE_WEIGHT

        p_goal = min(0.85, max(0.05, p_goal_raw * adj_goal))
        p_point = min(0.85, max(0.05, p_point_raw * adj_point))

        return {
            "p_goal": p_goal,
            "p_point": p_point,
            "goal_odds": fmt_american(win_prob_to_american(p_goal)),
            "point_odds": fmt_american(win_prob_to_american(p_point)),
            "games": appearances,
        }

    # ── Build props per matchup ───────────────────────────────────────────────
    prop_results: dict = {}

    for matchup in matchups:
        # Away players score against the home goalie; home players vs away goalie.
        away_goalie_factor = _goalie_factor(
            matchup.home_goalie_status, matchup.home_goalie_id, matchup.hometeam_id
        )
        home_goalie_factor = _goalie_factor(
            matchup.away_goalie_status, matchup.away_goalie_id, matchup.awayteam_id
        )

        home_abbr = _team_abbr(matchup.hometeam.team_name)
        away_abbr = _team_abbr(matchup.awayteam.team_name)

        # Collect all qualifying players from both teams into one flat list.
        # Each entry retains p_goal and p_point for sorting; they are stripped
        # before the result is returned.
        all_players: list = []

        for pid, team_id, first, last, pos in roster_entries:
            if team_id == matchup.hometeam_id:
                p = _player_props(pid, team_id, home_goalie_factor)
                abbr = home_abbr
            elif team_id == matchup.awayteam_id:
                p = _player_props(pid, team_id, away_goalie_factor)
                abbr = away_abbr
            else:
                continue
            if p:
                all_players.append(
                    {"name": f"{first} {last}", "pos": pos, "team_abbr": abbr, **p}
                )

        if not all_players:
            prop_results[matchup.id] = None
            continue

        # Two independent sorts — one per prop type, matching the DraftKings
        # convention of separate sections for each bet type.
        def _strip(player):
            return {k: v for k, v in player.items() if k not in ("p_goal", "p_point")}

        by_goal = [
            _strip(p)
            for p in sorted(all_players, key=lambda x: x["p_goal"], reverse=True)
        ]
        by_point = [
            _strip(p)
            for p in sorted(all_players, key=lambda x: x["p_point"], reverse=True)
        ]

        prop_results[matchup.id] = {
            "by_goal": by_goal,
            "by_point": by_point,
            "total": len(all_players),
        }

    return prop_results
