from django.shortcuts import render
from django.http import HttpResponse
from django.template import loader

from leagues.models import Player
from leagues.models import League
from leagues.models import Game
from leagues.models import Season
# Create your views here.

def home(request):
    context = {}
    context["season"] = Season.objects.get(is_current_season=1)
    context["players"] = Player.objects.all()
    context["league"] = League.objects.all()
    
    next = Game.objects.filter(categories__name="date").filter(name__gt=date.today()).order_by("time")[0]
    previous = Game.objects.filter(categories__name="date").filter(name__lt=date.today()).order_by("-time")[0]
    
    context["next"] = next
    context["previous"] = previous

    return render(request, "core/home.html", context=context)

def leagues(request):
    return render(request, "leagues/index.html")