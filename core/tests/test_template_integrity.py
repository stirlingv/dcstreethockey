"""
Regression tests for template bugs fixed in July 2026.

Covered bugs (each test names the template it protects):
- partials/stats.html: malformed goalie team onclick — handleTeam(''...') with a
  stray quote made the click a JS syntax error.
- partials/stats.html: the expand caret rendered with an empty id ("ex-") when
  the partial was included without a division (team page), so clicking it threw.
- partials/hof_player_rankings.html: the {% empty %} clause sat inside the row
  markup, leaving </tr> outside the loop and producing malformed table HTML.
- homepage_info.html / homepage_info_2.html: unbalanced <div> tags.
- leagues/player.html: debug console.log statements shipped to production.
- toggleTable() copies in schedule/scores/team/cups templates: used == instead
  of = so the expand indicator never toggled.
"""

import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from leagues.models import (
    Division,
    Team_Stat,
    MatchUp,
    Player,
    Roster,
    Season,
    Stat,
    Team,
    Week,
)


def _goalie_row(team_id=7, points=0):
    """Dict shaped like the values() rows the stats partial iterates over."""
    return {
        "id": 1,
        "first_name": "Pat",
        "last_name": "Netminder",
        "roster__team__id": team_id,
        "roster__team__team_name": "Blue Ballers",
        "roster__position1": 4,
        "roster__position2": None,
        "roster__is_captain": False,
        "sum_goals": 0,
        "sum_assists": 0,
        "total_points": points,
        "sum_goals_against": 10,
        "sum_games_played": 5,
        "rounded_average_goals_against": 2.0,
    }


class StatsPartialTest(TestCase):
    """partials/stats.html regressions."""

    def test_goalie_team_cell_is_real_link(self):
        html = render_to_string(
            "partials/stats.html",
            {"player_list": [_goalie_row(team_id=7)], "division": "Sunday D1"},
        )
        # Originally a malformed onclick (handleTeam(''...); now a real anchor.
        self.assertNotIn("handleTeam", html)
        self.assertIn('href="/teams/7/"', html)

    def test_player_cell_is_real_link(self):
        html = render_to_string(
            "partials/stats.html",
            {"player_list": [_goalie_row()], "division": "Sunday D1"},
        )
        self.assertIn('href="/player/1/"', html)

    def test_no_show_more_button_without_division(self):
        html = render_to_string("partials/stats.html", {"player_list": [_goalie_row()]})
        self.assertNotIn("show-more-btn", html)
        self.assertNotIn('id="ex-"', html)

    def test_show_more_button_only_for_long_lists(self):
        short = render_to_string(
            "partials/stats.html",
            {"player_list": [_goalie_row()], "division": "Sunday D1"},
        )
        self.assertNotIn("show-more-btn", short)

        long_list = [_goalie_row() for _ in range(25)]
        long_html = render_to_string(
            "partials/stats.html",
            {"player_list": long_list, "division": "Sunday D1"},
        )
        self.assertIn("show-more-btn", long_html)
        self.assertIn("Show all players", long_html)


class HofRankingsPartialTest(TestCase):
    """partials/hof_player_rankings.html rows must be well-formed."""

    def _rank_row(self, rank):
        return {
            "rank": rank,
            "id": rank,
            "first_name": "Player",
            "last_name": f"Number{rank}",
            "total_points": 10 - rank,
            "total_goals": 5,
            "total_assists": 5 - rank,
        }

    def test_rows_closed_with_players(self):
        html = render_to_string(
            "partials/hof_player_rankings.html",
            {
                "player_ranks": [self._rank_row(1), self._rank_row(2)],
                "section_name": "combined",
            },
        )
        self.assertEqual(html.count("<tr"), html.count("</tr"))
        # One header row plus one row per player.
        self.assertEqual(html.count("<tr"), 3)

    def test_rows_closed_when_empty(self):
        html = render_to_string(
            "partials/hof_player_rankings.html",
            {"player_ranks": [], "section_name": "combined"},
        )
        self.assertEqual(html.count("<tr"), html.count("</tr"))
        self.assertIn("No Offensive stats yet.", html)


class TemplateFixtureBase(TestCase):
    """Minimal season/team/matchup/stat fixture for full-page rendering."""

    def setUp(self):
        self.client = Client()
        self.season = Season.objects.create(
            year=datetime.date.today().year, season_type=1, is_current_season=True
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
        self.week = Week.objects.create(
            division=self.division,
            season=self.season,
            date=datetime.date.today() - datetime.timedelta(days=7),
        )
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )
        self.player = Player.objects.create(first_name="Casey", last_name="Wing")
        Roster.objects.create(
            player=self.player,
            team=self.home_team,
            position1=1,
            is_captain=False,
        )
        Stat.objects.create(
            player=self.player,
            team=self.home_team,
            matchup=self.matchup,
            goals=2,
            assists=1,
        )


class HomePageDivBalanceTest(TestCase):
    """homepage_info partials had unbalanced <div> tags."""

    def _get_home(self):
        # Mock MatchUp (the view uses PostgreSQL-only .distinct("week__date"))
        # and the weather fetch, following core/tests/test_cancellation.py.
        cache.clear()
        with (
            patch("core.views.home.MatchUp"),
            patch("core.views.home.requests.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"properties": {"periods": []}}
            return self.client.get(reverse("home"))

    def test_home_page_divs_balanced(self):
        response = self._get_home()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertEqual(content.count("<div"), content.count("</div"))

    def test_champion_photos_are_not_dead_links(self):
        response = self._get_home()
        content = response.content.decode()
        self.assertNotIn('<a href="#" class="bordered-feature-image">', content)


class PlayerPageTest(TemplateFixtureBase):
    """leagues/player.html shipped console.log debug output."""

    def test_player_page_has_no_console_log(self):
        response = self.client.get(reverse("player", args=[self.player.id]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The chart script must actually render for this test to mean anything.
        self.assertIn("playerTrendsSnapshot", content)
        self.assertNotIn("console.log", content)


class BoxScoreDisclosureTest(TemplateFixtureBase):
    """
    The copy-pasted toggleTable() JS (which once hid box scores behind an
    unlabeled ^ caret, with an ==-instead-of-= bug) is gone. Box scores now
    use a native <details> disclosure with a visible label.
    """

    def _get(self, url):
        cache.clear()
        with patch("core.views.home.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"properties": {"periods": []}}
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _assert_no_toggle_script(self, url):
        content = self._get(url)
        self.assertNotIn("function toggleTable", content)
        self.assertNotIn('class="expand"', content)

    def test_scores_page_uses_details_disclosure(self):
        content = self._get(reverse("scores"))
        self.assertNotIn("function toggleTable", content)
        self.assertIn("box-score-toggle", content)
        self.assertIn("Box score", content)

    def test_schedule_page(self):
        self._assert_no_toggle_script(reverse("schedule"))

    def test_cups_page(self):
        self._assert_no_toggle_script(reverse("cups"))

    def test_team_page(self):
        self._assert_no_toggle_script(reverse("teams", args=[self.home_team.id]))


class RealLinksTest(TemplateFixtureBase):
    """Team/player names must be real anchors, not onclick cells."""

    def _get(self, url):
        cache.clear()
        with patch("core.views.home.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"properties": {"periods": []}}
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_scores_page_team_links(self):
        content = self._get(reverse("scores"))
        self.assertIn(f'href="/teams/{self.home_team.id}/" class="cell-link"', content)
        self.assertNotIn('onclick="javascript:handleTeam', content)

    def test_standings_page_team_links(self):
        Team_Stat.objects.create(
            team=self.home_team,
            division=self.division,
            season=self.season,
            win=1,
            loss=0,
        )
        content = self._get(reverse("team_standings"))
        self.assertIn(f'href="/teams/{self.home_team.id}/" class="cell-link"', content)

    def test_scores_page_record_uses_current_format(self):
        # Post-2022 season: four-number W-OTW-OTL-L record (was W-L-T).
        content = self._get(reverse("scores"))
        self.assertIn("(0-0-0-0)", content)
        self.assertIn("Team records: W-OTW-OTL-L", content)


class HomeDivisionGroupingTest(TestCase):
    """Home-page date columns group games under division sub-headers."""

    def _render(self, matchups, one_row):
        return render_to_string(
            "core/homepage_detail_info.html",
            {
                "one_row": one_row,
                "matchup": matchups,
                "weather_data": {},
                "weather_unavailable": True,
            },
        )

    def test_division_labels_rendered_per_group(self):
        season = Season.objects.create(
            year=datetime.date.today().year, season_type=1, is_current_season=True
        )
        d1 = Division.objects.create(division=1)
        d2 = Division.objects.create(division=2)
        game_date = datetime.date.today() + datetime.timedelta(days=1)
        teams = {}
        for div, label in ((d1, "D1"), (d2, "D2")):
            for side in ("A", "B"):
                teams[(div, side)] = Team.objects.create(
                    team_name=f"{label} Team {side}",
                    team_color="Red",
                    division=div,
                    season=season,
                    is_active=True,
                )
        week1 = Week.objects.create(division=d1, season=season, date=game_date)
        week2 = Week.objects.create(division=d2, season=season, date=game_date)
        m1 = MatchUp.objects.create(
            week=week1,
            time=datetime.time(18, 0),
            hometeam=teams[(d1, "A")],
            awayteam=teams[(d1, "B")],
        )
        m2 = MatchUp.objects.create(
            week=week2,
            time=datetime.time(19, 0),
            hometeam=teams[(d2, "A")],
            awayteam=teams[(d2, "B")],
        )
        html = self._render([m1, m2], [m1])
        self.assertIn("home-division-label", html)
        self.assertIn(">D1</li>", html)
        self.assertIn(">D2</li>", html)
        # Games link to their team pages and the game center.
        self.assertIn(f'href="/teams/{teams[(d1, "A")].id}/"', html)
        self.assertIn(f'href="/matchup/{m1.id}/"', html)

    def test_label_rendered_once_per_division(self):
        season = Season.objects.create(
            year=datetime.date.today().year, season_type=1, is_current_season=True
        )
        d1 = Division.objects.create(division=1)
        game_date = datetime.date.today() + datetime.timedelta(days=1)
        t1 = Team.objects.create(
            team_name="One",
            team_color="Red",
            division=d1,
            season=season,
            is_active=True,
        )
        t2 = Team.objects.create(
            team_name="Two",
            team_color="Blue",
            division=d1,
            season=season,
            is_active=True,
        )
        week = Week.objects.create(division=d1, season=season, date=game_date)
        m1 = MatchUp.objects.create(
            week=week, time=datetime.time(18, 0), hometeam=t1, awayteam=t2
        )
        m2 = MatchUp.objects.create(
            week=week, time=datetime.time(19, 0), hometeam=t2, awayteam=t1
        )
        html = self._render([m1, m2], [m1])
        self.assertEqual(html.count("home-division-label"), 1)
