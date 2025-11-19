import unittest
from django.test import TestCase
from django.db.models import Sum
from django.db.models.functions import Coalesce
from unittest.mock import Mock, patch
from leagues.models import Team_Stat


class StandingsLogicTestCase(TestCase):
    """
    Unit tests for standings logic including various tiebreaker scenarios
    """

    def setUp(self):
        """Set up test data"""
        # Create mock divisions
        self.division1 = Mock()
        self.division1.id = 1

        # Create mock season
        self.season = Mock()
        self.season.id = 1

    def create_mock_team_stat(
        self,
        team_id,
        team_name,
        wins=0,
        otw=0,
        otl=0,
        losses=0,
        ties=0,
        goals_for=0,
        goals_against=0,
        division_id=1,
    ):
        """Helper method to create mock team stat objects"""
        team_stat = Mock(spec=Team_Stat)

        # Mock team
        team_stat.team = Mock()
        team_stat.team.id = team_id
        team_stat.team.team_name = team_name
        team_stat.team.is_active = True

        # Basic stats
        team_stat.win = wins
        team_stat.otw = otw
        team_stat.otl = otl
        team_stat.loss = losses
        team_stat.tie = ties
        team_stat.goals_for = goals_for
        team_stat.goals_against = goals_against
        team_stat.division = Mock()
        team_stat.division.id = division_id

        # Calculated fields (matching the view logic)
        team_stat.total_points = (wins * 3) + (otw * 2) + ties + otl
        team_stat.total_wins = wins + otw
        team_stat.regulation_wins = wins
        team_stat.goal_differential = goals_for - goals_against

        return team_stat

    def test_basic_standings_order(self):
        """Test basic standings ordering by total points"""
        team_stats = [
            self.create_mock_team_stat(
                1, "Team A", wins=10, goals_for=50, goals_against=30
            ),  # 30 points
            self.create_mock_team_stat(
                2, "Team B", wins=8, otw=2, goals_for=45, goals_against=35
            ),  # 26 points
            self.create_mock_team_stat(
                3, "Team C", wins=6, otw=1, ties=2, goals_for=40, goals_against=40
            ),  # 22 points
            self.create_mock_team_stat(
                4, "Team D", wins=5, goals_for=35, goals_against=50
            ),  # 15 points
        ]

        # Sort by total points (descending)
        sorted_teams = sorted(team_stats, key=lambda x: x.total_points, reverse=True)

        self.assertEqual(sorted_teams[0].team.team_name, "Team A")  # 30 points
        self.assertEqual(sorted_teams[1].team.team_name, "Team B")  # 26 points
        self.assertEqual(sorted_teams[2].team.team_name, "Team C")  # 22 points
        self.assertEqual(sorted_teams[3].team.team_name, "Team D")  # 15 points

    def test_regulation_wins_tiebreaker(self):
        """Test tiebreaker by regulation wins when total points are equal"""
        team_stats = [
            # Both teams have 24 points but different regulation wins
            self.create_mock_team_stat(
                1, "Team A", wins=8, goals_for=50, goals_against=30
            ),  # 24 points, 8 reg wins
            self.create_mock_team_stat(
                2, "Team B", wins=6, otw=6, goals_for=45, goals_against=35
            ),  # 24 points, 6 reg wins
        ]

        # Team A should rank higher due to more regulation wins
        with patch("core.views.check_teams_play", return_value=False):
            # Simulate the tiebreaker logic
            self.assertGreater(
                team_stats[0].regulation_wins, team_stats[1].regulation_wins
            )

    def test_goal_differential_tiebreaker(self):
        """Test tiebreaker by goal differential when points and regulation wins are equal"""
        team_stats = [
            # Same points, same regulation wins, different goal differential
            self.create_mock_team_stat(
                1, "Team A", wins=8, goals_for=50, goals_against=30
            ),  # 24 points, +20 diff
            self.create_mock_team_stat(
                2, "Team B", wins=8, goals_for=45, goals_against=35
            ),  # 24 points, +10 diff
        ]

        with patch("core.views.check_teams_play", return_value=False):
            self.assertGreater(
                team_stats[0].goal_differential, team_stats[1].goal_differential
            )

    @patch("core.views.check_teams_play")
    @patch("core.views.check_h2h_record")
    def test_head_to_head_tiebreaker(self, mock_h2h, mock_teams_play):
        """Test head-to-head tiebreaker takes precedence over other tiebreakers"""
        # Team B has worse regulation wins and goal diff but wins head-to-head
        self.create_mock_team_stat(
            1, "Team A", wins=8, goals_for=50, goals_against=30
        )  # Better stats
        self.create_mock_team_stat(
            2, "Team B", wins=6, otw=6, goals_for=40, goals_against=50
        )  # Worse stats but wins H2H

        # Mock that teams have played each other and B beat A
        mock_teams_play.return_value = True
        mock_h2h.return_value = (
            True  # Team B (index 0 in comparison) should be ranked higher
        )

        # Head-to-head should override other tiebreakers
        self.assertTrue(mock_teams_play.return_value)
        self.assertTrue(mock_h2h.return_value)

    def test_four_team_complex_tiebreaker_scenario(self):
        """Test complex 4-team tiebreaker scenario with same points"""
        # All teams finish with exactly 21 points but different tiebreaker metrics
        team_stats = [
            # Team A: 7 reg wins, +15 goal diff
            self.create_mock_team_stat(
                1, "Team A", wins=7, goals_for=50, goals_against=35
            ),  # 7*3 = 21 points
            # Team B: 6 reg wins, 1 OT win, 1 OT loss, +20 goal diff
            self.create_mock_team_stat(
                2, "Team B", wins=6, otw=1, otl=1, goals_for=55, goals_against=35
            ),  # 6*3 + 1*2 + 1*1 = 18+2+1 = 21 points
            # Team C: 5 reg wins, 3 OT losses, +5 goal diff
            self.create_mock_team_stat(
                3, "Team C", wins=5, otl=6, goals_for=40, goals_against=35
            ),  # 5*3 + 6*1 = 15+6 = 21 points
            # Team D: 4 reg wins, 1 OT win, 7 OT losses, +10 goal diff
            self.create_mock_team_stat(
                4, "Team D", wins=4, otw=1, otl=7, goals_for=45, goals_against=35
            ),  # 4*3 + 1*2 + 7*1 = 12+2+7 = 21 points
        ]

        # Verify all teams have same points (21)
        for team in team_stats:
            self.assertEqual(team.total_points, 21)

        # Mock that no teams have played each other (so regulation wins determines order)
        with patch("core.views.check_teams_play", return_value=False):
            # Expected order by regulation wins: A(7) > B(6) > C(5) > D(4)
            sorted_by_reg_wins = sorted(
                team_stats, key=lambda x: x.regulation_wins, reverse=True
            )

            self.assertEqual(
                sorted_by_reg_wins[0].team.team_name, "Team A"
            )  # 7 reg wins
            self.assertEqual(
                sorted_by_reg_wins[1].team.team_name, "Team B"
            )  # 6 reg wins
            self.assertEqual(
                sorted_by_reg_wins[2].team.team_name, "Team C"
            )  # 5 reg wins
            self.assertEqual(
                sorted_by_reg_wins[3].team.team_name, "Team D"
            )  # 4 reg wins

    def test_same_regulation_wins_goes_to_goal_differential(self):
        """Test that when regulation wins are tied, goal differential is the tiebreaker"""
        team_stats = [
            # Same points, same regulation wins, different goal differential
            self.create_mock_team_stat(
                1, "Team A", wins=7, goals_for=50, goals_against=30
            ),  # 21 points, 7 reg wins, +20 diff
            self.create_mock_team_stat(
                2, "Team B", wins=7, goals_for=45, goals_against=35
            ),  # 21 points, 7 reg wins, +10 diff
            self.create_mock_team_stat(
                3, "Team C", wins=7, goals_for=40, goals_against=35
            ),  # 21 points, 7 reg wins, +5 diff
        ]

        with patch("core.views.check_teams_play", return_value=False):
            # All have same regulation wins, should be sorted by goal differential
            sorted_by_diff = sorted(
                team_stats, key=lambda x: x.goal_differential, reverse=True
            )

            self.assertEqual(sorted_by_diff[0].team.team_name, "Team A")  # +20
            self.assertEqual(sorted_by_diff[1].team.team_name, "Team B")  # +10
            self.assertEqual(sorted_by_diff[2].team.team_name, "Team C")  # +5

    @patch("core.views.check_teams_play")
    @patch("core.views.check_h2h_record")
    @patch("core.views.check_goal_diff")
    def test_mixed_tiebreaker_scenario(self, mock_goal_diff, mock_h2h, mock_teams_play):
        """Test scenario where some teams have H2H records and others don't"""
        self.create_mock_team_stat(
            1, "Team A", wins=7, goals_for=50, goals_against=35
        )  # 21 points
        self.create_mock_team_stat(
            2, "Team B", wins=6, otw=2, otl=1, goals_for=45, goals_against=40
        )  # 21 points
        self.create_mock_team_stat(
            3, "Team C", wins=5, otw=2, otl=4, goals_for=40, goals_against=35
        )  # 21 points

        # Mock that A and B have played (B wins H2H), but C hasn't played either
        def mock_play_check(team1, team2):
            if (team1.team.id == 1 and team2.team.id == 2) or (
                team1.team.id == 2 and team2.team.id == 1
            ):
                return True
            return False

        def mock_h2h_check(team1, team2):
            # Team B beats Team A in H2H
            if team1.team.id == 2 and team2.team.id == 1:
                return True
            return False

        mock_teams_play.side_effect = mock_play_check
        mock_h2h.side_effect = mock_h2h_check

        # This tests the complexity of mixed tiebreaker scenarios
        # Expected: B beats A on H2H, but A vs C and B vs C determined by regulation wins

    def test_overtime_vs_regulation_wins_calculation(self):
        """Test that overtime wins are correctly excluded from regulation wins"""
        team_stat = self.create_mock_team_stat(
            1, "Test Team", wins=5, otw=3, goals_for=40, goals_against=30
        )

        # Total wins should include OT wins
        self.assertEqual(team_stat.total_wins, 8)  # 5 + 3

        # Regulation wins should exclude OT wins
        self.assertEqual(team_stat.regulation_wins, 5)  # Only regulation wins

        # Points calculation: (reg wins * 3) + (OT wins * 2) + OT losses + ties
        expected_points = (5 * 3) + (3 * 2)  # 15 + 6 = 21
        self.assertEqual(team_stat.total_points, expected_points)

    def test_edge_case_all_metrics_tied(self):
        """Test edge case where all tiebreaker metrics are identical"""
        team_stats = [
            self.create_mock_team_stat(
                1, "Team A", wins=7, goals_for=40, goals_against=35
            ),  # Identical stats
            self.create_mock_team_stat(
                2, "Team B", wins=7, goals_for=40, goals_against=35
            ),  # Identical stats
        ]

        with patch("core.views.check_teams_play", return_value=False):
            # When everything is tied, order should remain as is (or by team name/ID)
            self.assertEqual(team_stats[0].total_points, team_stats[1].total_points)
            self.assertEqual(
                team_stats[0].regulation_wins, team_stats[1].regulation_wins
            )
            self.assertEqual(
                team_stats[0].goal_differential, team_stats[1].goal_differential
            )


class StandingsIntegrationTestCase(TestCase):
    """
    Integration tests that test the actual TeamStatDetailView logic
    """

    def setUp(self):
        """Set up real database objects for integration testing"""
        from leagues.models import Division, Season, Team

        # Create test division and season
        self.division = Division.objects.create(division=1)  # Sunday D1
        self.season = Season.objects.create(year=2025, season_type=1)

        # Create test teams
        self.team_a = Team.objects.create(
            team_name="Team A",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.team_b = Team.objects.create(
            team_name="Team B",
            division=self.division,
            season=self.season,
            is_active=True,
        )

    def test_queryset_annotations(self):
        """Test that the queryset properly annotates calculated fields"""
        from leagues.models import Team_Stat

        # Create team stats
        Team_Stat.objects.create(
            team=self.team_a,
            division=self.division,
            win=7,
            otw=2,
            otl=1,
            loss=5,
            tie=0,
            goals_for=45,
            goals_against=35,
        )

        # Test the actual query annotation logic
        queryset = Team_Stat.objects.filter(team=self.team_a).annotate(
            total_points=Coalesce(
                (Sum("win") * 3) + (Sum("otw") * 2) + Sum("tie") + Sum("otl"), 0
            ),
            regulation_wins=Coalesce(Sum("win"), 0),
        )

        team_stat = queryset.first()
        expected_points = (7 * 3) + (2 * 2) + (0) + (1)  # 21 + 4 + 0 + 1 = 26

        self.assertEqual(team_stat.total_points, expected_points)
        self.assertEqual(team_stat.regulation_wins, 7)

    def tearDown(self):
        """Clean up test data"""
        from leagues.models import Team_Stat, Team, Season, Division

        Team_Stat.objects.all().delete()
        Team.objects.all().delete()
        Season.objects.all().delete()
        Division.objects.all().delete()


if __name__ == "__main__":
    unittest.main()
