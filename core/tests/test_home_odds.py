"""
Game Lines and Player Props on the home page schedule.

Covers core/views/home.py (odds_matchup_ids and the home view context),
core/templates/core/homepage_detail_info.html, the shared
leagues/templates/partials/odds_panels.html, and the static assets that make
the panels work on the home page.
"""

import datetime
import re
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.db.models.query import QuerySet
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from core.views.home import odds_matchup_ids
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

_original_distinct = QuerySet.distinct


def distinct_on_week_date(self, *field_names):
    """
    SQLite stand-in for the home view's PostgreSQL-only
    ``.distinct("week__date")``: keep the first row per game date, in the
    queryset's own ordering, so each date column renders once as it does in
    production.
    """
    if field_names == ("week__date",):
        first_per_date = {}
        for m in _original_distinct(self).select_related("week"):
            first_per_date.setdefault(m.week.date, m.pk)
        return _original_distinct(self).filter(pk__in=first_per_date.values())
    return _original_distinct(self, *field_names)


def get_home(client):
    """GET the home page under SQLite with the weather fetch mocked out."""
    cache.clear()
    with (
        patch.object(QuerySet, "distinct", distinct_on_week_date),
        patch("core.views.home.requests.get") as mock_get,
    ):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"properties": {"periods": []}}
        return client.get(reverse("home"))


def _static_text(path):
    found = finders.find(path)
    assert found, f"{path} not found by the staticfiles finder"
    with open(found, encoding="utf-8") as fh:
        return fh.read()


def _strip_css_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ---------------------------------------------------------------------------
# odds_matchup_ids — which home-page games get lines and props
# ---------------------------------------------------------------------------


def _fake_match(match_id, division, is_cancelled=False):
    div = None if division is None else SimpleNamespace(division=division)
    return SimpleNamespace(
        id=match_id,
        is_cancelled=is_cancelled,
        hometeam=SimpleNamespace(division=div),
    )


class OddsMatchupIdsTest(SimpleTestCase):
    def test_empty_input_returns_empty_list(self):
        self.assertEqual(odds_matchup_ids([]), [])

    def test_sunday_d2_game_included(self):
        self.assertEqual(odds_matchup_ids([_fake_match(7, 2)]), [7])

    def test_wednesday_and_monday_games_included(self):
        games = [_fake_match(3, 3), _fake_match(4, 4), _fake_match(5, 5)]
        self.assertEqual(odds_matchup_ids(games), [3, 4, 5])

    def test_sunday_d1_game_excluded(self):
        # Matches the Schedule page, which never shows odds for Sunday D1.
        self.assertEqual(odds_matchup_ids([_fake_match(1, 1)]), [])

    def test_cancelled_game_excluded(self):
        self.assertEqual(odds_matchup_ids([_fake_match(9, 2, is_cancelled=True)]), [])

    def test_team_without_division_excluded(self):
        self.assertEqual(odds_matchup_ids([_fake_match(11, None)]), [])

    def test_mixed_list_keeps_order_of_eligible_games(self):
        games = [
            _fake_match(1, 1),
            _fake_match(2, 4),
            _fake_match(3, 2, is_cancelled=True),
            _fake_match(4, 5),
        ]
        self.assertEqual(odds_matchup_ids(games), [2, 4])


# ---------------------------------------------------------------------------
# Home view integration
# ---------------------------------------------------------------------------


class HomeOddsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.season = Season.objects.create(
            year=datetime.date.today().year, season_type=1, is_current_season=True
        )
        self.d2 = Division.objects.create(division=2)
        self.home_team = self._team("Home Odds Team", self.d2, "Red")
        self.away_team = self._team("Away Odds Team", self.d2, "Blue")
        self.game_date = datetime.date.today() + datetime.timedelta(days=2)
        self.week = Week.objects.create(
            division=self.d2, season=self.season, date=self.game_date
        )
        self.matchup = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            hometeam=self.home_team,
            awayteam=self.away_team,
        )

    def _team(self, name, division, color):
        return Team.objects.create(
            team_name=name,
            team_color=color,
            division=division,
            season=self.season,
            is_active=True,
        )

    def _team_stats(self, team, division, goals_for, goals_against):
        Team_Stat.objects.create(
            division=division,
            season=self.season,
            team=team,
            win=4,
            loss=2,
            otw=0,
            otl=0,
            tie=0,
            goals_for=goals_for,
            goals_against=goals_against,
        )

    def _give_both_teams_stats(self):
        self._team_stats(self.home_team, self.d2, 24, 14)
        self._team_stats(self.away_team, self.d2, 15, 21)

    def test_context_has_lines_and_props_dicts(self):
        response = get_home(self.client)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["betting_lines"], dict)
        self.assertIsInstance(response.context["player_props"], dict)

    def test_game_lines_rendered_under_game(self):
        self._give_both_teams_stats()
        response = get_home(self.client)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["betting_lines"].get(self.matchup.id))
        mid = self.matchup.id
        self.assertContains(response, 'class="home-odds"', count=1)
        self.assertContains(response, ">Game Lines</button>", count=1)
        self.assertContains(response, f'aria-controls="bl-panel-{mid}"')
        # Panel starts collapsed; the button reveals it.
        self.assertContains(response, f'id="bl-panel-{mid}" hidden')
        self.assertContains(response, "SPREAD")
        self.assertContains(response, "MONEYLINE")
        self.assertContains(response, "For entertainment purposes only")

    def test_player_props_rendered_with_stat_history(self):
        player = Player.objects.create(first_name="Sniper", last_name="Wing")
        Roster.objects.create(player=player, team=self.home_team, position1=1)
        for i in range(3):
            past_week = Week.objects.create(
                division=self.d2,
                season=self.season,
                date=datetime.date.today() - datetime.timedelta(days=7 * (i + 1)),
            )
            past_game = MatchUp.objects.create(
                week=past_week,
                time=datetime.time(19, 0),
                hometeam=self.home_team,
                awayteam=self.away_team,
            )
            Stat.objects.create(
                player=player,
                team=self.home_team,
                matchup=past_game,
                goals=1,
                assists=1,
            )
        response = get_home(self.client)
        self.assertIsNotNone(response.context["player_props"].get(self.matchup.id))
        self.assertContains(response, ">Player Props</button>", count=1)
        self.assertContains(response, f'id="props-panel-{self.matchup.id}" hidden')
        self.assertContains(response, "Sniper Wing")
        self.assertContains(response, f'href="/player/{player.id}/"')

    def test_no_toggle_buttons_without_data(self):
        # No season stats and no rostered players: nothing to price.
        response = get_home(self.client)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["betting_lines"].get(self.matchup.id))
        self.assertNotContains(response, 'class="home-odds"')
        self.assertNotContains(response, "bl-toggle-btn")
        # The game itself is still listed.
        self.assertContains(response, "Home Odds Team")

    def test_sunday_d1_game_gets_no_lines(self):
        d1 = Division.objects.create(division=1)
        d1_home = self._team("D1 Home", d1, "Green")
        d1_away = self._team("D1 Away", d1, "Black")
        self._team_stats(d1_home, d1, 20, 10)
        self._team_stats(d1_away, d1, 10, 20)
        d1_week = Week.objects.create(
            division=d1,
            season=self.season,
            date=self.game_date + datetime.timedelta(days=1),
        )
        d1_game = MatchUp.objects.create(
            week=d1_week, time=datetime.time(18, 0), hometeam=d1_home, awayteam=d1_away
        )
        response = get_home(self.client)
        self.assertNotIn(d1_game.id, response.context["betting_lines"])
        self.assertNotIn(d1_game.id, response.context["player_props"])
        self.assertNotContains(response, f"bl-panel-{d1_game.id}")
        self.assertContains(response, "D1 Home")

    def test_cancelled_game_gets_no_lines(self):
        self._give_both_teams_stats()
        self.matchup.is_cancelled = True
        self.matchup.save()
        response = get_home(self.client)
        self.assertNotIn(self.matchup.id, response.context["betting_lines"])
        self.assertNotContains(response, 'class="home-odds"')
        self.assertContains(response, "game-cancelled-badge")

    def test_lines_for_one_game_do_not_leak_to_another(self):
        self._give_both_teams_stats()
        other_home = self._team("Unpriced Home", self.d2, "Green")
        other_away = self._team("Unpriced Away", self.d2, "Black")
        other = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(20, 0),
            hometeam=other_home,
            awayteam=other_away,
        )
        response = get_home(self.client)
        self.assertContains(response, f'id="bl-panel-{self.matchup.id}"', count=1)
        self.assertNotContains(response, f"bl-panel-{other.id}")

    def test_page_loads_shared_odds_script_and_styles(self):
        response = get_home(self.client)
        self.assertContains(response, "assets/js/odds.js")
        self.assertContains(response, "assets/css/schedule.css")

    def test_no_games_this_week(self):
        self.matchup.delete()
        response = get_home(self.client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["betting_lines"], {})
        self.assertEqual(response.context["player_props"], {})


# ---------------------------------------------------------------------------
# Static assets the panels depend on
# ---------------------------------------------------------------------------


class OddsStaticAssetsTest(SimpleTestCase):
    def test_odds_js_defines_panel_handlers(self):
        js = _static_text("assets/js/odds.js")
        self.assertIn("function toggleOdds(", js)
        self.assertIn("function showPropSort(", js)

    def test_quote_list_span_rule_disabled(self):
        # On tablet widths the theme pushed every span inside the home game
        # list 80px right, which broke the panels and the Cancelled badge.
        css = _strip_css_comments(_static_text("assets/css/main.css"))
        self.assertNotRegex(css, r"\.quote-list\s+li\s+span\s*\{")

    def test_home_props_list_is_single_column(self):
        css = _strip_css_comments(_static_text("assets/css/schedule.css"))
        self.assertRegex(css, r"\.home-odds\s+\.props-list\s*\{\s*display:\s*block;")

    def test_toggle_buttons_are_44px_on_phones(self):
        css = _strip_css_comments(_static_text("assets/css/schedule.css"))
        self.assertRegex(
            css,
            r"@media \(max-width: 767px\)\s*\{\s*\.bl-toggle-btn\s*\{"
            r"[^}]*min-height:\s*44px",
        )
