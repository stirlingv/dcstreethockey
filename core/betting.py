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

from collections import defaultdict
from math import exp

from leagues.models import MatchUp, Roster, Stat, Team_Stat

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

RECENT_GAMES = 5  # player-form window (most recent games)
FORM_WEIGHT = 0.4  # recent-form share of offensive estimate (vs season avg)
GOALIE_ADJ_WEIGHT = 0.5  # dampening on goalie GAA vs team-average adjustment
GOALIE_SUB_PENALTY = 1.5  # extra expected goals against when status is "Sub Needed"
LOGISTIC_SCALE = 0.7  # steepness of the win-probability sigmoid

# Standard vig applied to spread and total legs (informational only)
VIG = -110


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

        results[matchup.id] = {
            "away_spread": fmt_spread(away_spread),
            "home_spread": fmt_spread(home_spread),
            "total": f"{total_val:g}",
            "away_ml": fmt_american(away_ml),
            "home_ml": fmt_american(home_ml),
            "vig": fmt_american(VIG),
            "home_is_favorite": home_win_prob > 0.5,
        }

    return results
