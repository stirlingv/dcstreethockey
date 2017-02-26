from django.shortcuts import render
from django.http import HttpResponse
from django.template import loader

from leagues.models import Player
from leagues.models import League
# Create your views here.

def home(request):
    context = {}
    context["players"] = Player.objects.all()
    context["league"] = League.objects.all()
    return render(request, "core/home.html", context=context)

def leagues(request):
    return render(request, "leagues/index.html")