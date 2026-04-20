import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse

from leagues.models import Division, MatchUp, Season, Team, Week
from core.context_processors import _CANCELLED_GAMES_CACHE_KEY


def _make_team(name, division, season, color="Blue"):
    return Team.objects.create(
        team_name=name,
        team_color=color,
        division=division,
        season=season,
        is_active=True,
    )


def _make_matchup(week, away, home, time=None, is_cancelled=False):
    return MatchUp.objects.create(
        week=week,
        awayteam=away,
        hometeam=home,
        time=time or datetime.time(19, 0),
        is_cancelled=is_cancelled,
    )


class CancellationBannerContextTest(TestCase):
    """
    Tests for the cancelled_games context variable passed to the home view.

    MatchUp.objects is mocked throughout this class because the home view
    uses a PostgreSQL-specific .distinct("week__date") query; these tests
    run on the SQLite test database.
    """

    def setUp(self):
        cache.delete(_CANCELLED_GAMES_CACHE_KEY)
        self.client = Client()
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.today = datetime.date.today()
        self.away = _make_team("Away", self.division, self.season, "Blue")
        self.home = _make_team("Home", self.division, self.season, "Red")

    def _get_home(self):
        with patch("core.views.home.MatchUp") as MockMatchUp, patch(
            "core.views.home.requests.get"
        ) as mock_get, patch.dict("os.environ", {"OPENWEATHERMAP_API_KEY": "fake_key"}):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"list": []}
            response = self.client.get(reverse("home"))
        return response

    def _week(self, date=None, is_cancelled=False):
        return Week.objects.create(
            division=self.division,
            season=self.season,
            date=date or self.today,
            is_cancelled=is_cancelled,
        )

    def test_no_cancelled_games_when_no_cancelled_matchups(self):
        week = self._week()
        _make_matchup(week, self.away, self.home)
        response = self._get_home()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cancelled_games"], {})

    def test_cancelled_game_appears_for_today(self):
        week = self._week(is_cancelled=True)
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        self.assertIn(self.today, response.context["cancelled_games"])

    def test_past_cancelled_matchup_excluded_from_context(self):
        yesterday = self.today - datetime.timedelta(days=1)
        week = self._week(date=yesterday, is_cancelled=True)
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        self.assertEqual(response.context["cancelled_games"], {})

    def test_active_matchup_not_in_cancelled_games(self):
        week = self._week()
        _make_matchup(week, self.away, self.home, is_cancelled=False)
        response = self._get_home()
        self.assertNotIn(self.today, response.context["cancelled_games"])

    def test_multiple_cancelled_divisions_grouped_by_date(self):
        division2 = Division.objects.create(division=2)
        away2 = _make_team("Away2", division2, self.season, "Green")
        home2 = _make_team("Home2", division2, self.season, "Yellow")
        week1 = self._week(is_cancelled=True)
        week2 = Week.objects.create(
            division=division2, season=self.season, date=self.today, is_cancelled=True
        )
        _make_matchup(week1, self.away, self.home, is_cancelled=True)
        _make_matchup(week2, away2, home2, is_cancelled=True)
        response = self._get_home()
        self.assertIn(self.today, response.context["cancelled_games"])
        # Two divisions cancelled → two keys in the inner divisions dict
        self.assertEqual(
            len(response.context["cancelled_games"][self.today]["divisions"]), 2
        )

    def test_cancelled_games_contains_division_display_names(self):
        week = self._week(is_cancelled=True)
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        division_names = list(
            response.context["cancelled_games"][self.today]["divisions"].keys()
        )
        self.assertIn("Sunday D1", division_names)

    def test_cancelled_games_contains_matchup_objects(self):
        week = self._week(is_cancelled=True)
        matchup = _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        matchups = response.context["cancelled_games"][self.today]["divisions"][
            "Sunday D1"
        ]
        self.assertEqual(len(matchups), 1)
        self.assertEqual(matchups[0].pk, matchup.pk)

    def test_partial_flag_true_when_some_games_cancelled(self):
        week = self._week()
        away2 = _make_team("Away2", self.division, self.season, "Green")
        home2 = _make_team("Home2", self.division, self.season, "Yellow")
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        _make_matchup(week, away2, home2, is_cancelled=False)
        response = self._get_home()
        self.assertTrue(response.context["cancelled_games"][self.today]["partial"])

    def test_partial_flag_false_when_all_games_cancelled(self):
        week = self._week(is_cancelled=True)
        away2 = _make_team("Away2", self.division, self.season, "Green")
        home2 = _make_team("Home2", self.division, self.season, "Yellow")
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        _make_matchup(week, away2, home2, is_cancelled=True)
        response = self._get_home()
        self.assertFalse(response.context["cancelled_games"][self.today]["partial"])

    def test_future_cancelled_matchup_within_range_appears(self):
        future_date = self.today + datetime.timedelta(days=3)
        season2 = Season.objects.create(
            year=datetime.datetime.now().year + 1,
            season_type=2,
            is_current_season=False,
        )
        week = Week.objects.create(
            division=self.division,
            season=season2,
            date=future_date,
            is_cancelled=True,
        )
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        self.assertIn(future_date, response.context["cancelled_games"])

    def test_cancelled_games_sorted_by_date(self):
        division2 = Division.objects.create(division=2)
        away2 = _make_team("Away2", division2, self.season, "Green")
        home2 = _make_team("Home2", division2, self.season, "Yellow")
        future_date = self.today + datetime.timedelta(days=2)
        season2 = Season.objects.create(
            year=datetime.datetime.now().year + 1,
            season_type=2,
            is_current_season=False,
        )
        week_future = Week.objects.create(
            division=division2, season=season2, date=future_date, is_cancelled=True
        )
        week_today = self._week(is_cancelled=True)
        _make_matchup(week_future, away2, home2, is_cancelled=True)
        _make_matchup(week_today, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        dates = list(response.context["cancelled_games"].keys())
        self.assertEqual(dates, sorted(dates))


class CancellationBannerTemplateTest(TestCase):
    """Tests that the cancellation banner HTML renders correctly."""

    def setUp(self):
        cache.delete(_CANCELLED_GAMES_CACHE_KEY)
        self.client = Client()
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.today = datetime.date.today()
        self.away = _make_team("Away", self.division, self.season, "Blue")
        self.home = _make_team("Home", self.division, self.season, "Red")

    def _get_home(self):
        with patch("core.views.home.MatchUp") as MockMatchUp, patch(
            "core.views.home.requests.get"
        ) as mock_get, patch.dict("os.environ", {"OPENWEATHERMAP_API_KEY": "fake_key"}):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"list": []}
            response = self.client.get(reverse("home"))
        return response

    def _week(self, date=None, is_cancelled=False):
        return Week.objects.create(
            division=self.division,
            season=self.season,
            date=date or self.today,
            is_cancelled=is_cancelled,
        )

    def test_cancellation_banner_present_when_matchup_is_cancelled(self):
        week = self._week(is_cancelled=True)
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        self.assertContains(response, "Games Cancelled")

    def test_cancellation_banner_absent_when_no_cancelled_matchups(self):
        week = self._week()
        _make_matchup(week, self.away, self.home, is_cancelled=False)
        response = self._get_home()
        self.assertNotContains(response, "Games Cancelled")

    def test_cancellation_banner_absent_for_past_cancelled_matchup(self):
        yesterday = self.today - datetime.timedelta(days=1)
        week = self._week(date=yesterday, is_cancelled=True)
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        self.assertNotContains(response, "Games Cancelled")

    def test_cancellation_banner_shows_date(self):
        week = self._week(is_cancelled=True)
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        response = self._get_home()
        formatted_date = self.today.strftime("%B %-d")
        self.assertContains(response, formatted_date)

    def test_cancellation_banner_shows_game_time(self):
        week = self._week(is_cancelled=True)
        _make_matchup(
            week, self.away, self.home, time=datetime.time(19, 0), is_cancelled=True
        )
        response = self._get_home()
        self.assertContains(response, "7:00 PM")

    def test_partial_cancellation_shows_only_cancelled_game(self):
        week = self._week()
        _make_matchup(
            week, self.away, self.home, time=datetime.time(19, 0), is_cancelled=True
        )
        away2 = _make_team("Away2", self.division, self.season, "Green")
        home2 = _make_team("Home2", self.division, self.season, "Yellow")
        _make_matchup(
            week, away2, home2, time=datetime.time(20, 30), is_cancelled=False
        )
        response = self._get_home()
        self.assertContains(response, "Games Cancelled")
        self.assertContains(response, "7:00 PM")
        # 8:30 PM game is not cancelled — should not appear in banner
        self.assertNotContains(response, "8:30 PM")

    def test_banner_shows_team_names_for_cancelled_game(self):
        week = self._week(is_cancelled=True)
        _make_matchup(
            week, self.away, self.home, time=datetime.time(19, 0), is_cancelled=True
        )
        response = self._get_home()
        self.assertContains(response, "Away")
        self.assertContains(response, "Home")

    def test_banner_shows_some_games_cancelled_for_partial(self):
        week = self._week()
        away2 = _make_team("Away2", self.division, self.season, "Green")
        home2 = _make_team("Home2", self.division, self.season, "Yellow")
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        _make_matchup(week, away2, home2, is_cancelled=False)
        response = self._get_home()
        self.assertContains(response, "Some Games Cancelled")
        self.assertNotContains(response, "All Games Cancelled")

    def test_banner_shows_all_games_cancelled_for_full(self):
        week = self._week(is_cancelled=True)
        away2 = _make_team("Away2", self.division, self.season, "Green")
        home2 = _make_team("Home2", self.division, self.season, "Yellow")
        _make_matchup(week, self.away, self.home, is_cancelled=True)
        _make_matchup(week, away2, home2, is_cancelled=True)
        response = self._get_home()
        self.assertContains(response, "All Games Cancelled")
        self.assertNotContains(response, "Some Games Cancelled")
