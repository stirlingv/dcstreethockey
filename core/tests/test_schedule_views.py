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

from core.betting import (
    compute_betting_lines_for_matchups,
    compute_player_props_for_matchups,
    fmt_american,
    fmt_spread,
    win_prob_to_american,
)
from core.views.schedule import (
    add_goals_for_matchups,
    get_goalies_for_matchup,
    get_matches_for_division,
    get_matches_for_team,
    get_stats_for_matchup,
)
from leagues.models import (
    Division,
    MatchUp,
    Player,
    Roster,
    Season,
    Stat,
    Team,
    Team_Stat,
    Week,
)


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


# ---------------------------------------------------------------------------
# Betting lines — math helpers
# ---------------------------------------------------------------------------


class WinProbToAmericanTest(TestCase):
    def test_even_money(self):
        # 50% probability → +100 (or -100 depending on rounding; accept either)
        result = win_prob_to_american(0.5)
        self.assertIn(result, (100, -100))

    def test_heavy_favorite(self):
        # 75% probability → large negative number (favorite)
        result = win_prob_to_american(0.75)
        self.assertLess(result, 0)
        self.assertLessEqual(result, -200)

    def test_underdog(self):
        # 33% probability → positive number (underdog)
        result = win_prob_to_american(1 / 3)
        self.assertGreater(result, 0)

    def test_clamps_near_zero(self):
        # Should not blow up at extreme probabilities
        self.assertIsInstance(win_prob_to_american(0.0), int)
        self.assertIsInstance(win_prob_to_american(1.0), int)

    def test_symmetry(self):
        # Prob p and (1-p) should give opposite-sign odds of the same magnitude
        fav = win_prob_to_american(0.6)
        dog = win_prob_to_american(0.4)
        self.assertLess(fav, 0)
        self.assertGreater(dog, 0)


class FmtSpreadTest(TestCase):
    def test_negative_spread(self):
        self.assertEqual(fmt_spread(-1.5), "-1.5")

    def test_positive_spread(self):
        self.assertEqual(fmt_spread(1.5), "+1.5")

    def test_pick_em(self):
        self.assertEqual(fmt_spread(0.0), "PK")


class FmtAmericanTest(TestCase):
    def test_negative_odds(self):
        self.assertEqual(fmt_american(-150), "-150")

    def test_positive_odds(self):
        self.assertEqual(fmt_american(130), "+130")


# ---------------------------------------------------------------------------
# Betting lines — compute_betting_lines_for_matchups
# ---------------------------------------------------------------------------


class BettingLinesBase(TestCase):
    """Minimal fixture: two teams, one future matchup, season stats."""

    def setUp(self):
        self.season = Season.objects.create(
            year=2025, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.home_team = Team.objects.create(
            team_name="Home Squad",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.away_team = Team.objects.create(
            team_name="Away Squad",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        # Season stats: home team is clearly stronger
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=self.home_team,
            win=8,
            loss=2,
            otw=0,
            otl=0,
            tie=0,
            goals_for=40,
            goals_against=20,
        )
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=self.away_team,
            win=2,
            loss=8,
            otw=0,
            otl=0,
            tie=0,
            goals_for=20,
            goals_against=40,
        )
        future_date = datetime.date.today() + datetime.timedelta(days=3)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )
        # Players on each team
        self.home_player = Player.objects.create(first_name="Home", last_name="Player")
        self.away_player = Player.objects.create(first_name="Away", last_name="Player")
        Roster.objects.create(
            player=self.home_player,
            team=self.home_team,
            position1=1,
        )
        Roster.objects.create(
            player=self.away_player,
            team=self.away_team,
            position1=1,
        )


class ComputeBettingLinesTest(BettingLinesBase):
    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(compute_betting_lines_for_matchups([]), {})

    def test_returns_entry_for_matchup(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        self.assertIn(self.matchup.id, result)

    def test_lines_have_required_keys(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        self.assertIsNotNone(lines)
        for key in (
            "home_spread",
            "away_spread",
            "total",
            "home_ml",
            "away_ml",
            "vig",
            "home_is_favorite",
            "home_3way",
            "away_3way",
            "draw_3way",
        ):
            self.assertIn(key, lines, msg=f"Missing key: {key}")

    def test_stronger_team_is_favorite(self):
        # Home team (8-2, 4 GPG) should be favored over away team (2-8, 2 GPG)
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        self.assertTrue(lines["home_is_favorite"])

    def test_favorite_has_negative_spread(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        self.assertTrue(lines["home_spread"].startswith("-"))

    def test_underdog_has_positive_spread(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        self.assertTrue(lines["away_spread"].startswith("+"))

    def test_favorite_has_negative_moneyline(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        self.assertTrue(lines["home_ml"].startswith("-"))

    def test_underdog_has_positive_moneyline(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        self.assertTrue(lines["away_ml"].startswith("+"))

    def test_vig_is_minus_110(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        self.assertEqual(result[self.matchup.id]["vig"], "-110")

    def test_no_team_stats_returns_none(self):
        # Create a matchup whose teams have no Team_Stat rows
        no_stat_home = Team.objects.create(
            team_name="No Stats Home",
            team_color="Green",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        no_stat_away = Team.objects.create(
            team_name="No Stats Away",
            team_color="Yellow",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        future_date = datetime.date.today() + datetime.timedelta(days=4)
        week2 = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        matchup2 = MatchUp.objects.create(
            week=week2,
            time=datetime.time(20, 0),
            hometeam=no_stat_home,
            awayteam=no_stat_away,
        )
        result = compute_betting_lines_for_matchups([matchup2.id])
        self.assertIsNone(result[matchup2.id])

    def test_spreads_are_opposite_signs(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        home_val = float(lines["home_spread"].replace("PK", "0"))
        away_val = float(lines["away_spread"].replace("PK", "0"))
        self.assertAlmostEqual(home_val + away_val, 0.0, places=5)

    def test_total_is_positive(self):
        result = compute_betting_lines_for_matchups([self.matchup.id])
        self.assertGreater(float(result[self.matchup.id]["total"]), 0)

    def test_3way_draw_always_positive_odds(self):
        # Draw/OT is always a minority outcome — odds must be positive (underdog).
        result = compute_betting_lines_for_matchups([self.matchup.id])
        self.assertTrue(result[self.matchup.id]["draw_3way"].startswith("+"))

    def test_3way_favorite_matches_2way_favorite(self):
        # The team favored in the 2-way ML should also have better (lower
        # American) 3-way regulation-win odds than the underdog.
        result = compute_betting_lines_for_matchups([self.matchup.id])
        lines = result[self.matchup.id]
        home_3 = int(lines["home_3way"])
        away_3 = int(lines["away_3way"])
        if lines["home_is_favorite"]:
            self.assertLess(home_3, away_3)
        else:
            self.assertLess(away_3, home_3)

    def test_3way_higher_ot_rate_shifts_draw_odds_lower(self):
        # A team with a high OT rate should produce a shorter (lower) draw price
        # than one with no OT history (where the floor probability is used).
        #
        # Baseline: both teams have 0 OT games (draw uses THREEWAY_MIN_DRAW_PROB).
        baseline = compute_betting_lines_for_matchups([self.matchup.id])
        baseline_draw_odds = int(baseline[self.matchup.id]["draw_3way"])

        # Give both teams a 50% OT rate — draw should become shorter odds.
        from leagues.models import Team_Stat as TS

        TS.objects.filter(team=self.home_team).update(otw=5, otl=5, win=0, loss=0)
        TS.objects.filter(team=self.away_team).update(otw=5, otl=5, win=0, loss=0)

        high_ot = compute_betting_lines_for_matchups([self.matchup.id])
        high_ot_draw_odds = int(high_ot[self.matchup.id]["draw_3way"])

        self.assertLess(high_ot_draw_odds, baseline_draw_odds)


class GoalieSubPenaltyTest(BettingLinesBase):
    """Goalie sub-needed status should shift the total upward."""

    def test_sub_needed_increases_expected_goals(self):
        # Baseline total with confirmed goalies
        baseline = compute_betting_lines_for_matchups([self.matchup.id])
        baseline_total = float(baseline[self.matchup.id]["total"])

        # Now mark home goalie as Sub Needed
        self.matchup.home_goalie_status = 2
        self.matchup.save()
        penalised = compute_betting_lines_for_matchups([self.matchup.id])
        penalised_total = float(penalised[self.matchup.id]["total"])

        self.assertGreater(penalised_total, baseline_total)


class PlayerRecentFormTest(BettingLinesBase):
    """Recent player form should influence the offensive estimate."""

    def _add_past_matchup(self, days_ago):
        past_date = datetime.date.today() - datetime.timedelta(days=days_ago)
        week = Week.objects.create(
            division=self.division, season=self.season, date=past_date
        )
        return MatchUp.objects.create(
            week=week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )

    def test_hot_home_player_pushes_total_up(self):
        # Baseline (no recent stats): total driven purely by season averages
        baseline = compute_betting_lines_for_matchups([self.matchup.id])
        baseline_total = float(baseline[self.matchup.id]["total"])

        # Give home player an extreme recent run (10 goals/game) to ensure the
        # blended offensive estimate crosses the next 0.5 rounding boundary.
        # Season GPG for home = 4.0; recent = 10.0 → blended = 6.4 → home_exp
        # rises from 4.0 to 5.2, pushing total from 6.0 to 7.0.
        for days_ago in range(1, 6):
            past_matchup = self._add_past_matchup(days_ago * 3)
            Stat.objects.create(
                player=self.home_player,
                team=self.home_team,
                matchup=past_matchup,
                goals=10,
                assists=0,
            )

        hot = compute_betting_lines_for_matchups([self.matchup.id])
        hot_total = float(hot[self.matchup.id]["total"])

        self.assertGreater(hot_total, baseline_total)


# ---------------------------------------------------------------------------
# Schedule view — betting_lines in context
# ---------------------------------------------------------------------------


class ScheduleViewBettingLinesTest(TestCase):
    """Integration: schedule view must include betting_lines in context."""

    def setUp(self):
        self.client = Client()
        self.season = Season.objects.create(
            year=2025, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=2)
        self.home_team = Team.objects.create(
            team_name="Schedule Home",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.away_team = Team.objects.create(
            team_name="Schedule Away",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        future_date = datetime.date.today() + datetime.timedelta(days=3)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )

    def test_betting_lines_key_in_context(self):
        response = self.client.get(reverse("schedule"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("betting_lines", response.context)

    def test_betting_lines_is_dict(self):
        response = self.client.get(reverse("schedule"))
        self.assertIsInstance(response.context["betting_lines"], dict)

    def test_no_lines_without_team_stats(self):
        # With no Team_Stat rows, the matchup's lines should be None
        response = self.client.get(reverse("schedule"))
        lines = response.context["betting_lines"].get(self.matchup.id)
        self.assertIsNone(lines)

    def test_lines_rendered_with_team_stats(self):
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=self.home_team,
            win=5,
            loss=3,
            otw=0,
            otl=0,
            tie=0,
            goals_for=25,
            goals_against=20,
        )
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=self.away_team,
            win=3,
            loss=5,
            otw=0,
            otl=0,
            tie=0,
            goals_for=20,
            goals_against=25,
        )
        response = self.client.get(reverse("schedule"))
        self.assertEqual(response.status_code, 200)
        lines = response.context["betting_lines"].get(self.matchup.id)
        self.assertIsNotNone(lines)
        # Verify the sportsbook panel appears in the rendered HTML
        self.assertContains(response, "betting-lines")
        self.assertContains(response, "SPREAD")
        self.assertContains(response, "TOTAL")
        self.assertContains(response, "MONEYLINE")
        self.assertContains(response, "For entertainment purposes only")


# ---------------------------------------------------------------------------
# Player props — compute_player_props_for_matchups
# ---------------------------------------------------------------------------


class PlayerPropsBase(TestCase):
    """Fixture: two teams, one future matchup, season stats, and stat history."""

    def setUp(self):
        self.season = Season.objects.create(
            year=2025, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.home_team = Team.objects.create(
            team_name="Props Home",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.away_team = Team.objects.create(
            team_name="Props Away",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=self.home_team,
            win=5,
            loss=3,
            otw=0,
            otl=0,
            tie=0,
            goals_for=25,
            goals_against=20,
        )
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=self.away_team,
            win=3,
            loss=5,
            otw=0,
            otl=0,
            tie=0,
            goals_for=20,
            goals_against=25,
        )
        future_date = datetime.date.today() + datetime.timedelta(days=3)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )
        # Home player with enough game history
        self.home_player = Player.objects.create(first_name="Home", last_name="Scorer")
        Roster.objects.create(
            player=self.home_player,
            team=self.home_team,
            position1=1,  # Center
        )
        # Away player with enough game history
        self.away_player = Player.objects.create(first_name="Away", last_name="Forward")
        Roster.objects.create(
            player=self.away_player,
            team=self.away_team,
            position1=2,  # Wing
        )
        # Create 5 past games with stats for each player (meets PROP_MIN_GAMES)
        for i in range(5):
            past_date = datetime.date.today() - datetime.timedelta(days=(i + 1) * 5)
            past_week = Week.objects.create(
                division=self.division, season=self.season, date=past_date
            )
            past_matchup = MatchUp.objects.create(
                week=past_week,
                time=datetime.time(19, 0),
                hometeam=self.home_team,
                awayteam=self.away_team,
            )
            Stat.objects.create(
                player=self.home_player,
                team=self.home_team,
                matchup=past_matchup,
                goals=1 if i % 2 == 0 else 0,
                assists=1 if i % 3 == 0 else 0,
            )
            Stat.objects.create(
                player=self.away_player,
                team=self.away_team,
                matchup=past_matchup,
                goals=0,
                assists=1 if i % 2 == 0 else 0,
            )


class ComputePlayerPropsTest(PlayerPropsBase):
    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(compute_player_props_for_matchups([]), {})

    def test_returns_entry_for_matchup(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        self.assertIn(self.matchup.id, result)

    def test_result_has_expected_keys(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        props = result[self.matchup.id]
        self.assertIsNotNone(props)
        self.assertIn("by_goal", props)
        self.assertIn("by_point", props)
        self.assertIn("total", props)

    def test_home_player_appears_in_by_goal(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        names = [p["name"] for p in result[self.matchup.id]["by_goal"]]
        self.assertIn("Home Scorer", names)

    def test_away_player_appears_in_by_goal(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        names = [p["name"] for p in result[self.matchup.id]["by_goal"]]
        self.assertIn("Away Forward", names)

    def test_player_prop_has_required_keys(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        player = result[self.matchup.id]["by_goal"][0]
        for key in ("name", "pos", "team_abbr", "goal_odds", "point_odds", "games"):
            self.assertIn(key, player)

    def test_position_label_correct(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        home_entry = next(
            p for p in result[self.matchup.id]["by_goal"] if p["name"] == "Home Scorer"
        )
        self.assertEqual(home_entry["pos"], "C")

    def test_goal_odds_are_american_format(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        for p in result[self.matchup.id]["by_goal"]:
            odds = p["goal_odds"]
            self.assertTrue(
                odds.startswith("+") or odds.startswith("-"),
                msg=f"Unexpected odds format: {odds}",
            )

    def test_player_with_no_games_excluded(self):
        # A rostered player with zero recorded games should not appear —
        # we need at least one game of evidence (PROP_MIN_GAMES=1).
        no_games_player = Player.objects.create(first_name="Never", last_name="Played")
        Roster.objects.create(player=no_games_player, team=self.home_team, position1=2)
        result = compute_player_props_for_matchups([self.matchup.id])
        names = [p["name"] for p in result[self.matchup.id]["by_goal"]]
        self.assertNotIn("Never Played", names)

    def test_goalie_not_included_in_props(self):
        goalie = Player.objects.create(first_name="Net", last_name="Minder")
        Roster.objects.create(
            player=goalie, team=self.home_team, position1=4, is_primary_goalie=True
        )
        result = compute_player_props_for_matchups([self.matchup.id])
        names = [p["name"] for p in result[self.matchup.id]["by_goal"]]
        self.assertNotIn("Net Minder", names)

    def test_both_teams_mixed_in_by_goal(self):
        # Both home and away players should appear in the same by_goal list.
        result = compute_player_props_for_matchups([self.matchup.id])
        names = [p["name"] for p in result[self.matchup.id]["by_goal"]]
        self.assertIn("Home Scorer", names)
        self.assertIn("Away Forward", names)

    def test_total_reflects_player_count(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        props = result[self.matchup.id]
        # by_goal and by_point have the same players; total should equal len
        self.assertEqual(props["total"], len(props["by_goal"]))

    def test_team_abbr_present_on_each_player(self):
        result = compute_player_props_for_matchups([self.matchup.id])
        for p in result[self.matchup.id]["by_goal"]:
            self.assertTrue(len(p["team_abbr"]) > 0)

    def test_no_qualifying_players_returns_none(self):
        # Build a matchup with no stat history on either side.
        new_team_a = Team.objects.create(
            team_name="Empty A",
            team_color="White",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        new_team_b = Team.objects.create(
            team_name="Empty B",
            team_color="Black",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        future_date = datetime.date.today() + datetime.timedelta(days=10)
        w = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        m = MatchUp.objects.create(
            week=w,
            time=datetime.time(20, 0),
            hometeam=new_team_a,
            awayteam=new_team_b,
        )
        result = compute_player_props_for_matchups([m.id])
        self.assertIsNone(result[m.id])


class GoalieSubBoostPropsTest(PlayerPropsBase):
    """Sub Needed status should inflate scoring odds."""

    def test_sub_needed_inflates_goal_odds(self):
        # Baseline: Unconfirmed goalie (default)
        baseline = compute_player_props_for_matchups([self.matchup.id])
        baseline_all = {p["name"]: p for p in baseline[self.matchup.id]["by_goal"]}

        # Away goalie sub needed → home players score against a sub → better odds
        self.matchup.away_goalie_status = 2
        self.matchup.save()
        boosted = compute_player_props_for_matchups([self.matchup.id])
        boosted_all = {p["name"]: p for p in boosted[self.matchup.id]["by_goal"]}

        # Higher scoring probability always produces a numerically lower American
        # odds integer: a favorite goes -150 → -180 (more negative), an underdog
        # goes +200 → +160 (less positive). Both directions mean boost_odds < base_odds.
        base_odds = int(baseline_all["Home Scorer"]["goal_odds"])
        boost_odds = int(boosted_all["Home Scorer"]["goal_odds"])
        self.assertLess(boost_odds, base_odds)


class ScheduleViewPlayerPropsTest(TestCase):
    """Integration: schedule view must include player_props in context."""

    def setUp(self):
        self.client = Client()
        self.season = Season.objects.create(
            year=2025, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=2)
        self.home_team = Team.objects.create(
            team_name="View Props Home",
            team_color="Red",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.away_team = Team.objects.create(
            team_name="View Props Away",
            team_color="Blue",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        future_date = datetime.date.today() + datetime.timedelta(days=3)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )

    def test_player_props_key_in_context(self):
        response = self.client.get(reverse("schedule"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("player_props", response.context)

    def test_player_props_is_dict(self):
        response = self.client.get(reverse("schedule"))
        self.assertIsInstance(response.context["player_props"], dict)

    def test_props_panel_rendered_with_stat_history(self):
        player = Player.objects.create(first_name="Star", last_name="Forward")
        Roster.objects.create(player=player, team=self.home_team, position1=1)
        for i in range(4):
            past_date = datetime.date.today() - datetime.timedelta(days=(i + 1) * 4)
            pw = Week.objects.create(
                division=self.division, season=self.season, date=past_date
            )
            pm = MatchUp.objects.create(
                week=pw,
                time=datetime.time(19, 0),
                hometeam=self.home_team,
                awayteam=self.away_team,
            )
            Stat.objects.create(
                player=player,
                team=self.home_team,
                matchup=pm,
                goals=1,
                assists=1,
            )
        response = self.client.get(reverse("schedule"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "props-panel")
        self.assertContains(response, "Player Props")
        self.assertContains(response, "Star Forward")


class CareerRatePriorTest(PlayerPropsBase):
    """Career-rate prior: a player with a higher career goal rate should get
    better (shorter) odds than a player with the same recent form but a lower
    career rate, all else being equal."""

    def test_high_career_rate_beats_low_career_rate_same_recent_form(self):
        # Build a second matchup between two new teams so there is no
        # cross-contamination with PlayerPropsBase fixtures.
        veteran = Player.objects.create(first_name="Veteran", last_name="Scorer")
        newcomer = Player.objects.create(first_name="Newcomer", last_name="Scorer")

        team_v = Team.objects.create(
            team_name="Veteran Team",
            team_color="Green",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        team_n = Team.objects.create(
            team_name="Newcomer Team",
            team_color="Orange",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=team_v,
            win=4,
            loss=4,
            otw=0,
            otl=0,
            tie=0,
            goals_for=20,
            goals_against=20,
        )
        Team_Stat.objects.create(
            division=self.division,
            season=self.season,
            team=team_n,
            win=4,
            loss=4,
            otw=0,
            otl=0,
            tie=0,
            goals_for=20,
            goals_against=20,
        )
        Roster.objects.create(player=veteran, team=team_v, position1=1)
        Roster.objects.create(player=newcomer, team=team_n, position1=1)

        future_date = self.week.date + datetime.timedelta(days=1)
        new_week = Week.objects.create(
            division=self.division, season=self.season, date=future_date
        )
        matchup = MatchUp.objects.create(
            week=new_week,
            time=datetime.time(20, 0),
            hometeam=team_v,
            awayteam=team_n,
        )

        # Give veteran 20 career stat rows (15 with goals = 75% career rate)
        # plus 5 recent rows matching the newcomer's recent form (2/5 goals).
        for i in range(20):
            past_date = datetime.date.today() - datetime.timedelta(days=(i + 8) * 7)
            pw = Week.objects.create(
                division=self.division, season=self.season, date=past_date
            )
            pm = MatchUp.objects.create(
                week=pw,
                time=datetime.time(19, 0),
                hometeam=team_v,
                awayteam=team_n,
            )
            Stat.objects.create(
                player=veteran,
                team=team_v,
                matchup=pm,
                goals=1 if i < 15 else 0,
                assists=0,
            )

        # Give newcomer only 5 career stat rows — same 2/5 goals as veteran's
        # recent window, so recent form is identical but career rate is lower.
        for i in range(5):
            past_date = datetime.date.today() - datetime.timedelta(days=(i + 1) * 7)
            pw = Week.objects.create(
                division=self.division, season=self.season, date=past_date
            )
            pm = MatchUp.objects.create(
                week=pw,
                time=datetime.time(19, 0),
                hometeam=team_v,
                awayteam=team_n,
            )
            Stat.objects.create(
                player=newcomer,
                team=team_n,
                matchup=pm,
                goals=1 if i < 2 else 0,
                assists=0,
            )
            # Veteran's recent 5 rows mirror newcomer: 2 goals out of 5
            Stat.objects.create(
                player=veteran,
                team=team_v,
                matchup=pm,
                goals=1 if i < 2 else 0,
                assists=0,
            )

        result = compute_player_props_for_matchups([matchup.id])
        props = result[matchup.id]
        self.assertIsNotNone(props)

        vet_entry = next(
            (p for p in props["by_goal"] if p["name"] == "Veteran Scorer"), None
        )
        new_entry = next(
            (p for p in props["by_goal"] if p["name"] == "Newcomer Scorer"), None
        )
        self.assertIsNotNone(vet_entry, "Veteran should qualify for props")
        self.assertIsNotNone(new_entry, "Newcomer should qualify for props")

        # Career-rate prior should give veteran shorter (better) goal odds.
        # Lower American odds integer = shorter odds = more likely to score.
        vet_odds = int(vet_entry["goal_odds"])
        new_odds = int(new_entry["goal_odds"])
        self.assertLess(
            vet_odds,
            new_odds,
            msg=f"Veteran ({vet_odds}) should have shorter odds than newcomer ({new_odds})",
        )
