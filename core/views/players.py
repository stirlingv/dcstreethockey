from collections import OrderedDict, namedtuple

import numpy as np
from dal import autocomplete
from django.db import connection
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    FloatField,
    Func,
    IntegerField,
    Max,
    Min,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views.generic.list import ListView

from leagues.models import (
    Division,
    Player,
    Roster,
    Season,
    Stat,
    Team,
    Team_Stat,
)


def normalize_stat_scope(scope, default="regular"):
    scope_value = (scope or default).lower()
    if scope_value in {"regular", "postseason", "combined"}:
        return scope_value
    return default


def filter_stats_by_scope(stats, scope):
    scope_value = normalize_stat_scope(scope, default="combined")
    if scope_value == "regular":
        return stats.filter(Q(matchup__isnull=True) | Q(matchup__is_postseason=False))
    if scope_value == "postseason":
        return stats.filter(matchup__is_postseason=True)
    return stats


def get_player_stats(players, season, scope="regular"):
    scope_value = normalize_stat_scope(scope, default="regular")
    stat_filters = Q()
    if season == 0:
        stat_filters &= Q(stat__team__is_active=True)
    if scope_value == "regular":
        stat_filters &= (
            Q(stat__isnull=True)
            | Q(stat__matchup__isnull=True)
            | Q(stat__matchup__is_postseason=False)
        )
    elif scope_value == "postseason":
        stat_filters &= Q(stat__matchup__is_postseason=True)

    return (
        players.filter(stat_filters)
        .values(
            "id",
            "last_name",
            "first_name",
            "roster__team__team_name",
            "roster__team__id",
            "roster__position1",
            "roster__position2",
            "roster__is_captain",
        )
        .annotate(
            sum_goals=Sum(
                Case(
                    When(
                        stat__team=F("roster__team"),
                        stat__team__season__id=season
                        if season != 0
                        else F("roster__team__season__id"),
                        then=F("stat__goals"),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            sum_assists=Sum(
                Case(
                    When(
                        stat__team=F("roster__team"),
                        stat__team__season__id=season
                        if season != 0
                        else F("roster__team__season__id"),
                        then=F("stat__assists"),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            total_points=Sum(
                Case(
                    When(
                        stat__team=F("roster__team"),
                        stat__team__season__id=season
                        if season != 0
                        else F("roster__team__season__id"),
                        then=F("stat__assists") + F("stat__goals"),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            sum_goals_against=Sum(
                Case(
                    When(
                        stat__team=F("roster__team"),
                        stat__team__season__id=season
                        if season != 0
                        else F("roster__team__season__id"),
                        then=F("stat__goals_against") - F("stat__empty_net"),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            sum_games_played=Sum(
                Case(
                    When(
                        stat__team=F("roster__team"),
                        stat__team__season__id=season
                        if season != 0
                        else F("roster__team__season__id"),
                        then=1,
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            average_goals_against=Case(
                When(sum_games_played=0, then=Value(0.0)),
                default=ExpressionWrapper(
                    F("sum_goals_against") * 1.0 / F("sum_games_played"),
                    output_field=FloatField(),
                ),
                output_field=FloatField(),
            ),
        )
        .annotate(
            rounded_average_goals_against=Func(
                F("average_goals_against"),
                Value(2),
                function="ROUND",
                output_field=DecimalField(max_digits=10, decimal_places=2),
            )
        )
    )


def namedtuplefetchall(cursor):
    desc = cursor.description
    nt_result = namedtuple("Result", [col[0] for col in desc])
    return [nt_result(*row) for row in cursor.fetchall()]


def get_division_ranks(division, gender_filter):
    with connection.cursor() as cursor:
        if gender_filter == "all":
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank,
                       sub.id, sub.first_name, sub.last_name, sub.total_goals,
                       sub.total_assists, sub.total_points
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name,
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists,
                           (SUM(goals) + SUM(assists)) AS total_points
                    FROM leagues_stat
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id
                    JOIN leagues_team ON leagues_stat.team_id = leagues_team.id
                    JOIN leagues_division ON leagues_team.division_id = leagues_division.id
                    WHERE leagues_division.id = %s
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name
                    HAVING SUM(goals+assists) > 1
                ) sub
                ORDER BY sub.total_points DESC
                LIMIT 50;
            """
            cursor.execute(query, [division])
        elif gender_filter == "F":
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank,
                       sub.id, sub.first_name, sub.last_name, sub.total_goals,
                       sub.total_assists, sub.total_points
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name,
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists,
                           (SUM(goals) + SUM(assists)) AS total_points
                    FROM leagues_stat
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id
                    JOIN leagues_team ON leagues_stat.team_id = leagues_team.id
                    JOIN leagues_division ON leagues_team.division_id = leagues_division.id
                    WHERE leagues_division.id = %s AND leagues_player.gender = 'F'
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name
                    HAVING SUM(goals+assists) > 1
                ) sub
                ORDER BY sub.total_points DESC;
            """
            cursor.execute(query, [division])
        else:
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank,
                       sub.id, sub.first_name, sub.last_name, sub.total_goals,
                       sub.total_assists, sub.total_points
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name,
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists,
                           (SUM(goals) + SUM(assists)) AS total_points
                    FROM leagues_stat
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id
                    JOIN leagues_team ON leagues_stat.team_id = leagues_team.id
                    JOIN leagues_division ON leagues_team.division_id = leagues_division.id
                    WHERE leagues_division.id = %s AND leagues_player.gender = %s
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name
                    HAVING SUM(goals+assists) > 1
                ) sub
                ORDER BY sub.total_points DESC
                LIMIT 50;
            """
            cursor.execute(query, [division, gender_filter])
        return namedtuplefetchall(cursor)


def get_career_stats_for_player(player_id=0):
    if get_goalie_games_played(player_id) > 0:
        return Stat.objects.filter(player_id=player_id).aggregate(
            career_goals=Sum("goals"),
            career_assists=Sum("assists"),
            average_goals_per_season=ExpressionWrapper(
                Sum("goals") / get_seasons_played(player_id),
                output_field=DecimalField(),
            ),
            average_assists_per_season=ExpressionWrapper(
                Sum("assists") / get_seasons_played(player_id),
                output_field=DecimalField(),
            ),
            average_goals_against_per_game=ExpressionWrapper(
                Sum("goals_against") / get_goalie_games_played(player_id),
                output_field=DecimalField(),
            ),
            first_season=Min("team__season__year"),
        )
    return Stat.objects.filter(player_id=player_id).aggregate(
        career_goals=Sum("goals"),
        career_assists=Sum("assists"),
        first_season=Min("team__season__year"),
        average_goals_per_season=ExpressionWrapper(
            Sum("goals") / get_seasons_played(player_id), output_field=DecimalField()
        ),
        average_assists_per_season=ExpressionWrapper(
            Sum("assists") / get_seasons_played(player_id), output_field=DecimalField()
        ),
    )


def get_goalie_games_played(player):
    games_played = (
        Stat.objects.filter(player__id=player)
        .filter((Q(goals=0) | Q(goals=None)) & (Q(assists=0) | Q(assists=None)))
        .count()
    )
    return float(games_played)


def get_seasons_played(player):
    count = Roster.objects.filter(player__id=player, is_substitute=False).count()
    return float(count)


def get_offensive_stats_for_player(player, scope="combined"):
    return (
        filter_stats_by_scope(Stat.objects.filter(player_id=player), scope)
        .exclude((Q(goals=0) | Q(goals=None)) & (Q(assists=0) | Q(assists=None)))
        .values(
            "team__id",
            "team__team_name",
            "team__team_stat__win",
            "team__team_stat__loss",
            "team__team_stat__tie",
            "team__season__year",
            "team__season__season_type",
            "team__division",
        )
        .annotate(
            team_wins=Coalesce(Max("team__team_stat__win"), 0),
            team_losses=Coalesce(Max("team__team_stat__loss"), 0),
            team_otw=Coalesce(Max("team__team_stat__otw"), 0),
            team_otl=Coalesce(Max("team__team_stat__otl"), 0),
            sum_goals=Sum(
                Case(
                    When(
                        team=F("team"),
                        team__season__id=F("team__season__id"),
                        then=Coalesce("goals", 0),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            sum_assists=Sum(
                Case(
                    When(
                        team=F("team"),
                        team__season__id=F("team__season__id"),
                        then=Coalesce("assists", 0),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            total_points=Sum(
                Case(
                    When(
                        team=F("team"),
                        team__season__id=F("team__season__id"),
                        then=Coalesce("assists", 0) + Coalesce("goals", 0),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
        )
        .order_by("-team__season__year", "-team__season__season_type")
    )


def get_goalie_stats(player, scope="combined"):
    return (
        filter_stats_by_scope(
            Stat.objects.filter(
                Q(player_id=player)
                & ((Q(goals=0) | Q(goals=None)) & (Q(assists=0) | Q(assists=None)))
            ),
            scope,
        )
        .values(
            "team__id",
            "team__team_name",
            "team__team_stat__tie",
            "team__season__year",
            "team__season__season_type",
            "team__division",
        )
        .annotate(
            team_wins=Coalesce(Max("team__team_stat__win"), 0),
            team_losses=Coalesce(Max("team__team_stat__loss"), 0),
            team_otw=Coalesce(Max("team__team_stat__otw"), 0),
            team_otl=Coalesce(Max("team__team_stat__otl"), 0),
            sum_goals_against=Sum(
                Case(
                    When(
                        team=F("team"),
                        team__season__id=F("team__season__id"),
                        then=Coalesce("goals_against", 0) - Coalesce("empty_net", 0),
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            sum_games_played=Sum(
                Case(
                    When(
                        team=F("team"), team__season__id=F("team__season__id"), then=1
                    ),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            average_goals_against=Sum(
                Case(
                    When(
                        team=F("team"),
                        team__season__id=F("team__season__id"),
                        then=Coalesce("goals_against", 0.0)
                        - Coalesce("empty_net", 0.0),
                    ),
                    default=0.0,
                    output_field=DecimalField(),
                )
            )
            / Sum(
                Case(
                    When(
                        team=F("team"), team__season__id=F("team__season__id"), then=1.0
                    ),
                    default=0.0001,
                    output_field=DecimalField(),
                )
            ),
        )
        .order_by("-team__season__year", "-team__season__season_type")
    )


def get_average_stats_for_player(player_id, scope="combined"):
    stats = filter_stats_by_scope(Stat.objects.filter(player_id=player_id), scope)
    totals = stats.aggregate(
        total_goals=Coalesce(Sum("goals"), 0),
        total_assists=Coalesce(Sum("assists"), 0),
    )
    seasons_played = get_seasons_played(player_id)
    if seasons_played == 0:
        return {
            "average_goals_per_season": 0,
            "average_assists_per_season": 0,
        }
    return {
        "average_goals_per_season": totals["total_goals"] / seasons_played,
        "average_assists_per_season": totals["total_assists"] / seasons_played,
    }


def get_stats_for_past_team(team):
    team_name = Team.objects.filter(id=team).values_list("team_name", flat=True)
    return (
        Team_Stat.objects.filter(team__team_name__in=team_name)
        .values(
            "team__id",
            "team__team_name",
            "win",
            "otw",
            "otl",
            "loss",
            "tie",
            "goals_for",
            "goals_against",
            "team__season__year",
            "team__season__season_type",
            "team__division",
        )
        .order_by("-team__season__year", "-team__season__season_type")
    )


def calculate_player_stats(player, season_mapping, scope="combined"):
    offensive_stats = (
        filter_stats_by_scope(Stat.objects.filter(player=player), scope)
        .select_related("team__season", "team__division")
        .values(
            "team__season__year",
            "team__season__season_type",
            "team__team_name",
            "team__division",
            "team__id",
        )
        .annotate(
            sum_goals=Sum("goals"),
            sum_assists=Sum("assists"),
            team_wins=Max("team__team_stat__win"),
            team_losses=Max("team__team_stat__loss"),
            team_ties=Max("team__team_stat__tie"),
            team_otw=Max("team__team_stat__otw"),
            team_otl=Max("team__team_stat__otl"),
        )
        .order_by("team__season__year", "team__season__season_type")
    )  # Earliest to most recent for trend chart

    # Filter out seasons where both goals and assists are zero
    offensive_stats = [
        stat
        for stat in offensive_stats
        if (stat["sum_goals"] or 0) > 0 or (stat["sum_assists"] or 0) > 0
    ]

    # Create a separate list for the table with most recent seasons on top
    offensive_stats_table = list(offensive_stats)[::-1]

    player_seasons = [
        f"{stat['team__season__year']} {season_mapping.get(stat['team__season__season_type'], 'Unknown')} ({stat['team__team_name']})"
        for stat in offensive_stats
    ]
    player_goals = [
        stat["sum_goals"] if stat["sum_goals"] is not None else 0
        for stat in offensive_stats
    ]
    player_assists = [
        stat["sum_assists"] if stat["sum_assists"] is not None else 0
        for stat in offensive_stats
    ]
    player_points = [
        goals + assists for goals, assists in zip(player_goals, player_assists)
    ]

    # Calculate trend line for total points
    if player_points:
        x = np.arange(len(player_points))
        y = np.array(player_points)
        if len(x) > 1:  # Ensure there are enough points to calculate a trend line
            trend = np.polyfit(x, y, 1)
            trend_line = trend[0] * x + trend[1]
        else:
            trend_line = y  # Not enough points to calculate a trend line
        trend_line = (
            trend_line.tolist()
        )  # Convert numpy array to list for JSON serialization
    else:
        trend_line = []

    return {
        "offensive_stats": offensive_stats_table,  # Most recent to earliest for table
        "player_seasons": player_seasons,
        "player_goals": player_goals,
        "player_assists": player_assists,
        "player_points": player_points,
        "trend_line": trend_line,
    }


class PlayerAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Player.objects.none()

        qs = Player.objects.all()

        if self.q:
            qs = qs.filter(
                Q(first_name__icontains=self.q) | Q(last_name__icontains=self.q)
            )

        return qs


class PlayerStatDetailView(ListView):
    context_object_name = "player_stat_list"
    template_name = "stat_list.html"

    def get_queryset(self):
        return Stat.objects.filter(team__season__is_current_season=True)

    def get_context_data(self, **kwargs):
        context = super(PlayerStatDetailView, self).get_context_data(**kwargs)
        season = self.kwargs.get("season", "0")
        stat_scope = normalize_stat_scope(
            self.request.GET.get("scope", "regular"), default="regular"
        )
        context["seasons"] = Season.objects.order_by("-year", "-season_type")[:4]
        context["active_season"] = int(season)
        context["stat_scope"] = stat_scope
        context["stat_scope_label"] = {
            "regular": "Regular Season",
            "postseason": "Post Season",
            "combined": "Combined",
        }[stat_scope]
        context["player_stat_list"] = OrderedDict()

        divisions = Division.objects.all()
        for div in divisions:
            players = Player.objects.filter(roster__team__division=div).select_related(
                "roster__team"
            )
            player_stats = (
                get_player_stats(players, context["active_season"], scope=stat_scope)
                .filter(sum_games_played__gte=1)
                .order_by(
                    "rounded_average_goals_against",
                    "-total_points",
                    "-sum_goals",
                    "-sum_assists",
                )
            )
            context["player_stat_list"][str(div)] = player_stats

        return context


def PlayerAllTimeStats_list(request):
    context = {}
    gender_filter = request.GET.get("gender", "all")

    with connection.cursor() as cursor:
        if gender_filter == "all":
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank,
                       sub.id, sub.first_name, sub.last_name, sub.total_goals,
                       sub.total_assists, sub.total_points
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name,
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists,
                           (SUM(goals) + SUM(assists)) AS total_points
                    FROM leagues_stat
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name
                    HAVING SUM(goals+assists) > 1
                ) sub
                ORDER BY sub.total_points DESC
                LIMIT 100;
            """
        elif gender_filter == "F":
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank,
                       sub.id, sub.first_name, sub.last_name, sub.total_goals,
                       sub.total_assists, sub.total_points
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name,
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists,
                           (SUM(goals) + SUM(assists)) AS total_points
                    FROM leagues_stat
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id
                    WHERE leagues_player.gender = 'F'
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name
                    HAVING SUM(goals+assists) > 1
                ) sub
                ORDER BY sub.total_points DESC;
            """
        else:
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank,
                       sub.id, sub.first_name, sub.last_name, sub.total_goals,
                       sub.total_assists, sub.total_points
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name,
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists,
                           (SUM(goals) + SUM(assists)) AS total_points
                    FROM leagues_stat
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id
                    WHERE leagues_player.gender = %s
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name
                    HAVING SUM(goals+assists) > 1
                ) sub
                ORDER BY sub.total_points DESC
                LIMIT 100;
            """
        if gender_filter in ["M", "NB", "NA"]:
            cursor.execute(query, [gender_filter])
        else:
            cursor.execute(query)
        context["all_ranks"] = namedtuplefetchall(cursor)

    context["d1_ranks"] = get_division_ranks(1, gender_filter)
    context["d2_ranks"] = get_division_ranks(2, gender_filter)
    context["draft_ranks"] = get_division_ranks(3, gender_filter)
    context["mona_ranks"] = get_division_ranks(4, gender_filter)
    context["monb_ranks"] = get_division_ranks(5, gender_filter)
    context["selected_gender"] = gender_filter

    return render(request, "leagues/hof.html", context=context)


def player_view(request, player_id):
    player = get_object_or_404(Player, id=player_id)
    season_mapping = {1: "Spring", 2: "Summer", 3: "Fall", 4: "Winter"}
    stats = calculate_player_stats(player, season_mapping, scope="combined")
    career_stats = get_career_stats_for_player(player_id)
    stat_sections = [
        {
            "key": "regular",
            "label": "Regular Season",
            "offensive_stats": get_offensive_stats_for_player(
                player_id, scope="regular"
            ),
            "goalie_stats": get_goalie_stats(player_id, scope="regular"),
        },
        {
            "key": "postseason",
            "label": "Post Season",
            "offensive_stats": get_offensive_stats_for_player(
                player_id, scope="postseason"
            ),
            "goalie_stats": get_goalie_stats(player_id, scope="postseason"),
        },
        {
            "key": "combined",
            "label": "Combined",
            "offensive_stats": get_offensive_stats_for_player(
                player_id, scope="combined"
            ),
            "goalie_stats": get_goalie_stats(player_id, scope="combined"),
        },
    ]

    context = {
        "view": "player",
        "player": player,
        "career_stats": career_stats,
        "seasons": get_seasons_played(player_id),
        "goalie_stats": get_goalie_stats(player_id, scope="combined"),
        "stat_sections": stat_sections,
        "average_stats": {
            "combined": {
                "average_goals_per_season": career_stats.get(
                    "average_goals_per_season"
                ),
                "average_assists_per_season": career_stats.get(
                    "average_assists_per_season"
                ),
            },
            "regular": get_average_stats_for_player(player_id, scope="regular"),
            "postseason": get_average_stats_for_player(player_id, scope="postseason"),
        },
        **stats,
    }

    return render(request, "leagues/player.html", context)


def player_trends_view(request):
    player_id = request.GET.get("player_id")
    timespan = request.GET.get(
        "timespan", request.session.get("timespan", "all")
    )  # Default to all seasons if not provided
    division = request.GET.get("division", "all")  # Default to all divisions
    context = {"view": "player_trends"}

    # Store the timespan in the session
    request.session["timespan"] = timespan

    all_players = Player.objects.all()
    context["all_players"] = all_players

    divisions = Division.DIVISION_TYPE
    context["divisions"] = divisions

    if player_id:
        try:
            player = get_object_or_404(Player, id=player_id)
            season_mapping = {1: "Spring", 2: "Summer", 3: "Fall", 4: "Winter"}
            calculate_player_stats(player, season_mapping)

            # Apply division and timespan filters if necessary
            offensive_stats = (
                Stat.objects.filter(player=player)
                .select_related("team__season", "team__division")
                .values(
                    "team__season__year",
                    "team__season__season_type",
                    "team__team_name",
                    "team__division",
                    "team__id",
                )
                .annotate(sum_goals=Sum("goals"), sum_assists=Sum("assists"))
                .order_by("-team__season__year", "-team__season__season_type")
            )

            if division != "all":
                offensive_stats = offensive_stats.filter(team__division=division)

            if timespan != "all":
                timespan = int(timespan)
                offensive_stats = offensive_stats[:timespan]

            # Reverse the order to display the most recent seasons on the far right
            offensive_stats = list(offensive_stats)[::-1]

            # Check the player's position for each season and filter out seasons with zero goals and zero assists if the player's primary position is not goalie or defense
            filtered_stats = []
            for stat in offensive_stats:
                roster_entry = Roster.objects.filter(
                    player=player, is_substitute=False, team_id=stat["team__id"]
                ).first()
                primary_position = roster_entry.position1 if roster_entry else None
                sum_goals = stat["sum_goals"] if stat["sum_goals"] is not None else 0
                sum_assists = (
                    stat["sum_assists"] if stat["sum_assists"] is not None else 0
                )
                if primary_position not in [3, 4]:  # 3: Defense, 4: Goalie
                    if sum_goals > 0 or sum_assists > 0:
                        filtered_stats.append(stat)
                else:
                    filtered_stats.append(stat)

            player_seasons = [
                f"{stat['team__season__year']} {season_mapping.get(stat['team__season__season_type'], 'Unknown')} ({stat['team__team_name']})"
                for stat in filtered_stats
            ]
            player_goals = [
                stat["sum_goals"] if stat["sum_goals"] is not None else 0
                for stat in filtered_stats
            ]
            player_assists = [
                stat["sum_assists"] if stat["sum_assists"] is not None else 0
                for stat in filtered_stats
            ]
            player_points = [
                goals + assists for goals, assists in zip(player_goals, player_assists)
            ]

            average_goals = sum(player_goals) / len(player_goals) if player_goals else 0
            average_assists = (
                sum(player_assists) / len(player_assists) if player_assists else 0
            )
            average_points = (
                sum(player_points) / len(player_points) if player_points else 0
            )

            # Calculate trend line for total points
            x = np.arange(len(player_points))
            y = np.array(player_points)
            if len(x) > 1:  # Ensure there are enough points to calculate a trend line
                trend = np.polyfit(x, y, 1)
                trend_line = trend[0] * x + trend[1]
            else:
                trend_line = y  # Not enough points to calculate a trend line

            context.update(
                {
                    "player": player,
                    "player_seasons": player_seasons,
                    "player_goals": player_goals,
                    "player_assists": player_assists,
                    "player_points": player_points,
                    "trend_line": trend_line.tolist(),  # Convert numpy array to list for JSON serialization
                    "timespan": timespan,
                    "player_id": player_id,
                    "division": division,
                    "average_goals": average_goals,
                    "average_assists": average_assists,
                    "average_points": average_points,
                }
            )

            # Debug statements
            print(f"Player: {player.first_name} {player.last_name}")
            print(f"Seasons: {player_seasons}")
            print(f"Goals: {player_goals}")
            print(f"Assists: {player_assists}")
            print(f"Points: {player_points}")
            print(f"Average Goals: {average_goals}")
            print(f"Average Assists: {average_assists}")
            print(f"Average Points: {average_points}")
            print(f"Trend Line: {trend_line}")

        except Exception as e:
            print(f"Error: {e}")

    return render(request, "leagues/player_trends.html", context=context)
