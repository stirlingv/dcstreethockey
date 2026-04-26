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

from django.db.models import Count, Q, Sum

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

# How many of a player's most recent team games to use for recent-form scoring.
# The denominator is team games played (not inferred player appearances), so
# games where a player recorded no stats count as zeroes rather than absences.
PROP_HISTORY_GAMES = 10

# How much of the goalie quality factor flows through to scoring/point props.
# Goals are more directly goalie-dependent than assists, so the dampening
# differs between the two props.
PROP_GOAL_GOALIE_WEIGHT = 0.4
PROP_ASSIST_GOALIE_WEIGHT = 0.15
PROP_POINT_GOALIE_WEIGHT = 0.2

# Scoring probability multiplier when the opposing goalie status is "Sub Needed".
PROP_SUB_BOOST = 1.3

# Minimum team games in the current season before the goalie quality adjustment
# is applied.  A team's season GA average is meaningless with only 1–2 games
# played, so we skip the adjustment entirely until there is enough sample to
# produce a stable baseline.
PROP_GOALIE_MIN_TEAM_GAMES = 5

# Hard cap on per-game goal and point probabilities.  Elite scorers in this
# league top out around 80% of appearances.  The goalie-factor blowout risk
# (which motivated the earlier 0.72 cap) is already handled by
# PROP_GOALIE_MIN_TEAM_GAMES, so 0.80 is the honest ceiling here.
PROP_MAX_PROB = 0.80

# Shrinkage prior for player props.
#
# For goal probability we use a career-proportional prior (see below).
# For point probability we use a fixed phantom-game count.
#
# PROP_PRIOR_GAMES serves two roles:
#   • Fixed phantom-game count for the point-rate shrinkage (all players).
#   • Minimum phantom-game count for the goal-rate shrinkage (newcomers
#     with fewer than PROP_PRIOR_GAMES career appearances).
# Minimum phantom-game floor for prior strength; also the fixed phantom-game
# count used when anchoring the point-rate Bayesian blend.
PROP_PRIOR_GAMES = 5

# League-average baselines used when blending career rates toward the mean.
# PROP_PRIOR_GOAL_RATE is the league-average goals-per-team-game (GPG).
# PROP_PRIOR_POINT_RATE is the league-average points (goals+assists) per team-game.
PROP_PRIOR_GOAL_RATE = 0.30
PROP_PRIOR_ASSIST_RATE = 0.25
PROP_PRIOR_POINT_RATE = 0.55

# Division-specific league-average prior rates (goals/assists per team-game).
# Keys are Division.division integers (1=D1, 2=D2, 3=Draft, 4=Mon A, 5=Mon B).
# The PROP_PRIOR_* values above serve as fallback for any unrecognised division.
_DIVISION_PRIOR_GOAL_RATE: dict[int, float] = {
    1: 0.22,  # Sunday D1 — most competitive, fewest goals
    2: 0.30,  # Sunday D2
    3: 0.30,  # Wednesday Draft
    4: 0.32,  # Monday A
    5: 0.40,  # Monday B — recreational, highest scoring
}
_DIVISION_PRIOR_ASSIST_RATE: dict[int, float] = {
    1: 0.18,
    2: 0.25,
    3: 0.25,
    4: 0.26,
    5: 0.32,
}

# When a career season was played in a different division than the upcoming game,
# scale its recency weight by this factor.  Cross-division stats are informative
# but less predictive than same-division history.
PROP_CROSS_DIVISION_DECAY = 0.5

# Maximum phantom-game count for prior strength; caps how strongly career
# history resists a recent hot/cold streak.
PROP_CAREER_PRIOR_MAX_GAMES = 50

# Phantom games added when blending a player's career rate toward the league
# average.  Higher = more regression to the mean for players with thin histories.
CAREER_PRIOR_WEIGHT = 20

# Exponential recency decay applied across seasons when computing career priors.
# A value of 0.75 means last season counts 75% as much as the current season,
# two seasons ago counts 56%, etc.  Captures aging/improvement trends.
PROP_SEASON_DECAY = 0.75

# Fraction by which a player's career multi-point rate (games with ≥2 goals+assists)
# boosts their career prior.  A player with a 40% multi-point rate gets a
# 1 + 0.40 * 0.25 = 1.10 multiplier — reflecting elite scoring upside.
PROP_MULTI_POINT_BOOST = 0.25

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
    # Store Division.division (the integer 1–5) rather than the FK PK so that
    # comparisons against _DRAFT_DIVISION and the division-prior dicts are
    # unambiguous regardless of the auto-assigned PK order.
    team_info = {
        t.id: {
            "name": t.team_name,
            "division": t.division.division if t.division else None,
        }
        for t in Team.objects.filter(id__in=team_ids)
        .select_related("division")
        .only("id", "team_name", "division", "division__division")
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

    # Goals and points recorded per (player, matchup) in the recent window.
    # Missing keys mean 0 — the team-game window is the denominator, so games
    # where the player has no stat row count as zeroes, not absences.
    player_goal_totals: dict[tuple, int] = defaultdict(int)
    player_assist_totals: dict[tuple, int] = defaultdict(int)

    if all_window_ids:
        for row in Stat.objects.filter(
            player_id__in=all_player_ids,
            matchup_id__in=all_window_ids,
        ).values("player_id", "matchup_id", "goals", "assists"):
            key = (row["player_id"], row["matchup_id"])
            player_goal_totals[key] += row["goals"] or 0
            player_assist_totals[key] += row["assists"] or 0

    # ── 3d. Career prior: per-season production, recency-weighted ────────────
    #
    # Groups every Stat row by (player, team, season) to get per-season goal
    # and point totals.  Seasons are then weighted exponentially by recency
    # (most recent = 1.0, prior season = PROP_SEASON_DECAY, two seasons ago =
    # PROP_SEASON_DECAY^2, etc.) so that a player's recent productivity counts
    # more than their output from three seasons ago.
    #
    # The effective career rate is blended toward the league-average baseline
    # (PROP_PRIOR_GOAL_RATE / PROP_PRIOR_POINT_RATE) using CAREER_PRIOR_WEIGHT
    # phantom games, so players with thin histories stay close to the mean.
    #
    # Multi-point games (≥2 goals+assists in one game) signal elite upside that
    # isn't fully captured by averages alone; they apply a small multiplier.
    #
    # career_data[pid] = (career_gpg, career_ppp, prior_strength)
    career_season_rows = list(
        Stat.objects.filter(player_id__in=all_player_ids)
        .values(
            "player_id",
            "team_id",
            "team__season__year",
            "team__season__season_type",
            "team__division__division",  # integer 1–5; used for cross-division decay
        )
        .annotate(
            season_goals=Sum("goals"),
            season_assists=Sum("assists"),
            season_stat_games=Count("matchup_id", distinct=True),
            season_multi_pt=Count(
                "matchup_id",
                distinct=True,
                filter=(
                    Q(goals__gte=2)
                    | Q(assists__gte=2)
                    | Q(goals__gte=1, assists__gte=1)
                ),
            ),
        )
        .order_by(
            "player_id",
            "-team__season__year",
            "-team__season__season_type",
        )
    )

    # Team season game counts for all historical teams (reliable denominator).
    _career_team_ids = {row["team_id"] for row in career_season_rows}
    _career_team_games: dict[int, int] = {}
    for ts in Team_Stat.objects.filter(team_id__in=_career_team_ids):
        g = ts.win + ts.otw + ts.loss + ts.otl + ts.tie
        if g > 0:
            _career_team_games[ts.team_id] = g

    # Group seasons by player (query is already ordered by player_id).
    _player_seasons: dict[int, list] = defaultdict(list)
    for row in career_season_rows:
        _player_seasons[row["player_id"]].append(row)

    # career_data[(pid, division)] = (career_gpg, career_apg, prior_strength)
    #
    # Computed once per unique target division in the matchup set.  For each
    # target division, seasons played in a different division are weighted at
    # PROP_CROSS_DIVISION_DECAY of their normal recency weight — so a player's
    # D2 history still informs their D1 estimate, but at half the weight.  The
    # league-average prior also shifts per-division so that the regression-to-
    # mean anchor reflects typical scoring rates for that tier of competition.
    target_divisions = {team_info[m.hometeam_id]["division"] for m in matchups}

    career_data: dict[tuple, tuple] = {}
    for target_div in target_divisions:
        prior_goal = _DIVISION_PRIOR_GOAL_RATE.get(target_div, PROP_PRIOR_GOAL_RATE)
        prior_assist = _DIVISION_PRIOR_ASSIST_RATE.get(
            target_div, PROP_PRIOR_ASSIST_RATE
        )

        for pid, seasons in _player_seasons.items():
            # seasons ordered most-recent-first by the query above
            eff_goals = eff_assists = eff_games = eff_multi = 0.0
            total_stat_games = 0

            for i, s in enumerate(seasons):
                # Prefer Team_Stat game count; fall back to player's own stat-game
                # count if the historical team has no Team_Stat row.
                team_games = _career_team_games.get(
                    s["team_id"], s["season_stat_games"] or 0
                )
                if team_games == 0:
                    continue
                w = PROP_SEASON_DECAY**i
                # Seasons from a different division get a cross-division discount.
                if s["team__division__division"] != target_div:
                    w *= PROP_CROSS_DIVISION_DECAY
                eff_goals += w * (s["season_goals"] or 0)
                eff_assists += w * (s["season_assists"] or 0)
                eff_games += w * team_games
                eff_multi += w * (s["season_multi_pt"] or 0)
                total_stat_games += s["season_stat_games"] or 0

            if eff_games == 0:
                continue

            # Bayesian blend of recency-weighted career rates toward league average.
            career_gpg = (eff_goals + CAREER_PRIOR_WEIGHT * prior_goal) / (
                eff_games + CAREER_PRIOR_WEIGHT
            )
            career_apg = (eff_assists + CAREER_PRIOR_WEIGHT * prior_assist) / (
                eff_games + CAREER_PRIOR_WEIGHT
            )

            # Multi-point quality boost: players who regularly record 2+ stats/game
            # get a modest upward nudge, reflecting elite scoring upside.
            multi_rate = eff_multi / eff_games
            quality_mult = 1.0 + multi_rate * PROP_MULTI_POINT_BOOST
            career_gpg *= quality_mult
            career_apg *= quality_mult

            prior_strength = max(
                PROP_PRIOR_GAMES, min(total_stat_games, PROP_CAREER_PRIOR_MAX_GAMES)
            )
            career_data[(pid, target_div)] = (career_gpg, career_apg, prior_strength)

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
        # Require a minimum sample before trusting the season GA average as a
        # baseline.  With fewer games the average is too noisy to produce a
        # meaningful comparison against a goalie's career GAA.
        if games < PROP_GOALIE_MIN_TEAM_GAMES:
            return 1.0
        team_avg_ga = ts.goals_against / games
        return gaa / team_avg_ga if team_avg_ga > 0 else 1.0

    # ── Helper: props for one player ─────────────────────────────────────────
    def _player_props(
        pid: int, team_id: int, opp_goalie_factor: float, matchup_div: int
    ) -> dict | None:
        if team_info.get(team_id, {}).get("division") == _DRAFT_DIVISION:
            window = player_game_window.get(pid, [])
        else:
            window = game_window.get(team_id, [])

        # Players with no career history at all are excluded from props.
        career = career_data.get((pid, matchup_div))
        if career is None:
            return None
        career_gpg, career_apg, prior_strength = career

        # Recent form: sum actual goals and assists over all team-game window
        # entries.  Missing keys default to 0 — scoreless games and absent games
        # are both treated as zero, since we cannot reliably distinguish them.
        window_size = len(window)
        recent_goals = sum(player_goal_totals.get((pid, mid), 0) for mid in window)
        recent_assists = sum(player_assist_totals.get((pid, mid), 0) for mid in window)

        # Bayesian blend: anchor recent per-game rate to the career prior.
        # Goals use the full career prior_strength (up to 50 phantom games) —
        # goal-scoring is a stable individual skill. Assists use only
        # PROP_PRIOR_GAMES (5 phantom games) because assist rates are more
        # situational and line-mate-dependent, so recent form should dominate.
        denom_goal = window_size + prior_strength
        blended_gpg = (
            (recent_goals + prior_strength * career_gpg) / denom_goal
            if denom_goal
            else career_gpg
        )
        denom_assist = window_size + PROP_PRIOR_GAMES
        blended_apg = (
            (recent_assists + PROP_PRIOR_GAMES * career_apg) / denom_assist
            if denom_assist
            else career_apg
        )

        # Apply goalie quality factor as a rate multiplier in linear space
        # before the Poisson conversion, so the adjustment is proportional.
        adj_goal = 1.0 + (opp_goalie_factor - 1.0) * PROP_GOAL_GOALIE_WEIGHT
        adj_assist = 1.0 + (opp_goalie_factor - 1.0) * PROP_ASSIST_GOALIE_WEIGHT
        adj_gpg = max(0.0, blended_gpg * adj_goal)
        adj_apg = max(0.0, blended_apg * adj_assist)

        # Poisson: P(at least 1 goal/assist) = 1 − e^(−rate)
        # P(point) is derived from the same two processes — not blended separately —
        # so that P(point) = P(goal OR assist) is mathematically consistent:
        #   1 − e^(−GPG) × e^(−APG)  =  1 − e^(−(GPG + APG))
        p_goal = min(PROP_MAX_PROB, max(0.05, 1.0 - exp(-adj_gpg)))
        p_assist = min(PROP_MAX_PROB, max(0.05, 1.0 - exp(-adj_apg)))
        p_point = min(PROP_MAX_PROB, max(0.05, 1.0 - exp(-(adj_gpg + adj_apg))))

        return {
            "p_goal": p_goal,
            "p_assist": p_assist,
            "p_point": p_point,
            "goal_odds": fmt_american(win_prob_to_american(p_goal)),
            "assist_odds": fmt_american(win_prob_to_american(p_assist)),
            "point_odds": fmt_american(win_prob_to_american(p_point)),
            "games": window_size,
        }

    # ── Build props per matchup ───────────────────────────────────────────────
    prop_results: dict = {}

    for matchup in matchups:
        # Both teams in a matchup are always in the same division.
        matchup_div = team_info[matchup.hometeam_id]["division"]

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
                p = _player_props(pid, team_id, home_goalie_factor, matchup_div)
                abbr = home_abbr
            elif team_id == matchup.awayteam_id:
                p = _player_props(pid, team_id, away_goalie_factor, matchup_div)
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

        # Three independent sorts — one per prop type, matching the DraftKings /
        # FanDuel convention of separate markets for Goal, Assist, and Point.
        _prob_keys = {"p_goal", "p_assist", "p_point"}

        def _strip(player):
            return {k: v for k, v in player.items() if k not in _prob_keys}

        by_goal = [
            _strip(p)
            for p in sorted(all_players, key=lambda x: x["p_goal"], reverse=True)
        ]
        by_assist = [
            _strip(p)
            for p in sorted(all_players, key=lambda x: x["p_assist"], reverse=True)
        ]
        by_point = [
            _strip(p)
            for p in sorted(all_players, key=lambda x: x["p_point"], reverse=True)
        ]

        prop_results[matchup.id] = {
            "by_goal": by_goal,
            "by_assist": by_assist,
            "by_point": by_point,
            "total": len(all_players),
        }

    return prop_results
