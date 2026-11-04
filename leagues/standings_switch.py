"""
Moving a hand-kept season onto standings computed from its games.

A hand-kept season asks for each result twice: the score goes in as player
stats, then the admin retypes its consequence as W / OTW / L / OTL totals.
Everything the computed path needs is already there except one thing: which
games before the "went to OT" box existed were decided in overtime on a goal
rather than a shootout. The typed-in totals say how many overtime results
each team has, so the preview can show exactly how many such games are
still unmarked per team and which one-goal games are the candidates.

``preview`` works everything out without writing; ``switch`` flips the
season and rebuilds every record from the games.
"""

from django.db.models import Sum
from django.urls import reverse

from leagues.models import Division, Stat, Team, Team_Stat, Week
from leagues.results import recompute_team_stats, standings_games, tally_records
from leagues.templatetags.helpers import team_record

RECORD_FIELDS = ("win", "otw", "loss", "otl", "tie")
EMPTY_RECORD = {field: 0 for field in RECORD_FIELDS}


def points(record):
    return record["win"] * 3 + record["otw"] * 2 + record["otl"] + record.get("tie", 0)


def games_played(record):
    return sum(record.get(field, 0) for field in RECORD_FIELDS)


def divisions_for(season):
    """The divisions this season has weeks or teams in, in display order."""
    ids = set(Week.objects.filter(season=season).values_list("division_id", flat=True))
    ids |= set(Team.objects.filter(season=season).values_list("division_id", flat=True))
    ids.discard(None)
    return list(Division.objects.filter(pk__in=ids).order_by("division"))


def _record_text(season, record):
    return team_record(
        season.year,
        record["win"],
        record["loss"],
        otw=record["otw"],
        otl=record["otl"],
        ties=record.get("tie", 0),
    )


def _one_goal_games(season, division):
    """Decided games with a one-goal margin that carry no overtime marking:
    the only games that could have gone to overtime on a goal."""
    games = list(
        standings_games(season.pk, division.pk)
        .filter(went_to_overtime=False, shootout_winner_is_home__isnull=True)
        .select_related("hometeam", "awayteam", "week")
        .order_by("week__date", "time")
    )
    goals = {
        (row["matchup_id"], row["team_id"]): row["total"] or 0
        for row in Stat.objects.filter(matchup__in=games)
        .values("matchup_id", "team_id")
        .annotate(total=Sum("goals"))
    }
    candidates = []
    for game in games:
        home = goals.get((game.pk, game.hometeam_id))
        away = goals.get((game.pk, game.awayteam_id))
        if home is None and away is None:
            continue
        home, away = home or 0, away or 0
        if abs(home - away) != 1:
            continue
        game.home_goals, game.away_goals = home, away
        game.admin_url = reverse("admin:leagues_matchup_change", args=[game.pk])
        candidates.append(game)
    return candidates


def preview_division(season, division):
    """One division's typed-in records next to the records its games give."""
    computed, undecided = tally_records(season.pk, division.pk)
    typed = {
        row.team_id: row
        for row in Team_Stat.objects.filter(season=season, division=division)
    }
    team_ids = set(computed) | set(typed)
    teams = Team.objects.in_bulk(team_ids)
    one_goal = _one_goal_games(season, division)
    for game in undecided:
        game.admin_url = reverse("admin:leagues_matchup_change", args=[game.pk])

    rows = []
    for team_id in team_ids:
        team = teams.get(team_id)
        if team is None:
            continue
        typed_row = typed.get(team_id)
        typed_record = (
            {field: getattr(typed_row, field) for field in RECORD_FIELDS}
            if typed_row
            else dict(EMPTY_RECORD)
        )
        computed_record = computed.get(
            team_id,
            {**EMPTY_RECORD, "goals_for": 0, "goals_against": 0},
        )
        typed_ot = typed_record["otw"] + typed_record["otl"]
        computed_ot = computed_record["otw"] + computed_record["otl"]
        ot_to_mark = max(typed_ot - computed_ot, 0)
        rows.append(
            {
                "team": team,
                "typed_record": _record_text(season, typed_record),
                "computed_record": _record_text(season, computed_record),
                "typed_points": points(typed_record),
                "computed_points": points(computed_record),
                "typed_gp": games_played(typed_record),
                "computed_gp": games_played(computed_record),
                "ot_to_mark": ot_to_mark,
                "changed": any(
                    typed_record.get(f, 0) != computed_record.get(f, 0)
                    for f in RECORD_FIELDS
                ),
                "candidates": (
                    [g for g in one_goal if team_id in (g.hometeam_id, g.awayteam_id)]
                    if ot_to_mark
                    else []
                ),
            }
        )
    rows.sort(key=lambda row: (-row["computed_points"], row["team"].team_name.lower()))
    return {
        "division": division,
        "rows": rows,
        "undecided": undecided,
        "ot_to_mark": sum(row["ot_to_mark"] for row in rows),
        "changed": sum(1 for row in rows if row["changed"]),
    }


def preview(season):
    return [preview_division(season, division) for division in divisions_for(season)]


def switch(season):
    """Make this season's standings come from its games, and rebuild every
    record now. Returns the divisions rebuilt."""
    divisions = divisions_for(season)
    if not season.standings_from_games:
        season.standings_from_games = True
        season.save(update_fields=["standings_from_games"])
    for division in divisions:
        recompute_team_stats(season.pk, division.pk)
    return divisions
