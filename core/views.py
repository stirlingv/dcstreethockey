from django.shortcuts import render
from django.http import HttpResponse
from django.template import loader
from django.db import models
import datetime
from django.views.generic.list import ListView
from django.utils import timezone
from django.utils import formats

from leagues.models import Season
from leagues.models import MatchUp
from leagues.models import Week
from leagues.models import Stat
from leagues.models import Roster
# Create your views here.

def home(request):
    context = {}
    # context["season"] = Season.objects.get(is_current_season=1)
    context["season"] = Season.objects.all()
    context["matchup"] = MatchUp.objects.all()
    context["week"] = Week.objects.all()
    
    # now = datetime.datetime.now().date
    # print now

    # next_game = Game.objects.filter(date__gt=datetime.date.today()).order_by("time")[0]
    # print next_game
    # previous_game = Game.objects.filter(date__lt=now).order_by(time)[0]
    
    # context["next_game"] = next_game
    # context["previous_game"] = previous

    return render(request, "core/home.html", context=context)

def leagues(request):
    return render(request, "leagues/index.html")


class MatchUpDetailView(ListView):
    context_object_name = 'matchup_list'

    def get_queryset(self):
        return MatchUp.objects.order_by('time')

    def get_context_data(self, **kwargs):
        context = super(MatchUpDetailView, self).get_context_data(**kwargs)
        context["season"] = Season.objects.all()
        context["roster"] = Roster.objects.all()
        context["stat"] = Stat.objects.all()
        return context

