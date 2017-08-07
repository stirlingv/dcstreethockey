import datetime
from datetime import timedelta
from collections import OrderedDict

from django.shortcuts import render
from django.views.generic.list import ListView
from django.db.models.functions import Lower, Coalesce
from django.db.models import Sum, Q, Max, Avg
from django.db.models import F, When, IntegerField, FloatField, Case

from leagues.models import Season
from leagues.models import Division
from leagues.models import MatchUp
from leagues.models import Stat
from leagues.models import Roster
from leagues.models import Player
from leagues.models import Team_Stat
from leagues.models import Week
# Create your views here.

def home(request):
    context = {}
    # context["season"] = Season.objects.get(is_current_season=1)
    context["season"] = Season.objects.all()
    context["matchup"]  = MatchUp.objects.filter(week__date__range=(datetime.date.today(), datetime.date.today() + timedelta(days=6)))
    context["one_row"]  = MatchUp.objects.filter(week__date__range=(datetime.date.today(), datetime.date.today() + timedelta(days=6))).order_by('week__date').distinct('week__date')
    return render(request, "core/home.html", context=context)

def leagues(request):
    return render(request, "leagues/index.html")


class MatchUpDetailView(ListView):
    context_object_name = 'matchup_list'

    def __init__(self):
        super(MatchUpDetailView, self).__init__()
        self._next_week = None

    def get_queryset(self):
        self._next_week = Week.objects.order_by('date').filter(date__gte=datetime.datetime.today())
        if self._next_week:
            self._next_week = self._next_week[0]
        else:
            #No upcoming matches so use most recent.
            self._next_week = Week.objects.latest('date')
        return MatchUp.objects.order_by('time').filter(week__date=self._next_week.date)

    def get_context_data(self, **kwargs):
        context = super(MatchUpDetailView, self).get_context_data(**kwargs)
        context["date_of_week"] = self._next_week.date
        context["season"] = Season.objects.all()
        context["roster"] = Roster.objects.order_by(Lower('player__last_name')).filter(team__is_active=True)
        context["stat"] = Stat.objects.all().filter(team__is_active=True)

        return context

class TeamStatDetailView(ListView):
    context_object_name = 'team_list'

    def get_queryset(self):
        return Team_Stat.objects.order_by('-total_points','-win','loss','-tie')

    def get_context_data(self, **kwargs):
        context = super(TeamStatDetailView, self).get_context_data(**kwargs)

        context['team_list'] = context['team_list'].annotate(total_points = Coalesce((Sum('win') * 2) + Sum('tie'),0)).filter(team__is_active=True)
        # context["season"] = Season.objects.all()
        # context["roster"] = Roster.objects.order_by(Lower('player__last_name'))
        # context["stat"] = Stat.objects.all()

        return context

class PlayerStatDetailView(ListView):
    context_object_name = 'player_stat_list'

    def get_queryset(self):
        #return Stat.objects.filter(team__season__is_current_season=True)
        return Stat.objects.all()

    def get_context_data(self, **kwargs):
        context = super(PlayerStatDetailView, self).get_context_data(**kwargs)
        context['player_stat_list'] = OrderedDict()
        for div in Division.objects.all():
            context['player_stat_list'][str(div)] = Player.objects.filter(roster__team__division=div,
                    stat__matchup__is_postseason=False).values(
                    'last_name',
                    'first_name',
                    'roster__team__team_name',
                    'roster__position1',
                    'roster__position2',
                    ).annotate(
                    sum_goals=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__goals',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_assists=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__assists',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    total_points=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__assists', 0)+Coalesce('stat__goals',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_goals_against=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__goals_against', 0)-Coalesce('stat__empty_net', 0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_games_played=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True, then=1),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    average_goals_against=Avg(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__goals_against',0)),
                            default=0,
                            output_field=FloatField(),
                        )
                    ),
                    ).filter(sum_games_played__gte=1).order_by('-total_points', '-sum_goals', '-sum_assists', 'average_goals_against')
        return context

def get_stats_for_matchup(match):
    return Stat.objects.filter(matchup=match).exclude(
            Q(goals=None) & Q(assists=None)).exclude(
            Q(goals=0) & Q(assists=0)).order_by(
            '-goals', '-assists')

def get_goalies_for_matchup(match, home):
    if home:
        return Stat.objects.filter(matchup=match).filter(
                (Q(goals=0) | Q(goals=None)) & (Q(
                assists=0) | Q(assists=None))& Q(
                matchup__hometeam=F('team')))
    else:
        return Stat.objects.filter(matchup=match).filter(
                (Q(goals=0) | Q(goals=None)) & (Q(
                assists=0) | Q(assists=None))& Q(
                matchup__awayteam=F('team')))

def add_goals_for_matchups(matchups):
    return matchups.annotate(home_goals=Sum(
                Case(
                    When(hometeam=F('stat__team'), then=F('stat__goals')),
                    default=0,
                    output_field=IntegerField(),
                    )
                ),
            away_goals=Sum(
                Case(
                    When(awayteam=F('stat__team'), then=F('stat__goals')),
                    default=0,
                    output_field=IntegerField(),
                    )
                )
            )

def get_matches_for_division(division):
    return MatchUp.objects.filter(
            hometeam__division=division).order_by(
            '-week__date').filter(awayteam__is_active=True)

def schedule(request):
    context = {}
    context['schedule'] = OrderedDict()
    #Better to have a custom dictionary here than have 3 nested loops in the template
    for match in MatchUp.objects.order_by('week__date', 'time').filter(
            awayteam__is_active=True).filter(
            week__date__gte=datetime.datetime.today()).annotate(
            home_wins=Max('hometeam__team_stat__win')).annotate(
            home_losses=Max('hometeam__team_stat__loss')).annotate(
            home_ties=Max('hometeam__team_stat__tie')).annotate(
            away_wins=Max('awayteam__team_stat__win')).annotate(
            away_losses=Max('awayteam__team_stat__loss')).annotate(
            away_ties=Max('awayteam__team_stat__tie')):
        if not context['schedule'].get(str(match.week.date), False):
            context['schedule'][str(match.week.date)] = OrderedDict()
        if not context['schedule'][str(match.week.date)].get(
                str(match.awayteam.division), False):
            context['schedule'][str(match.week.date)][str(match.awayteam.division)] = []
        context['schedule'][str(match.week.date)][str(match.awayteam.division)].append(match)

    return render(request, "leagues/schedule.html", context=context)

def scores(request, division=1):
    context = {}
    context['divisions'] = Division.objects.all()
    context['matchups'] = OrderedDict()
    context['active_division'] = int(division)
    division = [i for i in Division.DIVISION_TYPE if context['active_division'] in i]
    #Check to see if the dvision from the URL is valid
    if len(division):
        #division ex: [(1, 'Sunday D1')]
        context['division_name'] = division[0][1]
        matchups = get_matches_for_division(context['active_division']).filter(
                week__date__lte=datetime.datetime.today())
        matchups = add_goals_for_matchups(matchups)
        for match in matchups:
            if not context['matchups'].get(str(match.week.date), False):
                context['matchups'][str(match.week.date)] = OrderedDict()
            context['matchups'][str(match.week.date)][str(match.id)] = {}
            context['matchups'][str(match.week.date)][str(match.id)]['match'] = match
            relevant_stats = get_stats_for_matchup(match)
            home_goalie_stats = get_goalies_for_matchup(match, home=True)
            away_goalie_stats= get_goalies_for_matchup(match, home=False)
            context['matchups'][str(match.week.date)][str(match.id)]['stats'] = relevant_stats
            context['matchups'][str(match.week.date)][str(match.id)]['home_goalie_stats'] = home_goalie_stats
            context['matchups'][str(match.week.date)][str(match.id)]['away_goalie_stats'] = away_goalie_stats
    return render(request, "leagues/scores.html", context=context)

