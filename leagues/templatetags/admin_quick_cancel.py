from collections import defaultdict
from datetime import date, timedelta

from django import template
from django.db.models import Count, F, Sum

from leagues.models import MatchUp, Stat, Team_Stat, Week

register = template.Library()


@register.inclusion_tag("admin/quick_cancel_widget.html", takes_context=True)
def quick_cancel_widget(context):
    today = date.today()
    cutoff = today + timedelta(days=7)

    upcoming_weeks = (
        Week.objects.filter(date__range=(today, cutoff))
        .select_related("division", "season")
        .order_by("date", "division__division", "pk")
    )

    # De-duplicate overlapping seasons: keep highest-pk week per (date, division).
    date_buckets = defaultdict(dict)  # {date: {division_id: week}}
    for week in upcoming_weeks:
        date_buckets[week.date][week.division_id] = week

    week_ids = [w.pk for d in date_buckets.values() for w in d.values()]
    matchups_by_week = defaultdict(list)
    for m in (
        MatchUp.objects.filter(week_id__in=week_ids, week__date__range=(today, cutoff))
        .select_related("hometeam", "awayteam")
        .order_by("time")
    ):
        matchups_by_week[m.week_id].append(m)

    grouped = {}
    for week_date in sorted(date_buckets.keys()):
        division_weeks = list(date_buckets[week_date].values())
        division_weeks.sort(key=lambda w: w.division.division)
        week_data = []
        for week in division_weeks:
            games = matchups_by_week[week.pk]
            all_c = all(g.is_cancelled for g in games) if games else week.is_cancelled
            any_c = any(g.is_cancelled for g in games) if games else week.is_cancelled
            week_data.append(
                {
                    "week": week,
                    "games": games,
                    "all_cancelled": all_c,
                    "any_cancelled": any_c,
                    "some_cancelled": any_c and not all_c,
                }
            )
        grouped[week_date] = {
            "divisions": week_data,
            "all_cancelled": all(d["all_cancelled"] for d in week_data),
            "any_cancelled": any(d["any_cancelled"] for d in week_data),
        }

    return {
        "grouped_weeks": grouped,
        "today": today,
        "csrf_token": context.get("csrf_token"),
    }


@register.inclusion_tag("admin/stats_entry_widget.html")
def stats_entry_widget():
    today = date.today()
    since = today - timedelta(days=7)

    matchups = list(
        MatchUp.objects.filter(
            week__date__range=(since, today),
            is_cancelled=False,
            week__is_cancelled=False,
        )
        .select_related("hometeam", "awayteam", "week__division", "week__season")
        .annotate(stat_count=Count("stat"))
        .order_by("week__date", "week__division__division", "time")
    )

    # Bulk-compute outcome status for all matchups in two queries.
    #
    # outcome_missing = True when a matchup has Stat rows (the score is visible)
    # but the team's Team_Stat games-played count (W+OTW+L+OTL+T) is lower than
    # the number of matchups this season that have Stat rows — meaning at least
    # one game's result wasn't recorded in the Game Outcome section.
    if matchups:
        team_ids = set()
        div_ids = set()
        season_ids = set()
        for m in matchups:
            team_ids.update([m.hometeam_id, m.awayteam_id])
            div_ids.add(m.week.division_id)
            season_ids.add(m.week.season_id)

        # Count distinct matchups-with-stats per (team, division, season) — season-wide
        stat_game_counts = {
            (
                row["team_id"],
                row["matchup__week__division_id"],
                row["matchup__week__season_id"],
            ): row["game_count"]
            for row in Stat.objects.filter(
                matchup__week__date__lte=today,
                matchup__week__season_id__in=season_ids,
                matchup__week__division_id__in=div_ids,
                matchup__is_cancelled=False,
                team_id__in=team_ids,
            )
            .values(
                "team_id",
                "matchup__week__division_id",
                "matchup__week__season_id",
            )
            .annotate(game_count=Count("matchup_id", distinct=True))
        }

        # Team_Stat games played (W+OTW+L+OTL+T) per (team, division, season)
        ts_gp = {
            (row["team_id"], row["division_id"], row["season_id"]): row["gp"]
            for row in Team_Stat.objects.filter(
                team_id__in=team_ids,
                division_id__in=div_ids,
                season_id__in=season_ids,
            )
            .annotate(gp=F("win") + F("otw") + F("loss") + F("otl") + F("tie"))
            .values("team_id", "division_id", "season_id", "gp")
        }

        # Per-game goals and goals-against per team, for the goalie-stats check.
        # A goalie's performance is a Stat row with goals_against; if a team
        # conceded goals (opponent scored) but no goals_against is recorded for
        # that team in the game, the goalie's stats were forgotten.
        gf_ga_by_matchup_team = {
            (row["matchup_id"], row["team_id"]): (
                row["g"] or 0,
                row["ga"] or 0,
            )
            for row in Stat.objects.filter(matchup_id__in=[m.pk for m in matchups])
            .values("matchup_id", "team_id")
            .annotate(g=Sum("goals"), ga=Sum("goals_against"))
        }

        for m in matchups:
            if m.stat_count == 0:
                m.outcome_missing = False
                m.goalie_missing = False
                continue
            key_home = (m.hometeam_id, m.week.division_id, m.week.season_id)
            key_away = (m.awayteam_id, m.week.division_id, m.week.season_id)
            home_gp = ts_gp.get(key_home, 0)
            away_gp = ts_gp.get(key_away, 0)
            home_stat_games = stat_game_counts.get(key_home, 0)
            away_stat_games = stat_game_counts.get(key_away, 0)
            m.outcome_missing = home_gp < home_stat_games or away_gp < away_stat_games

            home_gf, home_ga = gf_ga_by_matchup_team.get((m.pk, m.hometeam_id), (0, 0))
            away_gf, away_ga = gf_ga_by_matchup_team.get((m.pk, m.awayteam_id), (0, 0))
            # Home conceded the away team's goals (and vice versa).
            home_goalie_missing = away_gf > 0 and home_ga == 0
            away_goalie_missing = home_gf > 0 and away_ga == 0
            m.goalie_missing = home_goalie_missing or away_goalie_missing
    else:
        for m in matchups:
            m.outcome_missing = False
            m.goalie_missing = False

    # Group by date, then by division
    date_buckets = defaultdict(lambda: defaultdict(list))
    for m in matchups:
        date_buckets[m.week.date][m.week.division].append(m)

    grouped = {}
    for game_date in sorted(date_buckets.keys(), reverse=True):
        divisions = []
        for division, games in sorted(
            date_buckets[game_date].items(), key=lambda x: x[0].division
        ):
            divisions.append(
                {
                    "division": division,
                    "games": games,
                    "all_entered": all(g.stat_count > 0 for g in games),
                    "any_missing": any(g.stat_count == 0 for g in games),
                    "outcome_needed": any(g.outcome_missing for g in games),
                    "goalie_needed": any(
                        getattr(g, "goalie_missing", False) for g in games
                    ),
                }
            )
        grouped[game_date] = {
            "divisions": divisions,
            "all_entered": all(d["all_entered"] for d in divisions),
        }

    return {
        "grouped_games": grouped,
        "today": today,
    }
