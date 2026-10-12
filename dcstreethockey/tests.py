import importlib

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from core.views import PlayerStatDetailView
from dcstreethockey.context_processors import current_draft_board_url, draft_signup_url
from leagues.models import (
    Division,
    DraftSession,
    Player,
    Roster,
    Season,
    Stat,
    Team,
    Week,
)


class PlayerStatDetailViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.season = Season.objects.create(
            year=2023, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=1)
        self.team = Team.objects.create(
            team_name="Test Team",
            division=self.division,
            season=self.season,
            is_active=True,
        )
        self.player = Player.objects.create(first_name="John", last_name="Doe")
        self.roster = Roster.objects.create(
            player=self.player,
            team=self.team,
            position1=1,
            is_captain=False,
            player_number=None,
        )
        self.stat = Stat.objects.create(
            player=self.player, team=self.team, goals=5, assists=3
        )

    def test_get_queryset(self):
        request = self.factory.get(reverse("player_stats"))
        view = PlayerStatDetailView()
        view.request = request

        queryset = view.get_queryset()
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first(), self.stat)

    def test_get_context_data(self):
        request = self.factory.get(reverse("player_stats"))
        view = PlayerStatDetailView()
        view.request = request
        view.kwargs = {}  # Initialize kwargs as empty dict (default season)

        response = view.get(request)
        context = response.context_data

        self.assertIn("seasons", context)
        self.assertIn("active_season", context)
        self.assertIn("player_stat_list", context)
        self.assertEqual(context["active_season"], 0)

        player_stat_list = context["player_stat_list"]
        self.assertIn(str(self.division), player_stat_list)
        self.assertEqual(len(player_stat_list[str(self.division)]), 1)
        self.assertEqual(player_stat_list[str(self.division)][0]["first_name"], "John")
        self.assertEqual(player_stat_list[str(self.division)][0]["last_name"], "Doe")


class DraftSignupUrlContextProcessorTest(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.season = Season.objects.create(
            year=2024, season_type=3, is_current_season=True
        )
        self.division = Division.objects.create(division=3)

    def _make_request(self):
        return self.factory.get("/")

    def test_returns_none_when_no_open_signup(self):
        ctx = draft_signup_url(self._make_request())
        self.assertIsNone(ctx["draft_signup_url"])

    def test_returns_url_when_signup_is_open(self):
        DraftSession.objects.create(season=self.season, signups_open=True)
        ctx = draft_signup_url(self._make_request())
        self.assertIsNotNone(ctx["draft_signup_url"])
        self.assertIn(str(self.season.pk), ctx["draft_signup_url"])

    def test_returns_none_when_signup_is_closed(self):
        DraftSession.objects.create(season=self.season, signups_open=False)
        ctx = draft_signup_url(self._make_request())
        self.assertIsNone(ctx["draft_signup_url"])


class CurrentDraftBoardUrlContextProcessorTest(TestCase):
    """
    Priority order: open signups > in-progress draft > latest completed
    draft. Tier 1 must always match draft_signup_url's own season, since the
    "Draft Board" and "Sign Up" nav links must never point at different
    seasons for a captain/spectator to notice and be confused by.
    """

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def _make_request(self):
        return self.factory.get("/")

    def test_returns_none_when_no_draft_sessions_exist(self):
        ctx = current_draft_board_url(self._make_request())
        self.assertIsNone(ctx["current_draft_board_url"])

    def test_open_signups_win_even_over_a_newer_completed_season(self):
        # A newer, already-complete season must not outrank an older season
        # whose signups are still open — signups-open is tier 1 regardless
        # of chronology.
        older_open = Season.objects.create(
            year=2025, season_type=3, is_current_season=False
        )
        newer_complete = Season.objects.create(
            year=2026, season_type=3, is_current_season=True
        )
        open_session = DraftSession.objects.create(
            season=older_open, state=DraftSession.STATE_SETUP, signups_open=True
        )
        DraftSession.objects.create(
            season=newer_complete, state=DraftSession.STATE_COMPLETE, signups_open=False
        )

        ctx = current_draft_board_url(self._make_request())

        self.assertIn(str(open_session.pk), ctx["current_draft_board_url"])

    def test_matches_the_same_season_as_draft_signup_url(self):
        season = Season.objects.create(year=2026, season_type=3, is_current_season=True)
        session = DraftSession.objects.create(
            season=season, state=DraftSession.STATE_SETUP, signups_open=True
        )

        board_ctx = current_draft_board_url(self._make_request())
        cache.clear()
        signup_ctx = draft_signup_url(self._make_request())

        self.assertIn(str(session.pk), board_ctx["current_draft_board_url"])
        self.assertIn(str(season.pk), signup_ctx["draft_signup_url"])

    def test_falls_back_to_most_recent_in_progress_draft_when_no_signups_open(self):
        older_complete = Season.objects.create(
            year=2025, season_type=3, is_current_season=False
        )
        newer_in_progress = Season.objects.create(
            year=2026, season_type=3, is_current_season=True
        )
        DraftSession.objects.create(
            season=older_complete, state=DraftSession.STATE_COMPLETE, signups_open=False
        )
        in_progress_session = DraftSession.objects.create(
            season=newer_in_progress,
            state=DraftSession.STATE_ACTIVE,
            signups_open=False,
        )

        ctx = current_draft_board_url(self._make_request())

        self.assertIn(str(in_progress_session.pk), ctx["current_draft_board_url"])

    def test_falls_back_to_latest_completed_draft_when_nothing_else_pending(self):
        older = Season.objects.create(year=2025, season_type=3, is_current_season=False)
        newer = Season.objects.create(year=2026, season_type=3, is_current_season=True)
        DraftSession.objects.create(
            season=older, state=DraftSession.STATE_COMPLETE, signups_open=False
        )
        latest_complete = DraftSession.objects.create(
            season=newer, state=DraftSession.STATE_COMPLETE, signups_open=False
        )

        ctx = current_draft_board_url(self._make_request())

        self.assertIn(str(latest_complete.pk), ctx["current_draft_board_url"])

    def test_flips_over_once_a_newer_season_draft_session_is_created(self):
        season_2026 = Season.objects.create(
            year=2026, season_type=3, is_current_season=True
        )
        session_2026 = DraftSession.objects.create(
            season=season_2026, state=DraftSession.STATE_COMPLETE
        )
        ctx = current_draft_board_url(self._make_request())
        self.assertIn(str(session_2026.pk), ctx["current_draft_board_url"])

        cache.clear()
        season_2027 = Season.objects.create(
            year=2027, season_type=1, is_current_season=False
        )
        session_2027 = DraftSession.objects.create(
            season=season_2027, state=DraftSession.STATE_SETUP, signups_open=True
        )

        ctx = current_draft_board_url(self._make_request())
        self.assertIn(str(session_2027.pk), ctx["current_draft_board_url"])


class ProductionStaticStorageTest(SimpleTestCase):
    """
    Production must serve static files through WhiteNoise's compressed manifest
    storage so CSS/JS ship gzip + brotli compressed. Serving them uncompressed
    (plain ManifestStaticFilesStorage) needlessly inflates Render bandwidth,
    which is now metered in 1GB increments. Guard both the production and the
    shared not-DEBUG configuration against regressing to an uncompressed backend.
    """

    COMPRESSED = "whitenoise.storage.CompressedManifestStaticFilesStorage"

    def test_production_uses_compressed_whitenoise_storage(self):
        production = importlib.import_module("dcstreethockey.settings.production")
        self.assertEqual(production.STORAGES["staticfiles"]["BACKEND"], self.COMPRESSED)

    def test_base_not_debug_block_uses_compressed_whitenoise_storage(self):
        # The not-DEBUG branch of base.py (used by any non-debug deployment)
        # must configure the same compressed backend.
        import inspect

        from dcstreethockey.settings import base

        source = inspect.getsource(base)
        self.assertIn(self.COMPRESSED, source)
        self.assertNotIn(
            "django.contrib.staticfiles.storage.ManifestStaticFilesStorage", source
        )
