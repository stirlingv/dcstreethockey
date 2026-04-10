"""
Performance regression tests: query count ceilings for key views.

These tests verify that adding more data (teams, matchups, stats) does not cause
query counts to scale unboundedly (N+1 regressions).  They use Django's
CaptureQueriesContext rather than assertNumQueries so we can assert an upper
bound rather than an exact number, which makes the tests tolerant of minor
framework changes while still catching obvious regressions.

How to update ceilings:
  If a legitimate change increases query count, update the ceiling constant in
  the relevant test and leave a comment explaining why it changed.
"""
import datetime

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
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
    Week,
)

# ---------------------------------------------------------------------------
# Ceiling constants — update these when a deliberate change affects query count.
#
# Known N+1 issues (tracked for future optimization):
#   - standings view runs ~3 queries per team (tiebreaker checks via Python loop)
#   - goalie_status_board runs additional queries per matchup for roster goalie lookups
# ---------------------------------------------------------------------------
STANDINGS_QUERY_CEILING = 50  # ~3 q/team; see N+1 note above
SCORES_ALL_DIVISIONS_QUERY_CEILING = 35
SCORES_ONE_DIVISION_QUERY_CEILING = 25
PLAYER_STATS_QUERY_CEILING = 25
GOALIE_BOARD_QUERY_CEILING = 40  # roster goalie lookup per matchup; see N+1 note
# Max additional queries allowed per extra team added to standings
STANDINGS_QUERIES_PER_TEAM_BUDGET = 5


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_base(year=2025):
    season = Season.objects.create(year=year, season_type=1, is_current_season=True)
    division = Division.objects.create(division=1)
    return season, division


def _make_team(name, division, season, color="Red"):
    team = Team.objects.create(
        team_name=name,
        team_color=color,
        division=division,
        season=season,
        is_active=True,
    )
    Team_Stat.objects.create(
        division=division,
        season=season,
        team=team,
        win=3,
        loss=1,
        tie=0,
        otw=0,
        otl=0,
        goals_for=12,
        goals_against=6,
    )
    return team


def _make_player_with_stats(first, last, team, week):
    player = Player.objects.create(first_name=first, last_name=last)
    Roster.objects.create(player=player, team=team, position1=1, is_captain=False)
    matchup = MatchUp.objects.create(
        week=week,
        time=datetime.time(19, 0),
        hometeam=team,
        awayteam=team,
    )
    Stat.objects.create(player=player, team=team, matchup=matchup, goals=2, assists=1)
    return player


# ---------------------------------------------------------------------------
# Standings view
# ---------------------------------------------------------------------------


class StandingsQueryCountTest(TestCase):
    """Standings page must not run more than STANDINGS_QUERY_CEILING queries."""

    def setUp(self):
        self.client = Client()
        season, division = _make_base(year=2025)
        for i in range(8):
            _make_team(f"Standings Team {i}", division, season, color="Red")

    def test_standings_query_count_bounded(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("team_standings"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx.captured_queries),
            STANDINGS_QUERY_CEILING,
            msg=(
                f"Standings view ran {len(ctx.captured_queries)} queries with 8 teams "
                f"(ceiling: {STANDINGS_QUERY_CEILING}). Possible N+1 regression."
            ),
        )

    def test_standings_query_count_per_team_budget(self):
        """
        The standings view currently has a known N+1 pattern in its tiebreaker
        logic (~3 queries per team).  This test verifies that adding more teams
        does not exceed STANDINGS_QUERIES_PER_TEAM_BUDGET queries per team,
        catching any future regressions that make the pattern worse.

        To fix the underlying N+1: batch the head-to-head lookups in
        core/views/standings.py rather than querying per-pair.
        """
        season = Season.objects.filter(is_current_season=True).first()
        division = Division.objects.first()

        # Baseline with 8 teams
        with CaptureQueriesContext(connection) as baseline_ctx:
            self.client.get(reverse("team_standings"))
        baseline = len(baseline_ctx.captured_queries)

        # Add 4 more teams
        for i in range(8, 12):
            _make_team(f"Extra Team {i}", division, season, color="Blue")

        with CaptureQueriesContext(connection) as extended_ctx:
            response = self.client.get(reverse("team_standings"))
        self.assertEqual(response.status_code, 200)
        added_queries = len(extended_ctx.captured_queries) - baseline
        max_allowed = 4 * STANDINGS_QUERIES_PER_TEAM_BUDGET
        self.assertLessEqual(
            added_queries,
            max_allowed,
            msg=(
                f"Adding 4 teams increased query count by {added_queries} "
                f"(budget: {max_allowed} = 4 teams × {STANDINGS_QUERIES_PER_TEAM_BUDGET}). "
                "N+1 pattern is worse than expected."
            ),
        )


# ---------------------------------------------------------------------------
# Scores view — all divisions
# ---------------------------------------------------------------------------


class ScoresAllDivisionsQueryCountTest(TestCase):
    """scores/ (all divisions) must stay under ceiling with multiple matchups."""

    def setUp(self):
        self.client = Client()
        season, division = _make_base(year=2025)
        home = _make_team("Home Team", division, season)
        away = _make_team("Away Team", division, season, color="Blue")
        past_date = datetime.date.today() - datetime.timedelta(days=1)
        week = Week.objects.create(division=division, season=season, date=past_date)
        for i in range(6):
            MatchUp.objects.create(
                week=week,
                time=datetime.time(18 + i, 0),
                hometeam=home,
                awayteam=away,
            )

    def test_scores_all_divisions_query_count_bounded(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("scores"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx.captured_queries),
            SCORES_ALL_DIVISIONS_QUERY_CEILING,
            msg=(
                f"Scores (all divs) ran {len(ctx.captured_queries)} queries "
                f"(ceiling: {SCORES_ALL_DIVISIONS_QUERY_CEILING})."
            ),
        )


# ---------------------------------------------------------------------------
# Scores view — single division
# ---------------------------------------------------------------------------


class ScoresSingleDivisionQueryCountTest(TestCase):
    """scores/<division>/ must stay under ceiling with multiple matchups."""

    def setUp(self):
        self.client = Client()
        self.season, self.division = _make_base(year=2025)
        home = _make_team("Home Team", self.division, self.season)
        away = _make_team("Away Team", self.division, self.season, color="Blue")
        past_date = datetime.date.today() - datetime.timedelta(days=1)
        week = Week.objects.create(
            division=self.division, season=self.season, date=past_date
        )
        for i in range(5):
            MatchUp.objects.create(
                week=week,
                time=datetime.time(18 + i, 0),
                hometeam=home,
                awayteam=away,
            )

    def test_scores_division_query_count_bounded(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(f"/scores/{self.division.division}/")
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx.captured_queries),
            SCORES_ONE_DIVISION_QUERY_CEILING,
            msg=(
                f"Scores (div {self.division.division}) ran {len(ctx.captured_queries)} "
                f"queries (ceiling: {SCORES_ONE_DIVISION_QUERY_CEILING})."
            ),
        )


# ---------------------------------------------------------------------------
# Player stats view
# ---------------------------------------------------------------------------


class PlayerStatsQueryCountTest(TestCase):
    """player_stats/ must not issue an extra query per player."""

    def setUp(self):
        self.client = Client()
        season, division = _make_base(year=2025)
        team = _make_team("Stats Team", division, season)
        past_date = datetime.date.today() - datetime.timedelta(days=7)
        week = Week.objects.create(division=division, season=season, date=past_date)
        for i in range(10):
            _make_player_with_stats(f"Player{i}", f"Surname{i}", team, week)

    def test_player_stats_query_count_bounded(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("player_stats"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx.captured_queries),
            PLAYER_STATS_QUERY_CEILING,
            msg=(
                f"player_stats ran {len(ctx.captured_queries)} queries with 10 players "
                f"(ceiling: {PLAYER_STATS_QUERY_CEILING})."
            ),
        )


# ---------------------------------------------------------------------------
# Goalie status board
# ---------------------------------------------------------------------------


class GoalieBoardQueryCountTest(TestCase):
    """goalie-status/ must not run a query per matchup."""

    def setUp(self):
        self.client = Client()
        season, division = _make_base(year=2025)
        home = _make_team("Home", division, season)
        away = _make_team("Away", division, season, color="Blue")
        future_date = datetime.date.today() + datetime.timedelta(days=3)
        week = Week.objects.create(division=division, season=season, date=future_date)
        for i in range(6):
            MatchUp.objects.create(
                week=week,
                time=datetime.time(17 + i, 0),
                hometeam=home,
                awayteam=away,
            )

    def test_goalie_board_query_count_bounded(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("goalie_status_board"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(ctx.captured_queries),
            GOALIE_BOARD_QUERY_CEILING,
            msg=(
                f"Goalie board ran {len(ctx.captured_queries)} queries with 6 matchups "
                f"(ceiling: {GOALIE_BOARD_QUERY_CEILING})."
            ),
        )
