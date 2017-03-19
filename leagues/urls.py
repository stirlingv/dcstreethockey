from django.conf.urls import url
from core.views import MatchUpDetailView

urlpatterns = [
	url(r'^$', MatchUpDetailView.as_view(), name='matchup-detail'),
]