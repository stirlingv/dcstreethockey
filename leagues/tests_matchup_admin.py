import datetime

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from leagues.models import (
    Division,
    MatchUp,
    Player,
    Season,
    Stat,
    Team,
    Team_Stat,
    Week,
)


def _make_fixture():
    season = Season.objects.create(year=2024, season_type=1, is_current_season=True)
    division = Division.objects.create(division=1)
    week = Week.objects.create(
        division=division, season=season, date=datetime.date(2024, 4, 1)
    )
    away_team = Team.objects.create(
        team_name="Away Team",
        team_color="Blue",
        division=division,
        season=season,
        is_active=True,
    )
    home_team = Team.objects.create(
        team_name="Home Team",
        team_color="Red",
        division=division,
        season=season,
        is_active=True,
    )
    matchup = MatchUp.objects.create(
        week=week,
        awayteam=away_team,
        hometeam=home_team,
        time=datetime.time(10, 0),
    )
    return season, division, week, away_team, home_team, matchup


class MatchUpAdminGameOutcomeGetTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin", password="password", email="admin@example.com"
        )
        self.client.force_login(self.superuser)
        (
            self.season,
            self.division,
            self.week,
            self.away_team,
            self.home_team,
            self.matchup,
        ) = _make_fixture()

    def _url(self):
        return reverse("admin:leagues_matchup_change", args=[self.matchup.pk])

    def test_change_view_returns_200(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_context_has_stat_forms(self):
        resp = self.client.get(self._url())
        self.assertIn("home_stat_form", resp.context)
        self.assertIn("away_stat_form", resp.context)

    def test_context_has_team_names(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.context["home_team_name"], "Home Team")
        self.assertEqual(resp.context["away_team_name"], "Away Team")

    def test_existing_team_stat_prepopulates_form(self):
        Team_Stat.objects.create(
            team=self.home_team,
            division=self.division,
            season=self.season,
            win=3,
            loss=1,
        )
        resp = self.client.get(self._url())
        home_form = resp.context["home_stat_form"]
        self.assertEqual(int(home_form["win"].value()), 3)


class MatchUpAdminGameOutcomeSaveTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin", password="password", email="admin@example.com"
        )
        self.client.force_login(self.superuser)
        (
            self.season,
            self.division,
            self.week,
            self.away_team,
            self.home_team,
            self.matchup,
        ) = _make_fixture()

    def _url(self):
        return reverse("admin:leagues_matchup_change", args=[self.matchup.pk])

    def _post_data(self, **overrides):
        base = {
            "week": self.week.pk,
            "time": "10:00 AM",
            "awayteam": self.away_team.pk,
            "hometeam": self.home_team.pk,
            "away_goalie_status": 3,
            "home_goalie_status": 3,
            "stat_set-TOTAL_FORMS": "0",
            "stat_set-INITIAL_FORMS": "0",
            "stat_set-MIN_NUM_FORMS": "0",
            "stat_set-MAX_NUM_FORMS": "1000",
            "home_stat-win": "2",
            "home_stat-otw": "0",
            "home_stat-loss": "1",
            "home_stat-otl": "0",
            "home_stat-tie": "0",
            "home_stat-goals_for": "10",
            "home_stat-goals_against": "7",
            "away_stat-win": "1",
            "away_stat-otw": "0",
            "away_stat-loss": "2",
            "away_stat-otl": "0",
            "away_stat-tie": "0",
            "away_stat-goals_for": "7",
            "away_stat-goals_against": "10",
        }
        base.update(overrides)
        return base

    def test_post_creates_team_stats_when_none_exist(self):
        self.client.post(self._url(), self._post_data())
        home_stat = Team_Stat.objects.filter(
            team=self.home_team, division=self.division, season=self.season
        ).first()
        away_stat = Team_Stat.objects.filter(
            team=self.away_team, division=self.division, season=self.season
        ).first()
        self.assertIsNotNone(home_stat)
        self.assertIsNotNone(away_stat)
        self.assertEqual(home_stat.win, 2)
        self.assertEqual(home_stat.loss, 1)
        self.assertEqual(home_stat.goals_for, 10)
        self.assertEqual(away_stat.win, 1)
        self.assertEqual(away_stat.loss, 2)

    def test_post_updates_existing_team_stats(self):
        Team_Stat.objects.create(
            team=self.home_team,
            division=self.division,
            season=self.season,
            win=1,
            loss=0,
            goals_for=5,
            goals_against=3,
        )
        self.client.post(self._url(), self._post_data())
        home_stat = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home_stat.win, 2)
        self.assertEqual(home_stat.goals_for, 10)
        # Exactly one record — no duplicate created
        self.assertEqual(
            Team_Stat.objects.filter(
                team=self.home_team, division=self.division, season=self.season
            ).count(),
            1,
        )

    def test_team_stats_not_duplicated_across_saves(self):
        self.client.post(self._url(), self._post_data())
        self.client.post(self._url(), self._post_data(**{"home_stat-win": "3"}))
        self.assertEqual(
            Team_Stat.objects.filter(
                team=self.home_team, division=self.division, season=self.season
            ).count(),
            1,
        )
        self.assertEqual(
            Team_Stat.objects.get(
                team=self.home_team, division=self.division, season=self.season
            ).win,
            3,
        )


class TeamStatAdminComputedFieldTest(TestCase):
    """
    Tests for the goals_from_stat_records computed field on TeamStatAdmin
    and TeamStatInline.
    """

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin", password="password", email="admin@example.com"
        )
        self.client.force_login(self.superuser)
        (
            self.season,
            self.division,
            self.week,
            self.away_team,
            self.home_team,
            self.matchup,
        ) = _make_fixture()
        self.player = Player.objects.create(
            first_name="Test", last_name="Player", is_active=True
        )

    def _make_team_stat(self, team, goals_for=0):
        return Team_Stat.objects.create(
            team=team,
            division=self.division,
            season=self.season,
            goals_for=goals_for,
        )

    def _make_stat(self, team, goals):
        return Stat.objects.create(
            matchup=self.matchup,
            player=self.player,
            team=team,
            goals=goals,
        )

    def _admin_instance(self):
        from leagues.admin import TeamStatAdmin

        return TeamStatAdmin(Team_Stat, admin.site)

    def test_unsaved_object_returns_placeholder(self):
        ts = Team_Stat()
        result = self._admin_instance().goals_from_stat_records(ts)
        self.assertEqual(result, "—")

    def test_matching_gf_shows_checkmark(self):
        ts = self._make_team_stat(self.home_team, goals_for=3)
        self._make_stat(self.home_team, goals=3)
        result = str(self._admin_instance().goals_from_stat_records(ts))
        self.assertIn("✓", result)
        self.assertIn("3", result)
        self.assertNotIn("⚠", result)

    def test_gf_higher_than_stat_records_shows_warning(self):
        # GF manually set to 10, but only 7 goals in Stat records
        ts = self._make_team_stat(self.home_team, goals_for=10)
        self._make_stat(self.home_team, goals=7)
        result = str(self._admin_instance().goals_from_stat_records(ts))
        self.assertIn("⚠", result)
        self.assertIn("7", result)

    def test_no_stat_records_shows_zero(self):
        ts = self._make_team_stat(self.home_team, goals_for=5)
        result = str(self._admin_instance().goals_from_stat_records(ts))
        self.assertIn("⚠", result)
        self.assertIn("0", result)

    def test_stat_records_scoped_to_season_and_division(self):
        # Stat goals from a different season should not be counted
        other_season = Season.objects.create(year=2023, season_type=1)
        other_week = Week.objects.create(
            division=self.division,
            season=other_season,
            date=datetime.date(2023, 4, 1),
        )
        other_matchup = MatchUp.objects.create(
            week=other_week,
            awayteam=self.away_team,
            hometeam=self.home_team,
            time=datetime.time(10, 0),
        )
        Stat.objects.create(
            matchup=other_matchup,
            player=self.player,
            team=self.home_team,
            goals=5,
        )
        ts = self._make_team_stat(self.home_team, goals_for=0)
        result = str(self._admin_instance().goals_from_stat_records(ts))
        # The 5 goals from the other season should not appear
        self.assertIn("✓", result)
        self.assertIn("0", result)

    def test_team_stat_change_view_returns_200(self):
        ts = self._make_team_stat(self.home_team, goals_for=3)
        url = reverse("admin:leagues_team_stat_change", args=[ts.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
