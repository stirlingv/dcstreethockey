from django.contrib import admin
from django.conf.urls.static import static
from django.conf import settings
from django.urls import include, path, re_path
import debug_toolbar
from core.views import (
    MatchUpDetailView,
    TeamStatDetailView,
    PlayerStatDetailView,
    PlayerAutocomplete,
    home,
    schedule,
    teams,
    scores,
    cups,
    PlayerAllTimeStats_list,
    player_view,
    player_trends_view,
)

urlpatterns = [
    path('', home, name='home'),  # Home page
    path('admin/', admin.site.urls),  # Admin panel
    path('__debug__/', include(debug_toolbar.urls)),  # Debug toolbar

    # Include core app URLs directly
    path('roster/', MatchUpDetailView.as_view(), name='rosters'),
    re_path(r'^roster/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})$', MatchUpDetailView.as_view(), name='rosters'),
    path('team_standings/', TeamStatDetailView.as_view(), name='team_standings'),
    path('player_stats/', PlayerStatDetailView.as_view(), name='player_stats'),
    path('player_stats/<int:season>/', PlayerStatDetailView.as_view(), name='player_stats'),
    path('teams/<int:team>/', teams, name='teams'),
    path('player/<int:player_id>/', player_view, name='player'),
    path('hof/', PlayerAllTimeStats_list, name='hof'),
    path('schedule/', schedule, name='schedule'),
    path('scores/', scores, name='scores'),
    re_path(r'^scores/(?P<division>[0-9])/$', scores, name='scores'),
    path('cups/', cups, name='cups'),
    re_path(r'^cups/(?P<division>[0-9])/$', cups, name='cups'),
    path('player_trends/', player_trends_view, name='player_trends'),
    path('player-autocomplete/', PlayerAutocomplete.as_view(), name='player-autocomplete'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)