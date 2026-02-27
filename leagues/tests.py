from os.path import abspath, join, dirname
from shutil import rmtree
from tempfile import mkdtemp
import datetime

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase
from django.test.client import Client
from django.test.utils import override_settings

from leagues.forms import MatchUpForm
from leagues.models import Division, MatchUp, Player, Season, Team, Week


class ViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.media_folder = mkdtemp()

    def tearDown(self):
        rmtree(self.media_folder)

    # @mock.patch('storages.backends.s3boto.S3BotoStorage', FileSystemStorage)
    # def test_post_photo(self):
    #     photo_path = join(abspath(dirname(__file__)), 'fixtures/team.jpg')

    #     with open(photo_path) as photo:
    #         with override_settings(MEDIA_ROOT=self.media_folder):
    #             resp = self.client.post(reverse('create'), {
    #                 'first_name': 'Test',
    #                 'photo': photo
    #             })
    #             redirect = 'Location: http://testserver%s' % reverse('created')
    #             self.assertTrue(redirect in str(resp))


class MatchUpValidationTest(TestCase):
    def setUp(self):
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=datetime.date.today()
        )
        self.away_team = Team.objects.create(
            team_name="Away Team",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.home_team = Team.objects.create(
            team_name="Home Team",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.away_goalie = Player.objects.create(first_name="Away", last_name="Goalie")
        self.home_goalie = Player.objects.create(first_name="Home", last_name="Goalie")

    def test_sub_needed_with_goalie_raises_error(self):
        matchup = MatchUp(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.away_team,
            hometeam=self.home_team,
            away_goalie=self.away_goalie,
            away_goalie_status=2,
            home_goalie_status=3,
        )

        with self.assertRaises(ValidationError) as context:
            matchup.full_clean()

        self.assertIn("away_goalie", context.exception.error_dict)

    def test_sub_needed_without_goalie_is_valid(self):
        matchup = MatchUp(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.away_team,
            hometeam=self.home_team,
            away_goalie=None,
            away_goalie_status=2,
            home_goalie_status=3,
        )
        matchup.full_clean()

    def test_unconfirmed_with_goalie_is_valid(self):
        matchup = MatchUp(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.away_team,
            hometeam=self.home_team,
            away_goalie=self.away_goalie,
            away_goalie_status=3,
            home_goalie=self.home_goalie,
            home_goalie_status=3,
        )
        matchup.full_clean()

    def test_sub_needed_home_goalie_raises_error(self):
        matchup = MatchUp(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.away_team,
            hometeam=self.home_team,
            home_goalie=self.home_goalie,
            home_goalie_status=2,
            away_goalie_status=3,
        )

        with self.assertRaises(ValidationError) as context:
            matchup.full_clean()

        self.assertIn("home_goalie", context.exception.error_dict)


class MatchUpFormTest(TestCase):
    def setUp(self):
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=datetime.date.today()
        )
        self.away_team = Team.objects.create(
            team_name="Away Team",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.home_team = Team.objects.create(
            team_name="Home Team",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.away_goalie = Player.objects.create(first_name="Away", last_name="Goalie")
        self.home_goalie = Player.objects.create(first_name="Home", last_name="Goalie")

    def test_sub_needed_with_away_goalie_is_invalid(self):
        form = MatchUpForm(
            data={
                "week": self.week.id,
                "time": "12:00 PM",
                "awayteam": self.away_team.id,
                "hometeam": self.home_team.id,
                "away_goalie": self.away_goalie.id,
                "away_goalie_status": 2,
                "home_goalie_status": 3,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("away_goalie", form.errors)

    def test_sub_needed_with_home_goalie_is_invalid(self):
        form = MatchUpForm(
            data={
                "week": self.week.id,
                "time": "12:00 PM",
                "awayteam": self.away_team.id,
                "hometeam": self.home_team.id,
                "home_goalie": self.home_goalie.id,
                "home_goalie_status": 2,
                "away_goalie_status": 3,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("home_goalie", form.errors)

    def test_unconfirmed_with_goalie_keeps_selection(self):
        form = MatchUpForm(
            data={
                "week": self.week.id,
                "time": "12:00 PM",
                "awayteam": self.away_team.id,
                "hometeam": self.home_team.id,
                "away_goalie": self.away_goalie.id,
                "away_goalie_status": 3,
                "home_goalie": self.home_goalie.id,
                "home_goalie_status": 3,
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["away_goalie"], self.away_goalie)
        self.assertEqual(form.cleaned_data["home_goalie"], self.home_goalie)

    def test_confirmed_with_sub_goalie_is_valid(self):
        """Confirmed status with a substitute goalie should be valid."""
        sub_goalie = Player.objects.create(first_name="Sub", last_name="Goalie")
        form = MatchUpForm(
            data={
                "week": self.week.id,
                "time": "12:00 PM",
                "awayteam": self.away_team.id,
                "hometeam": self.home_team.id,
                "away_goalie": sub_goalie.id,
                "away_goalie_status": 1,  # Confirmed
                "home_goalie_status": 3,
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["away_goalie"], sub_goalie)

    def test_sub_needed_without_goalie_is_valid(self):
        """Sub Needed status without a goalie should be valid."""
        form = MatchUpForm(
            data={
                "week": self.week.id,
                "time": "12:00 PM",
                "awayteam": self.away_team.id,
                "hometeam": self.home_team.id,
                "away_goalie": "",
                "away_goalie_status": 2,  # Sub Needed
                "home_goalie_status": 3,
            }
        )
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data["away_goalie"])


class CaptainGoalieUpdateViewTest(TestCase):
    """Tests for the captain goalie update AJAX endpoint."""

    def setUp(self):
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=datetime.date.today()
        )
        self.away_team = Team.objects.create(
            team_name="Away Team",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.home_team = Team.objects.create(
            team_name="Home Team",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.goalie = Player.objects.create(first_name="Test", last_name="Goalie")
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.away_team,
            hometeam=self.home_team,
            away_goalie_status=3,
            home_goalie_status=3,
        )
        self.client = Client()

    def test_update_status_to_sub_needed_clears_goalie(self):
        """Setting status to Sub Needed should clear the goalie field."""
        # First set a goalie
        self.matchup.home_goalie = self.goalie
        self.matchup.home_goalie_status = 1
        self.matchup.save()

        url = reverse(
            "update_goalie_status",
            kwargs={
                "access_code": self.home_team.captain_access_code,
                "matchup_id": self.matchup.id,
            },
        )
        response = self.client.post(
            url,
            {"goalie_id": str(self.goalie.id), "status": "2"},  # Sub Needed
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], 2)
        self.assertEqual(data["goalie_name"], "")  # Should be blank

        # Verify database was updated
        self.matchup.refresh_from_db()
        self.assertIsNone(self.matchup.home_goalie)
        self.assertEqual(self.matchup.home_goalie_status, 2)

    def test_update_status_to_confirmed_with_goalie(self):
        """Setting status to Confirmed with a goalie should work."""
        url = reverse(
            "update_goalie_status",
            kwargs={
                "access_code": self.home_team.captain_access_code,
                "matchup_id": self.matchup.id,
            },
        )
        response = self.client.post(
            url,
            {"goalie_id": str(self.goalie.id), "status": "1"},  # Confirmed
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], 1)
        self.assertIn("Test Goalie", data["goalie_name"])

        # Verify database was updated
        self.matchup.refresh_from_db()
        self.assertEqual(self.matchup.home_goalie, self.goalie)
        self.assertEqual(self.matchup.home_goalie_status, 1)

    def test_update_away_team_goalie(self):
        """Away team captain should be able to update away goalie."""
        url = reverse(
            "update_goalie_status",
            kwargs={
                "access_code": self.away_team.captain_access_code,
                "matchup_id": self.matchup.id,
            },
        )
        response = self.client.post(
            url,
            {"goalie_id": str(self.goalie.id), "status": "1"},
        )
        self.assertEqual(response.status_code, 200)

        self.matchup.refresh_from_db()
        self.assertEqual(self.matchup.away_goalie, self.goalie)
        self.assertEqual(self.matchup.away_goalie_status, 1)

    def test_unauthorized_team_cannot_update(self):
        """A team not in the matchup should not be able to update."""
        other_team = Team.objects.create(
            team_name="Other Team",
            team_color="Green",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        url = reverse(
            "update_goalie_status",
            kwargs={
                "access_code": other_team.captain_access_code,
                "matchup_id": self.matchup.id,
            },
        )
        response = self.client.post(
            url,
            {"goalie_id": str(self.goalie.id), "status": "1"},
        )
        self.assertEqual(response.status_code, 403)

    def test_invalid_status_rejected(self):
        """Invalid status values should be rejected."""
        url = reverse(
            "update_goalie_status",
            kwargs={
                "access_code": self.home_team.captain_access_code,
                "matchup_id": self.matchup.id,
            },
        )
        response = self.client.post(
            url,
            {"goalie_id": str(self.goalie.id), "status": "99"},
        )
        self.assertEqual(response.status_code, 400)


class GoalieStatusBoardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.today = datetime.date.today()
        self.target_date = self.today + datetime.timedelta(days=1)

    def _create_matchup_for_week(
        self, week, team_prefix, away_goalie_status=3, home_goalie_status=3
    ):
        away_team = Team.objects.create(
            team_name=f"{team_prefix} Away",
            team_color="Blue",
            division=week.division,
            season=week.season,
            is_active=True,
        )
        home_team = Team.objects.create(
            team_name=f"{team_prefix} Home",
            team_color="Red",
            division=week.division,
            season=week.season,
            is_active=True,
        )
        return MatchUp.objects.create(
            week=week,
            time=datetime.time(12, 0),
            awayteam=away_team,
            hometeam=home_team,
            away_goalie_status=away_goalie_status,
            home_goalie_status=home_goalie_status,
        )

    def test_includes_same_day_games_from_current_and_non_current_seasons(self):
        division = Division.objects.create(division=2)
        previous_season = Season.objects.create(
            year=self.today.year - 1, season_type=4, is_current_season=False
        )
        current_season = Season.objects.create(
            year=self.today.year, season_type=1, is_current_season=True
        )

        previous_week = Week.objects.create(
            division=division,
            season=previous_season,
            date=self.target_date,
        )
        current_week = Week.objects.create(
            division=division,
            season=current_season,
            date=self.target_date,
        )

        self._create_matchup_for_week(
            previous_week,
            "Championship",
            away_goalie_status=2,
        )
        self._create_matchup_for_week(current_week, "NewSeason")

        response = self.client.get(reverse("goalie_status_board"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Championship Away")
        self.assertContains(response, "NewSeason Away")
        # The sub-needed game from the non-current season should still count.
        self.assertEqual(response.context["sub_needed_count"], 1)

    def test_includes_all_weeks_for_same_date_not_just_first_four_rows(self):
        season = Season.objects.create(
            year=self.today.year, season_type=1, is_current_season=True
        )

        for division_number in [1, 2, 3, 4, 5]:
            division = Division.objects.create(division=division_number)
            week = Week.objects.create(
                division=division,
                season=season,
                date=self.target_date,
            )
            self._create_matchup_for_week(week, f"D{division_number}")

        response = self.client.get(reverse("goalie_status_board"))

        self.assertEqual(response.status_code, 200)
        day_sections = [
            item
            for item in response.context["weeks_data"]
            if item["week"].date == self.target_date
        ]
        self.assertEqual(len(day_sections), 5)
        self.assertContains(response, "D1 Away")
        self.assertContains(response, "D5 Away")


class GoalieDisplayInfoTest(TestCase):
    """Tests for the get_goalie_display_info helper function."""

    def setUp(self):
        from leagues.models import Roster

        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=datetime.date.today()
        )
        self.team = Team.objects.create(
            team_name="Test Team",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.roster_goalie = Player.objects.create(
            first_name="Roster", last_name="Goalie"
        )
        self.sub_goalie = Player.objects.create(first_name="Sub", last_name="Goalie")
        # Add roster goalie to team roster
        Roster.objects.create(
            player=self.roster_goalie,
            team=self.team,
            position1=4,  # Goalie
            is_substitute=False,
        )
        self.other_team = Team.objects.create(
            team_name="Other Team",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )

    def test_sub_needed_returns_blank_goalie_name(self):
        """When status is Sub Needed, goalie_name should be blank."""
        from leagues.views import get_goalie_display_info

        matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.team,
            hometeam=self.other_team,
            away_goalie=None,
            away_goalie_status=2,  # Sub Needed
            home_goalie_status=3,
        )
        info = get_goalie_display_info(
            matchup, self.team, "away_goalie", "away_goalie_status"
        )
        self.assertEqual(info["goalie_name"], "")
        self.assertEqual(info["status"], 2)
        self.assertIsNone(info["goalie"])

    def test_unconfirmed_with_no_goalie_shows_roster_goalie(self):
        """When status is Unconfirmed and no goalie set, show roster goalie."""
        from leagues.views import get_goalie_display_info

        matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.team,
            hometeam=self.other_team,
            away_goalie=None,
            away_goalie_status=3,  # Unconfirmed
            home_goalie_status=3,
        )
        info = get_goalie_display_info(
            matchup, self.team, "away_goalie", "away_goalie_status"
        )
        self.assertEqual(info["goalie_name"], "Roster Goalie")
        self.assertEqual(info["goalie"], self.roster_goalie)
        self.assertTrue(info["is_roster_goalie"])
        self.assertFalse(info["is_sub"])

    def test_confirmed_with_sub_shows_sub_info(self):
        """When confirmed with a sub goalie, should show sub info."""
        from leagues.views import get_goalie_display_info

        matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(12, 0),
            awayteam=self.team,
            hometeam=self.other_team,
            away_goalie=self.sub_goalie,
            away_goalie_status=1,  # Confirmed
            home_goalie_status=3,
        )
        info = get_goalie_display_info(
            matchup, self.team, "away_goalie", "away_goalie_status"
        )
        self.assertEqual(info["goalie_name"], "Sub Goalie")
        self.assertEqual(info["goalie"], self.sub_goalie)
        self.assertTrue(info["is_sub"])
        self.assertFalse(info["is_roster_goalie"])


class PrimaryGoalieTest(TestCase):
    """Tests for primary goalie designation and selection logic."""

    def setUp(self):
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.team = Team.objects.create(
            team_name="Test Team",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.goalie1 = Player.objects.create(first_name="Primary", last_name="Goalie")
        self.goalie2 = Player.objects.create(first_name="Backup", last_name="Goalie")

    def test_primary_goalie_selected_over_first_goalie(self):
        """Primary goalie should be returned even if not first in queryset."""
        from leagues.models import Roster
        from leagues.views import get_roster_goalie

        # Create first goalie (not primary)
        Roster.objects.create(
            player=self.goalie1,
            team=self.team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=False,
        )
        # Create second goalie (primary)
        Roster.objects.create(
            player=self.goalie2,
            team=self.team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=True,
        )

        result = get_roster_goalie(self.team)
        self.assertEqual(result, self.goalie2)

    def test_fallback_to_first_goalie_when_no_primary(self):
        """Without a primary goalie, return first non-substitute goalie."""
        from leagues.models import Roster
        from leagues.views import get_roster_goalie

        Roster.objects.create(
            player=self.goalie1,
            team=self.team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=False,
        )
        Roster.objects.create(
            player=self.goalie2,
            team=self.team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=False,
        )

        result = get_roster_goalie(self.team)
        self.assertIn(result, [self.goalie1, self.goalie2])

    def test_primary_goalie_validation_prevents_duplicate(self):
        """Only one primary goalie allowed per team."""
        from leagues.models import Roster

        Roster.objects.create(
            player=self.goalie1,
            team=self.team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=True,
        )
        duplicate = Roster(
            player=self.goalie2,
            team=self.team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=True,
        )

        with self.assertRaises(ValidationError) as context:
            duplicate.full_clean()

        self.assertIn("is_primary_goalie", context.exception.error_dict)

    def test_primary_goalie_on_different_teams_allowed(self):
        """Different teams can each have their own primary goalie."""
        from leagues.models import Roster

        other_team = Team.objects.create(
            team_name="Other Team",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )

        # Primary on first team
        roster1 = Roster(
            player=self.goalie1,
            team=self.team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=True,
        )
        roster1.full_clean()
        roster1.save()

        # Primary on second team (should be allowed)
        roster2 = Roster(
            player=self.goalie2,
            team=other_team,
            position1=4,
            is_substitute=False,
            is_primary_goalie=True,
        )
        roster2.full_clean()  # Should not raise
        roster2.save()

    def test_substitute_goalie_not_returned_as_roster_goalie(self):
        """Substitute goalies should not be returned by get_roster_goalie."""
        from leagues.models import Roster
        from leagues.views import get_roster_goalie

        # Only a substitute goalie on roster
        Roster.objects.create(
            player=self.goalie1,
            team=self.team,
            position1=4,
            is_substitute=True,
            is_primary_goalie=False,
        )

        result = get_roster_goalie(self.team)
        self.assertIsNone(result)

    def test_position2_goalie_selected(self):
        """Goalie with position2=4 should be found."""
        from leagues.models import Roster
        from leagues.views import get_roster_goalie

        Roster.objects.create(
            player=self.goalie1,
            team=self.team,
            position1=1,  # Not goalie
            position2=4,  # Goalie as secondary position
            is_substitute=False,
            is_primary_goalie=True,
        )

        result = get_roster_goalie(self.team)
        self.assertEqual(result, self.goalie1)


class WeekCancellationModelTest(TestCase):
    """Tests for the Week.is_cancelled field."""

    def setUp(self):
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.today = datetime.date.today()

    def test_is_cancelled_defaults_to_false(self):
        week = Week.objects.create(
            division=self.division, season=self.season, date=self.today
        )
        self.assertFalse(week.is_cancelled)

    def test_can_mark_week_as_cancelled(self):
        week = Week.objects.create(
            division=self.division, season=self.season, date=self.today
        )
        week.is_cancelled = True
        week.save()
        week.refresh_from_db()
        self.assertTrue(week.is_cancelled)

    def test_can_restore_cancelled_week(self):
        week = Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        week.is_cancelled = False
        week.save()
        week.refresh_from_db()
        self.assertFalse(week.is_cancelled)

    def test_bulk_update_cancels_all_for_date(self):
        division2 = Division.objects.create(division=2)
        Week.objects.create(division=self.division, season=self.season, date=self.today)
        Week.objects.create(division=division2, season=self.season, date=self.today)
        count = Week.objects.filter(date=self.today).update(is_cancelled=True)
        self.assertEqual(count, 2)
        self.assertEqual(
            Week.objects.filter(date=self.today, is_cancelled=True).count(), 2
        )

    def test_cancelled_flag_persists_across_instances(self):
        week = Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        reloaded = Week.objects.get(pk=week.pk)
        self.assertTrue(reloaded.is_cancelled)

    def test_uncancelled_week_not_in_cancelled_filter(self):
        Week.objects.create(division=self.division, season=self.season, date=self.today)
        self.assertFalse(
            Week.objects.filter(date=self.today, is_cancelled=True).exists()
        )


class WeekAdminQuickCancelViewTest(TestCase):
    """Tests for WeekAdmin quick-cancel views."""

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="adminpass123"
        )
        self.client.login(username="admin", password="adminpass123")
        self.quick_cancel_permission = Permission.objects.get(
            content_type__app_label="leagues",
            codename="can_quick_cancel_games",
        )

        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division1 = Division.objects.create(division=1)
        self.division2 = Division.objects.create(division=2)
        self.today = datetime.date.today()
        self.week = Week.objects.create(
            division=self.division1, season=self.season, date=self.today
        )

    def _create_quick_cancel_user(self, username):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@test.com",
            password="testpass123",
            is_staff=True,
        )
        group = Group.objects.create(name="Quick Cancel Operators Test Group")
        group.permissions.add(self.quick_cancel_permission)
        user.groups.add(group)
        return user

    def test_quick_cancel_week_toggles_to_cancelled(self):
        url = reverse("admin:leagues_week_quick_cancel", args=[self.week.pk])
        response = self.client.post(url)
        self.week.refresh_from_db()
        self.assertTrue(self.week.is_cancelled)
        self.assertRedirects(response, reverse("admin:index"))

    def test_quick_cancel_week_toggles_back_to_active(self):
        self.week.is_cancelled = True
        self.week.save()
        url = reverse("admin:leagues_week_quick_cancel", args=[self.week.pk])
        self.client.post(url)
        self.week.refresh_from_db()
        self.assertFalse(self.week.is_cancelled)

    def test_quick_cancel_week_get_redirects_without_change(self):
        url = reverse("admin:leagues_week_quick_cancel", args=[self.week.pk])
        response = self.client.get(url)
        self.assertRedirects(response, reverse("admin:index"))
        self.week.refresh_from_db()
        self.assertFalse(self.week.is_cancelled)

    def test_quick_cancel_week_requires_login(self):
        self.client.logout()
        url = reverse("admin:leagues_week_quick_cancel", args=[self.week.pk])
        response = self.client.post(url)
        # Should redirect to login, not succeed
        self.assertNotEqual(response.status_code, 200)
        self.week.refresh_from_db()
        self.assertFalse(self.week.is_cancelled)

    def test_quick_cancel_date_cancels_all_weeks_for_date(self):
        week2 = Week.objects.create(
            division=self.division2, season=self.season, date=self.today
        )
        date_str = self.today.strftime("%Y-%m-%d")
        url = reverse("admin:leagues_week_quick_cancel_date", args=[date_str, 1])
        self.client.post(url)
        self.week.refresh_from_db()
        week2.refresh_from_db()
        self.assertTrue(self.week.is_cancelled)
        self.assertTrue(week2.is_cancelled)

    def test_quick_cancel_date_restores_all_weeks_for_date(self):
        week2 = Week.objects.create(
            division=self.division2,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        self.week.is_cancelled = True
        self.week.save()
        date_str = self.today.strftime("%Y-%m-%d")
        url = reverse("admin:leagues_week_quick_cancel_date", args=[date_str, 0])
        self.client.post(url)
        self.week.refresh_from_db()
        week2.refresh_from_db()
        self.assertFalse(self.week.is_cancelled)
        self.assertFalse(week2.is_cancelled)

    def test_quick_cancel_date_get_redirects_without_change(self):
        date_str = self.today.strftime("%Y-%m-%d")
        url = reverse("admin:leagues_week_quick_cancel_date", args=[date_str, 1])
        response = self.client.get(url)
        self.assertRedirects(response, reverse("admin:index"))
        self.week.refresh_from_db()
        self.assertFalse(self.week.is_cancelled)

    def test_quick_cancel_week_does_not_affect_other_dates(self):
        tomorrow = self.today + datetime.timedelta(days=1)
        other_week = Week.objects.create(
            division=self.division1, season=self.season, date=tomorrow
        )
        url = reverse("admin:leagues_week_quick_cancel", args=[self.week.pk])
        self.client.post(url)
        other_week.refresh_from_db()
        self.assertFalse(other_week.is_cancelled)

    def test_staff_user_with_quick_cancel_permission_can_toggle(self):
        self.client.logout()
        self._create_quick_cancel_user("qc-user")
        self.client.login(username="qc-user", password="testpass123")

        url = reverse("admin:leagues_week_quick_cancel", args=[self.week.pk])
        response = self.client.post(url)

        self.week.refresh_from_db()
        self.assertTrue(self.week.is_cancelled)
        self.assertRedirects(response, reverse("admin:index"))

    def test_staff_user_without_quick_cancel_permission_gets_403(self):
        self.client.logout()
        User.objects.create_user(
            username="staff-no-perm",
            email="staff-no-perm@test.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.login(username="staff-no-perm", password="testpass123")

        url = reverse("admin:leagues_week_quick_cancel", args=[self.week.pk])
        response = self.client.post(url)

        self.week.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.week.is_cancelled)


class QuickCancelTemplateTagTest(TestCase):
    """Tests for the quick_cancel_widget template tag logic."""

    def setUp(self):
        self.season = Season.objects.create(
            year=datetime.datetime.now().year, season_type=1, is_current_season=True
        )
        self.division1 = Division.objects.create(division=1)
        self.division2 = Division.objects.create(division=2)
        self.today = datetime.date.today()

    def _call_tag(self):
        from leagues.templatetags.admin_quick_cancel import quick_cancel_widget

        return quick_cancel_widget({"csrf_token": "testtoken"})

    def test_shows_weeks_within_upcoming_window(self):
        Week.objects.create(
            division=self.division1, season=self.season, date=self.today
        )
        result = self._call_tag()
        self.assertIn(self.today, result["grouped_weeks"])

    def test_excludes_past_weeks(self):
        past_date = self.today - datetime.timedelta(days=1)
        Week.objects.create(division=self.division1, season=self.season, date=past_date)
        result = self._call_tag()
        self.assertNotIn(past_date, result["grouped_weeks"])

    def test_includes_weeks_just_beyond_one_week(self):
        # The window is 90 days, so a week 8 days out should still be shown.
        future_date = self.today + datetime.timedelta(days=8)
        Week.objects.create(
            division=self.division1, season=self.season, date=future_date
        )
        result = self._call_tag()
        self.assertIn(future_date, result["grouped_weeks"])

    def test_all_cancelled_true_when_all_weeks_cancelled(self):
        Week.objects.create(
            division=self.division1,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        result = self._call_tag()
        info = result["grouped_weeks"][self.today]
        self.assertTrue(info["all_cancelled"])
        self.assertTrue(info["any_cancelled"])

    def test_all_cancelled_false_when_none_are_cancelled(self):
        Week.objects.create(
            division=self.division1,
            season=self.season,
            date=self.today,
            is_cancelled=False,
        )
        result = self._call_tag()
        info = result["grouped_weeks"][self.today]
        self.assertFalse(info["all_cancelled"])
        self.assertFalse(info["any_cancelled"])

    def test_mixed_state_sets_any_but_not_all_cancelled(self):
        Week.objects.create(
            division=self.division1,
            season=self.season,
            date=self.today,
            is_cancelled=True,
        )
        Week.objects.create(
            division=self.division2,
            season=self.season,
            date=self.today,
            is_cancelled=False,
        )
        result = self._call_tag()
        info = result["grouped_weeks"][self.today]
        self.assertFalse(info["all_cancelled"])
        self.assertTrue(info["any_cancelled"])

    def test_empty_result_when_no_upcoming_weeks(self):
        result = self._call_tag()
        self.assertEqual(result["grouped_weeks"], {})

    def test_today_passed_in_context(self):
        result = self._call_tag()
        self.assertEqual(result["today"], self.today)

    def test_multiple_divisions_grouped_under_same_date(self):
        Week.objects.create(
            division=self.division1, season=self.season, date=self.today
        )
        Week.objects.create(
            division=self.division2, season=self.season, date=self.today
        )
        result = self._call_tag()
        self.assertEqual(len(result["grouped_weeks"][self.today]["weeks"]), 2)


class CreateQuickCancelGroupCommandTest(TestCase):
    def test_command_creates_group_permission_and_user(self):
        call_command(
            "create_quick_cancel_group",
            username="brett",
            password="brettrules",
        )

        group = Group.objects.get(name="Quick Cancel Operators")
        permission = Permission.objects.get(
            content_type__app_label="leagues",
            codename="can_quick_cancel_games",
        )
        self.assertEqual(list(group.permissions.all()), [permission])

        user = User.objects.get(username="brett")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("brettrules"))
        self.assertEqual(list(user.groups.all()), [group])
        self.assertEqual(user.user_permissions.count(), 0)

    def test_command_is_idempotent_for_existing_user(self):
        existing = User.objects.create_user(
            username="brett",
            email="old@example.com",
            password="oldpassword",
            is_staff=False,
            is_superuser=True,
        )
        extra_group = Group.objects.create(name="Other Group")
        existing.groups.add(extra_group)

        call_command(
            "create_quick_cancel_group",
            username="brett",
            password="brettrules",
            email="brett@example.com",
        )

        existing.refresh_from_db()
        self.assertTrue(existing.is_staff)
        self.assertFalse(existing.is_superuser)
        self.assertEqual(existing.email, "brett@example.com")
        self.assertTrue(existing.check_password("brettrules"))
        self.assertEqual(existing.groups.count(), 1)
        self.assertEqual(existing.groups.first().name, "Quick Cancel Operators")
