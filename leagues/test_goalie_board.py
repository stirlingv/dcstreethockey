"""
Goalie Status Board: public "Can't make it?" and "I can sub" actions,
captain confirmation of volunteers, goalie chips on the schedule and game
pages, and the admin for volunteers and status changes.

Covers leagues/goalie_board.py, the board/captain views in leagues/views.py,
the chips added to core/views/schedule.py, and the related admin.
"""

import datetime

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from leagues.goalie_board import (
    goalie_sides_for_matchups,
    match_listed_goalie,
    over_rate_limit,
    RATE_LIMIT_POSTS,
)
from leagues.models import (
    Division,
    GoalieStatusChange,
    GoalieSubOffer,
    MatchUp,
    Player,
    Roster,
    Season,
    Team,
    Week,
)

CONFIRMED = MatchUp.GOALIE_STATUS_CONFIRMED
SUB_NEEDED = MatchUp.GOALIE_STATUS_SUB_NEEDED
UNCONFIRMED = MatchUp.GOALIE_STATUS_UNCONFIRMED


class BoardFixture(TestCase):
    """One upcoming game. The away side needs a sub, the home side doesn't."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.season = Season.objects.create(
            year=datetime.date.today().year, season_type=1, is_current_season=True
        )
        self.division = Division.objects.create(division=2)
        self.away = self._team("Iced Out", "Blue")
        self.home = self._team("Lumber Kings", "Red")
        self.away_goalie = self._goalie(self.away, "Pat", "Pads")
        self.home_goalie = self._goalie(self.home, "Sam", "Stopper")
        self.date = datetime.date.today() + datetime.timedelta(days=3)
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=self.date
        )
        self.game = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(19, 0),
            awayteam=self.away,
            hometeam=self.home,
            away_goalie_status=SUB_NEEDED,
            home_goalie_status=CONFIRMED,
        )
        self.board_url = reverse("goalie_status_board")

    def _team(self, name, color):
        return Team.objects.create(
            team_name=name,
            team_color=color,
            division=self.division,
            season=self.season,
            is_active=True,
        )

    def _goalie(self, team, first, last):
        player = Player.objects.create(first_name=first, last_name=last)
        Roster.objects.create(
            player=player, team=team, position1=4, is_primary_goalie=True
        )
        return player

    def _report(self, side="home", **data):
        payload = {"name": "Casey Captain", "note": ""}
        payload.update(data)
        return self.client.post(
            reverse("report_sub_needed", args=[self.game.id, side]), payload
        )

    def _offer(self, side="away", **data):
        payload = {"name": "Sam Stopper", "phone": "202-555-0100", "note": ""}
        payload.update(data)
        return self.client.post(
            reverse("offer_sub", args=[self.game.id, side]), payload
        )

    def _reload(self):
        self.game.refresh_from_db()
        return self.game


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class GoalieSidesForMatchupsTest(BoardFixture):
    def test_empty_input(self):
        self.assertEqual(goalie_sides_for_matchups([]), {})

    def test_sides_describe_each_team(self):
        info = goalie_sides_for_matchups([self.game])[self.game.id]
        self.assertEqual(info["away"]["team"], self.away)
        self.assertEqual(info["home"]["team"], self.home)
        self.assertTrue(info["away"]["needs_sub"])
        self.assertEqual(info["away"]["goalie_name"], "")
        self.assertFalse(info["home"]["needs_sub"])
        self.assertEqual(info["home"]["goalie_name"], "Sam Stopper")
        self.assertEqual(info["home"]["status_display"], "Confirmed")
        self.assertFalse(info["home"]["is_sub"])

    def test_named_goalie_from_another_team_is_a_sub(self):
        self.game.home_goalie = self.away_goalie
        self.game.save()
        info = goalie_sides_for_matchups([self.game])[self.game.id]["home"]
        self.assertEqual(info["goalie_name"], "Pat Pads")
        self.assertTrue(info["is_sub"])

    def test_team_without_roster_goalie(self):
        Roster.objects.filter(team=self.home).delete()
        info = goalie_sides_for_matchups([self.game])[self.game.id]["home"]
        self.assertIsNone(info["goalie"])
        self.assertEqual(info["goalie_name"], "")

    def test_volunteers_and_reporter_attached_to_the_right_side(self):
        GoalieStatusChange.objects.create(
            matchup=self.game,
            team=self.away,
            status=SUB_NEEDED,
            reported_by="Pat Pads",
            source=GoalieStatusChange.SOURCE_BOARD,
        )
        offer = GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Alex Wall", phone="1"
        )
        GoalieSubOffer.objects.create(
            matchup=self.game,
            team=self.away,
            name="Declined Dan",
            status=GoalieSubOffer.STATUS_DECLINED,
        )
        info = goalie_sides_for_matchups([self.game])[self.game.id]
        self.assertEqual(info["away"]["volunteers"], [offer])
        self.assertEqual(info["away"]["reported_by"], "Pat Pads")
        self.assertEqual(info["home"]["volunteers"], [])
        self.assertEqual(info["home"]["reported_by"], "")

    def test_reporter_only_shown_while_their_status_stands(self):
        GoalieStatusChange.objects.create(
            matchup=self.game,
            team=self.home,
            status=SUB_NEEDED,
            reported_by="Old Report",
            source=GoalieStatusChange.SOURCE_BOARD,
        )
        # Home is Confirmed now, so the stale Sub Needed report isn't credited.
        info = goalie_sides_for_matchups([self.game])[self.game.id]["home"]
        self.assertEqual(info["reported_by"], "")

    def test_query_count_does_not_grow_with_games(self):
        for i in range(5):
            MatchUp.objects.create(
                week=self.week,
                time=datetime.time(20 + i % 3, 0),
                awayteam=self.home,
                hometeam=self.away,
            )
        games = list(MatchUp.objects.select_related("awayteam", "hometeam"))
        with self.assertNumQueries(4):
            goalie_sides_for_matchups(games)


class MatchListedGoalieTest(BoardFixture):
    def test_matches_a_listed_goalie_ignoring_case(self):
        self.assertEqual(match_listed_goalie("sam STOPPER"), self.home_goalie)

    def test_non_goalie_is_not_matched(self):
        wing = Player.objects.create(first_name="Wally", last_name="Wing")
        Roster.objects.create(player=wing, team=self.home, position1=2)
        self.assertIsNone(match_listed_goalie("Wally Wing"))

    def test_can_play_goalie_flag_counts(self):
        fill_in = Player.objects.create(
            first_name="Fill", last_name="In", can_play_goalie=True
        )
        self.assertEqual(match_listed_goalie("Fill In"), fill_in)

    def test_single_word_or_unknown_name(self):
        self.assertIsNone(match_listed_goalie("Sam"))
        self.assertIsNone(match_listed_goalie("Nobody Here"))


class RateLimitTest(TestCase):
    def test_limit_counts_posts_per_address(self):
        cache.clear()
        from django.test import RequestFactory

        request = RequestFactory().post("/", REMOTE_ADDR="10.0.0.9")
        for _ in range(RATE_LIMIT_POSTS):
            self.assertFalse(over_rate_limit(request))
        self.assertTrue(over_rate_limit(request))
        other = RequestFactory().post("/", REMOTE_ADDR="10.0.0.10")
        self.assertFalse(over_rate_limit(other))


# ---------------------------------------------------------------------------
# Public board page
# ---------------------------------------------------------------------------


class BoardPageTest(BoardFixture):
    def test_page_renders_cards_with_the_right_action_per_side(self):
        response = self.client.get(self.board_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="game-{self.game.id}"')
        # Away needs a sub: volunteer form posts to the away side.
        self.assertContains(response, "I can sub")
        self.assertContains(response, reverse("offer_sub", args=[self.game.id, "away"]))
        # Home is confirmed: report form posts to the home side.
        self.assertContains(response, "Can&rsquo;t make it?")
        self.assertContains(
            response, reverse("report_sub_needed", args=[self.game.id, "home"])
        )
        self.assertNotContains(
            response, reverse("offer_sub", args=[self.game.id, "home"])
        )
        self.assertContains(response, "Sam Stopper")
        self.assertContains(response, "John Romps")
        self.assertContains(response, "1 game needs a goalie sub")

    def test_goalie_name_suggestions_listed(self):
        response = self.client.get(self.board_url)
        self.assertContains(response, 'id="goalie-names"')
        self.assertContains(response, '<option value="Pat Pads">')

    def test_volunteers_and_reporter_shown(self):
        GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Alex Wall", phone="202-555-0199"
        )
        GoalieStatusChange.objects.create(
            matchup=self.game,
            team=self.away,
            status=SUB_NEEDED,
            reported_by="Pat Pads",
            source=GoalieStatusChange.SOURCE_BOARD,
        )
        response = self.client.get(self.board_url)
        self.assertContains(response, "1 volunteer:")
        self.assertContains(response, "Alex Wall")
        self.assertContains(response, "Reported by Pat Pads")
        # Phone numbers are for the captain, never the public page.
        self.assertNotContains(response, "202-555-0199")

    def test_past_games_are_not_listed(self):
        self.week.date = datetime.date.today() - datetime.timedelta(days=1)
        self.week.save()
        response = self.client.get(self.board_url)
        self.assertNotContains(response, f'id="game-{self.game.id}"')


# ---------------------------------------------------------------------------
# Public: "Can't make it?"
# ---------------------------------------------------------------------------


class ReportSubNeededTest(BoardFixture):
    def test_get_not_allowed(self):
        self.assertEqual(
            self.client.get(
                reverse("report_sub_needed", args=[self.game.id, "home"])
            ).status_code,
            405,
        )

    def test_marks_side_sub_needed_and_records_reporter(self):
        self.game.home_goalie = self.away_goalie
        self.game.save()
        response = self._report("home", name="Casey Captain", note="Sam is away")
        self.assertRedirects(
            response,
            f"{self.board_url}#game-{self.game.id}",
            fetch_redirect_response=False,
        )
        game = self._reload()
        self.assertEqual(game.home_goalie_status, SUB_NEEDED)
        self.assertIsNone(game.home_goalie)
        self.assertEqual(game.away_goalie_status, SUB_NEEDED)  # untouched side
        change = GoalieStatusChange.objects.get()
        self.assertEqual(change.team, self.home)
        self.assertEqual(change.reported_by, "Casey Captain")
        self.assertEqual(change.note, "Sam is away")
        self.assertEqual(change.source, GoalieStatusChange.SOURCE_BOARD)

    def test_success_message_shown_on_the_board(self):
        response = self.client.post(
            reverse("report_sub_needed", args=[self.game.id, "home"]),
            {"name": "Casey Captain"},
            follow=True,
        )
        self.assertContains(response, "Thanks, Casey Captain.")
        self.assertContains(response, "Lumber Kings is now marked Sub Needed")
        self.assertContains(response, "John Romps and the captain can see it")

    def test_name_required(self):
        response = self._report("home", name="   ")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._reload().home_goalie_status, CONFIRMED)
        self.assertFalse(GoalieStatusChange.objects.exists())

    def test_honeypot_discards_silently(self):
        response = self._report("home", website="http://spam.example")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._reload().home_goalie_status, CONFIRMED)

    def test_unknown_side_past_and_cancelled_games_rejected(self):
        self.assertEqual(self._report("left").status_code, 404)
        self.game.is_cancelled = True
        self.game.save()
        self.assertEqual(self._report("home").status_code, 404)
        self.game.is_cancelled = False
        self.game.save()
        self.week.date = datetime.date.today() - datetime.timedelta(days=1)
        self.week.save()  # rescheduling resets statuses, so re-confirm first
        MatchUp.objects.filter(pk=self.game.pk).update(home_goalie_status=CONFIRMED)
        self.assertEqual(self._report("home").status_code, 404)
        self.assertEqual(self._reload().home_goalie_status, CONFIRMED)
        self.assertFalse(GoalieStatusChange.objects.exists())

    def test_rate_limit_blocks_a_flood(self):
        for _ in range(RATE_LIMIT_POSTS):
            self._report("home")
        self.game.home_goalie_status = CONFIRMED
        self.game.save()
        response = self.client.post(
            reverse("report_sub_needed", args=[self.game.id, "home"]),
            {"name": "Flood"},
            follow=True,
        )
        self.assertContains(response, "Too many updates")
        self.assertEqual(self._reload().home_goalie_status, CONFIRMED)

    @override_settings(
        GOALIE_CZAR_EMAIL="czar@example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_emails_the_goalie_czar_when_configured(self):
        response = self.client.post(
            reverse("report_sub_needed", args=[self.game.id, "home"]),
            {"name": "Casey Captain"},
            follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["czar@example.com"])
        self.assertIn("Lumber Kings", mail.outbox[0].subject)
        self.assertIn("Casey Captain reported", mail.outbox[0].body)
        self.assertContains(response, "John Romps has been emailed")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_no_email_without_an_address(self):
        self._report("home")
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# Public: "I can sub"
# ---------------------------------------------------------------------------


class OfferSubTest(BoardFixture):
    def test_get_not_allowed(self):
        self.assertEqual(
            self.client.get(
                reverse("offer_sub", args=[self.game.id, "away"])
            ).status_code,
            405,
        )

    def test_listed_goalie_offer_links_the_player(self):
        response = self._offer(name="sam stopper", note="Can do 7pm")
        self.assertRedirects(
            response,
            f"{self.board_url}#game-{self.game.id}",
            fetch_redirect_response=False,
        )
        offer = GoalieSubOffer.objects.get()
        self.assertEqual(offer.player, self.home_goalie)
        self.assertEqual(offer.team, self.away)
        self.assertEqual(offer.phone, "202-555-0100")
        self.assertEqual(offer.note, "Can do 7pm")
        self.assertEqual(offer.status, GoalieSubOffer.STATUS_OFFERED)
        # Offering doesn't change the status: the captain confirms.
        self.assertEqual(self._reload().away_goalie_status, SUB_NEEDED)

    def test_unlisted_name_is_kept_as_text(self):
        self._offer(name="Riley Newcomer")
        offer = GoalieSubOffer.objects.get()
        self.assertIsNone(offer.player)
        self.assertEqual(offer.name, "Riley Newcomer")

    def test_repeat_offer_updates_instead_of_duplicating(self):
        self._offer(name="Sam Stopper", phone="111")
        self._offer(name="Sam Stopper", phone="222")
        self._offer(name="Riley Newcomer", phone="333")
        self._offer(name="riley newcomer", phone="444")
        offers = {o.name.lower(): o.phone for o in GoalieSubOffer.objects.all()}
        self.assertEqual(offers, {"sam stopper": "222", "riley newcomer": "444"})

    def test_name_and_phone_required(self):
        self._offer(phone="")
        self._offer(name="")
        self.assertFalse(GoalieSubOffer.objects.exists())

    def test_side_that_does_not_need_a_sub_gets_no_offer(self):
        response = self.client.post(
            reverse("offer_sub", args=[self.game.id, "home"]),
            {"name": "Sam Stopper", "phone": "1"},
            follow=True,
        )
        self.assertFalse(GoalieSubOffer.objects.exists())
        self.assertContains(response, "marked as needing a sub for this game anymore")

    def test_success_message(self):
        response = self.client.post(
            reverse("offer_sub", args=[self.game.id, "away"]),
            {"name": "Sam Stopper", "phone": "1"},
            follow=True,
        )
        self.assertContains(response, "Thanks, Sam Stopper!")
        self.assertContains(response, "Iced Out&#x27;s captain and John Romps")

    @override_settings(
        GOALIE_CZAR_EMAIL="czar@example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_emails_the_goalie_czar(self):
        self._offer(name="Sam Stopper", phone="202-555-0100")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Goalie sub offered", mail.outbox[0].subject)
        self.assertIn("202-555-0100", mail.outbox[0].body)


# ---------------------------------------------------------------------------
# Captain page: volunteers, confirm, decline
# ---------------------------------------------------------------------------


class CaptainVolunteersTest(BoardFixture):
    def setUp(self):
        super().setUp()
        self.offer = GoalieSubOffer.objects.create(
            matchup=self.game,
            team=self.away,
            player=self.home_goalie,
            name="Sam Stopper",
            phone="202-555-0100",
            note="Can do 7pm",
        )
        self.other = GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Riley Newcomer", phone="1"
        )
        self.code = self.away.captain_access_code
        self.page = reverse("captain_goalie_update", args=[self.code])

    def test_captain_page_lists_volunteers_with_contact_and_actions(self):
        response = self.client.get(self.page)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Volunteers (2)")
        self.assertContains(response, 'href="tel:202-555-0100"')
        self.assertContains(response, "Can do 7pm")
        self.assertContains(
            response, reverse("confirm_sub_offer", args=[self.code, self.offer.id])
        )
        self.assertContains(
            response, reverse("decline_sub_offer", args=[self.code, self.offer.id])
        )

    def test_other_teams_captain_page_does_not_show_them(self):
        response = self.client.get(
            reverse("captain_goalie_update", args=[self.home.captain_access_code])
        )
        self.assertNotContains(response, "Volunteers (")
        self.assertNotContains(response, "202-555-0100")

    def test_confirm_names_the_volunteer_as_goalie(self):
        response = self.client.post(
            reverse("confirm_sub_offer", args=[self.code, self.offer.id]), follow=True
        )
        self.assertContains(response, "Sam Stopper is confirmed in goal")
        game = self._reload()
        self.assertEqual(game.away_goalie, self.home_goalie)
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        self.offer.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.offer.status, GoalieSubOffer.STATUS_CONFIRMED)
        self.assertIsNotNone(self.offer.confirmed_at)
        self.assertEqual(self.other.status, GoalieSubOffer.STATUS_DECLINED)
        change = GoalieStatusChange.objects.get()
        self.assertEqual(change.source, GoalieStatusChange.SOURCE_CAPTAIN)
        self.assertEqual(change.goalie, self.home_goalie)
        # The public board now shows the sub.
        board = self.client.get(self.board_url)
        self.assertContains(board, "Sam Stopper")
        self.assertContains(board, "Sub</span>")

    def test_confirming_an_unlisted_volunteer_creates_a_goalie(self):
        self.client.post(reverse("confirm_sub_offer", args=[self.code, self.other.id]))
        player = Player.objects.get(first_name="Riley", last_name="Newcomer")
        self.assertTrue(player.can_play_goalie)
        self.assertEqual(self._reload().away_goalie, player)

    def test_decline_removes_the_volunteer_only(self):
        self.client.post(reverse("decline_sub_offer", args=[self.code, self.offer.id]))
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, GoalieSubOffer.STATUS_DECLINED)
        self.assertEqual(self._reload().away_goalie_status, SUB_NEEDED)

    def test_only_the_offers_team_captain_can_act(self):
        wrong = self.home.captain_access_code
        self.assertEqual(
            self.client.post(
                reverse("confirm_sub_offer", args=[wrong, self.offer.id])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("decline_sub_offer", args=[wrong, self.offer.id])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("confirm_sub_offer", args=[self.code, self.offer.id])
            ).status_code,
            405,
        )
        self.assertEqual(self._reload().away_goalie_status, SUB_NEEDED)

    def test_confirming_twice_is_harmless(self):
        url = reverse("confirm_sub_offer", args=[self.code, self.offer.id])
        self.client.post(url)
        response = self.client.post(url, follow=True)
        self.assertContains(response, "already handled")
        self.assertEqual(GoalieStatusChange.objects.count(), 1)

    @override_settings(
        GOALIE_CZAR_EMAIL="czar@example.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_captain_status_update_is_logged_and_sub_needed_emailed(self):
        response = self.client.post(
            reverse(
                "update_goalie_status",
                args=[self.home.captain_access_code, self.game.id],
            ),
            {"status": SUB_NEEDED},
        )
        self.assertEqual(response.status_code, 200)
        change = GoalieStatusChange.objects.get(team=self.home)
        self.assertEqual(change.status, SUB_NEEDED)
        self.assertEqual(change.reported_by, "Lumber Kings captain")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Lumber Kings", mail.outbox[0].subject)


# ---------------------------------------------------------------------------
# Chips on the schedule and game pages
# ---------------------------------------------------------------------------


class ScheduleChipsTest(BoardFixture):
    def test_schedule_shows_a_chip_per_side_linking_to_the_board(self):
        response = self.client.get(reverse("schedule"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "gc-sub-needed")
        self.assertContains(response, "Sub needed")
        self.assertContains(response, "gc-confirmed")
        self.assertContains(response, f"{self.board_url}#game-{self.game.id}")
        self.assertContains(response, "1 upcoming game needs a goalie sub")
        self.assertContains(response, "What are the goalie chips?")

    def test_no_alert_when_nothing_is_needed(self):
        self.game.away_goalie_status = UNCONFIRMED
        self.game.save()
        response = self.client.get(reverse("schedule"))
        self.assertNotContains(response, "need a goalie sub")
        self.assertContains(response, "gc-unconfirmed")

    def test_cancelled_game_has_no_chips(self):
        self.game.is_cancelled = True
        self.game.save()
        response = self.client.get(reverse("schedule"))
        self.assertNotContains(response, "goalie-chip")

    def test_game_page_shows_chips_for_an_upcoming_game(self):
        response = self.client.get(reverse("matchup_detail", args=[self.game.id]))
        self.assertContains(response, "goalie-line-detail")
        self.assertContains(response, "Iced Out goalie")
        self.assertContains(response, "Sub needed")

    def test_game_page_hides_chips_for_a_past_game(self):
        self.week.date = datetime.date.today() - datetime.timedelta(days=7)
        self.week.save()
        response = self.client.get(reverse("matchup_detail", args=[self.game.id]))
        self.assertNotContains(response, "goalie-line-detail")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class GoalieBoardAdminTest(BoardFixture):
    def setUp(self):
        super().setUp()
        User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.login(username="admin", password="password")
        self.offer = GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Riley Newcomer", phone="1"
        )

    def test_offers_changelist_and_confirm_action(self):
        url = reverse("admin:leagues_goaliesuboffer_changelist")
        self.assertContains(self.client.get(url), "Riley Newcomer")
        response = self.client.post(
            url,
            {"action": "confirm_offers", "_selected_action": [str(self.offer.id)]},
            follow=True,
        )
        self.assertContains(response, "Confirmed 1 volunteer as goalie")
        game = self._reload()
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        self.assertEqual(game.away_goalie.last_name, "Newcomer")
        self.assertEqual(
            GoalieStatusChange.objects.get().source, GoalieStatusChange.SOURCE_ADMIN
        )

    def test_goalie_status_page_shows_volunteers_inline(self):
        response = self.client.get(
            reverse("admin:leagues_matchupgoaliestatus_change", args=[self.game.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Volunteers from the board")
        self.assertContains(response, "Riley Newcomer")

    def test_status_change_log_is_read_only(self):
        GoalieStatusChange.objects.create(
            matchup=self.game,
            team=self.away,
            status=SUB_NEEDED,
            reported_by="Pat Pads",
            source=GoalieStatusChange.SOURCE_BOARD,
        )
        response = self.client.get(
            reverse("admin:leagues_goaliestatuschange_changelist")
        )
        self.assertContains(response, "Pat Pads")
        self.assertEqual(
            self.client.get(
                reverse("admin:leagues_goaliestatuschange_add")
            ).status_code,
            403,
        )
