from django.shortcuts import render
import datetime
from datetime import timedelta
from django.views.generic.list import ListView
from django.db.models.functions import Lower
from django.db.models.functions import Lower, Coalesce
from django.db.models import Sum
from django.db.models import F, Count, Value

from leagues.models import Season
from leagues.models import Division
from leagues.models import MatchUp
from leagues.models import Stat
from leagues.models import Roster
from leagues.models import Team_Stat
from leagues.models import Week
from leagues.models import Player
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
    return Stat.objects.filter(matchup=match).exclude(
            goals=None).order_by('-assists').order_by('-goals')

def get_matches_for_date(year, month, day):
    try:
        return MatchUp.objects.filter(
                     week__date__year=int(year)).filter(
                     week__date__month=int(month)).filter(
                     week__date__day=int(day)).order_by(
                     '-week__date').filter(awayteam__is_active=True)
    except:
        return []

def get_schedule_for_date(year, month, day):
    try:
        return MatchUp.objects.filter(
                     week__date__year=int(year)).filter(
                     week__date__month=int(month)).filter(
                     week__date__day=int(day)).order_by(
                     '-week__date').distinct('week__date').filter(
                     awayteam__is_active=True)
    except:
        return []

def schedule(request, month="0", day="0", year="0"):
    print "WOAH rendering schedule", month, day, year
    context = {}
    # context["season"] = Season.objects.get(is_current_season=1)
    context["season"] = Season.objects.all()
    context["divisions"] = Division.objects.all()
    context["matchups"]  = MatchUp.objects.order_by('week__date','time').filter(awayteam__is_active=True)
    context["schedule"] = MatchUp.objects.order_by('-week__date').distinct(
            'week__date').filter(awayteam__is_active=True)
    context["game_days"] =[]
    context['stats'] = []

    for mdate in MatchUp.objects.order_by('-week__date','time').distinct(
                'week__date').values('week__date'):
        context["game_days"].append({'day': '{:02d}'.format(mdate['week__date'].day),
            'month': '{:02d}'.format(mdate['week__date'].month),
            'year': mdate['week__date'].year, 'date': mdate['week__date']})
    if month is not "0" and day is not "0" and year is not "0":
        try:
            stats = []
            context['matchups'] = get_matches_for_date(year, month, day)
            context['schedule'] = get_schedule_for_date(year, month, day)
            for match in context['matchups']:
                relevant_stats = get_stats_for_matchup(match)
                stats.extend(relevant_stats)
            context['stats'] = stats

        except Exception as e:
            print e
            print "Invalid date: ", month, day, year
    return render(request, "leagues/schedule.html", context=context)

