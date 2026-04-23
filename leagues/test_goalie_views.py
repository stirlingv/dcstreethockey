"""
Tests for goalie status views and helper functions in leagues/views.py.

Covers:
  - get_roster_goalie()  — primary goalie, fallback, no goalie, position2, substitute exclusion
  - get_goalie_display_info() — sub-needed, explicit sub, no explicit goalie
  - goalie_status_board view — HTTP 200, sub_needed_count, past games excluded
  - captain_goalie_update view — valid/invalid access code, past matchups excluded
  - update_goalie_status endpoint — confirmed, sub-needed, unauthorized, invalid inputs
"""
import datetime
import uuid

from django.test import Client, TestCase
from django.urls import reverse

from leagues.models import Division, MatchUp, Player, Roster, Season, Team, Week
from leagues.views import get_goalie_display_info, get_roster_goalie


# ---------------------------------------------------------------------------
# Shared fixture helper
# ---------------------------------------------------------------------------


def make_season(year=2024):
    return Season.objects.create(year=year, season_type=1, is_current_season=True)


def make_division(division=1):
    return Division.objects.create(division=division)


def make_team(name, division, season, color="Red", active=True):
    return Team.objects.create(
        team_name=name,
        team_color=color,
        division=division,
        season=season,
        is_active=active,
    )


def make_week(division, season, offset_days=3):
    date = datetime.date.today() + datetime.timedelta(days=offset_days)
    return Week.objects.create(division=division, season=season, date=date)


def make_matchup(week, home, away, time=None):
    return MatchUp.objects.create(
        week=week,
        time=time or datetime.time(19, 0),
        hometeam=home,
        awayteam=away,
    )


# ---------------------------------------------------------------------------
# get_roster_goalie
# ---------------------------------------------------------------------------


class GetRosterGoalieTest(TestCase):
    def setUp(self):
        season = make_season()
        division = make_division()
        self.team = make_team("Goalies FC", division, season)

    def _goalie(self, first, last, **kwargs):
        p = Player.objects.create(first_name=first, last_name=last)
        Roster.objects.create(
            player=p, team=self.team, position1=4, is_captain=False, **kwargs
        )
        return p

    def _player(self, first, last):
        p = Player.objects.create(first_name=first, last_name=last)
        Roster.objects.create(player=p, team=self.team, position1=1, is_captain=False)
        return p

    def test_returns_primary_goalie_when_set(self):
        goalie = self._goalie("Primary", "Goalie", is_primary_goalie=True)
        self.assertEqual(get_roster_goalie(self.team), goalie)

    def test_falls_back_to_first_non_primary_goalie(self):
        goalie = self._goalie("Only", "Goalie", is_primary_goalie=False)
        self.assertEqual(get_roster_goalie(self.team), goalie)

    def test_returns_none_when_no_goalie_on_roster(self):
        self._player("Fast", "Forward")
        self.assertIsNone(get_roster_goalie(self.team))

    def test_returns_none_when_only_substitute_goalie(self):
        self._goalie("Sub", "Goalie", is_substitute=True)
        self.assertIsNone(get_roster_goalie(self.team))

    def test_finds_goalie_listed_in_position2(self):
        p = Player.objects.create(first_name="Dual", last_name="Role")
        Roster.objects.create(
            player=p, team=self.team, position1=1, position2=4, is_captain=False
        )
        self.assertEqual(get_roster_goalie(self.team), p)

    def test_primary_goalie_preferred_over_earlier_non_primary(self):
        first = self._goalie("First", "Goalie", is_primary_goalie=False)
        primary = self._goalie("Primary", "GoalieB", is_primary_goalie=True)
        self.assertEqual(get_roster_goalie(self.team), primary)

    def test_returns_none_for_empty_roster(self):
        self.assertIsNone(get_roster_goalie(self.team))


# ---------------------------------------------------------------------------
# get_goalie_display_info
# ---------------------------------------------------------------------------


class GetGoalieDisplayInfoTest(TestCase):
    def setUp(self):
        season = make_season()
        division = make_division()
        self.home_team = make_team("Home", division, season)
        self.away_team = make_team("Away", division, season, color="Blue")
        week = make_week(division, season)
        self.matchup = make_matchup(week, self.home_team, self.away_team)
        self.roster_goalie = Player.objects.create(
            first_name="Roster", last_name="Goalie"
        )
        Roster.objects.create(
            player=self.roster_goalie,
            team=self.home_team,
            position1=4,
            is_captain=False,
            is_primary_goalie=True,
        )

    def test_sub_needed_returns_no_goalie_name(self):
        self.matchup.home_goalie_status = 2
        self.matchup.save()
        info = get_goalie_display_info(
            self.matchup, self.home_team, "home_goalie", "home_goalie_status"
        )
        self.assertEqual(info["goalie_name"], "")
        self.assertIsNone(info["goalie"])
        self.assertFalse(info["is_sub"])

    def test_no_explicit_goalie_defaults_to_roster_goalie(self):
        self.matchup.home_goalie = None
        self.matchup.home_goalie_status = 3  # Unconfirmed
        self.matchup.save()
        info = get_goalie_display_info(
            self.matchup, self.home_team, "home_goalie", "home_goalie_status"
        )
        self.assertEqual(info["goalie"], self.roster_goalie)
        self.assertFalse(info["is_sub"])
        self.assertTrue(info["is_roster_goalie"])

    def test_explicit_sub_goalie_flagged_as_sub(self):
        sub_goalie = Player.objects.create(first_name="Sub", last_name="Goalie")
        self.matchup.home_goalie = sub_goalie
        self.matchup.home_goalie_status = 1  # Confirmed
        self.matchup.save()
        info = get_goalie_display_info(
            self.matchup, self.home_team, "home_goalie", "home_goalie_status"
        )
        self.assertTrue(info["is_sub"])
        self.assertFalse(info["is_roster_goalie"])

    def test_roster_goalie_as_explicit_goalie_not_flagged_as_sub(self):
        self.matchup.home_goalie = self.roster_goalie
        self.matchup.home_goalie_status = 1
        self.matchup.save()
        info = get_goalie_display_info(
            self.matchup, self.home_team, "home_goalie", "home_goalie_status"
        )
        self.assertFalse(info["is_sub"])
        self.assertTrue(info["is_roster_goalie"])

    def test_no_roster_goalie_shows_no_goalie_message(self):
        """Team with no goalie on roster and no explicit goalie set."""
        empty_team = make_team(
            "No Goalie", self.home_team.division, self.home_team.season, color="Green"
        )
        week = Week.objects.get(id=self.matchup.week_id)
        matchup2 = make_matchup(
            week, empty_team, self.away_team, time=datetime.time(20, 0)
        )
        info = get_goalie_display_info(
            matchup2, empty_team, "home_goalie", "home_goalie_status"
        )
        self.assertEqual(info["goalie_name"], "No goalie on roster")


# ---------------------------------------------------------------------------
# goalie_status_board view
# ---------------------------------------------------------------------------


class GoalieStatusBoardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        season = make_season()
        self.division = make_division()
        self.home_team = make_team("Home", self.division, season)
        self.away_team = make_team("Away", self.division, season, color="Blue")
        self.week = make_week(self.division, season, offset_days=3)
        self.matchup = make_matchup(self.week, self.home_team, self.away_team)

    def test_returns_200(self):
        self.assertEqual(
            self.client.get(reverse("goalie_status_board")).status_code, 200
        )

    def test_context_has_weeks_data_and_sub_needed_count(self):
        response = self.client.get(reverse("goalie_status_board"))
        self.assertIn("weeks_data", response.context)
        self.assertIn("sub_needed_count", response.context)

    def test_sub_needed_count_reflects_home_sub_needed(self):
        self.matchup.home_goalie_status = 2
        self.matchup.save()
        response = self.client.get(reverse("goalie_status_board"))
        self.assertEqual(response.context["sub_needed_count"], 1)

    def test_sub_needed_count_zero_when_all_confirmed(self):
        self.matchup.home_goalie_status = 1
        self.matchup.away_goalie_status = 1
        self.matchup.save()
        response = self.client.get(reverse("goalie_status_board"))
        self.assertEqual(response.context["sub_needed_count"], 0)

    def test_past_games_not_shown(self):
        past_week = Week.objects.create(
            division=self.division,
            season=self.week.season,
            date=datetime.date.today() - datetime.timedelta(days=3),
        )
        make_matchup(
            past_week, self.home_team, self.away_team, time=datetime.time(20, 0)
        )
        response = self.client.get(reverse("goalie_status_board"))
        all_dates = [wd["week"].date for wd in response.context["weeks_data"]]
        for d in all_dates:
            self.assertGreaterEqual(
                d, datetime.date.today(), msg=f"Past date {d} shown on board"
            )

    def test_status_choices_in_context(self):
        response = self.client.get(reverse("goalie_status_board"))
        self.assertIn("status_choices", response.context)

    def test_two_sub_needed_counted_correctly(self):
        self.matchup.home_goalie_status = 2
        self.matchup.away_goalie_status = 2
        self.matchup.save()
        response = self.client.get(reverse("goalie_status_board"))
        self.assertEqual(response.context["sub_needed_count"], 1)  # still 1 matchup


# ---------------------------------------------------------------------------
# captain_goalie_update view
# ---------------------------------------------------------------------------


class CaptainGoalieUpdateViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        season = make_season()
        self.division = make_division()
        self.team = make_team("Captains", self.division, season)
        self.opponent = make_team("Opponent", self.division, season, color="Blue")
        self.week = make_week(self.division, season, offset_days=3)
        self.matchup = make_matchup(self.week, self.team, self.opponent)

    def _url(self, code=None):
        code = code or self.team.captain_access_code
        return reverse("captain_goalie_update", args=[str(code)])

    def test_valid_access_code_returns_200(self):
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_invalid_access_code_returns_404(self):
        self.assertEqual(self.client.get(self._url(uuid.uuid4())).status_code, 404)

    def test_inactive_team_code_returns_404(self):
        season = Season.objects.get(id=self.team.season_id)
        inactive = make_team(
            "Inactive", self.division, season, color="Gray", active=False
        )
        self.assertEqual(
            self.client.get(self._url(inactive.captain_access_code)).status_code, 404
        )

    def test_context_contains_correct_team(self):
        response = self.client.get(self._url())
        self.assertEqual(response.context["team"], self.team)

    def test_upcoming_matchup_present_in_context(self):
        response = self.client.get(self._url())
        ids = [m["matchup"].id for m in response.context["matchups_data"]]
        self.assertIn(self.matchup.id, ids)

    def test_past_matchup_not_shown(self):
        past_week = Week.objects.create(
            division=self.division,
            season=self.week.season,
            date=datetime.date.today() - datetime.timedelta(days=7),
        )
        past_matchup = make_matchup(
            past_week, self.team, self.opponent, time=datetime.time(20, 0)
        )
        response = self.client.get(self._url())
        ids = [m["matchup"].id for m in response.context["matchups_data"]]
        self.assertNotIn(past_matchup.id, ids)

    def test_is_home_flag_set_correctly(self):
        """Team is home — matchup data should reflect is_home=True."""
        response = self.client.get(self._url())
        entry = next(
            m
            for m in response.context["matchups_data"]
            if m["matchup"].id == self.matchup.id
        )
        self.assertTrue(entry["is_home"])

    def test_is_home_false_when_team_is_away(self):
        url = reverse(
            "captain_goalie_update", args=[str(self.opponent.captain_access_code)]
        )
        response = self.client.get(url)
        entry = next(
            m
            for m in response.context["matchups_data"]
            if m["matchup"].id == self.matchup.id
        )
        self.assertFalse(entry["is_home"])


# ---------------------------------------------------------------------------
# update_goalie_status endpoint
# ---------------------------------------------------------------------------


class UpdateGoalieStatusEndpointTest(TestCase):
    def setUp(self):
        self.client = Client()
        season = make_season()
        self.division = make_division()
        self.team = make_team("Updaters", self.division, season)
        self.opponent = make_team("Opponent", self.division, season, color="Blue")
        week = make_week(self.division, season, offset_days=3)
        self.matchup = make_matchup(week, self.team, self.opponent)
        self.goalie = Player.objects.create(
            first_name="Test", last_name="Goalie", is_active=True
        )
        Roster.objects.create(
            player=self.goalie,
            team=self.team,
            position1=4,
            is_captain=False,
            is_primary_goalie=True,
        )

    def _url(self, code=None, matchup_id=None):
        return reverse(
            "update_goalie_status",
            args=[
                str(code or self.team.captain_access_code),
                matchup_id or self.matchup.id,
            ],
        )

    # -- happy paths --

    def test_set_confirmed_status_for_home_team(self):
        response = self.client.post(
            self._url(), {"goalie_id": self.goalie.id, "status": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.matchup.refresh_from_db()
        self.assertEqual(self.matchup.home_goalie_status, 1)

    def test_set_unconfirmed_status(self):
        response = self.client.post(
            self._url(), {"goalie_id": self.goalie.id, "status": 3}
        )
        self.assertEqual(response.status_code, 200)
        self.matchup.refresh_from_db()
        self.assertEqual(self.matchup.home_goalie_status, 3)

    def test_sub_needed_clears_goalie_field(self):
        response = self.client.post(
            self._url(), {"goalie_id": self.goalie.id, "status": 2}
        )
        self.assertEqual(response.status_code, 200)
        self.matchup.refresh_from_db()
        self.assertIsNone(self.matchup.home_goalie)
        self.assertEqual(self.matchup.home_goalie_status, 2)

    def test_sub_needed_response_goalie_name_is_blank(self):
        response = self.client.post(self._url(), {"status": 2})
        self.assertEqual(response.json()["goalie_name"], "")

    def test_away_team_updates_away_side(self):
        url = self._url(code=self.opponent.captain_access_code)
        response = self.client.post(url, {"status": 1})
        self.assertEqual(response.status_code, 200)
        self.matchup.refresh_from_db()
        self.assertEqual(self.matchup.away_goalie_status, 1)

    def test_response_includes_status_display_text(self):
        response = self.client.post(self._url(), {"status": 1})
        self.assertEqual(response.json()["status_display"], "Confirmed")

    def test_response_is_sub_false_for_roster_goalie(self):
        response = self.client.post(
            self._url(), {"goalie_id": self.goalie.id, "status": 1}
        )
        self.assertFalse(response.json()["is_sub"])

    def test_response_is_sub_true_for_substitute_goalie(self):
        sub = Player.objects.create(
            first_name="Sub", last_name="GoalieY", is_active=True
        )
        response = self.client.post(self._url(), {"goalie_id": sub.id, "status": 1})
        self.assertTrue(response.json()["is_sub"])

    # -- error paths --

    def test_get_request_returns_405(self):
        self.assertEqual(self.client.get(self._url()).status_code, 405)

    def test_invalid_access_code_returns_404(self):
        self.assertEqual(
            self.client.post(self._url(code=uuid.uuid4()), {"status": 1}).status_code,
            404,
        )

    def test_team_not_in_matchup_returns_403(self):
        # Create a third team whose captain tries to update a matchup they're not in.
        third_team = make_team(
            "Third Team",
            self.team.division,
            Season.objects.get(id=self.team.season_id),
            color="Green",
        )
        url = self._url(code=third_team.captain_access_code)
        self.assertEqual(self.client.post(url, {"status": 1}).status_code, 403)

    def test_invalid_status_value_returns_400(self):
        self.assertEqual(self.client.post(self._url(), {"status": 99}).status_code, 400)

    def test_missing_status_returns_400(self):
        self.assertEqual(self.client.post(self._url(), {}).status_code, 400)

    def test_non_integer_status_returns_400(self):
        self.assertEqual(
            self.client.post(self._url(), {"status": "bad"}).status_code, 400
        )

    def test_invalid_goalie_id_returns_400(self):
        self.assertEqual(
            self.client.post(
                self._url(), {"goalie_id": 999999, "status": 1}
            ).status_code,
            400,
        )

    def test_roster_sentinel_does_not_set_explicit_goalie(self):
        """Passing goalie_id='roster' should leave the explicit goalie field as None."""
        self.client.post(self._url(), {"goalie_id": "roster", "status": 1})
        self.matchup.refresh_from_db()
        self.assertIsNone(self.matchup.home_goalie)
        self.assertEqual(self.matchup.home_goalie_status, 1)


# ---------------------------------------------------------------------------
# can_play_goalie flag
# ---------------------------------------------------------------------------


class CanPlayGoalieTest(TestCase):
    """Players flagged can_play_goalie appear in goalie sub dropdowns even when
    they have no goalie position on any roster entry."""

    def setUp(self):
        self.client = Client()
        season = make_season()
        self.division = make_division()
        self.team = make_team("Test Team", self.division, season)
        self.opponent = make_team("Opponent", self.division, season, color="Blue")
        self.week = make_week(self.division, season, offset_days=3)
        self.matchup = make_matchup(self.week, self.team, self.opponent)

        # Roster goalie so the page renders properly
        self.roster_goalie = Player.objects.create(
            first_name="Roster", last_name="Goalie", is_active=True
        )
        Roster.objects.create(
            player=self.roster_goalie,
            team=self.team,
            position1=4,
            is_captain=False,
            is_primary_goalie=True,
        )

    def _url(self):
        return reverse(
            "captain_goalie_update", args=[str(self.team.captain_access_code)]
        )

    def test_can_play_goalie_player_appears_in_all_goalies(self):
        """A non-goalie player with can_play_goalie=True should appear in the dropdown."""
        flex = Player.objects.create(
            first_name="Flex", last_name="Player", is_active=True, can_play_goalie=True
        )
        Roster.objects.create(
            player=flex, team=self.team, position1=3, is_captain=False
        )
        response = self.client.get(self._url())
        self.assertIn(flex, response.context["all_goalies"])

    def test_non_goalie_without_flag_excluded_from_all_goalies(self):
        """A non-goalie player without can_play_goalie should NOT appear in the dropdown."""
        defender = Player.objects.create(
            first_name="Def", last_name="Ender", is_active=True, can_play_goalie=False
        )
        Roster.objects.create(
            player=defender, team=self.team, position1=3, is_captain=False
        )
        response = self.client.get(self._url())
        self.assertNotIn(defender, response.context["all_goalies"])

    def test_inactive_can_play_goalie_player_excluded(self):
        """can_play_goalie has no effect for inactive players."""
        inactive = Player.objects.create(
            first_name="Old", last_name="Timer", is_active=False, can_play_goalie=True
        )
        response = self.client.get(self._url())
        self.assertNotIn(inactive, response.context["all_goalies"])

    def test_rostered_goalie_still_appears_without_flag(self):
        """The existing logic still works — goalie position on roster is sufficient."""
        response = self.client.get(self._url())
        self.assertIn(self.roster_goalie, response.context["all_goalies"])
