"""
Tests for schedule/scores/cups views and their helper functions.

Covers:
  - add_goals_for_matchups() annotation
  - get_stats_for_matchup() filtering
  - get_goalies_for_matchup() filtering
  - get_matches_for_division() queryset
  - get_matches_for_team() queryset
  - scores view (all divisions, specific division, invalid division)
  - schedule view
  - cups view
"""
import datetime

from django.db.models import F, Q
from django.test import Client, TestCase
from django.urls import reverse

from core.views.schedule import (
    add_goals_for_matchups,
    get_goalies_for_matchup,
    get_matches_for_division,
    get_matches_for_team,
    get_stats_for_matchup,
)
from leagues.models import Division, MatchUp, Player, Roster, Season, Stat, Team, Week


# ---------------------------------------------------------------------------
# Shared fixture mixin
# ---------------------------------------------------------------------------


class ScheduleTestBase(TestCase):
    """Creates a minimal season/division/team/matchup fixture for reuse."""

    def setUp(self):
        self.season = Season.objects.create(
            year=2024, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.home_team = Team.objects.create(
            team_name="Home Team",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.away_team = Team.objects.create(
            team_name="Away Team",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.past_date = datetime.date.today() - datetime.timedelta(days=7)
        self.week = Week.objects.create(
            division=self.division,
            season=self.season,
            date=self.past_date,
        )
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )
        self.home_player = Player.objects.create(first_name="Home", last_name="Player")
        self.away_player = Player.objects.create(first_name="Away", last_name="Forward")
        Roster.objects.create(
            player=self.home_player,
            team=self.home_team,
            position1=1,
            is_captain=False,
        )
        Roster.objects.create(
            player=self.away_player,
            team=self.away_team,
            position1=1,
            is_captain=False,
        )


# ---------------------------------------------------------------------------
# add_goals_for_matchups
# ---------------------------------------------------------------------------


class AddGoalsForMatchupsTest(ScheduleTestBase):
    """Tests for the add_goals_for_matchups() annotation."""

    def test_no_stats_gives_zero_goals_for_both_teams(self):
        m = add_goals_for_matchups(MatchUp.objects.filter(id=self.matchup.id)).first()
        self.assertEqual(m.home_goals, 0)
        self.assertEqual(m.away_goals, 0)

    def test_home_goals_attributed_to_home_team(self):
        Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=3,
            assists=1,
        )
        m = add_goals_for_matchups(MatchUp.objects.filter(id=self.matchup.id)).first()
        self.assertEqual(m.home_goals, 3)
        self.assertEqual(m.away_goals, 0)

    def test_away_goals_attributed_to_away_team(self):
        Stat.objects.create(
            player=self.away_player,
            team=self.away_team,
            matchup=self.matchup,
            goals=2,
            assists=0,
        )
        m = add_goals_for_matchups(MatchUp.objects.filter(id=self.matchup.id)).first()
        self.assertEqual(m.home_goals, 0)
        self.assertEqual(m.away_goals, 2)

    def test_both_teams_goals_independent(self):
        Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=4,
        )
        Stat.objects.create(
            player=self.away_player,
            team=self.away_team,
            matchup=self.matchup,
            goals=1,
        )
        m = add_goals_for_matchups(MatchUp.objects.filter(id=self.matchup.id)).first()
        self.assertEqual(m.home_goals, 4)
        self.assertEqual(m.away_goals, 1)

    def test_multiple_scorers_summed_for_home_team(self):
        p2 = Player.objects.create(first_name="Second", last_name="Scorer")
        Roster.objects.create(
            player=p2, team=self.home_team, position1=2, is_captain=False
        )
        Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=2,
        )
        Stat.objects.create(
            player=p2, team=self.home_team, matchup=self.matchup, goals=3
        )
        m = add_goals_for_matchups(MatchUp.objects.filter(id=self.matchup.id)).first()
        self.assertEqual(m.home_goals, 5)

    def test_assists_do_not_inflate_goal_count(self):
        Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=1,
            assists=5,
        )
        m = add_goals_for_matchups(MatchUp.objects.filter(id=self.matchup.id)).first()
        self.assertEqual(m.home_goals, 1)


# ---------------------------------------------------------------------------
# get_stats_for_matchup
# ---------------------------------------------------------------------------


class GetStatsForMatchupTest(ScheduleTestBase):
    """Tests for the get_stats_for_matchup() filtering logic."""

    def test_includes_stat_with_goals(self):
        stat = Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=2,
            assists=0,
        )
        self.assertIn(stat, get_stats_for_matchup(self.matchup))

    def test_includes_stat_with_assists_only(self):
        stat = Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=0,
            assists=1,
        )
        self.assertIn(stat, get_stats_for_matchup(self.matchup))

    def test_excludes_zero_goals_and_zero_assists(self):
        Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=0,
            assists=0,
        )
        self.assertEqual(list(get_stats_for_matchup(self.matchup)), [])

    def test_excludes_null_goals_and_null_assists(self):
        Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=None,
            assists=None,
        )
        self.assertEqual(list(get_stats_for_matchup(self.matchup)), [])

    def test_ordered_by_goals_descending(self):
        p2 = Player.objects.create(first_name="Top", last_name="Scorer")
        Roster.objects.create(
            player=p2, team=self.home_team, position1=1, is_captain=False
        )
        low = Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=1,
        )
        high = Stat.objects.create(
            player=p2, team=self.home_team, matchup=self.matchup, goals=3
        )
        result = list(get_stats_for_matchup(self.matchup))
        self.assertEqual(result[0], high)
        self.assertEqual(result[1], low)


# ---------------------------------------------------------------------------
# get_goalies_for_matchup
# ---------------------------------------------------------------------------


class GetGoaliesForMatchupTest(ScheduleTestBase):
    """Tests for get_goalies_for_matchup() which identifies goalie stat rows."""

    def _create_goalie(self, first, last, team):
        goalie = Player.objects.create(first_name=first, last_name=last)
        Roster.objects.create(player=goalie, team=team, position1=4, is_captain=False)
        return goalie

    def test_home_goalie_stat_identified(self):
        goalie = self._create_goalie("Home", "Goalie", self.home_team)
        stat = Stat.objects.create(
            player=goalie,
            team=self.home_team,
            matchup=self.matchup,
            goals=0,
            assists=0,
        )
        result = list(get_goalies_for_matchup(self.matchup, home=True))
        self.assertIn(stat, result)

    def test_away_goalie_stat_identified(self):
        goalie = self._create_goalie("Away", "Goalie", self.away_team)
        stat = Stat.objects.create(
            player=goalie,
            team=self.away_team,
            matchup=self.matchup,
            goals=0,
            assists=0,
        )
        result = list(get_goalies_for_matchup(self.matchup, home=False))
        self.assertIn(stat, result)

    def test_home_query_does_not_return_away_goalie(self):
        goalie = self._create_goalie("Away", "GoalieX", self.away_team)
        Stat.objects.create(
            player=goalie,
            team=self.away_team,
            matchup=self.matchup,
            goals=0,
            assists=0,
        )
        result = list(get_goalies_for_matchup(self.matchup, home=True))
        self.assertEqual(result, [])

    def test_non_goalie_stat_not_returned_as_goalie(self):
        """A non-goalie player with goals > 0 must not appear in the goalie query."""
        Stat.objects.create(
            player=self.home_player,
            team=self.home_team,
            matchup=self.matchup,
            goals=2,
            assists=1,
        )
        result = list(get_goalies_for_matchup(self.matchup, home=True))
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# get_matches_for_division / get_matches_for_team
# ---------------------------------------------------------------------------


class GetMatchesForDivisionTest(ScheduleTestBase):
    def test_returns_matchups_for_division(self):
        self.assertIn(self.matchup, get_matches_for_division(self.division))

    def test_excludes_matchups_with_inactive_away_team(self):
        inactive = Team.objects.create(
            team_name="Inactive",
            team_color="Gray",
            division=self.division,
            season=self.season,
            is_active=False,
        )
        inactive_matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(20, 0),
            hometeam=self.home_team,
            awayteam=inactive,
        )
        results = list(get_matches_for_division(self.division))
        self.assertNotIn(inactive_matchup, results)

    def test_ordered_most_recent_first(self):
        future_week = Week.objects.create(
            division=self.division,
            season=self.season,
            date=datetime.date.today() + datetime.timedelta(days=7),
        )
        future_matchup = MatchUp.objects.create(
            week=future_week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )
        results = list(get_matches_for_division(self.division))
        self.assertEqual(results[0], future_matchup)


class GetMatchesForTeamTest(ScheduleTestBase):
    def test_includes_home_matchup(self):
        self.assertIn(self.matchup, get_matches_for_team(self.home_team.id))

    def test_includes_away_matchup(self):
        self.assertIn(self.matchup, get_matches_for_team(self.away_team.id))

    def test_excludes_matchup_for_unrelated_team(self):
        other = Team.objects.create(
            team_name="Other Team",
            team_color="Green",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.assertNotIn(self.matchup, get_matches_for_team(other.id))


# ---------------------------------------------------------------------------
# scores view
# ---------------------------------------------------------------------------


class ScoresViewTest(ScheduleTestBase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_all_divisions_returns_200(self):
        response = self.client.get(reverse("scores"))
        self.assertEqual(response.status_code, 200)

    def test_specific_division_returns_200(self):
        response = self.client.get(f"/scores/{self.division.division}/")
        self.assertEqual(response.status_code, 200)

    def test_invalid_division_returns_200_with_empty_matchups(self):
        response = self.client.get("/scores/9/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matchups"], {})

    def test_context_has_required_keys(self):
        response = self.client.get(reverse("scores"))
        for key in ("divisions", "matchups", "active_division"):
            self.assertIn(key, response.context)

    def test_default_active_division_is_zero(self):
        response = self.client.get(reverse("scores"))
        self.assertEqual(response.context["active_division"], 0)

    def test_division_name_in_context_for_valid_division(self):
        response = self.client.get(f"/scores/{self.division.division}/")
        self.assertIn("division_name", response.context)
        self.assertEqual(response.context["division_name"], "Sunday D1")


# ---------------------------------------------------------------------------
# schedule view
# ---------------------------------------------------------------------------


class ScheduleViewTest(ScheduleTestBase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_returns_200(self):
        response = self.client.get(reverse("schedule"))
        self.assertEqual(response.status_code, 200)

    def test_context_has_schedule_key(self):
        response = self.client.get(reverse("schedule"))
        self.assertIn("schedule", response.context)

    def test_past_games_not_in_schedule(self):
        """The past matchup created in setUp must not appear in the forward schedule."""
        response = self.client.get(reverse("schedule"))
        today = datetime.date.today()
        for date_key in response.context["schedule"]:
            self.assertGreaterEqual(
                datetime.date.fromisoformat(str(date_key)),
                today,
                msg=f"Found past date {date_key} in schedule",
            )

    def test_future_game_appears_in_schedule(self):
        future_date = datetime.date.today() + datetime.timedelta(days=7)
        future_week = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        MatchUp.objects.create(
            week=future_week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )
        response = self.client.get(reverse("schedule"))
        self.assertIn(future_date, response.context["schedule"])


# ---------------------------------------------------------------------------
# cups view
# ---------------------------------------------------------------------------


class CupsViewTest(ScheduleTestBase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_valid_division_returns_200(self):
        response = self.client.get(f"/cups/{self.division.division}/")
        self.assertEqual(response.status_code, 200)

    def test_context_has_matchups_key(self):
        response = self.client.get(f"/cups/{self.division.division}/")
        self.assertIn("matchups", response.context)

    def test_invalid_division_returns_200_empty_matchups(self):
        response = self.client.get("/cups/9/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["matchups"], {})

    def test_only_championship_games_returned(self):
        """Regular season matchups must not appear; only is_championship=True ones."""
        champ_matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(20, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
            is_championship=True,
        )
        response = self.client.get(f"/cups/{self.division.division}/")
        all_match_ids = [
            m["match"].id
            for date_data in response.context["matchups"].values()
            for m in date_data.values()
        ]
        self.assertIn(champ_matchup.id, all_match_ids)
        self.assertNotIn(self.matchup.id, all_match_ids)
