from os.path import abspath, join, dirname
from shutil import rmtree
from tempfile import mkdtemp
import datetime

from django.core.exceptions import ValidationError
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
