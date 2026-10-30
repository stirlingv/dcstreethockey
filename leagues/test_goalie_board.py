"""
Goalie Status Board: public "Yes, confirmed" / "No, need a sub" / "Select a goalie" actions,
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
        self.home_captain = self._player(self.home, "Casey", "Captain", captain=True)
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

    def _player(self, team, first, last, captain=False):
        player = Player.objects.create(first_name=first, last_name=last)
        Roster.objects.create(player=player, team=team, position1=1, is_captain=captain)
        return player

    def _report(self, side="home", **data):
        payload = {"name": "Casey Captain", "note": ""}
        payload.update(data)
        return self.client.post(
            reverse("report_sub_needed", args=[self.game.id, side]), payload
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
        # roster goalies, rosters (for the "who's reporting?" picker),
        # players, offers, status changes: one query each however many games.
        with self.assertNumQueries(5):
            goalie_sides_for_matchups(games)


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
        # Away needs a sub: "Select a goalie" posts to the away side.
        self.assertNotContains(response, "I can sub")
        self.assertContains(response, "Select a goalie")
        self.assertContains(response, "Pat Pads (roster goalie)")
        self.assertContains(
            response, reverse("confirm_goalie", args=[self.game.id, "away"])
        )
        # Home is confirmed: only "Need a sub", posting to the home side.
        self.assertContains(response, "Need a sub")
        self.assertNotContains(response, "Is Sam Stopper playing?")
        self.assertContains(
            response, reverse("report_sub_needed", args=[self.game.id, "home"])
        )
        self.assertNotContains(
            response, reverse("confirm_goalie", args=[self.game.id, "home"])
        )
        self.assertContains(response, "Sam Stopper")
        self.assertContains(response, "John Romps")
        self.assertContains(response, "1 game needs a goalie sub")
        self.assertContains(response, f'href="#game-{self.game.id}"')

    def test_unconfirmed_side_offers_confirm_and_need_a_sub_beside_the_goalie(self):
        # The coordinator asked for the buttons next to the goalie's name
        # with no "Is Sam Stopper playing?" line, so a game fits on a phone
        # screen: the name on the row is the question.
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        response = self.client.get(self.board_url)
        self.assertNotContains(response, "playing?")
        self.assertNotContains(response, "Yes, confirmed")
        self.assertNotContains(response, "No, need a sub")
        self.assertContains(
            response,
            'aria-label="Confirm Sam Stopper is playing for Lumber Kings">Confirm</button>',
        )
        self.assertContains(response, "Need a sub")
        self.assertContains(
            response, reverse("confirm_goalie", args=[self.game.id, "home"])
        )
        self.assertContains(
            response, reverse("report_sub_needed", args=[self.game.id, "home"])
        )
        self.assertContains(response, 'class="side-row side-unconfirmed"')

    def test_confirm_label_falls_back_when_the_team_has_no_roster_goalie(self):
        Roster.objects.filter(team=self.home).delete()
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        response = self.client.get(self.board_url)
        self.assertContains(
            response, 'aria-label="Confirm your goalie is playing for Lumber Kings"'
        )
        self.assertContains(response, "No goalie on roster")
        self.game.home_goalie_status = SUB_NEEDED
        self.game.save()
        response = self.client.get(self.board_url)
        self.assertContains(response, "Select a goalie")
        self.assertNotContains(response, "Sam Stopper (roster goalie)")

    def test_rows_carry_their_status_for_the_colour_stripe(self):
        response = self.client.get(self.board_url)
        self.assertContains(response, 'class="side-row side-needs-sub"')
        self.assertContains(response, 'class="side-row side-confirmed"')
        # A confirmed row's only action is the quiet one.
        self.assertContains(response, 'class="board-btn board-btn-quiet"')
        self.assertNotContains(response, 'class="board-btn board-btn-success"')

    def test_summary_links_to_every_game_needing_a_sub(self):
        other = self._team("Night Owls", "Black")
        self._goalie(other, "Max", "Mitts")
        later = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(20, 0),
            awayteam=other,
            hometeam=self.home,
            away_goalie_status=SUB_NEEDED,
            home_goalie_status=SUB_NEEDED,
        )
        fine = MatchUp.objects.create(
            week=self.week,
            time=datetime.time(21, 0),
            awayteam=self.away,
            hometeam=other,
            away_goalie_status=CONFIRMED,
            home_goalie_status=UNCONFIRMED,
        )
        response = self.client.get(self.board_url)
        self.assertContains(response, "2 games need a goalie sub")
        html = response.content.decode()
        summary = html[
            html.index('class="needs-sub-list"') : html.index("week-section")
        ]
        self.assertIn(f'href="#game-{self.game.id}"', summary)
        self.assertIn(f'href="#game-{later.id}"', summary)
        self.assertNotIn(f'href="#game-{fine.id}"', summary)
        self.assertIn("Iced Out</span>", summary)
        self.assertIn("Night Owls and Lumber Kings</span>", summary)
        self.assertIn(f"{self.date:%a %b %-d} &middot; 7:00 PM", summary)
        self.assertIn("Iced Out @ Lumber Kings", summary)
        self.assertLess(
            summary.index(f"#game-{self.game.id}"), summary.index(f"#game-{later.id}")
        )

    def test_summary_counts_unconfirmed_goalies(self):
        response = self.client.get(self.board_url)
        self.assertNotContains(response, "still unconfirmed")
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        response = self.client.get(self.board_url)
        self.assertContains(response, "1 goalie still unconfirmed")
        self.game.away_goalie_status = UNCONFIRMED
        self.game.save()
        response = self.client.get(self.board_url)
        self.assertContains(response, "2 goalies still unconfirmed")
        self.assertContains(response, "Every game has a goalie")
        self.assertNotContains(response, "need a goalie sub")

    def test_cancelled_game_is_marked_and_has_no_buttons(self):
        self.game.is_cancelled = True
        self.game.save()
        self.game.away_goalie_status = SUB_NEEDED
        self.game.save()
        response = self.client.get(self.board_url)
        self.assertContains(response, f'id="game-{self.game.id}"')
        self.assertContains(response, "Cancelled")
        self.assertContains(response, "Every game has a goalie")
        self.assertNotContains(response, "still unconfirmed")
        self.assertNotContains(response, "Select a goalie")
        self.assertNotContains(response, "Need a sub")
        self.assertNotContains(
            response, reverse("confirm_goalie", args=[self.game.id, "away"])
        )

    def test_goalie_pickers_list_goalies_not_other_players(self):
        response = self.client.get(self.board_url)
        html = response.content.decode()
        picker = html[html.index('name="goalie"') :]
        picker = picker[: picker.index("</select>")]
        self.assertIn(
            f'<option value="{self.away_goalie.id}">Pat Pads</option>', picker
        )
        self.assertNotIn("Casey Captain", picker)
        self.assertIn("Someone else", picker)

    def test_report_form_lists_the_teams_roster(self):
        response = self.client.get(self.board_url)
        self.assertContains(
            response, f'<option value="{self.home_captain.id}">Casey Captain</option>'
        )
        self.assertContains(response, "Someone else")
        # The reporter field says whose name it wants; the coordinator read
        # "Who's reporting?" as "who's the replacement".
        self.assertContains(response, "Your name")
        self.assertNotContains(response, "reporting?")
        self.assertContains(response, "Already found a sub?")

    def test_found_a_goalie_picker_lists_volunteers_first(self):
        GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Alex Wall", phone="1"
        )
        response = self.client.get(self.board_url)
        html = response.content.decode()
        self.assertIn("Volunteered on the board", html)
        self.assertLess(html.index("Alex Wall</option>"), html.index("(roster goalie)"))

    def test_report_form_without_a_roster_asks_for_a_name(self):
        Roster.objects.filter(team=self.home).delete()
        response = self.client.get(self.board_url)
        html = response.content.decode()
        form = html[
            html.index(reverse("report_sub_needed", args=[self.game.id, "home"])) :
        ]
        form = form[: form.index("Mark Sub Needed")]
        self.assertNotIn('name="player_id"', form)
        self.assertIn(
            'name="name" maxlength="100" autocomplete="name" placeholder="First Last">',
            form,
        )

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
            {"player_id": str(self.home_captain.id)},
            follow=True,
        )
        self.assertContains(response, "Thanks, Casey Captain.")
        self.assertContains(response, "Lumber Kings is now marked Sub Needed")
        self.assertContains(response, "John Romps and the captain can see it")

    def test_already_found_a_sub_confirms_the_game_instead(self):
        response = self._report(
            "home",
            sub=str(self.away_goalie.id),
            player_id=str(self.home_captain.id),
            note="Sam is away",
        )
        self.assertEqual(response.status_code, 302)
        game = self._reload()
        self.assertEqual(game.home_goalie_status, CONFIRMED)
        self.assertEqual(game.home_goalie, self.away_goalie)
        change = GoalieStatusChange.objects.get()
        self.assertEqual(change.status, CONFIRMED)
        self.assertEqual(change.goalie, self.away_goalie)
        self.assertEqual(change.reported_by, "Casey Captain")
        self.assertEqual(change.note, "Sub: Pat Pads. Sam is away")
        self.assertEqual(len(mail.outbox), 0)
        board = self.client.get(self.board_url)
        self.assertContains(board, "Pat Pads is confirmed in goal for Lumber Kings")
        self.assertContains(board, "as a sub")
        self.assertContains(board, 'class="goalie-name is-sub">Pat Pads')

    def test_already_found_someone_the_site_does_not_know(self):
        self._report("home", sub="other", sub_name="Riley Newcomer")
        game = self._reload()
        self.assertEqual(game.home_goalie_status, CONFIRMED)
        self.assertIsNone(game.home_goalie)
        self.assertContains(
            self.client.get(self.board_url),
            'class="goalie-name is-sub">Riley Newcomer',
        )

    def test_reporter_is_optional(self):
        response = self.client.post(
            reverse("report_sub_needed", args=[self.game.id, "home"]),
            {"note": "no idea who"},
            follow=True,
        )
        self.assertEqual(self._reload().home_goalie_status, SUB_NEEDED)
        change = GoalieStatusChange.objects.get()
        self.assertEqual(change.reported_by, "")
        self.assertIsNone(change.reported_by_player)
        self.assertContains(response, "Thanks. Lumber Kings is now marked Sub Needed")
        self.assertNotContains(response, "Reported by")

    def test_reporter_picked_from_the_roster_is_linked(self):
        self._report("home", player_id=str(self.home_captain.id), name="ignored")
        change = GoalieStatusChange.objects.get()
        self.assertEqual(change.reported_by_player, self.home_captain)
        self.assertEqual(change.reported_by, "Casey Captain")
        self.assertContains(
            self.client.get(self.board_url), "Reported by Casey Captain"
        )

    def test_someone_else_types_a_name(self):
        self._report("home", player_id="other", name="Guest Gary")
        change = GoalieStatusChange.objects.get()
        self.assertIsNone(change.reported_by_player)
        self.assertEqual(change.reported_by, "Guest Gary")

    def test_a_player_from_another_team_is_not_accepted_as_reporter(self):
        self._report("home", player_id=str(self.away_goalie.id), name="")
        change = GoalieStatusChange.objects.get()
        self.assertIsNone(change.reported_by_player)
        self.assertEqual(change.reported_by, "")

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
# Public: "Yes, confirmed" / "can play after all"
# ---------------------------------------------------------------------------


class ConfirmGoalieTest(BoardFixture):
    def _confirm(self, side="home", **data):
        return self.client.post(
            reverse("confirm_goalie", args=[self.game.id, side]), data
        )

    def test_get_not_allowed(self):
        response = self.client.get(
            reverse("confirm_goalie", args=[self.game.id, "home"])
        )
        self.assertEqual(response.status_code, 405)

    def test_confirms_an_unconfirmed_side_in_one_tap(self):
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        response = self._confirm("home")
        self.assertRedirects(
            response,
            f"{self.board_url}#game-{self.game.id}",
            fetch_redirect_response=False,
        )
        game = self._reload()
        self.assertEqual(game.home_goalie_status, CONFIRMED)
        self.assertIsNone(game.home_goalie)  # roster goalie stands
        change = GoalieStatusChange.objects.get()
        self.assertEqual(change.team, self.home)
        self.assertEqual(change.status, CONFIRMED)
        self.assertEqual(change.goalie, self.home_goalie)
        self.assertEqual(change.reported_by, "")
        self.assertEqual(change.source, GoalieStatusChange.SOURCE_BOARD)
        board = self.client.get(self.board_url)
        self.assertContains(board, "Sam Stopper is confirmed in goal for Lumber Kings")

    def test_unconfirmed_row_confirms_without_opening_a_form(self):
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        response = self.client.get(self.board_url)
        self.assertContains(response, 'class="board-tap"')
        # The Sub Needed row asks who's in goal instead.
        self.assertContains(response, "Who&rsquo;s in goal for Iced Out")

    def test_confirming_a_sub_needed_side_releases_open_volunteers(self):
        kept = GoalieSubOffer.objects.create(
            matchup=self.game,
            team=self.away,
            name="Alex Wall",
            phone="202-555-0199",
            status=GoalieSubOffer.STATUS_DECLINED,
        )
        open_offer = GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Jo Glove", phone="202-555-0198"
        )
        other_side = GoalieSubOffer.objects.create(
            matchup=self.game, team=self.home, name="Sam Stopper", phone="1"
        )
        response = self._confirm("away")
        self.assertEqual(response.status_code, 302)
        game = self._reload()
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        open_offer.refresh_from_db()
        self.assertEqual(open_offer.status, GoalieSubOffer.STATUS_DECLINED)
        kept.refresh_from_db()
        self.assertEqual(kept.status, GoalieSubOffer.STATUS_DECLINED)
        other_side.refresh_from_db()
        self.assertEqual(other_side.status, GoalieSubOffer.STATUS_OFFERED)
        board = self.client.get(self.board_url)
        self.assertContains(board, "Pat Pads is confirmed in goal for Iced Out")
        self.assertContains(board, "1 other volunteer marked not needed")
        self.assertNotContains(board, "Jo Glove")

    def test_found_a_goalie_picks_a_volunteer(self):
        offer = GoalieSubOffer.objects.create(
            matchup=self.game,
            team=self.away,
            player=self.home_goalie,
            name="Sam Stopper",
            phone="1",
        )
        other = GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Alex Wall", phone="2"
        )
        response = self._confirm(
            "away",
            goalie=f"offer-{offer.id}",
            player_id=str(self.away_goalie.id),
        )
        self.assertEqual(response.status_code, 302)
        game = self._reload()
        self.assertEqual(game.away_goalie, self.home_goalie)
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        offer.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(offer.status, GoalieSubOffer.STATUS_CONFIRMED)
        self.assertEqual(other.status, GoalieSubOffer.STATUS_DECLINED)
        change = GoalieStatusChange.objects.get()
        self.assertEqual(change.goalie, self.home_goalie)
        self.assertEqual(change.reported_by_player, self.away_goalie)
        self.assertEqual(change.note, "Sub: Sam Stopper")
        board = self.client.get(self.board_url)
        self.assertContains(board, "Sam Stopper is confirmed in goal for Iced Out")
        self.assertContains(board, "1 other volunteer marked not needed")
        self.assertContains(board, 'class="goalie-name is-sub">Sam Stopper')

    def test_found_a_goalie_picks_a_listed_goalie(self):
        self._confirm("away", goalie=str(self.home_goalie.id))
        game = self._reload()
        self.assertEqual(game.away_goalie, self.home_goalie)
        self.assertEqual(game.away_goalie_status, CONFIRMED)

    def test_listed_goalie_who_also_volunteered_confirms_their_offer(self):
        offer = GoalieSubOffer.objects.create(
            matchup=self.game,
            team=self.away,
            player=self.home_goalie,
            name="Sam Stopper",
            phone="1",
        )
        self._confirm("away", goalie=str(self.home_goalie.id))
        offer.refresh_from_db()
        self.assertEqual(offer.status, GoalieSubOffer.STATUS_CONFIRMED)
        self.assertEqual(self._reload().away_goalie, self.home_goalie)

    def test_found_a_goalie_someone_else_is_kept_by_name(self):
        self._confirm("away", goalie="other", goalie_name="Riley Newcomer")
        game = self._reload()
        self.assertIsNone(game.away_goalie)
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        self.assertFalse(Player.objects.filter(last_name="Newcomer").exists())
        offer = GoalieSubOffer.objects.get()
        self.assertEqual(offer.status, GoalieSubOffer.STATUS_CONFIRMED)
        self.assertEqual(offer.name, "Riley Newcomer")
        board = self.client.get(self.board_url)
        self.assertContains(board, 'class="goalie-name is-sub">Riley Newcomer')

    def test_roster_goalie_after_all(self):
        GoalieSubOffer.objects.create(
            matchup=self.game, team=self.away, name="Alex Wall", phone="1"
        )
        self._confirm("away", goalie="roster")
        game = self._reload()
        self.assertIsNone(game.away_goalie)
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        self.assertEqual(
            GoalieSubOffer.objects.get().status, GoalieSubOffer.STATUS_DECLINED
        )
        self.assertContains(self.client.get(self.board_url), "Pat Pads")

    def test_unknown_choice_falls_back_to_the_roster_goalie(self):
        self._confirm("away", goalie="offer-999")
        self._confirm("home", goalie="999999")
        game = self._reload()
        self.assertIsNone(game.away_goalie)
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        self.assertIsNone(game.home_goalie)

    def test_keeps_an_arranged_sub_in_goal(self):
        sub = Player.objects.create(first_name="Robin", last_name="Relief")
        self.game.home_goalie = sub
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        self._confirm("home")
        game = self._reload()
        self.assertEqual(game.home_goalie, sub)
        self.assertEqual(game.home_goalie_status, CONFIRMED)
        self.assertEqual(GoalieStatusChange.objects.get().goalie, sub)

    def test_honeypot_discards_silently(self):
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        self._confirm("home", website="http://spam")
        self.assertEqual(self._reload().home_goalie_status, UNCONFIRMED)
        self.assertFalse(GoalieStatusChange.objects.exists())

    def test_unknown_side_past_and_cancelled_games_rejected(self):
        self.assertEqual(self._confirm("left").status_code, 404)
        self.game.is_cancelled = True
        self.game.save()
        self.assertEqual(self._confirm("home").status_code, 404)
        self.game.is_cancelled = False
        self.game.save()
        self.week.date = datetime.date.today() - datetime.timedelta(days=1)
        self.week.save()
        self.assertEqual(self._confirm("home").status_code, 404)

    def test_rate_limit_blocks_a_flood(self):
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        for _ in range(RATE_LIMIT_POSTS):
            self._confirm("home")
        self.game.home_goalie_status = UNCONFIRMED
        self.game.save()
        self._confirm("home")
        self.assertEqual(self._reload().home_goalie_status, UNCONFIRMED)


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

    def test_confirming_an_unlisted_volunteer_shows_them_by_name(self):
        self.client.post(reverse("confirm_sub_offer", args=[self.code, self.other.id]))
        self.assertFalse(Player.objects.filter(last_name="Newcomer").exists())
        game = self._reload()
        self.assertIsNone(game.away_goalie)
        self.assertEqual(game.away_goalie_status, CONFIRMED)
        board = self.client.get(self.board_url)
        self.assertContains(board, "Riley Newcomer")
        self.assertContains(board, 'class="goalie-name is-sub">Riley Newcomer')
        self.assertNotContains(board, 'class="goalie-name ">Pat Pads')
        page = self.client.get(self.page)
        self.assertContains(page, "Riley Newcomer (Sub)")

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
        self.assertContains(response, "Goalie confirmed")
        self.assertContains(response, f"{self.board_url}#game-{self.game.id}")
        self.assertContains(response, "1 upcoming game needs a goalie sub")
        self.assertContains(response, "What are the goalie chips?")
        # The explainer names the board's buttons as they are today.
        self.assertContains(response, "<strong>Confirm</strong>")
        self.assertNotContains(response, "Yes, confirmed")

    def test_chips_sit_under_their_team_in_the_teams_row(self):
        # The coordinator found a game took half a phone screen: the chips
        # were a full-width row of their own, labelled "Away goalie" / "Home
        # goalie" so the reader had to map them back to the teams. Now each
        # chip is in the teams grid, directly under its team, and the team
        # itself is the label.
        html = self.client.get(reverse("schedule")).content.decode()
        self.assertNotIn("Away goalie", html)
        self.assertNotIn("Home goalie", html)
        self.assertNotIn('class="goalie-line"', html)
        teams = html[html.index('class="game-teams"') :]
        teams = teams[: teams.index("</div>")]
        order = [
            teams.index("Iced Out</span>"),
            teams.index("Lumber Kings</span>"),
            teams.index("gc-sub-needed"),
            teams.index("game-at-spacer"),
            teams.index("gc-confirmed"),
        ]
        self.assertEqual(order, sorted(order))

    def test_record_is_its_own_span_so_it_never_wraps_mid_number(self):
        response = self.client.get(reverse("schedule"))
        self.assertContains(
            response,
            '<span class="game-team-name">Iced Out</span>\n'
            '                            <span class="game-team-record">(0-0-0-0)</span>',
        )

    def test_no_alert_when_nothing_is_needed(self):
        self.game.away_goalie_status = UNCONFIRMED
        self.game.save()
        response = self.client.get(reverse("schedule"))
        self.assertNotContains(response, "need a goalie sub")
        self.assertContains(response, "gc-unconfirmed")
        self.assertContains(response, "Goalie unconfirmed")

    def test_team_page_schedule_tab_uses_the_same_compact_row(self):
        response = self.client.get(reverse("teams", args=[self.home.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "assets/css/schedule.css")
        self.assertContains(response, 'class="game-teams"')
        # Chips are a schedule-page feature; the team page has no board link.
        self.assertNotContains(response, "goalie-chip")

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
        # Riley isn't a player yet, so the game shows the name without a link.
        self.assertIsNone(game.away_goalie)
        self.assertContains(self.client.get(self.board_url), "Riley Newcomer")
        self.assertEqual(
            GoalieStatusChange.objects.get().source, GoalieStatusChange.SOURCE_ADMIN
        )

    def test_linking_a_player_to_a_confirmed_offer_names_them_as_goalie(self):
        offer = GoalieSubOffer.objects.create(
            matchup=self.game,
            team=self.away,
            name="Riley Newcomer",
            phone="1",
            status=GoalieSubOffer.STATUS_CONFIRMED,
        )
        riley = Player.objects.create(
            first_name="Riley", last_name="Newcomer", can_play_goalie=True
        )
        response = self.client.post(
            reverse("admin:leagues_goaliesuboffer_change", args=[offer.id]),
            {
                "matchup": self.game.id,
                "team": self.away.id,
                "player": riley.id,
                "name": "Riley Newcomer",
                "phone": "1",
                "note": "",
                "status": GoalieSubOffer.STATUS_CONFIRMED,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._reload().away_goalie, riley)
        self.assertContains(response, "now named as goalie")

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
