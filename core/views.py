from django.shortcuts import render
import datetime
from datetime import timedelta
from django.views.generic.list import ListView
from django.db.models.functions import Lower
from django.db.models.functions import Lower, Coalesce
from django.db.models import Sum
from django.db.models import F, Count, Value

from leagues.models import Season
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
                   total_points=Coalesce(Sum('goals') + Sum('assists'),0),
        ).order_by('-total_points', '-sum_goals', '-sum_assists')

        return context

def schedule(request):
    context = {}
    # context["season"] = Season.objects.get(is_current_season=1)
    context["season"] = Season.objects.all()
    context["matchup"]  = MatchUp.objects.order_by('week__date','time').filter(awayteam__is_active=True)  
    context["game_days"]  = MatchUp.objects.order_by('week__date').distinct('week__date').filter(awayteam__is_active=True)
    return render(request, "leagues/schedule.html", context=context)
        
