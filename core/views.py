import datetime
from datetime import timedelta
from collections import OrderedDict

from django.shortcuts import render
from django.views.generic.list import ListView
from django.db.models.functions import Lower, Coalesce
from django.db.models import Sum, Q, Max
from django.db.models import F, When, IntegerField, Case

from leagues.models import Season
from leagues.models import Division
from leagues.models import MatchUp
from leagues.models import Stat
from leagues.models import Roster
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

        context['player_stat_list'] = context['player_stat_list'].values(
            'player__first_name',
            'player__last_name',
            'team__division',
            'team__team_name',
            'team__season',
            'season__is_current_season',
            'roster__position1',
            'roster__position2'
        ).annotate(sum_goals=Coalesce(Sum('goals'), 0),
                   sum_assists=Coalesce(Sum('assists'), 0),
                   sum_goals_against=Coalesce(Sum('goals_against'), 0),
                   sum_empty_net=Coalesce(Sum('empty_net'), 0),
                   total_points=Coalesce(Sum('goals'),0) + Coalesce(Sum('assists'),0),
        ).order_by('-total_points', '-sum_goals', '-sum_assists')

        return context

def get_stats_for_matchup(match):
    print "Getting stats for match: ", match.id
    return Stat.objects.filter(matchup=match).exclude(Q(
            goals=None) & Q(assists=None)).order_by('-assists').order_by('-goals')

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
    try:
        return MatchUp.objects.filter(
                     hometeam__division=division).order_by(
                     '-week__date').filter(awayteam__is_active=True)
    except:
        return []

def get_schedule_for_division(division):
    try:
        return MatchUp.objects.filter(
                     hometeam__division=division).order_by(
                     '-week__date').distinct('week__date').filter(
                     awayteam__is_active=True)
    except:
        return []

def schedule(request):
    context = {}
    context["schedule"] = OrderedDict()

    for match in MatchUp.objects.order_by('week__date', 'time').filter(
            awayteam__is_active=True).filter(
            week__date__gte=datetime.datetime.today()).annotate(
            home_wins=Max('hometeam__team_stat__win')).annotate(
            home_losses=Max('hometeam__team_stat__loss')).annotate(
            home_ties=Max('hometeam__team_stat__tie')).annotate(
            away_wins=Max('awayteam__team_stat__win')).annotate(
            away_losses=Max('awayteam__team_stat__loss')).annotate(
            away_ties=Max('awayteam__team_stat__tie')):
        if not context["schedule"].get(str(match.week.date), False):
            context["schedule"][str(match.week.date)] = OrderedDict()
        if not context["schedule"][str(match.week.date)].get(
                str(match.awayteam.division), False):
            context["schedule"][str(match.week.date)][str(match.awayteam.division)] = []
        context["schedule"][str(match.week.date)][str(match.awayteam.division)].append(match)

    return render(request, "leagues/schedule.html", context=context)

def scores(request, division=1):
    context = {}
    context["divisions"] = Division.objects.all()
    context["matchups"]  = MatchUp.objects.order_by('week__date','time').filter(awayteam__is_active=True)
    for match in context["matchups"]:
        print "Match: " + str(match)
    context["schedule"] = MatchUp.objects.order_by('-week__date').distinct(
            'week__date').filter(awayteam__is_active=True)
    context['stats'] = []
    context['active_division'] = int(division)
    #Check to see if the dvision from the URL is valid
    if len([i for i in Division.DIVISION_TYPE if context['active_division'] in i]):
        try:
            stats = []
            context['matchups'] = get_matches_for_division(context['active_division'])
            context['schedule'] = get_schedule_for_division(context['active_division'])
            for match in context['matchups']:
                relevant_stats = get_stats_for_matchup(match)
                stats.extend(relevant_stats)
            context['stats'] = stats

        except Exception as e:
            print e
    context['matchups'] = add_goals_for_matchups(context['matchups'])
    return render(request, "leagues/scores.html", context=context)

