import datetime
from collections import OrderedDict

from django.db.models import Case, F, IntegerField, Max, Q, Sum, When
from django.db.models.functions import Coalesce, Lower
from django.shortcuts import render
from django.views.generic.list import ListView

from leagues.models import Division, MatchUp, Player, Roster, Stat, Team, Week

from .players import get_player_stats, get_stats_for_past_team


class MatchUpDetailView(ListView):
    context_object_name = "matchup_list"

    def __init__(self):
        super(MatchUpDetailView, self).__init__()
        self._next_week = None

    def get_queryset(self):
        self._next_week = Week.objects.filter(
            date__gte=datetime.datetime.today()
        ).order_by("date")
        if self._next_week:
            self._next_week = self._next_week[0]
        else:
            # No upcoming matches so use most recent.
            self._next_week = Week.objects.latest("date")
        return MatchUp.objects.order_by("time").filter(week__date=self._next_week.date)

    def get_context_data(self, **kwargs):
        context = super(MatchUpDetailView, self).get_context_data(**kwargs)
        context["date_of_week"] = self.kwargs.get("date", self._next_week.date)
        matchups = MatchUp.objects.filter(week__date=context["date_of_week"]).order_by(
            "time"
        )
        dmatchups = OrderedDict()
        for match in matchups:
            dmatchups[match.id] = {}
            dmatchups[match.id]["matchup"] = match
            dmatchups[match.id]["hometeamroster"] = Roster.objects.filter(
                team=match.hometeam
            ).order_by(
                "player_number", Lower("player__last_name"), Lower("player__first_name")
            )
            dmatchups[match.id]["awayteamroster"] = Roster.objects.filter(
                team=match.awayteam
            ).order_by(
                "player_number", Lower("player__last_name"), Lower("player__first_name")
            )

        context["matchups"] = dmatchups

        return context


def get_stats_for_matchup(match):
    return (
        Stat.objects.filter(matchup=match)
        .exclude(Q(goals=None) & Q(assists=None))
        .exclude(Q(goals=0) & Q(assists=0))
        .order_by("-goals", "-assists")
    )


def get_goalies_for_matchup(match, home):
    if home:
        return Stat.objects.filter(matchup=match).filter(
            (Q(goals=0) | Q(goals=None))
            & (Q(assists=0) | Q(assists=None))
            & Q(matchup__hometeam=F("team"))
        )
    else:
        return Stat.objects.filter(matchup=match).filter(
            (Q(goals=0) | Q(goals=None))
            & (Q(assists=0) | Q(assists=None))
            & Q(matchup__awayteam=F("team"))
        )


def add_goals_for_matchups(matchups):
    return matchups.annotate(
        home_goals=Sum(
            Case(
                When(hometeam=F("stat__team"), then=F("stat__goals")),
                default=0,
                output_field=IntegerField(),
            )
        ),
        away_goals=Sum(
            Case(
                When(awayteam=F("stat__team"), then=F("stat__goals")),
                default=0,
                output_field=IntegerField(),
            )
        ),
    )


def get_matches_for_division(division):
    return (
        MatchUp.objects.filter(hometeam__division=division)
        .order_by("-week__date")
        .filter(awayteam__is_active=True)
    )


def get_championships_for_division(division):
    return (
        MatchUp.objects.filter(hometeam__division=division)
        .order_by("-week__date")
        .filter(is_championship=True)
    )


def get_matches_for_team(team):
    return MatchUp.objects.filter(
        (Q(hometeam__id=team) | Q(awayteam__id=team))
    ).order_by("-week__date")


def get_detailed_matchups(matchups):
    result = OrderedDict()
    for match in (
        matchups.select_related("hometeam")
        .select_related("awayteam")
        .select_related("week")
        .annotate(
            home_wins=Coalesce(Max("hometeam__team_stat__win"), 0),
            home_losses=Coalesce(Max("hometeam__team_stat__loss"), 0),
            home_ties=Coalesce(Max("hometeam__team_stat__tie"), 0),
            home_otw=Coalesce(Max("hometeam__team_stat__otw"), 0),
            home_otl=Coalesce(Max("hometeam__team_stat__otl"), 0),
            away_wins=Coalesce(Max("awayteam__team_stat__win"), 0),
            away_losses=Coalesce(Max("awayteam__team_stat__loss"), 0),
            away_otw=Coalesce(Max("awayteam__team_stat__otw"), 0),
            away_otl=Coalesce(Max("awayteam__team_stat__otl"), 0),
            away_ties=Coalesce(Max("awayteam__team_stat__tie"), 0),
        )
    ):
        if not result.get(str(match.week.date), False):
            result[str(match.week.date)] = OrderedDict()
        result[str(match.week.date)][str(match.id)] = {}
        result[str(match.week.date)][str(match.id)]["match"] = match
        relevant_stats = get_stats_for_matchup(match)
        home_goalie_stats = get_goalies_for_matchup(match, home=True)
        away_goalie_stats = get_goalies_for_matchup(match, home=False)
        result[str(match.week.date)][str(match.id)]["stats"] = relevant_stats
        result[str(match.week.date)][str(match.id)][
            "home_goalie_stats"
        ] = home_goalie_stats
        result[str(match.week.date)][str(match.id)][
            "away_goalie_stats"
        ] = away_goalie_stats
    return result


def get_schedule_for_matchups(matchups):
    schedule = OrderedDict()
    for match in matchups.annotate(
        home_wins=Coalesce(Max("hometeam__team_stat__win"), 0),
        home_losses=Coalesce(Max("hometeam__team_stat__loss"), 0),
        home_ties=Coalesce(Max("hometeam__team_stat__tie"), 0),
        home_otw=Coalesce(Max("hometeam__team_stat__otw"), 0),
        home_otl=Coalesce(Max("hometeam__team_stat__otl"), 0),
        away_wins=Coalesce(Max("awayteam__team_stat__win"), 0),
        away_losses=Coalesce(Max("awayteam__team_stat__loss"), 0),
        away_otw=Coalesce(Max("awayteam__team_stat__otw"), 0),
        away_otl=Coalesce(Max("awayteam__team_stat__otl"), 0),
        away_ties=Coalesce(Max("awayteam__team_stat__tie"), 0),
    ):
        game_date = match.week.date
        if not schedule.get(game_date, False):
            schedule[game_date] = OrderedDict()
        if not schedule[game_date].get(str(match.awayteam.division), False):
            schedule[game_date][str(match.awayteam.division)] = []
        schedule[game_date][str(match.awayteam.division)].append(match)
    return schedule


def schedule(request):
    context = {}
    context["view"] = "schedule"
    # Better to have a custom dictionary here than have 3 nested loops in the template
    matchups = (
        MatchUp.objects.order_by("week__date", "time")
        .filter(awayteam__is_active=True)
        .filter(week__date__gte=datetime.datetime.today())
    )
    context["schedule"] = get_schedule_for_matchups(matchups)
    return render(request, "leagues/schedule.html", context=context)


def teams(request, team=0):
    context = {}
    team = int(team)
    context["view"] = "teams"
    context["schedule"] = OrderedDict()
    schedulematchups = (
        MatchUp.objects.order_by("week__date", "time")
        .filter(awayteam__is_active=True)
        .filter(Q(awayteam__id=team) | Q(hometeam__id=team))
        .filter(week__date__gte=datetime.datetime.today())
    )
    context["schedule"] = get_schedule_for_matchups(schedulematchups)
    context["team"] = Team.objects.annotate(
        wins=Coalesce(Max("team_stat__win"), 0),
        otw=Coalesce(Max("team_stat__otw"), 0),
        otl=Coalesce(Max("team_stat__otl"), 0),
        losses=Coalesce(Max("team_stat__loss"), 0),
        ties=Coalesce(Max("team_stat__tie"), 0),
    ).get(id=team)
    scorematchups = get_matches_for_team(team).filter(
        week__date__lte=datetime.datetime.today()
    )
    scorematchups = add_goals_for_matchups(scorematchups)
    context["matchups"] = get_detailed_matchups(scorematchups)
    context["roster"] = []
    players = Player.objects.filter(roster__team__id=team, roster__is_substitute=False)
    season = players.values_list("roster__team__season__id", flat=True).distinct()
    context["past_team_stats"] = get_stats_for_past_team(team)
    context["player_list"] = get_player_stats(
        players, int(season[0]), scope="combined"
    ).order_by("-total_points", "-sum_goals", "-sum_assists", "average_goals_against")
    for rosteritem in (
        Roster.objects.select_related("team")
        .select_related("player")
        .filter(team__id=team, is_substitute=False)
    ):
        context["roster"].append(
            {
                "player": rosteritem.player.first_name
                + " "
                + rosteritem.player.last_name,
                "position": [
                    y for x, y in Roster.POSITION_TYPE if x == rosteritem.position1
                ][0],
            }
        )

    return render(request, "leagues/team.html", context=context)


def scores(request, division=1):
    context = {}
    context["view"] = "scores"
    context["divisions"] = Division.objects.all()
    context["matchups"] = OrderedDict()
    context["active_division"] = int(division)
    division = [i for i in Division.DIVISION_TYPE if context["active_division"] in i]
    # Check to see if the dvision from the URL is valid
    if len(division):
        # division ex: [(1, 'Sunday D1')]
        context["division_name"] = division[0][1]
        matchups = get_matches_for_division(context["active_division"]).filter(
            week__date__lte=datetime.datetime.today()
        )
        matchups = add_goals_for_matchups(matchups)
        context["matchups"] = get_detailed_matchups(matchups)
    return render(request, "leagues/scores.html", context=context)


def cups(request, division=1):
    context = {}
    context["view"] = "cups"
    context["divisions"] = Division.objects.all()
    context["matchups"] = OrderedDict()
    context["active_division"] = int(division)
    division = [i for i in Division.DIVISION_TYPE if context["active_division"] in i]
    # Check to see if the dvision from the URL is valid
    if len(division):
        # division ex: [(1, 'Sunday D1')]
        context["division_name"] = division[0][1]
        matchups = get_championships_for_division(context["active_division"])
        matchups = add_goals_for_matchups(matchups)
        context["matchups"] = get_detailed_matchups(matchups)
    return render(request, "leagues/cups.html", context=context)
