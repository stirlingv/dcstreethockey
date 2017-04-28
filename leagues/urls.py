from django.conf.urls import url
from core.views import MatchUpDetailView
from core.views import TeamStatDetailView

urlpatterns = [
	url(r'^roster/$', MatchUpDetailView.as_view(), name='rosters'),
	url(r'^team_standings/$', TeamStatDetailView.as_view(), name='team_standings'),
]