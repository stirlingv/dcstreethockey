"""
Site-wide smoke tests: open every admin page and every public URL.

These catch the failures unit tests miss after a dependency upgrade or
removal, such as a template tag library that no longer loads, an admin
column that raises, or a view whose import broke. Both sweeps also fail
when a new admin model or URL is added without being covered here, so
coverage can't silently drift.
"""

import datetime
import traceback
from contextlib import contextmanager
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.models.query import QuerySet
from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from dcstreethockey.smoke_data import build_smoke_data
from leagues.admin import _DRAFT_OBJECT_NAMES
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

# Admin views that may legitimately refuse access even for a superuser.
ADMIN_OPTIONAL_STATUSES = {200, 302, 403}


@contextmanager
def sqlite_safe_distinct():
    """Let views that use PostgreSQL's DISTINCT ON render under SQLite.

    The test database is SQLite, which rejects ``.distinct("field")``. For a
    smoke test the exact de-duplication doesn't matter, only that the page
    renders, so drop the field list. The production smoke job in CI renders
    the same pages against real PostgreSQL.
    """
    if connection.vendor == "postgresql":
        yield
        return
    original = QuerySet.distinct

    def distinct(self, *field_names):
        return original(self)

    with patch.object(QuerySet, "distinct", distinct):
        yield


class AdminSmokeTest(TestCase):
    """Every registered admin model: changelist, search, add, change,
    history and delete confirmation all render for a superuser."""

    @classmethod
    def setUpTestData(cls):
        cls.data = build_smoke_data()
        cls.superuser = get_user_model().objects.create_superuser(
            "smoke-admin", "admin@example.com", "smoke-password"
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def _get(self, url):
        # Follow redirects: the Week and MatchUp lists redirect to the
        # current season's filter on purpose.
        response = self.client.get(url, follow=True)
        self.assertLess(response.status_code, 500, url)
        for hop, _ in response.redirect_chain:
            self.assertTrue(hop.startswith("/admin/") or hop.startswith("?"), hop)
        return response

    def test_admin_index_lists_every_app(self):
        response = self._get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        # A dashboard section that fails shows a notice instead of a 500, so
        # check here that every section actually rendered.
        self.assertNotContains(response, "dashboard-section-error")
        for model in admin.site._registry:
            if model.__name__ in _DRAFT_OBJECT_NAMES:
                continue  # folded into the single "Setup Draft" entry
            with self.subTest(model=model._meta.label):
                self.assertContains(
                    response,
                    reverse(
                        f"admin:{model._meta.app_label}_"
                        f"{model._meta.model_name}_changelist"
                    ),
                )
        self.assertContains(
            response, reverse("admin:leagues_draftsession_draft_setup_hub")
        )

    def test_every_registered_model_has_smoke_data(self):
        # If this fails, add a row for the new model in smoke_data.py.
        for model in admin.site._registry:
            with self.subTest(model=model._meta.label):
                self.assertTrue(model._default_manager.exists())

    def test_every_admin_page_renders(self):
        for model, model_admin in admin.site._registry.items():
            info = f"admin:{model._meta.app_label}_{model._meta.model_name}"
            obj = model._default_manager.order_by("pk").first()
            with self.subTest(model=model._meta.label, page="changelist"):
                response = self._get(reverse(f"{info}_changelist"))
                self.assertEqual(response.status_code, 200)
            if model_admin.search_fields:
                with self.subTest(model=model._meta.label, page="search"):
                    url = reverse(f"{info}_changelist") + "?q=Smoke"
                    self.assertEqual(self._get(url).status_code, 200)
            with self.subTest(model=model._meta.label, page="add"):
                response = self._get(reverse(f"{info}_add"))
                self.assertIn(response.status_code, ADMIN_OPTIONAL_STATUSES)
            with self.subTest(model=model._meta.label, page="change"):
                response = self._get(reverse(f"{info}_change", args=[obj.pk]))
                self.assertIn(response.status_code, ADMIN_OPTIONAL_STATUSES)
            with self.subTest(model=model._meta.label, page="history"):
                response = self._get(reverse(f"{info}_history", args=[obj.pk]))
                self.assertEqual(response.status_code, 200)
            with self.subTest(model=model._meta.label, page="delete"):
                response = self._get(reverse(f"{info}_delete", args=[obj.pk]))
                self.assertIn(response.status_code, ADMIN_OPTIONAL_STATUSES)

    def test_every_list_filter_renders(self):
        for model, model_admin in admin.site._registry.items():
            changelist = reverse(
                f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
            )
            response = self._get(changelist)
            if response.status_code != 200 or "cl" not in response.context:
                continue
            for spec in response.context["cl"].filter_specs:
                for choice in spec.choices(response.context["cl"]):
                    query = choice.get("query_string")
                    if not query or query == "?":
                        continue
                    with self.subTest(model=model._meta.label, filter=query):
                        url = changelist + query
                        self.assertEqual(self._get(url).status_code, 200)
                    break  # one value per filter keeps the sweep fast

    def _custom_admin_urls(self):
        d = self.data
        return {
            "leagues_matchup_schedule_manager": [],
            "leagues_matchupgoaliestatus_add_goalie_sub": [],
            "leagues_draftsession_draft_setup_hub": [],
            "leagues_draftsession_start_signups": [],
            "leagues_draftsession_setup_teams": [d["draft"].pk],
            "leagues_season_switch_to_computed": [d["season"].pk],
        }

    # Custom admin URLs that change data, so a GET must not act. The quick
    # cancel views redirect on GET. The photo approve/reject views act on
    # GET today, so the sweep skips them rather than mutate the fixture.
    STATE_CHANGING_ADMIN_URLS = {
        "leagues_week_quick_cancel",
        "leagues_week_quick_cancel_date",
        "leagues_matchup_quick_cancel",
        "leagues_matchup_fix_week_division",
        "leagues_pendingplayerphoto_approve_single",
        "leagues_pendingplayerphoto_reject_single",
        "leagues_pendingteamphoto_approve_single",
        "leagues_pendingteamphoto_reject_single",
    }

    def test_every_custom_admin_url_is_classified(self):
        # If this fails, add the new admin URL to _custom_admin_urls (safe
        # to GET) or STATE_CHANGING_ADMIN_URLS.
        model_admin_suffixes = (
            "_changelist",
            "_add",
            "_change",
            "_delete",
            "_history",
        )
        custom = set()
        for model_admin in admin.site._registry.values():
            for pattern in model_admin.get_urls():
                if pattern.name and not pattern.name.endswith(model_admin_suffixes):
                    custom.add(pattern.name)
        classified = set(self._custom_admin_urls()) | self.STATE_CHANGING_ADMIN_URLS
        self.assertEqual(custom - classified, set())

    def test_every_custom_admin_page_renders(self):
        for name, args in self._custom_admin_urls().items():
            with self.subTest(url=name):
                response = self._get(reverse(f"admin:{name}", args=args))
                self.assertEqual(response.status_code, 200)

    def test_quick_cancel_ignores_get(self):
        played = self.data["played"]
        week = played.week
        urls = [
            reverse("admin:leagues_week_quick_cancel", args=[week.pk]),
            reverse(
                "admin:leagues_week_quick_cancel_date",
                args=[week.date.isoformat(), 1],
            ),
            reverse("admin:leagues_matchup_quick_cancel", args=[played.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
        self.assertFalse(Week.objects.get(pk=week.pk).is_cancelled)
        self.assertFalse(MatchUp.objects.get(pk=played.pk).is_cancelled)

    def test_admin_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("admin:leagues_player_changelist"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])


def _url_names(patterns, namespace=None):
    """Yield the name of every non-admin URL pattern."""
    for entry in patterns:
        if isinstance(entry, URLResolver):
            if entry.namespace in ("admin", "djdt"):
                continue
            yield from _url_names(entry.url_patterns, entry.namespace)
        elif isinstance(entry, URLPattern):
            yield entry.name


class PublicUrlSmokeTest(TestCase):
    """Every public URL answers a GET without a server error, and pages
    meant for visitors return 200."""

    # URL name -> statuses a GET may return. 405 means the endpoint is
    # POST-only; 400 means it refuses the smoke draft's current state.
    EXPECTED = {
        "home": {200},
        "rosters": {200},
        "team_standings": {200},
        "player_stats": {200},
        "teams": {200},
        "player": {200},
        "matchup_detail": {200},
        "hof": {200},
        "schedule": {200},
        "scores": {200},
        "cups": {200},
        "player_trends": {200},
        "player-autocomplete": {200},
        "goalie-autocomplete": {200},
        "upload_player_photo": {200},
        "upload_team_photo": {200},
        "goalie_status_board": {200},
        "captain_goalie_update": {200},
        "update_goalie_status": {405},
        "report_sub_needed": {405},
        "confirm_goalie": {405},
        "confirm_sub_offer": {405},
        "decline_sub_offer": {405},
        "captain_urls_list": {200},
        "draft_signup": {200},
        "draft_board_spectator": {200},
        "draft_board_commissioner": {200},
        "draft_board_captain": {200},
        "draft_captain_portal": {200},
        "draft_draw_positions": {405},
        "draft_advance_state": {405},
        "draft_end": {405},
        "draft_undo_pick": {405},
        "draft_make_pick": {405},
        "draft_finalize": {405},
        "draft_swap_pick": {405},
        "draft_reset": {405},
        "draft_set_captain_rounds": {405},
        "draft_email_team": {400},
        "captain_roster_details": {200, 400, 404},
        "draft_add_late_signup": {405},
        "draft_results_download": {404},
        "draft_dev_autofill": {405},
        "draft_sessions_list": {200},
    }

    # Patterns without a name: the legacy /leagues/ redirect and, in DEBUG,
    # the static file server. They're covered by explicit requests below.
    UNNAMED_PATHS = {"/leagues/schedule/": {301, 302}}

    @classmethod
    def setUpTestData(cls):
        cls.data = build_smoke_data()

    def _urls(self):
        d = self.data
        draft, team = d["draft"], d["draft_teams"][0]
        board = [draft.pk, draft.commissioner_token]
        captain = [draft.pk, team.captain_token]
        played = d["played"]
        args = {
            "rosters": [],
            "team_standings": [],
            "teams": [d["home"].pk],
            "player": [d["players"]["home_center"].pk],
            "matchup_detail": [played.pk],
            "upload_player_photo": [d["players"]["home_center"].pk],
            "upload_team_photo": [d["home"].pk],
            "captain_goalie_update": [d["home"].captain_access_code],
            "update_goalie_status": [d["home"].captain_access_code, played.pk],
            "report_sub_needed": [d["upcoming"].pk, "home"],
            "confirm_goalie": [d["upcoming"].pk, "home"],
            "confirm_sub_offer": [d["away"].captain_access_code, d["sub_offer"].pk],
            "decline_sub_offer": [d["away"].captain_access_code, d["sub_offer"].pk],
            "draft_signup": [d["draft_season"].pk],
            "draft_board_spectator": [draft.pk],
            "draft_board_commissioner": board,
            "draft_board_captain": captain,
            "draft_captain_portal": [draft.pk],
            "draft_draw_positions": board,
            "draft_advance_state": board,
            "draft_end": board,
            "draft_undo_pick": board,
            "draft_make_pick": [draft.pk],
            "draft_finalize": board,
            "draft_swap_pick": board,
            "draft_reset": board,
            "draft_set_captain_rounds": board,
            "draft_email_team": captain,
            "captain_roster_details": captain,
            "draft_add_late_signup": board,
            "draft_results_download": [draft.pk],
            "draft_dev_autofill": board,
        }
        urls = {name: reverse(name, args=args.get(name, [])) for name in self.EXPECTED}
        # Pages that also take an optional argument.
        urls["player_stats (season)"] = reverse("player_stats", args=[d["season"].pk])
        urls["scores (division)"] = reverse("scores", args=[1])
        urls["cups (division)"] = reverse("cups", args=[1])
        urls["rosters (print)"] = reverse(
            "scoresheet_print", args=[played.week.date.isoformat()]
        )
        return urls

    def test_every_named_url_is_covered(self):
        # If this fails, add the new URL name to EXPECTED with the statuses
        # a GET should return.
        names = {n for n in _url_names(get_resolver().url_patterns) if n}
        names.discard("scoresheet_print")  # covered as "rosters (print)"
        self.assertEqual(names - set(self.EXPECTED), set())

    def test_every_public_url_responds(self):
        for label, url in self._urls().items():
            name = label.split(" (")[0]
            expected = self.EXPECTED.get(name, {200})
            with self.subTest(url=url), sqlite_safe_distinct():
                response = self.client.get(url)
                self.assertIn(response.status_code, expected, f"{label}: {url}")

    def test_legacy_leagues_urls_redirect(self):
        for path, expected in self.UNNAMED_PATHS.items():
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, expected)

    def test_unknown_url_returns_404_not_500(self):
        self.assertEqual(self.client.get("/no-such-page/").status_code, 404)


class SeedSmokeDataCommandTest(TestCase):
    def test_seeds_an_empty_database(self):
        out = StringIO()
        call_command("seed_smoke_data", stdout=out)
        self.assertIn("Seeded smoke data", out.getvalue())
        for model in admin.site._registry:
            with self.subTest(model=model._meta.label):
                if model is get_user_model():
                    continue  # CI creates the admin user separately
                self.assertTrue(model._default_manager.exists())

    def test_refuses_a_database_with_league_data(self):
        build_smoke_data()
        teams_before = Team.objects.count()
        with self.assertRaises(CommandError):
            call_command("seed_smoke_data", stdout=StringIO())
        self.assertEqual(Team.objects.count(), teams_before)


class OddDataSmokeTest(TestCase):
    """Every page still loads when the league holds rows in shapes the
    database allows but nobody planned for.

    In November 2026 the admin home page returned a 500, and a sweep with
    data like this found a dozen more pages that one odd row could take
    down: the team page of a team with no roster yet, the schedule when a
    rostered player had been deleted, the standings with a record row that
    had lost its team. Each of those is a single row, and each took a whole
    page offline for every visitor.

    The fixture below adds one of each such row to the smoke league, then
    opens every public page and every admin page, including the pages of the
    odd rows themselves. When this fails, the message names the URL and the
    line that raised: make that code cope with the row (skip it, or show a
    placeholder) rather than removing the row from the fixture.
    """

    @classmethod
    def setUpTestData(cls):
        cls.data = d = build_smoke_data()
        cls.superuser = get_user_model().objects.create_superuser(
            "odd-admin", "odd@example.com", "smoke-password"
        )
        today = timezone.localdate()
        home, away, players = d["home"], d["away"], d["players"]

        def game(days, home_team, away_team, division="same", season="same", **kw):
            week = Week.objects.create(
                division=d["division"] if division == "same" else division,
                season=d["season"] if season == "same" else season,
                date=today + datetime.timedelta(days=days),
            )
            matchup = MatchUp.objects.create(
                week=week,
                time=datetime.time(19, 0),
                hometeam=home_team,
                awayteam=away_team,
                **kw,
            )
            if days < 0:
                for team, scorer, goals in (
                    (home_team, players["home_center"], 2),
                    (away_team, players["away_center"], 1),
                ):
                    Stat.objects.create(
                        matchup=matchup, team=team, player=scorer, goals=goals
                    )
            return matchup

        def team(name, **kw):
            kw.setdefault("division", d["division"])
            kw.setdefault("season", d["season"])
            kw.setdefault("is_active", True)
            return Team.objects.create(team_name=name, team_color="Red", **kw)

        # Weeks filed without a division, recent and upcoming.
        game(-2, home, away, division=None)
        game(2, home, away, division=None)

        # Teams with no roster at all (a new season before rosters are
        # entered), one of them inactive, with past, present and future games.
        bare_a, bare_b = team("Bare A"), team("Bare B", is_active=False)
        game(-2, bare_a, bare_b)
        game(0, bare_b, bare_a)
        game(2, bare_a, bare_b)

        # Teams missing their division or their season.
        no_division, no_season = team("No Division", division=None), team(
            "No Season", season=None
        )
        for odd in (no_division, no_season):
            Roster.objects.create(
                player=Player.objects.create(first_name="Odd", last_name=odd.team_name),
                team=odd,
                position1=1,
            )
            game(-3, odd, away)
            game(3, home, odd)
        game(-3, home, no_division, division=None)

        # A season with no type and a division with no number.
        odd_season = Season.objects.create(year=today.year, season_type=None)
        odd_division = Division.objects.create(division=None)
        odd_a = team("Odd A", division=odd_division, season=odd_season)
        odd_b = team("Odd B", division=odd_division, season=odd_season)
        Team_Stat.objects.create(
            team=odd_a, division=odd_division, season=odd_season, win=1
        )
        game(-2, odd_a, odd_b, division=odd_division, season=odd_season)
        game(2, odd_a, odd_b, division=odd_division, season=odd_season)

        # Games filed under another division or season than their teams.
        other_division = Division.objects.create(division=5)
        last_year = Season.objects.create(
            year=today.year - 1, season_type=1, standings_from_games=False
        )
        game(-2, home, away, division=other_division)
        game(3, home, away, season=last_year)
        game(-400, home, away, season=last_year)

        # Playoff games: decided in a shootout, a final today, a past final.
        game(
            -1,
            home,
            away,
            is_postseason=True,
            shootout_winner_is_home=False,
            went_to_overtime=True,
        )
        game(0, home, away, is_postseason=True, is_championship=True)
        game(-4, away, home, is_postseason=True, is_championship=True)

        # A game that isn't on any week.
        weekless = MatchUp.objects.create(
            week=None, time=datetime.time(19, 0), hometeam=home, awayteam=away
        )
        Stat.objects.create(
            matchup=weekless, team=home, player=players["home_center"], goals=2
        )

        # Stat rows with no team, no game, a team that wasn't playing, and
        # every number blank.
        outsider = team("Outsider", division=Division.objects.create(division=4))
        scorer = players["home_center"]
        Stat.objects.create(matchup=d["played"], team=None, player=scorer, goals=1)
        Stat.objects.create(
            matchup=d["played"], team=outsider, player=scorer, goals_against=3
        )
        Stat.objects.create(matchup=None, team=home, player=scorer, goals=1)
        Stat.objects.create(
            matchup=d["played"],
            team=home,
            player=players["away_defense"],
            goals=None,
            assists=None,
            goals_against=None,
            empty_net=None,
        )

        # Record rows that lost their team, division or season, and a
        # duplicate row for one team.
        for fields in (
            {"team": None, "division": d["division"], "season": d["season"]},
            {"team": home, "division": None, "season": d["season"]},
            {"team": away, "division": d["division"], "season": None},
            {"team": home, "division": d["division"], "season": d["season"]},
        ):
            Team_Stat.objects.create(win=1, **fields)

        # Roster rows left behind when their player or team was deleted
        # (both are SET_NULL). Done last: update() skips Roster.save().
        Roster.objects.filter(player=players["home_defense"]).update(player=None)
        Roster.objects.filter(player=players["away_goalie"]).update(player=None)
        Roster.objects.filter(player=players["away_defense"]).update(team=None)

    def _urls(self):
        d = self.data
        today = timezone.localdate()
        public = PublicUrlSmokeTest()
        public.data = d
        urls = [
            url
            for label, url in public._urls().items()
            if 200 in PublicUrlSmokeTest.EXPECTED.get(label.split(" (")[0], {200})
        ]
        for delta in (-3, -2, -1, 0, 2, 3):
            day = today + datetime.timedelta(days=delta)
            urls.append(reverse("scoresheet_print", args=[day.isoformat()]))
        for number in (1, 2, 3, 4, 5):
            urls += [reverse("scores", args=[number]), reverse("cups", args=[number])]
        for season in Season.objects.all():
            picker = f"?sunday={season.pk}&monday={season.pk}&wednesday={season.pk}"
            urls += [
                reverse("player_stats", args=[season.pk]),
                reverse("team_standings") + picker,
                reverse("admin:leagues_season_switch_to_computed", args=[season.pk]),
            ]
        for team in Team.objects.all():
            urls += [
                reverse("teams", args=[team.pk]),
                reverse("captain_goalie_update", args=[team.captain_access_code]),
            ]
        urls += [
            reverse("matchup_detail", args=[pk])
            for pk in MatchUp.objects.filter(week__isnull=False).values_list(
                "pk", flat=True
            )
        ]
        urls += [
            reverse("player", args=[pk])
            for pk in Player.objects.values_list("pk", flat=True)
        ]
        manager = reverse("admin:leagues_matchup_schedule_manager")
        urls += [reverse("admin:index"), manager]
        urls += [
            f"{manager}?division_id={pk}"
            for pk in Division.objects.values_list("pk", flat=True)
        ]
        for model in admin.site._registry:
            info = f"admin:{model._meta.app_label}_{model._meta.model_name}"
            changelist = reverse(f"{info}_changelist")
            urls += [changelist, f"{changelist}?all=1&timeframe=all"]
            urls.append(reverse(f"{info}_add"))
            urls += [
                reverse(f"{info}_change", args=[obj.pk])
                for obj in model._default_manager.all()[:80]
            ]
        return urls

    def test_no_page_returns_a_server_error(self):
        client = Client(raise_request_exception=False)
        client.force_login(self.superuser)
        failures = []
        for url in self._urls():
            with sqlite_safe_distinct():
                response = client.get(url, follow=True)
            if response.status_code < 500:
                continue
            where = ""
            exc_info = getattr(response, "exc_info", None)
            if exc_info:
                frames = traceback.extract_tb(exc_info[2])
                ours = [f for f in frames if "site-packages" not in f.filename]
                frame = (ours or frames)[-1]
                where = (
                    f" {exc_info[0].__name__}: {str(exc_info[1])[:120]} "
                    f"({frame.filename.rsplit('/', 2)[-2]}/"
                    f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno})"
                )
            failures.append(f"{url} -> {response.status_code}{where}")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_game_on_no_week_has_no_public_page(self):
        weekless = MatchUp.objects.get(week__isnull=True)
        url = reverse("matchup_detail", args=[weekless.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_admin_home_page_sections_all_render(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "dashboard-section-error")
        self.assertContains(response, "No division set")

    def test_odd_rows_are_left_off_rather_than_breaking_the_page(self):
        # A team with no roster yet still has a page.
        bare = Team.objects.get(team_name="Bare A")
        response = self.client.get(reverse("teams", args=[bare.pk]))
        self.assertContains(response, "Bare A")
        # Division tabs only link to divisions that have a number.
        with sqlite_safe_distinct():
            scores = self.client.get(reverse("scores")).content.decode()
        self.assertNotIn("/scores/None/", scores)
        # A stat with no team has no line on the player page.
        scorer = self.data["players"]["home_center"]
        player_page = self.client.get(reverse("player", args=[scorer.pk]))
        self.assertNotContains(player_page, "/teams/None/")

    def test_labels_of_odd_rows_never_raise(self):
        for model in (MatchUp, Stat, Team_Stat, Roster, Team, Week, Season, Division):
            for obj in model.objects.all():
                with self.subTest(model=model.__name__, pk=obj.pk):
                    self.assertIsInstance(str(obj), str)
