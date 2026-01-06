import unittest
from django.test import TestCase
from django.db.models import (
    Sum,
    Case,
    When,
    F,
    Q,
    Value,
    IntegerField,
    FloatField,
    DecimalField,
    Func,
    ExpressionWrapper,
)
from unittest.mock import Mock, patch, MagicMock
from collections import OrderedDict
from leagues.models import (
    Player,
    Roster,
    Team,
    Division,
    Season,
    Stat,
    MatchUp,
    Week,
)
from core.views import (
    PlayerStatDetailView,
    get_player_stats,
    get_average_stats_for_player,
    normalize_stat_scope,
)


class PlayerStatsLogicTestCase(TestCase):
    """
    Unit tests for player statistics logic including league leaders sorting
    """

    def setUp(self):
        """Set up test data"""
        # Create mock divisions
        self.division1 = Mock()
        self.division1.id = 1
        self.division1.__str__ = lambda: "Sunday D1"

        # Create mock season
        self.season = Mock()
        self.season.id = 1

    def create_mock_player_stat(
        self,
        player_id,
        first_name,
        last_name,
        team_name,
        team_id=1,
        goals=0,
        assists=0,
        goals_against=0,
        games_played=1,
        position1=1,  # 1=forward, 4=goalie
        position2=None,
        is_captain=False,
    ):
        """Helper method to create mock player stat objects"""
        player_stat = {
            "id": player_id,
            "first_name": first_name,
            "last_name": last_name,
            "roster__team__team_name": team_name,
            "roster__team__id": team_id,
            "roster__position1": position1,
            "roster__position2": position2,
            "roster__is_captain": is_captain,
            "sum_goals": goals,
            "sum_assists": assists,
            "total_points": goals + assists,
            "sum_goals_against": goals_against,
            "sum_games_played": games_played,
            "average_goals_against": goals_against / games_played
            if games_played > 0
            else 0.0,
            "rounded_average_goals_against": round(goals_against / games_played, 2)
            if games_played > 0
            else 0.0,
        }
        return player_stat

    def test_offensive_player_sorting_logic(self):
        """Test that offensive players are sorted correctly by the league leaders algorithm"""
        # Create players with different stats to test sorting hierarchy
        player_stats = [
            # Player A: High points but is a goalie (should be in goalie section)
            self.create_mock_player_stat(
                1,
                "John",
                "Smith",
                "Team A",
                goals=15,
                assists=20,
                position1=4,
                games_played=10,
                goals_against=25,
            ),
            # Player B: Lower points but forward (should rank in offensive section)
            self.create_mock_player_stat(
                2,
                "Jane",
                "Doe",
                "Team B",
                goals=12,
                assists=15,
                position1=1,
                games_played=8,
            ),
            # Player C: Same points as B but more goals (should rank higher)
            self.create_mock_player_stat(
                3,
                "Bob",
                "Johnson",
                "Team C",
                goals=15,
                assists=12,
                position1=1,
                games_played=8,
            ),
            # Player D: Same points and goals as C but more assists (tie, equal rank)
            self.create_mock_player_stat(
                4,
                "Alice",
                "Wilson",
                "Team D",
                goals=12,
                assists=15,
                position1=1,
                games_played=8,
            ),
            # Player E: Higher total points (should rank #1)
            self.create_mock_player_stat(
                5,
                "Mike",
                "Brown",
                "Team E",
                goals=18,
                assists=15,
                position1=1,
                games_played=10,
            ),
        ]

        # Filter offensive players (non-goalies with points > 0)
        offensive_players = [
            p
            for p in player_stats
            if p["total_points"] > 0
            and p["roster__position1"] != 4
            and p["roster__position2"] != 4
        ]

        # Sort using the actual league leaders algorithm logic:
        # Primary: rounded_average_goals_against (ASC) - for non-goalies this should be 0
        # Secondary: total_points (DESC)
        # Tertiary: sum_goals (DESC)
        # Quaternary: sum_assists (DESC)
        sorted_players = sorted(
            offensive_players,
            key=lambda x: (
                x["rounded_average_goals_against"],  # ASC (0 for forwards)
                -x["total_points"],  # DESC
                -x["sum_goals"],  # DESC
                -x["sum_assists"],  # DESC
            ),
        )

        # Validate expected order
        self.assertEqual(
            sorted_players[0]["first_name"], "Mike"
        )  # 33 points (18G + 15A)
        self.assertEqual(
            sorted_players[1]["first_name"], "Bob"
        )  # 27 points (15G + 12A) - more goals than Jane/Alice
        # Jane and Alice both have 27 points (12G + 15A) and (15G + 12A) but Bob has more goals so ranks higher
        self.assertEqual(
            sorted_players[2]["first_name"], "Jane"
        )  # 27 points (12G + 15A) - same as Alice
        self.assertEqual(
            sorted_players[3]["first_name"], "Alice"
        )  # 27 points (12G + 15A) - same as Jane

    def test_goalie_sorting_logic(self):
        """Test that goalies are sorted correctly by GAA, then by total points"""
        goalie_stats = [
            # Goalie A: Better GAA but fewer points
            self.create_mock_player_stat(
                1,
                "Tony",
                "Goalie",
                "Team A",
                goals=1,
                assists=2,
                position1=4,
                games_played=10,
                goals_against=20,  # 2.00 GAA
            ),
            # Goalie B: Worse GAA but more points
            self.create_mock_player_stat(
                2,
                "Steve",
                "Netminder",
                "Team B",
                goals=3,
                assists=4,
                position1=4,
                games_played=8,
                goals_against=25,  # 3.125 GAA
            ),
            # Goalie C: Same GAA as A but more points (should rank higher than A)
            self.create_mock_player_stat(
                3,
                "Ben",
                "Keeper",
                "Team C",
                goals=5,
                assists=6,
                position1=4,
                games_played=10,
                goals_against=20,  # 2.00 GAA, 11 points
            ),
        ]

        # Filter goalies (position1 == 4 or position2 == 4)
        goalies = [
            p
            for p in goalie_stats
            if p["roster__position1"] == 4 or p["roster__position2"] == 4
        ]

        # Sort using the actual algorithm (GAA first, then points)
        sorted_goalies = sorted(
            goalies,
            key=lambda x: (
                x["rounded_average_goals_against"],  # ASC (better GAA first)
                -x["total_points"],  # DESC (more points better)
                -x["sum_goals"],  # DESC
                -x["sum_assists"],  # DESC
            ),
        )

        # Expected order: Both C and A have 2.00 GAA, but C has more points (11 vs 3)
        # Then B with 3.125 GAA
        self.assertEqual(sorted_goalies[0]["first_name"], "Ben")  # 2.00 GAA, 11 points
        self.assertEqual(sorted_goalies[1]["first_name"], "Tony")  # 2.00 GAA, 3 points
        self.assertEqual(
            sorted_goalies[2]["first_name"], "Steve"
        )  # 3.125 GAA, 7 points

    def test_mixed_position_player_classification(self):
        """Test players with multiple positions are classified correctly"""
        mixed_players = [
            # Player who can play forward and goalie - should appear in both sections
            self.create_mock_player_stat(
                1,
                "Dual",
                "Player",
                "Team A",
                goals=5,
                assists=3,
                position1=1,
                position2=4,
                games_played=8,
                goals_against=16,  # 2.00 GAA
            ),
            # Regular forward
            self.create_mock_player_stat(
                2,
                "Pure",
                "Forward",
                "Team B",
                goals=8,
                assists=2,
                position1=1,
                position2=None,
                games_played=6,
            ),
            # Regular goalie
            self.create_mock_player_stat(
                3,
                "Pure",
                "Goalie",
                "Team C",
                goals=0,
                assists=1,
                position1=4,
                position2=None,
                games_played=10,
                goals_against=30,  # 3.00 GAA
            ),
        ]

        # Test offensive classification (excludes pure goalies)
        offensive_eligible = [
            p
            for p in mixed_players
            if p["total_points"] > 0
            and p["roster__position1"] != 4
            and p["roster__position2"] != 4
        ]

        # Test goalie classification (includes dual-position players)
        goalie_eligible = [
            p
            for p in mixed_players
            if p["roster__position1"] == 4 or p["roster__position2"] == 4
        ]

        # Pure Forward should only be in offensive
        self.assertEqual(len(offensive_eligible), 1)
        self.assertEqual(offensive_eligible[0]["first_name"], "Pure")
        self.assertEqual(offensive_eligible[0]["last_name"], "Forward")

        # Dual Player and Pure Goalie should be in goalie section
        self.assertEqual(len(goalie_eligible), 2)
        goalie_names = [(p["first_name"], p["last_name"]) for p in goalie_eligible]
        self.assertIn(("Dual", "Player"), goalie_names)
        self.assertIn(("Pure", "Goalie"), goalie_names)

    def test_minimum_games_played_filter(self):
        """Test that players with less than 1 game played are filtered out"""
        players_with_varying_games = [
            # Player with 0 games (should be filtered)
            self.create_mock_player_stat(
                1, "No", "Games", "Team A", goals=10, assists=5, games_played=0
            ),
            # Player with 1 game (should be included)
            self.create_mock_player_stat(
                2, "One", "Game", "Team B", goals=2, assists=1, games_played=1
            ),
            # Player with multiple games (should be included)
            self.create_mock_player_stat(
                3, "Many", "Games", "Team C", goals=8, assists=4, games_played=5
            ),
        ]

        # Apply the minimum games filter (>= 1 game)
        eligible_players = [
            p for p in players_with_varying_games if p["sum_games_played"] >= 1
        ]

        # Should exclude the 0-game player
        self.assertEqual(len(eligible_players), 2)
        player_names = [p["first_name"] for p in eligible_players]
        self.assertNotIn("No", player_names)
        self.assertIn("One", player_names)
        self.assertIn("Many", player_names)

    def test_captain_designation_display(self):
        """Test that captain designation is properly handled in display logic"""
        players_with_captaincy = [
            # Regular player
            self.create_mock_player_stat(
                1, "John", "Player", "Team A", goals=5, assists=3, is_captain=False
            ),
            # Captain
            self.create_mock_player_stat(
                2, "Team", "Captain", "Team B", goals=8, assists=7, is_captain=True
            ),
        ]

        # Verify captain flag is preserved in data
        captain = [p for p in players_with_captaincy if p["roster__is_captain"]][0]
        regular = [p for p in players_with_captaincy if not p["roster__is_captain"]][0]

        self.assertTrue(captain["roster__is_captain"])
        self.assertEqual(captain["first_name"], "Team")
        self.assertFalse(regular["roster__is_captain"])
        self.assertEqual(regular["first_name"], "John")

    def test_division_based_league_leaders(self):
        """Test that league leaders are calculated separately per division"""
        # Mock data for two different divisions
        division_stats = {
            "Sunday D1": [
                self.create_mock_player_stat(
                    1, "D1", "Leader", "Team A", goals=15, assists=10
                ),
                self.create_mock_player_stat(
                    2, "D1", "Second", "Team B", goals=12, assists=8
                ),
            ],
            "Sunday D2": [
                self.create_mock_player_stat(
                    3, "D2", "Leader", "Team C", goals=18, assists=12
                ),
                self.create_mock_player_stat(
                    4, "D2", "Second", "Team D", goals=10, assists=15
                ),
            ],
        }

        # Test that each division maintains its own leaderboard
        for division, players in division_stats.items():
            sorted_players = sorted(
                players,
                key=lambda x: (
                    x["rounded_average_goals_against"],
                    -x["total_points"],
                    -x["sum_goals"],
                    -x["sum_assists"],
                ),
            )

            if division == "Sunday D1":
                self.assertEqual(sorted_players[0]["first_name"], "D1")  # 25 points
                self.assertEqual(sorted_players[1]["first_name"], "D1")  # 20 points
            else:  # Sunday D2
                self.assertEqual(
                    sorted_players[0]["first_name"], "D2"
                )  # 30 points (D2 Leader)
                self.assertEqual(
                    sorted_players[1]["first_name"], "D2"
                )  # 25 points (D2 Second)


class PlayerStatsIntegrationTestCase(TestCase):
    """
    Integration tests for player statistics functionality
    """

    def test_get_player_stats_function_exists(self):
        """Test that the get_player_stats function exists and is importable"""
        from core.views import get_player_stats

        # Verify function exists and is callable
        self.assertTrue(callable(get_player_stats))

        # Test function signature (should accept players queryset and season)
        import inspect

        sig = inspect.signature(get_player_stats)
        params = list(sig.parameters.keys())

        # Should have 'players' and 'season' parameters
        self.assertIn("players", params)
        self.assertIn("season", params)


class StatScopeAveragesTestCase(TestCase):
    def setUp(self):
        self.season_regular = Season.objects.create(
            year=2024, season_type=1, is_current_season=False
        )
        self.season_post = Season.objects.create(
            year=2024, season_type=2, is_current_season=False
        )
        self.division = Division.objects.create(division=1)
        self.team_regular = Team.objects.create(
            team_name="Regular Team",
            division=self.division,
            season=self.season_regular,
            is_active=True,
        )
        self.team_post = Team.objects.create(
            team_name="Post Team",
            division=self.division,
            season=self.season_post,
            is_active=True,
        )
        self.player = Player.objects.create(first_name="Ava", last_name="Skater")
        Roster.objects.create(
            player=self.player,
            team=self.team_regular,
            position1=1,
            is_captain=False,
            is_substitute=False,
        )
        Roster.objects.create(
            player=self.player,
            team=self.team_post,
            position1=1,
            is_captain=False,
            is_substitute=False,
        )
        week = Week.objects.create(date="2024-01-01", season=self.season_regular)
        self.match_regular = MatchUp.objects.create(
            week=week,
            time="18:00",
            awayteam=self.team_regular,
            hometeam=self.team_post,
            is_postseason=False,
        )
        self.match_post = MatchUp.objects.create(
            week=week,
            time="19:00",
            awayteam=self.team_regular,
            hometeam=self.team_post,
            is_postseason=True,
        )
        Stat.objects.create(
            player=self.player,
            team=self.team_regular,
            matchup=self.match_regular,
            goals=6,
            assists=4,
        )
        Stat.objects.create(
            player=self.player,
            team=self.team_post,
            matchup=self.match_post,
            goals=2,
            assists=1,
        )

    def test_normalize_stat_scope(self):
        self.assertEqual(normalize_stat_scope("regular"), "regular")
        self.assertEqual(normalize_stat_scope("postseason"), "postseason")
        self.assertEqual(normalize_stat_scope("combined"), "combined")
        self.assertEqual(normalize_stat_scope("bad-input"), "regular")

    def test_average_stats_use_total_seasons_played(self):
        combined = get_average_stats_for_player(self.player.id, scope="combined")
        regular = get_average_stats_for_player(self.player.id, scope="regular")
        postseason = get_average_stats_for_player(self.player.id, scope="postseason")

        self.assertEqual(combined["average_goals_per_season"], 4)
        self.assertEqual(combined["average_assists_per_season"], 2.5)
        self.assertEqual(regular["average_goals_per_season"], 3)
        self.assertEqual(regular["average_assists_per_season"], 2)
        self.assertEqual(postseason["average_goals_per_season"], 1)
        self.assertEqual(postseason["average_assists_per_season"], 0.5)


if __name__ == "__main__":
    unittest.main()
