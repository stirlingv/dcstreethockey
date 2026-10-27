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
    Roster,
    Season,
    Stat,
    Team,
    Team_Stat,
    TeamPhoto,
    Week,
)


def _make_fixture(standings_from_games=False):
    # Hand-kept standings by default: most of these tests cover the way
    # every season before Fall 2026 was entered.
    season = Season.objects.create(
        standings_from_games=standings_from_games,
        year=2024,
        season_type=1,
        is_current_season=True,
    )
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
        # GF/GA are summed from player stats, never taken from the form.
        self.assertEqual(home_stat.goals_for, 0)
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
        # GF/GA are not taken from the form: with no player stats on this
        # game, the stored value stays as it was.
        self.assertEqual(home_stat.goals_for, 5)
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

    def test_gf_ga_are_never_taken_from_the_form(self):
        # GF/GA are summed from player stats; a posted value is ignored.
        self.client.post(self._url(), self._post())
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 0)
        self.assertEqual(home.goals_against, 0)

    def test_gf_ga_shown_read_only_on_hand_kept_season(self):
        html = self.client.get(self._url()).content.decode()
        self.assertNotIn('name="home_stat-goals_for"', html)
        self.assertIn("summed from player stats when you save", html)

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
            standings_from_games=False, year=2025, season_type=1, is_current_season=True
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

    def test_record_row_cannot_be_added_by_hand(self):
        """The season record is created from the team's own division and
        season, so the inline no longer asks for either or lets a row be
        added: a posted new row is ignored and exactly one record exists."""
        data = self._post(
            **{
                "team_stat_set-TOTAL_FORMS": "1",
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
        rows = Team_Stat.objects.filter(team=team)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(
            (rows[0].division, rows[0].season), (self.division, self.season)
        )
        self.assertEqual(rows[0].win, 0)

    def test_inline_does_not_ask_for_division_or_season(self):
        self.client.post(self._add_url(), self._post())
        team = Team.objects.get(team_name="New Team")
        html = self.client.get(
            reverse("admin:leagues_team_change", args=[team.pk])
        ).content.decode()
        self.assertNotIn('name="team_stat_set-0-division"', html)
        self.assertNotIn('name="team_stat_set-0-season"', html)
        # Hand-kept season: the record itself is still editable.
        self.assertIn('name="team_stat_set-0-win"', html)


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


class MatchUpAdminPostseasonTest(TestCase):
    """
    Postseason games must not affect the regular-season standings record:
    no win/loss is written to Team_Stat, and playoff goals are excluded from
    the GF/GA recompute. The change form replaces the Game Outcome section with
    a note for playoff games.
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

    def _url(self, matchup):
        return reverse("admin:leagues_matchup_change", args=[matchup.pk])

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
            "home_stat-goals_for": "5",
            "home_stat-goals_against": "2",
            "away_stat-win": "0",
            "away_stat-otw": "0",
            "away_stat-loss": "1",
            "away_stat-otl": "0",
            "away_stat-tie": "0",
            "away_stat-goals_for": "2",
            "away_stat-goals_against": "5",
        }
        base.update(overrides)
        return base

    def test_postseason_change_view_shows_playoff_note_not_outcome(self):
        self.matchup.is_postseason = True
        self.matchup.save()
        html = self.client.get(self._url(self.matchup)).content.decode()
        self.assertIn("Playoff game", html)
        self.assertNotIn('class="module game-outcome-module"', html)
        # The W/L record inputs are not rendered for playoff games.
        self.assertNotIn('name="home_stat-win"', html)

    def test_regular_change_view_shows_game_outcome(self):
        html = self.client.get(self._url(self.matchup)).content.decode()
        self.assertNotIn("Playoff game", html)
        self.assertIn('class="module game-outcome-module"', html)
        self.assertIn('name="home_stat-win"', html)

    def test_postseason_outcome_not_written_to_team_stat(self):
        self.matchup.is_postseason = True
        self.matchup.save()
        self.client.post(self._url(self.matchup), self._post(is_postseason="on"))
        self.assertFalse(
            Team_Stat.objects.filter(
                team=self.home_team, division=self.division, season=self.season
            ).exists()
        )
        self.assertFalse(
            Team_Stat.objects.filter(
                team=self.away_team, division=self.division, season=self.season
            ).exists()
        )

    def test_regular_save_excludes_postseason_goals_from_gf(self):
        # Regular game: home scored 3. Playoff game: home scored 5.
        post_week = Week.objects.create(
            division=self.division,
            season=self.season,
            date=datetime.date(2024, 5, 1),
        )
        post_game = MatchUp.objects.create(
            week=post_week,
            awayteam=self.away_team,
            hometeam=self.home_team,
            time=datetime.time(12, 0),
            is_postseason=True,
        )
        p = self._player()
        Stat.objects.create(
            matchup=self.matchup, team=self.home_team, player=p, goals=3, assists=0
        )
        Stat.objects.create(
            matchup=post_game, team=self.home_team, player=p, goals=5, assists=0
        )
        # Saving the regular game recomputes GF from regular games only.
        self.client.post(self._url(self.matchup), self._post())
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 3)


class ScoresheetGridTest(TestCase):
    """
    Scoresheet grid on the matchup change form: rostered players are entered
    in a roster-shaped grid (ss-<player_id>-<field> inputs); blank means no
    stat row, an explicit 0 GA is a recorded shutout.
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
        self.home_center = Player.objects.create(
            first_name="Casey", last_name="Center", is_active=True
        )
        self.away_wing = Player.objects.create(
            first_name="Alex", last_name="Wing", is_active=True
        )
        self.home_goalie = Player.objects.create(
            first_name="Pat", last_name="Goalie", is_active=True
        )
        Roster.objects.create(player=self.home_center, team=self.home_team, position1=1)
        Roster.objects.create(player=self.away_wing, team=self.away_team, position1=2)
        Roster.objects.create(
            player=self.home_goalie,
            team=self.home_team,
            position1=4,
            is_primary_goalie=True,
        )

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
            "home_stat-win": "1",
            "home_stat-otw": "0",
            "home_stat-loss": "0",
            "home_stat-otl": "0",
            "home_stat-tie": "0",
            "home_stat-goals_for": "0",
            "home_stat-goals_against": "0",
            "away_stat-win": "0",
            "away_stat-otw": "0",
            "away_stat-loss": "1",
            "away_stat-otl": "0",
            "away_stat-tie": "0",
            "away_stat-goals_for": "0",
            "away_stat-goals_against": "0",
            "ss-player-ids": (
                f"{self.home_center.pk},{self.away_wing.pk},{self.home_goalie.pk}"
            ),
        }
        base.update(overrides)
        return base

    # ── Rendering ─────────────────────────────────────────────────────

    def test_change_view_renders_scoresheet_grid(self):
        response = self.client.get(self._url())
        self.assertContains(response, "Scoresheet")
        self.assertContains(response, f'name="ss-{self.home_center.pk}-goals"')
        self.assertContains(response, f'name="ss-{self.home_goalie.pk}-goals_against"')
        self.assertContains(response, 'name="ss-player-ids"')

    def test_grid_prefills_existing_stats(self):
        Stat.objects.create(
            matchup=self.matchup,
            team=self.home_team,
            player=self.home_center,
            goals=2,
            assists=1,
        )
        response = self.client.get(self._url())
        self.assertContains(
            response,
            f'name="ss-{self.home_center.pk}-goals" value="2"',
        )

    def test_inline_excludes_rostered_players(self):
        rostered_stat = Stat.objects.create(
            matchup=self.matchup,
            team=self.home_team,
            player=self.home_center,
            goals=2,
        )
        unrostered = Player.objects.create(
            first_name="Sub", last_name="Goalie", is_active=True
        )
        sub_stat = Stat.objects.create(
            matchup=self.matchup,
            team=self.away_team,
            player=unrostered,
            goals_against=2,
        )
        response = self.client.get(self._url())
        content = response.content.decode()
        self.assertIn(f'value="{sub_stat.pk}"', content)
        self.assertNotIn(f'name="stat_set-0-id" value="{rostered_stat.pk}"', content)

    def test_quick_outcome_buttons_render(self):
        response = self.client.get(self._url())
        self.assertContains(response, 'id="qo-home"')
        self.assertContains(response, 'id="qo-away"')
        self.assertContains(response, "went to OT / shootout")

    # ── Saving ────────────────────────────────────────────────────────

    def test_grid_creates_stat_rows(self):
        self.client.post(
            self._url(),
            self._post_data(
                **{
                    f"ss-{self.home_center.pk}-goals": "2",
                    f"ss-{self.home_center.pk}-assists": "1",
                }
            ),
        )
        stat = Stat.objects.get(matchup=self.matchup, player=self.home_center)
        self.assertEqual(stat.team, self.home_team)
        self.assertEqual(stat.goals, 2)
        self.assertEqual(stat.assists, 1)

    def test_blank_rows_create_nothing(self):
        self.client.post(self._url(), self._post_data())
        self.assertEqual(Stat.objects.filter(matchup=self.matchup).count(), 0)

    def test_grid_updates_existing_stat(self):
        Stat.objects.create(
            matchup=self.matchup,
            team=self.home_team,
            player=self.home_center,
            goals=1,
        )
        self.client.post(
            self._url(),
            self._post_data(
                **{
                    f"ss-{self.home_center.pk}-goals": "3",
                    f"ss-{self.home_center.pk}-assists": "0",
                }
            ),
        )
        stat = Stat.objects.get(matchup=self.matchup, player=self.home_center)
        self.assertEqual(stat.goals, 3)

    def test_clearing_grid_row_deletes_stat(self):
        Stat.objects.create(
            matchup=self.matchup,
            team=self.home_team,
            player=self.home_center,
            goals=1,
        )
        self.client.post(
            self._url(),
            self._post_data(
                **{
                    f"ss-{self.home_center.pk}-goals": "",
                    f"ss-{self.home_center.pk}-assists": "",
                }
            ),
        )
        self.assertFalse(
            Stat.objects.filter(matchup=self.matchup, player=self.home_center).exists()
        )

    def test_goalie_explicit_zero_ga_records_shutout(self):
        self.client.post(
            self._url(),
            self._post_data(**{f"ss-{self.home_goalie.pk}-goals_against": "0"}),
        )
        stat = Stat.objects.get(matchup=self.matchup, player=self.home_goalie)
        self.assertEqual(stat.goals_against, 0)

    def test_grid_goals_feed_team_stat_recompute(self):
        self.client.post(
            self._url(),
            self._post_data(
                **{
                    f"ss-{self.home_center.pk}-goals": "4",
                    f"ss-{self.away_wing.pk}-goals": "1",
                    "home_stat-goals_for": "99",
                    "away_stat-goals_for": "99",
                }
            ),
        )
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        away = Team_Stat.objects.get(
            team=self.away_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 4)
        self.assertEqual(home.goals_against, 1)
        self.assertEqual(away.goals_for, 1)
        self.assertEqual(away.goals_against, 4)

    def test_negative_values_clamped_to_zero(self):
        self.client.post(
            self._url(),
            self._post_data(**{f"ss-{self.home_center.pk}-goals": "-3"}),
        )
        stat = Stat.objects.get(matchup=self.matchup, player=self.home_center)
        self.assertEqual(stat.goals, 0)

    # ── Goalie goals and assists ──────────────────────────────────────

    def test_goalie_row_has_goal_and_assist_boxes(self):
        response = self.client.get(self._url())
        g = self.home_goalie.pk
        self.assertContains(
            response,
            f'class="ss-input" name="ss-{g}-goals" value="" '
            f'data-team="{self.home_team.pk}" data-ss="goals"',
        )
        self.assertContains(
            response,
            f'class="ss-input" name="ss-{g}-assists" value="" '
            f'data-team="{self.home_team.pk}" data-ss="assists"',
        )
        # The old hidden inputs are gone, so each field is posted once.
        self.assertNotContains(response, f'type="hidden" name="ss-{g}-goals"')
        self.assertNotContains(response, f'type="hidden" name="ss-{g}-assists"')

    def test_empty_net_column_says_goals_against(self):
        response = self.client.get(self._url())
        self.assertContains(response, ">EN GA</abbr>")
        self.assertContains(response, "Not counted in GAA")
        self.assertContains(response, "If a goalie scores or gets an assist")

    def test_goalie_assist_saved_with_goals_against(self):
        g = self.home_goalie.pk
        self.client.post(
            self._url(),
            self._post_data(
                **{
                    f"ss-{g}-goals_against": "3",
                    f"ss-{g}-empty_net": "",
                    f"ss-{g}-goals": "",
                    f"ss-{g}-assists": "1",
                }
            ),
        )
        rows = list(
            Stat.objects.filter(matchup=self.matchup, player=self.home_goalie).values(
                "goals", "assists", "goals_against", "empty_net"
            )
        )
        self.assertEqual(
            rows, [{"goals": 0, "assists": 1, "goals_against": 3, "empty_net": 0}]
        )

    def test_goalie_goal_counts_toward_team_goals_for(self):
        g = self.home_goalie.pk
        self.client.post(
            self._url(),
            self._post_data(
                **{
                    f"ss-{self.home_center.pk}-goals": "2",
                    f"ss-{g}-goals_against": "0",
                    f"ss-{g}-goals": "1",
                }
            ),
        )
        home = Team_Stat.objects.get(
            team=self.home_team, division=self.division, season=self.season
        )
        self.assertEqual(home.goals_for, 3)
        stat = Stat.objects.get(matchup=self.matchup, player=self.home_goalie)
        self.assertEqual((stat.goals, stat.goals_against), (1, 0))

    def test_existing_goalie_points_prefill(self):
        Stat.objects.create(
            matchup=self.matchup,
            team=self.home_team,
            player=self.home_goalie,
            goals=1,
            assists=2,
            goals_against=4,
        )
        response = self.client.get(self._url())
        g = self.home_goalie.pk
        self.assertContains(response, f'name="ss-{g}-goals" value="1"')
        self.assertContains(response, f'name="ss-{g}-assists" value="2"')
        self.assertContains(response, f'name="ss-{g}-goals_against" value="4"')

    # ── Sub goalie instruction & subs section ─────────────────────────

    def _inline_row(self, player, team, **values):
        row = {
            "stat_set-TOTAL_FORMS": "1",
            "stat_set-0-player": str(player.pk),
            "stat_set-0-team": str(team.pk),
            "stat_set-0-goals": "0",
            "stat_set-0-assists": "0",
            "stat_set-0-goals_against": "0",
            "stat_set-0-empty_net": "0",
        }
        row.update({f"stat_set-0-{k}": str(v) for k, v in values.items()})
        return row

    def test_sub_goalie_instruction_links_to_this_games_goalie(self):
        response = self.client.get(self._url())
        self.assertContains(response, "Sub in goal?")
        self.assertContains(
            response,
            reverse("admin:leagues_matchupgoaliestatus_change", args=[self.matchup.pk]),
        )
        self.assertContains(response, "Can play goalie")

    def test_rostered_player_in_subs_section_is_rejected_with_message(self):
        # Regression: this used to save, then the scoresheet grid silently
        # overwrote it, so the goalie's assist was lost without a warning.
        data = self._post_data(
            **{
                f"ss-{self.home_goalie.pk}-goals_against": "3",
                **self._inline_row(self.home_goalie, self.home_team, assists=1),
            }
        )
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Pat Goalie is on the Home Team roster, so their stats go in the "
            "scoresheet above.",
        )
        self.assertFalse(Stat.objects.filter(matchup=self.matchup).exists())

    def test_rejected_save_keeps_what_was_typed_in_the_grid(self):
        data = self._post_data(
            **{
                f"ss-{self.home_center.pk}-goals": "4",
                f"ss-{self.home_goalie.pk}-goals_against": "2",
                **self._inline_row(self.away_wing, self.home_team, goals=1),
            }
        )
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'name="ss-{self.home_center.pk}-goals" value="4"'
        )
        self.assertContains(
            response, f'name="ss-{self.home_goalie.pk}-goals_against" value="2"'
        )

    def test_unrostered_sub_still_saves(self):
        # The subs section offers rostered players plus anyone who can play
        # goalie, so a walk-in sub goalie has "Can play goalie" ticked.
        sub = Player.objects.create(
            first_name="Sub", last_name="Keeper", is_active=True, can_play_goalie=True
        )
        data = self._post_data(
            **self._inline_row(sub, self.home_team, assists=1, goals_against=2)
        )
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)
        stat = Stat.objects.get(matchup=self.matchup, player=sub)
        self.assertEqual((stat.assists, stat.goals_against), (1, 2))

    def test_roster_substitute_still_saves_in_subs_section(self):
        sub = Player.objects.create(first_name="Roster", last_name="Sub")
        Roster.objects.create(
            player=sub, team=self.home_team, position1=2, is_substitute=True
        )
        response = self.client.post(
            self._url(),
            self._post_data(**self._inline_row(sub, self.home_team, goals=1)),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Stat.objects.filter(matchup=self.matchup, player=sub).exists())


class StatRosterAdminTest(TestCase):
    """Standalone Stat and Roster admins: usable changelists, no bare admin."""

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
            first_name="Casey", last_name="Center", is_active=True
        )
        Roster.objects.create(player=self.player, team=self.home_team, position1=1)
        Stat.objects.create(
            matchup=self.matchup, team=self.home_team, player=self.player, goals=1
        )

    def test_stat_changelist_renders(self):
        response = self.client.get(reverse("admin:leagues_stat_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_stat_changelist_search(self):
        response = self.client.get(
            reverse("admin:leagues_stat_changelist"), {"q": "Casey"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Center")

    def test_roster_changelist_renders(self):
        response = self.client.get(reverse("admin:leagues_roster_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_matchup_time_column_is_sortable(self):
        from leagues.admin import MatchUpAdmin

        self.assertEqual(MatchUpAdmin.formatted_time.admin_order_field, "time")


# ---------------------------------------------------------------------------
# Seasons whose standings are computed from game results
# ---------------------------------------------------------------------------


def _computed_fixture():
    """A computed-standings season with one rostered player per team."""
    season, division, week, away_team, home_team, matchup = _make_fixture(
        standings_from_games=True
    )
    home_player = Player.objects.create(first_name="Harper", last_name="Home")
    away_player = Player.objects.create(first_name="Avery", last_name="Away")
    Roster.objects.create(player=home_player, team=home_team, position1=1)
    Roster.objects.create(player=away_player, team=away_team, position1=1)
    return {
        "season": season,
        "division": division,
        "week": week,
        "away_team": away_team,
        "home_team": home_team,
        "matchup": matchup,
        "home_player": home_player,
        "away_player": away_player,
    }


class ComputedStandingsMatchupAdminTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin", password="password", email="admin@example.com"
        )
        self.client.force_login(self.superuser)
        self.f = _computed_fixture()

    def _url(self):
        return reverse("admin:leagues_matchup_change", args=[self.f["matchup"].pk])

    def _post(self, home_goals="", away_goals="", **overrides):
        f = self.f
        data = {
            "week": f["week"].pk,
            "time": "10:00 AM",
            "awayteam": f["away_team"].pk,
            "hometeam": f["home_team"].pk,
            "stat_set-TOTAL_FORMS": "0",
            "stat_set-INITIAL_FORMS": "0",
            "stat_set-MIN_NUM_FORMS": "0",
            "stat_set-MAX_NUM_FORMS": "1000",
            "ss-player-ids": f"{f['home_player'].pk},{f['away_player'].pk}",
            f"ss-{f['home_player'].pk}-goals": home_goals,
            f"ss-{f['away_player'].pk}-goals": away_goals,
        }
        data.update(overrides)
        return data

    def _record(self, team):
        row = Team_Stat.objects.filter(
            team=team, division=self.f["division"], season=self.f["season"]
        ).first()
        if row is None:
            return None
        return (row.win, row.otw, row.otl, row.loss, row.goals_for, row.goals_against)

    def test_change_view_asks_only_for_overtime(self):
        html = self.client.get(self._url()).content.decode()
        self.assertIn('name="went_to_overtime"', html)
        self.assertIn('id="result-line"', html)
        self.assertIn("Season records so far", html)
        self.assertNotIn('name="home_stat-win"', html)
        self.assertNotIn('id="qo-home"', html)
        self.assertNotIn('name="home_stat-goals_for"', html)

    def test_save_computes_records_from_the_score(self):
        resp = self.client.post(self._url(), self._post("3", "1"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._record(self.f["home_team"]), (1, 0, 0, 0, 3, 1))
        self.assertEqual(self._record(self.f["away_team"]), (0, 0, 0, 1, 1, 3))

    def test_overtime_box_makes_it_an_overtime_result(self):
        self.client.post(self._url(), self._post("3", "2", went_to_overtime="on"))
        self.assertTrue(MatchUp.objects.get(pk=self.f["matchup"].pk).went_to_overtime)
        self.assertEqual(self._record(self.f["home_team"])[:4], (0, 1, 0, 0))
        self.assertEqual(self._record(self.f["away_team"])[:4], (0, 0, 1, 0))

    def test_tie_without_shootout_winner_is_refused(self):
        resp = self.client.post(self._url(), self._post("2", "2"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Goals are tied 2-2")
        self.assertContains(resp, "pick who won the shootout")
        # Nothing was saved: no stat rows, no games in the standings.
        self.assertEqual(Stat.objects.filter(matchup=self.f["matchup"]).count(), 0)
        self.assertIn(self._record(self.f["home_team"]), (None, (0, 0, 0, 0, 0, 0)))

    def test_tie_with_shootout_winner_counts_as_overtime(self):
        self.client.post(
            self._url(),
            self._post(
                "2", "2", went_to_overtime="on", shootout_winner_is_home="false"
            ),
        )
        game = MatchUp.objects.get(pk=self.f["matchup"].pk)
        self.assertIs(game.shootout_winner_is_home, False)
        self.assertTrue(game.went_to_overtime)
        self.assertEqual(self._record(self.f["away_team"])[:4], (0, 1, 0, 0))
        self.assertEqual(self._record(self.f["home_team"])[:4], (0, 0, 1, 0))

    def test_shootout_pick_implies_overtime_even_without_the_box(self):
        self.client.post(
            self._url(), self._post("1", "1", shootout_winner_is_home="true")
        )
        self.assertTrue(MatchUp.objects.get(pk=self.f["matchup"].pk).went_to_overtime)
        self.assertEqual(self._record(self.f["home_team"])[:4], (0, 1, 0, 0))

    def test_saving_twice_never_double_counts(self):
        self.client.post(self._url(), self._post("3", "1"))
        self.client.post(self._url(), self._post("3", "1"))
        self.assertEqual(self._record(self.f["home_team"]), (1, 0, 0, 0, 3, 1))

    def test_correcting_the_score_moves_the_win(self):
        self.client.post(self._url(), self._post("3", "1"))
        self.client.post(self._url(), self._post("1", "3"))
        self.assertEqual(self._record(self.f["home_team"])[:4], (0, 0, 0, 1))
        self.assertEqual(self._record(self.f["away_team"])[:4], (1, 0, 0, 0))

    def test_save_with_no_stats_is_allowed(self):
        # Refs, notes or goalie status can be saved before the game is played.
        resp = self.client.post(self._url(), self._post())
        self.assertEqual(resp.status_code, 302)
        self.assertIn(self._record(self.f["home_team"]), (None, (0, 0, 0, 0, 0, 0)))

    def test_postseason_game_is_not_counted(self):
        self.client.post(self._url(), self._post("3", "1", is_postseason="on"))
        self.assertIn(self._record(self.f["home_team"]), (None, (0, 0, 0, 0, 0, 0)))

    def test_record_shown_after_save(self):
        self.client.post(self._url(), self._post("3", "1"))
        html = self.client.get(self._url()).content.decode()
        self.assertIn("1-0-0-0", html)
        self.assertIn("0-0-0-1", html)

    def test_sub_stats_count_toward_the_score(self):
        sub = Player.objects.create(first_name="Sam", last_name="Sub")
        Roster.objects.create(
            player=sub, team=self.f["away_team"], position1=2, is_substitute=True
        )
        self.client.post(
            self._url(),
            self._post(
                "1",
                "",
                **{
                    "stat_set-TOTAL_FORMS": "1",
                    "stat_set-0-player": sub.pk,
                    "stat_set-0-team": self.f["away_team"].pk,
                    "stat_set-0-goals": "2",
                    "stat_set-0-assists": "0",
                    "stat_set-0-goals_against": "0",
                    "stat_set-0-empty_net": "0",
                },
            ),
        )
        self.assertEqual(self._record(self.f["away_team"])[:4], (1, 0, 0, 0))


class WrongDivisionWeekTest(TestCase):
    """A week filed under the wrong division: the game page says so and
    offers a one-click fix, and the game can't be saved until it is fixed."""

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin", password="password", email="admin@example.com"
        )
        self.client.force_login(self.superuser)
        self.f = _computed_fixture()
        self.wrong_division = Division.objects.create(division=3)
        self.wrong_week = Week.objects.create(
            division=self.wrong_division,
            season=self.f["season"],
            date=datetime.date(2024, 4, 8),
        )
        # objects.create() skips validation, like the old admin did.
        self.game = MatchUp.objects.create(
            week=self.wrong_week,
            awayteam=self.f["away_team"],
            hometeam=self.f["home_team"],
            time=datetime.time(19, 0),
        )

    def _change(self):
        return reverse("admin:leagues_matchup_change", args=[self.game.pk])

    def _fix(self):
        return reverse("admin:leagues_matchup_fix_week_division", args=[self.game.pk])

    def test_change_view_warns_and_offers_the_fix(self):
        resp = self.client.get(self._change())
        self.assertContains(resp, "filed under the wrong division")
        self.assertContains(resp, "Change the week&#x27;s division to Sunday D1")
        self.assertContains(resp, self._fix())

    def test_right_week_shows_no_warning(self):
        resp = self.client.get(
            reverse("admin:leagues_matchup_change", args=[self.f["matchup"].pk])
        )
        self.assertNotContains(resp, "filed under the wrong division")

    def test_saving_is_refused_until_fixed(self):
        resp = self.client.post(
            self._change(),
            {
                "week": self.wrong_week.pk,
                "time": "07:00 PM",
                "awayteam": self.f["away_team"].pk,
                "hometeam": self.f["home_team"].pk,
                "stat_set-TOTAL_FORMS": "0",
                "stat_set-INITIAL_FORMS": "0",
                "stat_set-MIN_NUM_FORMS": "0",
                "stat_set-MAX_NUM_FORMS": "1000",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "play in Sunday D1, but this week is filed under")

    def test_fix_refiles_the_week_when_every_game_belongs(self):
        resp = self.client.post(self._fix())
        self.assertRedirects(resp, self._change())
        self.wrong_week.refresh_from_db()
        self.assertEqual(self.wrong_week.division, self.f["division"])
        self.assertNotContains(self.client.get(self._change()), "wrong division")

    def test_fix_moves_the_games_when_the_right_week_exists(self):
        right_week = Week.objects.create(
            division=self.f["division"],
            season=self.f["season"],
            date=self.wrong_week.date,
        )
        self.client.post(self._fix())
        self.game.refresh_from_db()
        self.assertEqual(self.game.week, right_week)
        self.assertFalse(Week.objects.filter(pk=self.wrong_week.pk).exists())

    def test_fix_leaves_other_divisions_games_on_the_week(self):
        other_a, other_b = (
            Team.objects.create(
                team_name=name,
                team_color="Red",
                division=self.wrong_division,
                season=self.f["season"],
                is_active=True,
            )
            for name in ("Wed A", "Wed B")
        )
        real_wednesday_game = MatchUp.objects.create(
            week=self.wrong_week,
            awayteam=other_a,
            hometeam=other_b,
            time=datetime.time(20, 0),
        )
        self.client.post(self._fix())
        self.game.refresh_from_db()
        real_wednesday_game.refresh_from_db()
        self.assertEqual(self.game.week.division, self.f["division"])
        self.assertEqual(real_wednesday_game.week, self.wrong_week)
        self.wrong_week.refresh_from_db()
        self.assertEqual(self.wrong_week.division, self.wrong_division)

    def test_fix_ignores_get(self):
        resp = self.client.get(self._fix())
        self.assertRedirects(resp, self._change())
        self.wrong_week.refresh_from_db()
        self.assertEqual(self.wrong_week.division, self.wrong_division)

    def test_fix_rebuilds_the_standings(self):
        Stat.objects.create(
            matchup=self.game,
            team=self.f["home_team"],
            player=self.f["home_player"],
            goals=2,
        )
        self.client.post(self._fix())
        row = Team_Stat.objects.get(
            team=self.f["home_team"], division=self.f["division"]
        )
        self.assertEqual(row.win, 1)


class MatchUpAddFormWeekChoicesTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(
            User.objects.create_superuser("admin", "a@example.com", "password")
        )
        self.f = _computed_fixture()

    def test_week_dropdown_offers_only_seasons_in_play(self):
        old_season = Season.objects.create(year=2019, season_type=1)
        old_week = Week.objects.create(
            division=self.f["division"],
            season=old_season,
            date=datetime.date(2019, 4, 1),
        )
        resp = self.client.get(reverse("admin:leagues_matchup_add"))
        weeks = list(resp.context["adminform"].form.fields["week"].queryset)
        self.assertIn(self.f["week"], weeks)
        self.assertNotIn(old_week, weeks)


class WeekAdminSeasonInferenceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(
            User.objects.create_superuser("admin", "a@example.com", "password")
        )
        self.f = _computed_fixture()

    def _post(self, **overrides):
        data = {
            "division": self.f["division"].pk,
            "season": "",
            "date": "2024-04-15",
            "matchup_set-TOTAL_FORMS": "0",
            "matchup_set-INITIAL_FORMS": "0",
            "matchup_set-MIN_NUM_FORMS": "0",
            "matchup_set-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def _game_row(self, away, home, i=0):
        return {
            "matchup_set-TOTAL_FORMS": str(i + 1),
            f"matchup_set-{i}-time": "07:00 PM",
            f"matchup_set-{i}-awayteam": away.pk,
            f"matchup_set-{i}-hometeam": home.pk,
            f"matchup_set-{i}-away_goalie_status": 3,
            f"matchup_set-{i}-home_goalie_status": 3,
        }

    def test_season_is_not_required(self):
        resp = self.client.get(reverse("admin:leagues_week_add"))
        self.assertFalse(resp.context["adminform"].form.fields["season"].required)
        self.assertContains(resp, "Leave blank")

    def test_season_comes_from_the_teams_in_the_games(self):
        other_season = Season.objects.create(year=2030, season_type=1)
        Team.objects.create(
            team_name="Future",
            team_color="Blue",
            division=self.f["division"],
            season=other_season,
            is_active=True,
        )
        resp = self.client.post(
            reverse("admin:leagues_week_add"),
            self._post(**self._game_row(self.f["away_team"], self.f["home_team"])),
        )
        self.assertEqual(resp.status_code, 302)
        week = Week.objects.get(date=datetime.date(2024, 4, 15))
        # The teams are 2024 teams, so the week is 2024 even though a newer
        # season has teams in this division.
        self.assertEqual(week.season, self.f["season"])
        self.assertEqual(week.matchup_set.count(), 1)

    def test_empty_week_takes_newest_season_with_teams(self):
        other_season = Season.objects.create(year=2030, season_type=1)
        Team.objects.create(
            team_name="Future",
            team_color="Blue",
            division=self.f["division"],
            season=other_season,
            is_active=True,
        )
        self.client.post(reverse("admin:leagues_week_add"), self._post())
        week = Week.objects.get(date=datetime.date(2024, 4, 15))
        self.assertEqual(week.season, other_season)

    def test_games_from_the_wrong_division_are_refused(self):
        other = Division.objects.create(division=3)
        resp = self.client.post(
            reverse("admin:leagues_week_add"),
            self._post(
                division=other.pk,
                **self._game_row(self.f["away_team"], self.f["home_team"]),
            ),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "but this week is filed under Wednesday Draft League")
        self.assertFalse(Week.objects.filter(date=datetime.date(2024, 4, 15)).exists())

    def test_games_mixing_divisions_are_refused(self):
        other = Division.objects.create(division=3)
        a, b = (
            Team.objects.create(
                team_name=name,
                team_color="Red",
                division=other,
                season=self.f["season"],
                is_active=True,
            )
            for name in ("Wed A", "Wed B")
        )
        data = self._post(**self._game_row(self.f["away_team"], self.f["home_team"]))
        data.update(self._game_row(a, b, i=1))
        resp = self.client.post(reverse("admin:leagues_week_add"), data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "These games mix divisions")


class TeamAdminDefaultsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(
            User.objects.create_superuser("admin", "a@example.com", "password")
        )
        self.f = _computed_fixture()

    def test_new_team_defaults_to_newest_season_and_active(self):
        newest = Season.objects.create(year=2031, season_type=2)
        form = (
            self.client.get(reverse("admin:leagues_team_add")).context["adminform"].form
        )
        self.assertEqual(form.initial["season"], newest.pk)
        self.assertIs(form.initial["is_active"], True)

    def test_record_is_read_only_for_computed_seasons(self):
        Stat.objects.create(
            matchup=self.f["matchup"],
            team=self.f["home_team"],
            player=self.f["home_player"],
            goals=2,
        )
        html = self.client.get(
            reverse("admin:leagues_team_change", args=[self.f["home_team"].pk])
        ).content.decode()
        self.assertNotIn('name="team_stat_set-0-win"', html)
        self.assertIn("Season record", html)


class SeasonAdminTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(
            User.objects.create_superuser("admin", "a@example.com", "password")
        )
        self.f = _computed_fixture()

    def test_current_season_flag_is_hidden(self):
        resp = self.client.get(reverse("admin:leagues_season_add"))
        self.assertNotContains(resp, 'name="is_current_season"')
        self.assertNotContains(resp, 'name="standings_from_games"')

    def test_list_shows_which_divisions_play_each_season(self):
        resp = self.client.get(reverse("admin:leagues_season_changelist"))
        self.assertContains(resp, "Playing now")
        self.assertContains(resp, "Sunday D1")
        self.assertContains(resp, "From game results")


class ScheduleManagerFilesGamesByTeamDivisionTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(
            User.objects.create_superuser("admin", "a@example.com", "password")
        )
        self.f = _computed_fixture()
        self.wrong_division = Division.objects.create(division=3)
        # The dropdown only lists divisions with upcoming weeks.
        Week.objects.create(
            division=self.wrong_division,
            season=self.f["season"],
            date=datetime.date.today() + datetime.timedelta(days=3),
        )

    def test_new_game_is_filed_under_the_teams_division(self):
        on = datetime.date.today() + datetime.timedelta(days=7)
        self.client.post(
            reverse("admin:leagues_matchup_schedule_manager"),
            {
                "division_id": self.wrong_division.pk,
                "filter_date": "",
                "matchup_pks": "",
                "new_row_count": "1",
                "new_0_division_id": self.wrong_division.pk,
                "new_0_date": on.isoformat(),
                "new_0_time": "19:00",
                "new_0_away": self.f["away_team"].pk,
                "new_0_home": self.f["home_team"].pk,
            },
        )
        game = MatchUp.objects.get(week__date=on)
        self.assertEqual(game.week.division, self.f["division"])
        self.assertEqual(game.week.season, self.f["season"])
