from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.views import PlayerStatDetailView
from dcstreethockey.context_processors import draft_signup_url
from leagues.models import (
    Division,
    DraftSession,
    Player,
    Roster,
    Season,
    Stat,
    Team,
    Week,
)


class PlayerStatDetailViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.season = Season.objects.create(
            year=2023, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.team = Team.objects.create(
            team_name="Test Team",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.player = Player.objects.create(first_name="John", last_name="Doe")
        self.roster = Roster.objects.create(
            player=self.player,
            team=self.team,
            position1=1,
            is_captain=False,
            player_number=None,
        )
        self.stat = Stat.objects.create(
            player=self.player, team=self.team, goals=5, assists=3
        )

    def test_get_queryset(self):
        request = self.factory.get(reverse("player_stats"))
        view = PlayerStatDetailView()
        view.request = request

        queryset = view.get_queryset()
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first(), self.stat)

    def test_get_context_data(self):
        request = self.factory.get(reverse("player_stats"))
        view = PlayerStatDetailView()
        view.request = request
        view.kwargs = {}  # Initialize kwargs as empty dict (default season)

        response = view.get(request)
        context = response.context_data

        self.assertIn("seasons", context)
        self.assertIn("active_season", context)
        self.assertIn("player_stat_list", context)
        self.assertEqual(context["active_season"], 0)

        player_stat_list = context["player_stat_list"]
        self.assertIn(str(self.division), player_stat_list)
        self.assertEqual(len(player_stat_list[str(self.division)]), 1)
        self.assertEqual(player_stat_list[str(self.division)][0]["first_name"], "John")
        self.assertEqual(player_stat_list[str(self.division)][0]["last_name"], "Doe")


class DraftSignupUrlContextProcessorTest(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.season = Season.objects.create(
            year=2024, season_type=3, is_current_season=True
        )
        self.division = Division.objects.create(division=3)

    def _make_request(self):
        return self.factory.get("/")

    def test_returns_none_when_no_open_signup(self):
        ctx = draft_signup_url(self._make_request())
        self.assertIsNone(ctx["draft_signup_url"])

    def test_returns_url_when_signup_is_open(self):
        DraftSession.objects.create(season=self.season, signups_open=True)
        ctx = draft_signup_url(self._make_request())
        self.assertIsNotNone(ctx["draft_signup_url"])
        self.assertIn(str(self.season.pk), ctx["draft_signup_url"])

    def test_returns_none_when_signup_is_closed(self):
        DraftSession.objects.create(season=self.season, signups_open=False)
        ctx = draft_signup_url(self._make_request())
        self.assertIsNone(ctx["draft_signup_url"])
