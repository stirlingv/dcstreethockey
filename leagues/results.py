"""
Game results, and the standings computed from them.

For a season with ``standings_from_games`` set, each team's record in
``Team_Stat`` is a cache rebuilt from its games: the score comes from the
player stats entered for the game, the overtime flag and the shootout winner
come from the game itself. Nothing is typed in twice, re-saving a game never
double-counts, and cancelling or deleting a game takes it straight back out
of the standings.

Seasons kept by hand (every season before Fall 2026) are left exactly as
they were: ``recompute_team_stats`` does nothing for them.
"""

import threading
from contextlib import contextmanager
from dataclasses import dataclass

from django.db.models import Sum

from leagues.models import MatchUp, Season, Stat, Team, Team_Stat, Week


@dataclass(frozen=True)
class GameResult:
    home_goals: int
    away_goals: int
    winner_id: int
    loser_id: int
    overtime: bool
    shootout: bool

    @property
    def winner_is_home(self):
        return self.winner_id == self.home_id

    # Set by game_result(); kept out of the dataclass fields so equality
    # compares the outcome only.
    home_id: int = 0


def goals_for_matchup(matchup):
    """(home goals, away goals) from the player stats entered for the game."""
    totals = {
        row["team_id"]: row["total"] or 0
        for row in Stat.objects.filter(matchup=matchup)
        .values("team_id")
        .annotate(total=Sum("goals"))
    }
    return totals.get(matchup.hometeam_id, 0), totals.get(matchup.awayteam_id, 0)


def game_result(matchup, home_goals, away_goals):
    """The result of a game, or None when the score is tied and no shootout
    winner has been recorded (the game is undecided as far as the standings
    are concerned)."""
    shootout = matchup.shootout_winner_is_home is not None
    if home_goals > away_goals:
        winner, loser = matchup.hometeam_id, matchup.awayteam_id
    elif away_goals > home_goals:
        winner, loser = matchup.awayteam_id, matchup.hometeam_id
    elif shootout:
        if matchup.shootout_winner_is_home:
            winner, loser = matchup.hometeam_id, matchup.awayteam_id
        else:
            winner, loser = matchup.awayteam_id, matchup.hometeam_id
    else:
        return None
    return GameResult(
        home_goals=home_goals,
        away_goals=away_goals,
        winner_id=winner,
        loser_id=loser,
        overtime=bool(matchup.went_to_overtime) or shootout,
        shootout=shootout,
        home_id=matchup.hometeam_id,
    )


def tied_without_shootout_message(home_name, away_name, home_goals, away_goals):
    """The plain-language reason a tied game can't be saved yet."""
    return (
        f"Goals are tied {home_goals}-{away_goals} ({home_name} {home_goals}, "
        f"{away_name} {away_goals}). Tick “went to OT / shootout” and "
        "pick who won the shootout, or fix the goals above."
    )


def standings_from_games(season):
    """True when this season's records are computed rather than typed in."""
    return bool(season and season.standings_from_games)


# ---------------------------------------------------------------------------
# Recompute
# ---------------------------------------------------------------------------

_state = threading.local()


@contextmanager
def standings_recompute_deferred():
    """Collapse the recomputes triggered inside the block into one per
    season/division, run when the block exits. Saving a game touches dozens
    of stat rows, each of which would otherwise rebuild the standings."""
    if getattr(_state, "pending", None) is not None:
        yield
        return
    _state.pending = set()
    try:
        yield
    finally:
        pending, _state.pending = _state.pending, None
    for season_id, division_id in pending:
        recompute_team_stats(season_id, division_id)


def recompute_for_week_id(week_id):
    pair = (
        Week.objects.filter(pk=week_id).values_list("season_id", "division_id").first()
    )
    if pair:
        recompute_team_stats(*pair)


def recompute_team_stats(season_id, division_id):
    """Rebuild every team's record for one season and division from its
    games. Does nothing for seasons whose records are kept by hand."""
    if season_id is None or division_id is None:
        return
    pending = getattr(_state, "pending", None)
    if pending is not None:
        pending.add((season_id, division_id))
        return
    season = Season.objects.filter(pk=season_id).first()
    if not standings_from_games(season):
        return

    matchups = list(
        MatchUp.objects.filter(
            week__season_id=season_id,
            week__division_id=division_id,
            is_cancelled=False,
            is_postseason=False,
        ).exclude(week__is_cancelled=True)
    )
    goals = {
        (row["matchup_id"], row["team_id"]): row["total"] or 0
        for row in Stat.objects.filter(matchup__in=matchups)
        .values("matchup_id", "team_id")
        .annotate(total=Sum("goals"))
    }

    team_ids = set(
        Team.objects.filter(season_id=season_id, division_id=division_id).values_list(
            "pk", flat=True
        )
    )
    for m in matchups:
        team_ids.update((m.hometeam_id, m.awayteam_id))

    tally = {
        tid: {
            "win": 0,
            "otw": 0,
            "loss": 0,
            "otl": 0,
            "goals_for": 0,
            "goals_against": 0,
        }
        for tid in team_ids
    }
    for m in matchups:
        home_goals = goals.get((m.pk, m.hometeam_id), 0)
        away_goals = goals.get((m.pk, m.awayteam_id), 0)
        tally[m.hometeam_id]["goals_for"] += home_goals
        tally[m.hometeam_id]["goals_against"] += away_goals
        tally[m.awayteam_id]["goals_for"] += away_goals
        tally[m.awayteam_id]["goals_against"] += home_goals
        result = game_result(m, home_goals, away_goals)
        if result is None:
            continue
        if result.overtime:
            tally[result.winner_id]["otw"] += 1
            tally[result.loser_id]["otl"] += 1
        else:
            tally[result.winner_id]["win"] += 1
            tally[result.loser_id]["loss"] += 1

    for team_id, record in tally.items():
        rows = list(
            Team_Stat.objects.filter(
                team_id=team_id, season_id=season_id, division_id=division_id
            ).order_by("pk")
        )
        if rows:
            row = rows[0]
            for dup in rows[1:]:
                dup.delete()
        else:
            row = Team_Stat(
                team_id=team_id, season_id=season_id, division_id=division_id
            )
        changed = not row.pk or row.tie != 0
        for field, value in record.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed = True
        row.tie = 0
        if changed:
            row.save()
