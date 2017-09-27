from django.conf.urls import url
from core.views import MatchUpDetailView
from core.views import TeamStatDetailView
from core.views import PlayerStatDetailView
import core.views as core_view

urlpatterns = [
	url(r'^roster/$', MatchUpDetailView.as_view(), name='rosters'),
	url(r'^roster/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})$', MatchUpDetailView.as_view(), name='rosters'),
	url(r'^team_standings/$', TeamStatDetailView.as_view(), name='team_standings'),
	url(r'^player_stats/$', PlayerStatDetailView.as_view(), name='player_stats'),
	url(r'^player_stats/(?P<season>[0-9]+)/$', PlayerStatDetailView.as_view(), name='player_stats'),
	url(r'^teams/(?P<team>[0-9]+)/$', core_view.teams, name='teams'),
	url(r'^schedule/$', core_view.schedule, name='schedule'),
	url(r'^scores/$', core_view.scores, name='scores'),
	url(r'^scores/(?P<division>[0-9])/$', core_view.scores, name='scores'),

]
