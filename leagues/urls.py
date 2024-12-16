from django.urls import path, re_path
from core.views import MatchUpDetailView, TeamStatDetailView, PlayerStatDetailView, PlayerAutocomplete
import core.views as core_view

urlpatterns = [
    path('roster/', MatchUpDetailView.as_view(), name='rosters'),
    re_path(r'^roster/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})$', MatchUpDetailView.as_view(), name='rosters'),
    path('team_standings/', TeamStatDetailView.as_view(), name='team_standings'),
    path('player_stats/', PlayerStatDetailView.as_view(), name='player_stats'),
    path('player_stats/<int:season>/', PlayerStatDetailView.as_view(), name='player_stats'),
    path('teams/<int:team>/', core_view.teams, name='teams'),
    path('player/<int:player_id>/', core_view.player_view, name='player'),  # Updated to use player_id
    path('hof/', core_view.PlayerAllTimeStats_list, name='hof'),
    path('schedule/', core_view.schedule, name='schedule'),
    path('scores/', core_view.scores, name='scores'),
    re_path(r'^scores/(?P<division>[0-9])/$', core_view.scores, name='scores'),
    path('cups/', core_view.cups, name='cups'),
    re_path(r'^cups/(?P<division>[0-9])/$', core_view.cups, name='cups'),
    path('player_trends/', core_view.player_trends_view, name='player_trends'),
    path('player-autocomplete/', PlayerAutocomplete.as_view(), name='player-autocomplete'),
]

app_name = "leagues"
