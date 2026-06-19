import datetime
import json

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
    TeamPhoto,
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

    def test_change_view_renders_live_game_score_summary(self):
        # The per-game score box (live from player stats) and the team-name
        # JS vars the script needs to render the shootout line must be present.
        resp = self.client.get(self._url())
        html = resp.content.decode()
        self.assertIn('id="game-score-summary"', html)
        self.assertIn('id="score-home"', html)
        self.assertIn('id="score-away"', html)
        self.assertIn('id="game-score-shootout"', html)
        self.assertIn('id="goalie-stats-warning"', html)
        self.assertIn('var statHomeTeamName = "Home Team";', html)
        self.assertIn('var statAwayTeamName = "Away Team";', html)


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


class MatchUpAdminGFGAAutoComputeTest(TestCase):
    """
    When Stat rows exist for a team this season, saving the game outcome form
    should override the manually-entered GF/GA with values derived from Stat
    records. When no Stat rows exist, the form values are used as-is.
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

    def _url(self):
        return reverse("admin:leagues_matchup_change", args=[self.matchup.pk])

    def _player(self, name="P"):
        return Player.objects.create(first_name=name, last_name="X", is_active=True)

    def _post(self, **overrides):
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
            "home_stat-win": "1",
            "home_stat-otw": "0",
            "home_stat-loss": "0",
            "home_stat-otl": "0",
            "home_stat-tie": "0",
            "home_stat-goals_for": "99",
            "home_stat-goals_against": "99",
            "away_stat-win": "0",
            "away_stat-otw": "0",
            "away_stat-loss": "1",
            "away_stat-otl": "0",
            "away_stat-tie": "0",
            "away_stat-goals_for": "99",
            "away_stat-goals_against": "99",
        }
        base.update(overrides)
        return base

    def test_gf_ga_from_form_when_no_stats(self):
        self.client.post(self._url(), self._post())
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 99)
        self.assertEqual(home.goals_against, 99)

    def test_gf_ga_auto_computed_when_stats_exist(self):
        p = self._player()
        Stat.objects.create(
            matchup=self.matchup, team=self.home_team, player=p, goals=3, assists=0
        )
        Stat.objects.create(
            matchup=self.matchup, team=self.away_team, player=p, goals=1, assists=0
        )
        self.client.post(self._url(), self._post())
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        away = Team_Stat.objects.get(
            team=self.away_team, division=self.division, season=self.season
        )
        # Form said 99 for both; stats override to actual totals
        self.assertEqual(home.goals_for, 3)
        self.assertEqual(home.goals_against, 1)
        self.assertEqual(away.goals_for, 1)
        self.assertEqual(away.goals_against, 3)

    def test_deleting_all_stats_via_inline_zeroes_gf_ga(self):
        """
        Marking all stat rows for deletion and saving should reset GF and GA to 0.
        Without the had_stats fix, stat_qs.exists() is False after the inline delete
        so the recompute branch was skipped, leaving GF at its previous value.
        """
        p = self._player()
        stat = Stat.objects.create(
            matchup=self.matchup, team=self.home_team, player=p, goals=3, assists=0
        )
        away_stat = Stat.objects.create(
            matchup=self.matchup, team=self.away_team, player=p, goals=1, assists=0
        )
        self.client.post(self._url(), self._post())
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 3)

        # Second save: mark every stat row for deletion via the inline.
        self.client.post(
            self._url(),
            self._post(
                **{
                    "stat_set-TOTAL_FORMS": "2",
                    "stat_set-INITIAL_FORMS": "2",
                    "stat_set-0-id": stat.pk,
                    "stat_set-0-matchup": self.matchup.pk,
                    "stat_set-0-player": p.pk,
                    "stat_set-0-team": self.home_team.pk,
                    "stat_set-0-goals": "3",
                    "stat_set-0-assists": "0",
                    "stat_set-0-DELETE": "on",
                    "stat_set-1-id": away_stat.pk,
                    "stat_set-1-matchup": self.matchup.pk,
                    "stat_set-1-player": p.pk,
                    "stat_set-1-team": self.away_team.pk,
                    "stat_set-1-goals": "1",
                    "stat_set-1-assists": "0",
                    "stat_set-1-DELETE": "on",
                }
            ),
        )
        home.refresh_from_db()
        self.assertEqual(home.goals_for, 0)
        self.assertEqual(home.goals_against, 0)

    def test_deleting_some_stats_reduces_gf(self):
        """Deleting one stat row reduces GF by that player's goals on the next save."""
        p1 = self._player("A")
        p2 = self._player("B")
        Stat.objects.create(
            matchup=self.matchup, team=self.home_team, player=p1, goals=2, assists=0
        )
        stat2 = Stat.objects.create(
            matchup=self.matchup, team=self.home_team, player=p2, goals=1, assists=0
        )
        self.client.post(self._url(), self._post())
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 3)

        # Delete one stat directly (e.g. via the Stat admin), then re-save the
        # matchup. stat_qs.exists() is still True (stat1 remains) so the normal
        # recompute path runs and drops GF from 3 to 2.
        stat2.delete()
        self.client.post(self._url(), self._post())
        home.refresh_from_db()
        self.assertEqual(home.goals_for, 2)

    def test_ga_accumulates_across_all_season_opponents(self):
        """GA is the total of all goals conceded all season, not just tonight's opponent."""
        third_team = Team.objects.create(
            team_name="Third Team",
            team_color="Green",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        week2 = Week.objects.create(
            division=self.division,
            season=self.season,
            date=datetime.date(2024, 4, 8),
        )
        matchup2 = MatchUp.objects.create(
            week=week2,
            awayteam=third_team,
            hometeam=self.home_team,
            time=datetime.time(10, 0),
        )
        p = self._player()
        # Earlier game: home scored 5, conceded 2 vs third_team
        Stat.objects.create(
            matchup=matchup2, team=self.home_team, player=p, goals=5, assists=0
        )
        Stat.objects.create(
            matchup=matchup2, team=third_team, player=p, goals=2, assists=0
        )
        # Tonight: home scored 3, away scored 1
        Stat.objects.create(
            matchup=self.matchup, team=self.home_team, player=p, goals=3, assists=0
        )
        Stat.objects.create(
            matchup=self.matchup, team=self.away_team, player=p, goals=1, assists=0
        )
        self.client.post(self._url(), self._post())
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 8)  # 5 + 3
        self.assertEqual(home.goals_against, 3)  # 2 + 1


class TeamAdminAutoCreateTeamStatTest(TestCase):
    """
    When a new Team is saved via the admin, a blank Team_Stat record should be
    created automatically so standings tracking can begin immediately.
    """

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin", password="password", email="admin@example.com"
        )
        self.client.force_login(self.superuser)
        self.division = Division.objects.create(division=1)
        self.season = Season.objects.create(
            year=2025, season_type=1, is_current_season=True
        )
        self.team_photo = TeamPhoto.objects.create()

    def _add_url(self):
        return reverse("admin:leagues_team_add")

    def _post(self, **overrides):
        base = {
            "team_name": "New Team",
            "team_color": "Blue",
            "division": self.division.pk,
            "season": self.season.pk,
            "team_photo": self.team_photo.pk,
            "is_active": "on",
            "team_stat_set-TOTAL_FORMS": "0",
            "team_stat_set-INITIAL_FORMS": "0",
            "team_stat_set-MIN_NUM_FORMS": "0",
            "team_stat_set-MAX_NUM_FORMS": "1000",
            "roster_set-TOTAL_FORMS": "0",
            "roster_set-INITIAL_FORMS": "0",
            "roster_set-MIN_NUM_FORMS": "0",
            "roster_set-MAX_NUM_FORMS": "1000",
        }
        base.update(overrides)
        return base

    def test_team_stat_auto_created_for_new_team(self):
        self.client.post(self._add_url(), self._post())
        team = Team.objects.get(team_name="New Team")
        self.assertEqual(
            Team_Stat.objects.filter(
                team=team, division=self.division, season=self.season
            ).count(),
            1,
        )
        ts = Team_Stat.objects.get(
            team=team, division=self.division, season=self.season
        )
        self.assertEqual(ts.win, 0)
        self.assertEqual(ts.goals_for, 0)

    def test_no_duplicate_when_inline_also_saves_team_stat(self):
        data = self._post(
            **{
                "team_stat_set-TOTAL_FORMS": "1",
                "team_stat_set-0-division": self.division.pk,
                "team_stat_set-0-season": self.season.pk,
                "team_stat_set-0-win": "2",
                "team_stat_set-0-otw": "0",
                "team_stat_set-0-loss": "1",
                "team_stat_set-0-otl": "0",
                "team_stat_set-0-tie": "0",
                "team_stat_set-0-goals_for": "6",
                "team_stat_set-0-goals_against": "4",
            }
        )
        self.client.post(self._add_url(), data)
        team = Team.objects.get(team_name="New Team")
        self.assertEqual(
            Team_Stat.objects.filter(
                team=team, division=self.division, season=self.season
            ).count(),
            1,
        )
        # Inline's values should be preserved (get_or_create found the inline-created record)
        ts = Team_Stat.objects.get(
            team=team, division=self.division, season=self.season
        )
        self.assertEqual(ts.win, 2)
        self.assertEqual(ts.goals_for, 6)


class MatchUpAdminShootoutSaveTest(TestCase):
    """Admin save_model correctly persists shootout_winner_is_home."""

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
            "home_stat-win": "0",
            "home_stat-otw": "1",
            "home_stat-loss": "0",
            "home_stat-otl": "0",
            "home_stat-tie": "0",
            "home_stat-goals_for": "4",
            "home_stat-goals_against": "3",
            "away_stat-win": "0",
            "away_stat-otw": "0",
            "away_stat-loss": "0",
            "away_stat-otl": "1",
            "away_stat-tie": "0",
            "away_stat-goals_for": "3",
            "away_stat-goals_against": "4",
        }
        base.update(overrides)
        return base

    def test_home_wins_shootout(self):
        self.client.post(self._url(), self._post_data(shootout_winner_is_home="true"))
        self.matchup.refresh_from_db()
        self.assertIs(self.matchup.shootout_winner_is_home, True)

    def test_away_wins_shootout(self):
        self.client.post(self._url(), self._post_data(shootout_winner_is_home="false"))
        self.matchup.refresh_from_db()
        self.assertIs(self.matchup.shootout_winner_is_home, False)

    def test_no_shootout_saved_as_none(self):
        self.client.post(self._url(), self._post_data(shootout_winner_is_home=""))
        self.matchup.refresh_from_db()
        self.assertIsNone(self.matchup.shootout_winner_is_home)

    def test_postseason_clears_shootout_winner(self):
        self.client.post(
            self._url(),
            self._post_data(shootout_winner_is_home="true", is_postseason="on"),
        )
        self.matchup.refresh_from_db()
        self.assertIsNone(self.matchup.shootout_winner_is_home)


class MatchUpAdminPriorGFGAContextTest(TestCase):
    """
    The change form passes per-team "prior" GF/GA (every game this
    season/division except tonight's) to the GF/GA auto-fill JS.

    Regression: GA must sum the goals scored by *every* opponent across the
    team's games, not tonight's opponent's season-total goals. With multiple
    opponents the old code reported the wrong GA (e.g. a team that conceded
    2 + 8 + 2 = 12 was told its GA "should" be tonight's opponent's 4 goals).
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
            self.tonight_opponent,  # "away" team in tonight's game
            self.team,  # team of interest ("home" tonight) — the Vita Dipas
            self.tonight_matchup,
        ) = _make_fixture()

    def _player(self, name):
        return Player.objects.create(first_name=name, last_name="X", is_active=True)

    def _team(self, name):
        return Team.objects.create(
            team_name=name,
            team_color="Green",
            division=self.division,
            season=self.season,
            is_active=True,
        )

    def _matchup(self, home, away):
        return MatchUp.objects.create(
            week=self.week, hometeam=home, awayteam=away, time=datetime.time(11, 0)
        )

    def _goals(self, matchup, team, goals):
        Stat.objects.create(
            matchup=matchup,
            team=team,
            player=self._player(f"{team.team_name}-{matchup.pk}"),
            goals=goals,
            assists=0,
        )

    def test_prior_ga_sums_all_opponents_not_tonight_opponent(self):
        opp_a = self._team("Opp A")
        opp_b = self._team("Opp B")

        # Prior game 1: team won 4-2 (team at home).
        g1 = self._matchup(home=self.team, away=opp_a)
        self._goals(g1, self.team, 4)
        self._goals(g1, opp_a, 2)

        # Prior game 2: team lost 3-8 (team on the road — exercises the
        # Q(awayteam=team) branch of the prior-games query).
        g2 = self._matchup(home=opp_b, away=self.team)
        self._goals(g2, self.team, 3)
        self._goals(g2, opp_b, 8)

        # Tonight's opponent has only scored 2 goals all season; the old GA
        # logic would wrongly suggest the team's GA is 2.
        self._goals(self.tonight_matchup, self.tonight_opponent, 2)

        resp = self.client.get(
            reverse("admin:leagues_matchup_change", args=[self.tonight_matchup.pk])
        )
        self.assertEqual(resp.status_code, 200)
        prior = json.loads(resp.context["stat_prior_json"])

        # Team is the "home" side tonight. Prior GF = 4 + 3 = 7.
        self.assertEqual(prior["home_gf"], 7)
        # Prior GA = goals from BOTH opponents = 2 + 8 = 10 (not tonight's 2).
        self.assertEqual(prior["home_ga"], 10)

    def test_prior_excludes_tonights_matchup(self):
        # Stats already saved for tonight must NOT be counted in the prior
        # totals (the JS adds tonight's goals separately from the live form).
        self._goals(self.tonight_matchup, self.team, 5)
        self._goals(self.tonight_matchup, self.tonight_opponent, 1)

        resp = self.client.get(
            reverse("admin:leagues_matchup_change", args=[self.tonight_matchup.pk])
        )
        prior = json.loads(resp.context["stat_prior_json"])
        self.assertEqual(prior["home_gf"], 0)
        self.assertEqual(prior["home_ga"], 0)
        self.assertEqual(prior["away_gf"], 0)
        self.assertEqual(prior["away_ga"], 0)
