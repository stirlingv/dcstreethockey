import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse

from leagues.models import Division, Season, Week


class CancellationBannerContextTest(TestCase):
    """
    Tests for the cancelled_games context variable passed to the home view.

    MatchUp.objects is mocked throughout this class because the home view
    uses a PostgreSQL-specific .distinct("week__date") query; these tests
    run on the SQLite test database.
    """

    def setUp(self):
        self.client = Client()
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.today = datetime.date.today()

    def _get_home(self):
        """
        Hit the home view with all external dependencies mocked out.
        Returns the response object.
        """
        with patch("core.views.MatchUp") as MockMatchUp, patch(
            "core.views.requests.get"
        ) as mock_get, patch.dict("os.environ", {"OPENWEATHERMAP_API_KEY": "fake_key"}):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"list": []}
            # MagicMock chaining: filter().order_by() / filter().order_by().distinct()
            # both return iterables (empty by default via MagicMock.__iter__)
            response = self.client.get(reverse("home"))
        return response

    def test_no_cancelled_games_when_no_cancelled_weeks(self):
        Week.objects.create(division=self.division, season=self.season, date=self.today)
        response = self._get_home()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cancelled_games"], {})

    def test_cancelled_game_appears_for_today(self):
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        response = self._get_home()
        self.assertIn(self.today, response.context["cancelled_games"])

    def test_past_cancelled_week_excluded_from_context(self):
        yesterday = self.today - datetime.timedelta(days=1)
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=yesterday,
            is_cancelled=True,
        )
        response = self._get_home()
        self.assertEqual(response.context["cancelled_games"], {})

    def test_active_week_not_in_cancelled_games(self):
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=False,
        )
        response = self._get_home()
        self.assertNotIn(self.today, response.context["cancelled_games"])

    def test_multiple_cancelled_divisions_grouped_by_date(self):
        division2 = Division.objects.create(division=2)
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        Week.objects.create(
            division=division2,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        response = self._get_home()
        self.assertIn(self.today, response.context["cancelled_games"])
        self.assertEqual(len(response.context["cancelled_games"][self.today]), 2)

    def test_cancelled_games_contains_division_display_names(self):
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        response = self._get_home()
        division_names = response.context["cancelled_games"][self.today]
        self.assertIn("Sunday D1", division_names)

    def test_future_cancelled_week_within_range_appears(self):
        future_date = self.today + datetime.timedelta(days=3)
        season2 = Season.objects.create(
            year=datetime.datetime.now().year + 1,
            season_type=2,
            is_current_season=False,
        )
        Week.objects.create(
            division=self.division,
            season=season2,
            date=future_date,
            is_cancelled=True,
        )
        response = self._get_home()
        self.assertIn(future_date, response.context["cancelled_games"])

    def test_cancelled_games_sorted_by_date(self):
        division2 = Division.objects.create(division=2)
        future_date = self.today + datetime.timedelta(days=2)
        season2 = Season.objects.create(
            year=datetime.datetime.now().year + 1,
            season_type=2,
            is_current_season=False,
        )
        Week.objects.create(
            division=division2,
            season=season2,
            date=future_date,
            is_cancelled=True,
        )
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        response = self._get_home()
        dates = list(response.context["cancelled_games"].keys())
        self.assertEqual(dates, sorted(dates))


class CancellationBannerTemplateTest(TestCase):
    """
    Tests that the cancellation banner HTML is rendered correctly in the
    home page response.
    """

    def setUp(self):
        self.client = Client()
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.today = datetime.date.today()

    def _get_home(self):
        with patch("core.views.MatchUp") as MockMatchUp, patch(
            "core.views.requests.get"
        ) as mock_get, patch.dict("os.environ", {"OPENWEATHERMAP_API_KEY": "fake_key"}):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"list": []}
            response = self.client.get(reverse("home"))
        return response

    def test_cancellation_banner_present_when_week_is_cancelled(self):
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        response = self._get_home()
        self.assertContains(response, "Games Cancelled")

    def test_cancellation_banner_absent_when_no_cancelled_weeks(self):
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=False,
        )
        response = self._get_home()
        self.assertNotContains(response, "Games Cancelled")

    def test_cancellation_banner_absent_for_past_cancelled_week(self):
        yesterday = self.today - datetime.timedelta(days=1)
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=yesterday,
            is_cancelled=True,
        )
        response = self._get_home()
        self.assertNotContains(response, "Games Cancelled")

    def test_cancellation_banner_shows_date(self):
        Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        response = self._get_home()
        formatted_date = self.today.strftime("%B %-d")
        self.assertContains(response, formatted_date)
