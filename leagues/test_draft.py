"""
Unit and integration tests for the Wednesday Draft League draft functionality.

Coverage:
  Models     – DraftTeam.save, DraftSession.current_pick,
               DraftSession.pick_order_for_round (snake, randomized, continuity)
  Views      – draft_signup, board views, draw_positions, advance_state,
               make_pick, undo_last_pick, swap_pick, reset_draft
  Logic      – _process_auto_captain_picks, _session_state_payload
  Validation – captain cross-team guard, goalie-per-team limit,
               already-drafted, wrong-turn, state guards, token auth
"""

import datetime
import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse

from leagues.models import (
    DraftPick,
    DraftRound,
    DraftSession,
    DraftTeam,
    Season,
    SeasonSignup,
)
from leagues.draft_views import _process_auto_captain_picks, _session_state_payload


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class DraftTestBase(TestCase):
    """
    Per-test fixture factory.  Every test gets a clean DB state with:
      • 1 Season  (year=current, season_type=4 "Winter" — unlikely to collide)
      • 1 DraftSession  (3 teams, 3 rounds, SETUP, signups open)
      • 3 captain SeasonSignups  →  3 DraftTeams (draft positions 1–3 drawn)
      • 6 regular player SeasonSignups
      • 2 goalie SeasonSignups
    """

    def setUp(self):
        self.season = Season.objects.create(
            year=datetime.date.today().year,
            season_type=4,
            is_current_season=False,
        )
        self.session = DraftSession.objects.create(
            season=self.season,
            num_teams=3,
            num_rounds=3,
            state=DraftSession.STATE_SETUP,
            signups_open=True,
        )

        # Captain signups
        self.cap1 = SeasonSignup.objects.create(
            season=self.season,
            first_name="Alice",
            last_name="Alpha",
            email="alice@test.com",
            primary_position=SeasonSignup.POSITION_CENTER,
            secondary_position=SeasonSignup.POSITION_WING,
            captain_interest=SeasonSignup.CAPTAIN_YES,
        )
        self.cap2 = SeasonSignup.objects.create(
            season=self.season,
            first_name="Bob",
            last_name="Beta",
            email="bob@test.com",
            primary_position=SeasonSignup.POSITION_WING,
            secondary_position=SeasonSignup.POSITION_CENTER,
            captain_interest=SeasonSignup.CAPTAIN_YES,
        )
        self.cap3 = SeasonSignup.objects.create(
            season=self.season,
            first_name="Carol",
            last_name="Gamma",
            email="carol@test.com",
            primary_position=SeasonSignup.POSITION_DEFENSE,
            secondary_position=SeasonSignup.POSITION_ONE_THING,
            captain_interest=SeasonSignup.CAPTAIN_YES,
        )

        # Teams — positions already drawn (1, 2, 3)
        self.team1 = DraftTeam.objects.create(
            session=self.session, captain=self.cap1, draft_position=1
        )
        self.team2 = DraftTeam.objects.create(
            session=self.session, captain=self.cap2, draft_position=2
        )
        self.team3 = DraftTeam.objects.create(
            session=self.session, captain=self.cap3, draft_position=3
        )

        # Regular player signups
        _positions = [
            SeasonSignup.POSITION_CENTER,
            SeasonSignup.POSITION_WING,
            SeasonSignup.POSITION_DEFENSE,
            SeasonSignup.POSITION_CENTER,
            SeasonSignup.POSITION_WING,
            SeasonSignup.POSITION_DEFENSE,
        ]
        self.players = [
            SeasonSignup.objects.create(
                season=self.season,
                first_name=f"Player{i}",
                last_name=f"Test{i}",
                email=f"player{i}@test.com",
                primary_position=_positions[i - 1],
                secondary_position=SeasonSignup.POSITION_ONE_THING,
                captain_interest=SeasonSignup.CAPTAIN_NO,
            )
            for i in range(1, 7)
        ]

        # Goalie signups
        self.goalie1 = SeasonSignup.objects.create(
            season=self.season,
            first_name="Gary",
            last_name="Goalie",
            email="gary@test.com",
            primary_position=SeasonSignup.POSITION_GOALIE,
            secondary_position=SeasonSignup.POSITION_ONE_THING,
            captain_interest=SeasonSignup.CAPTAIN_NO,
        )
        self.goalie2 = SeasonSignup.objects.create(
            season=self.season,
            first_name="Greta",
            last_name="Goal",
            email="greta@test.com",
            primary_position=SeasonSignup.POSITION_GOALIE,
            secondary_position=SeasonSignup.POSITION_ONE_THING,
            captain_interest=SeasonSignup.CAPTAIN_NO,
        )

        self.client = Client()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _activate(self):
        self.session.state = DraftSession.STATE_ACTIVE
        self.session.save(update_fields=["state"])

    def _complete(self):
        self.session.state = DraftSession.STATE_COMPLETE
        self.session.save(update_fields=["state"])

    def _make_pick(self, team, signup, round_number, pick_number, auto=False):
        return DraftPick.objects.create(
            session=self.session,
            team=team,
            signup=signup,
            round_number=round_number,
            pick_number=pick_number,
            is_auto_captain=auto,
        )

    def _post_pick(self, signup_pk, *, captain_token=None, commissioner_token=None):
        data = {"signup_pk": signup_pk}
        if captain_token:
            data["captain_token"] = str(captain_token)
        if commissioner_token:
            data["commissioner_token"] = str(commissioner_token)
        return self.client.post(
            reverse("draft_make_pick", args=[self.session.pk]), data
        )


# ---------------------------------------------------------------------------
# Model: DraftTeam
# ---------------------------------------------------------------------------


class DraftTeamModelTests(DraftTestBase):
    def test_team_name_auto_generated_from_captain(self):
        new_signup = SeasonSignup.objects.create(
            season=self.season,
            first_name="Zara",
            last_name="Zeta",
            email="zara@test.com",
            primary_position=SeasonSignup.POSITION_WING,
            secondary_position=SeasonSignup.POSITION_ONE_THING,
            captain_interest=SeasonSignup.CAPTAIN_NO,
        )
        # Create a second session to avoid unique_together conflict
        session2 = DraftSession.objects.create(
            season=Season.objects.create(
                year=datetime.date.today().year, season_type=3, is_current_season=False
            ),
            num_teams=1,
            num_rounds=1,
        )
        team = DraftTeam.objects.create(
            session=session2, captain=new_signup, draft_position=1
        )
        self.assertEqual(team.team_name, "Zara's Team")

    def test_team_name_preserved_when_provided(self):
        new_signup = SeasonSignup.objects.create(
            season=self.season,
            first_name="Zara",
            last_name="Zeta",
            email="zara@test.com",
            primary_position=SeasonSignup.POSITION_WING,
            secondary_position=SeasonSignup.POSITION_ONE_THING,
            captain_interest=SeasonSignup.CAPTAIN_NO,
        )
        session2 = DraftSession.objects.create(
            season=Season.objects.create(
                year=datetime.date.today().year, season_type=3, is_current_season=False
            ),
            num_teams=1,
            num_rounds=1,
        )
        team = DraftTeam.objects.create(
            session=session2,
            captain=new_signup,
            team_name="The Rockets",
            draft_position=1,
        )
        self.assertEqual(team.team_name, "The Rockets")

    def test_existing_teams_have_auto_generated_names(self):
        # Teams created in setUp without explicit team_name should be auto-named
        self.assertEqual(self.team1.team_name, "Alice's Team")
        self.assertEqual(self.team2.team_name, "Bob's Team")
        self.assertEqual(self.team3.team_name, "Carol's Team")


# ---------------------------------------------------------------------------
# Model: DraftSession.current_pick
# ---------------------------------------------------------------------------


class DraftSessionCurrentPickTests(DraftTestBase):
    def test_no_picks_returns_round_1_index_0(self):
        self._activate()
        self.assertEqual(self.session.current_pick, (1, 0))

    def test_after_one_pick_returns_round_1_index_1(self):
        self._activate()
        self._make_pick(self.team1, self.players[0], 1, 0)
        self.assertEqual(self.session.current_pick, (1, 1))

    def test_after_full_first_round_returns_round_2_index_0(self):
        self._activate()
        self._make_pick(self.team1, self.players[0], 1, 0)
        self._make_pick(self.team2, self.players[1], 1, 1)
        self._make_pick(self.team3, self.players[2], 1, 2)
        self.assertEqual(self.session.current_pick, (2, 0))

    def test_draft_complete_returns_none(self):
        self._activate()
        # Fill all 9 slots (3 teams × 3 rounds)
        all_signups = self.players[:6] + [self.cap1, self.cap2, self.cap3]
        slot = 0
        for r in range(1, 4):
            for p in range(3):
                self._make_pick(
                    [self.team1, self.team2, self.team3][p],
                    all_signups[slot],
                    r,
                    p,
                )
                slot += 1
        self.assertIsNone(self.session.current_pick)


# ---------------------------------------------------------------------------
# Model: DraftSession.pick_order_for_round (snake + randomized)
# ---------------------------------------------------------------------------


class DraftPickOrderTests(DraftTestBase):
    def test_round_1_forward_order(self):
        order = self.session.pick_order_for_round(1)
        self.assertEqual(order, [self.team1.pk, self.team2.pk, self.team3.pk])

    def test_round_2_snake_reversed(self):
        order = self.session.pick_order_for_round(2)
        self.assertEqual(order, [self.team3.pk, self.team2.pk, self.team1.pk])

    def test_round_3_snake_forward_again(self):
        order = self.session.pick_order_for_round(3)
        self.assertEqual(order, [self.team1.pk, self.team2.pk, self.team3.pk])

    def test_randomized_round_is_deterministic(self):
        DraftRound.objects.create(
            session=self.session,
            round_number=2,
            order_type=DraftRound.ORDER_RANDOMIZED,
        )
        order_a = self.session.pick_order_for_round(2)
        order_b = self.session.pick_order_for_round(2)
        self.assertEqual(order_a, order_b)
        # Must contain all three teams
        self.assertCountEqual(order_a, [self.team1.pk, self.team2.pk, self.team3.pk])

    def test_snake_continuity_after_randomized_round(self):
        """
        Round 2 is randomized.  Round 3's snake parity should be as if
        round 2 never happened (effective_round = 3 - 1 = 2, even → reversed).
        """
        DraftRound.objects.create(
            session=self.session,
            round_number=2,
            order_type=DraftRound.ORDER_RANDOMIZED,
        )
        order = self.session.pick_order_for_round(3)
        self.assertEqual(order, [self.team3.pk, self.team2.pk, self.team1.pk])

    def test_round_3_without_randomized_round_is_forward(self):
        """
        Without any randomized rounds, round 3 (odd effective round) is forward.
        """
        order = self.session.pick_order_for_round(3)
        self.assertEqual(order, [self.team1.pk, self.team2.pk, self.team3.pk])


# ---------------------------------------------------------------------------
# View: draft_signup
# ---------------------------------------------------------------------------


class DraftSignupViewTests(DraftTestBase):
    def _signup_url(self):
        return reverse("draft_signup", args=[self.season.pk])

    def _valid_post_data(self, first="New", last="Player"):
        return {
            "first_name": first,
            "last_name": last,
            "email": "new@test.com",
            "primary_position": SeasonSignup.POSITION_WING,
            "secondary_position": SeasonSignup.POSITION_CENTER,
            "captain_interest": SeasonSignup.CAPTAIN_NO,
        }

    def test_get_renders_signup_form(self):
        response = self.client.get(self._signup_url())
        self.assertEqual(response.status_code, 200)

    def test_valid_post_creates_signup(self):
        before = SeasonSignup.objects.filter(season=self.season).count()
        self.client.post(self._signup_url(), self._valid_post_data())
        self.assertEqual(
            SeasonSignup.objects.filter(season=self.season).count(), before + 1
        )

    def test_post_missing_name_shows_error(self):
        data = self._valid_post_data()
        data["first_name"] = ""
        response = self.client.post(self._signup_url(), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "required")
        self.assertFalse(
            SeasonSignup.objects.filter(
                last_name=data["last_name"], first_name=""
            ).exists()
        )

    def test_same_name_different_email_is_allowed(self):
        self.client.post(self._signup_url(), self._valid_post_data())
        data = self._valid_post_data()
        data["email"] = "other@test.com"
        response = self.client.post(self._signup_url(), data)
        # No error — two players with the same name but different emails is valid
        self.assertEqual(
            SeasonSignup.objects.filter(
                season=self.season, first_name="New", last_name="Player"
            ).count(),
            2,
        )

    def test_post_duplicate_email_shows_error(self):
        self.client.post(self._signup_url(), self._valid_post_data())
        # Same email, different name
        data = self._valid_post_data(first="Different", last="Person")
        response = self.client.post(self._signup_url(), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "email address is already signed up")

    def test_signups_closed_shows_closed_page(self):
        self.session.signups_open = False
        self.session.save(update_fields=["signups_open"])
        response = self.client.get(self._signup_url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "leagues/draft_signup_closed.html")


# ---------------------------------------------------------------------------
# Views: board pages render
# ---------------------------------------------------------------------------


class BoardViewTests(DraftTestBase):
    def test_spectator_view_renders(self):
        response = self.client.get(
            reverse("draft_board_spectator", args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_commissioner_view_renders(self):
        response = self.client.get(
            reverse(
                "draft_board_commissioner",
                args=[self.session.pk, self.session.commissioner_token],
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_commissioner_wrong_token_returns_404(self):
        import uuid

        response = self.client.get(
            reverse(
                "draft_board_commissioner",
                args=[self.session.pk, uuid.uuid4()],
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_captain_view_renders(self):
        response = self.client.get(
            reverse(
                "draft_board_captain",
                args=[self.session.pk, self.team1.captain_token],
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_captain_wrong_token_returns_404(self):
        import uuid

        response = self.client.get(
            reverse(
                "draft_board_captain",
                args=[self.session.pk, uuid.uuid4()],
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_captain_portal_renders(self):
        response = self.client.get(
            reverse("draft_captain_portal", args=[self.session.pk])
        )
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# View: draw_positions
# ---------------------------------------------------------------------------


class DrawPositionsViewTests(DraftTestBase):
    def setUp(self):
        super().setUp()
        # Reset positions so draw tests start clean
        self.session.teams.update(draft_position=None)
        # Mock channel layer used inside draw_positions
        mock_layer = MagicMock()
        self._layer_patcher = patch(
            "channels.layers.get_channel_layer", return_value=mock_layer
        )
        self._async_patcher = patch(
            "asgiref.sync.async_to_sync",
            side_effect=lambda f: (lambda *a, **kw: None),
        )
        self._layer_patcher.start()
        self._async_patcher.start()

    def tearDown(self):
        self._layer_patcher.stop()
        self._async_patcher.stop()
        super().tearDown()

    def _draw_url(self):
        return reverse(
            "draft_draw_positions",
            args=[self.session.pk, self.session.commissioner_token],
        )

    def test_draw_assigns_positions_to_all_teams(self):
        self.client.post(self._draw_url())
        positions = list(self.session.teams.values_list("draft_position", flat=True))
        self.assertFalse(any(p is None for p in positions))
        self.assertCountEqual(positions, [1, 2, 3])

    def test_draw_from_setup_auto_advances_to_draw_state(self):
        self.assertEqual(self.session.state, DraftSession.STATE_SETUP)
        self.client.post(self._draw_url())
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, DraftSession.STATE_DRAW)

    def test_draw_closes_signups(self):
        self.assertTrue(self.session.signups_open)
        self.client.post(self._draw_url())
        self.session.refresh_from_db()
        self.assertFalse(self.session.signups_open)

    def test_draw_wrong_state_returns_400(self):
        self._activate()
        response = self.client.post(self._draw_url())
        self.assertEqual(response.status_code, 400)

    def test_draw_wrong_token_returns_404(self):
        import uuid

        url = reverse("draft_draw_positions", args=[self.session.pk, uuid.uuid4()])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_draw_returns_reveal_order_sorted_by_position(self):
        response = self.client.post(self._draw_url())
        data = json.loads(response.content)
        positions = [item["position"] for item in data["reveal_order"]]
        self.assertEqual(positions, sorted(positions))


# ---------------------------------------------------------------------------
# View: advance_state
# ---------------------------------------------------------------------------


class AdvanceStateViewTests(DraftTestBase):
    def setUp(self):
        super().setUp()
        self._broadcast_patcher = patch("leagues.draft_views._broadcast_state_change")
        self._broadcast_patcher.start()

    def tearDown(self):
        self._broadcast_patcher.stop()
        super().tearDown()

    def _advance_url(self):
        return reverse(
            "draft_advance_state",
            args=[self.session.pk, self.session.commissioner_token],
        )

    def test_setup_to_draw(self):
        self.client.post(self._advance_url())
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, DraftSession.STATE_DRAW)

    def test_draw_to_active(self):
        self.session.state = DraftSession.STATE_DRAW
        self.session.save(update_fields=["state"])
        self.client.post(self._advance_url())
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, DraftSession.STATE_ACTIVE)

    def test_draw_to_active_closes_signups(self):
        self.session.state = DraftSession.STATE_DRAW
        self.session.signups_open = True
        self.session.save(update_fields=["state", "signups_open"])
        self.client.post(self._advance_url())
        self.session.refresh_from_db()
        self.assertFalse(self.session.signups_open)

    def test_active_to_paused(self):
        self._activate()
        self.client.post(self._advance_url())
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, DraftSession.STATE_PAUSED)

    def test_paused_to_active(self):
        self.session.state = DraftSession.STATE_PAUSED
        self.session.save(update_fields=["state"])
        self.client.post(self._advance_url())
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, DraftSession.STATE_ACTIVE)

    def test_complete_state_has_no_transition(self):
        self._complete()
        response = self.client.post(self._advance_url())
        self.assertEqual(response.status_code, 400)

    def test_wrong_token_returns_404(self):
        import uuid

        url = reverse("draft_advance_state", args=[self.session.pk, uuid.uuid4()])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# View: make_pick — auth, turn order, and all validations
# ---------------------------------------------------------------------------


class MakePickViewTests(DraftTestBase):
    def setUp(self):
        super().setUp()
        self._activate()
        self._broadcast_patcher = patch("leagues.draft_views._broadcast_state_change")
        self._broadcast_patcher.start()

    def tearDown(self):
        self._broadcast_patcher.stop()
        super().tearDown()

    def test_captain_makes_valid_pick(self):
        # Round 1, slot 0 → team1's turn
        response = self._post_pick(
            self.players[0].pk, captain_token=self.team1.captain_token
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertTrue(
            DraftPick.objects.filter(
                session=self.session, signup=self.players[0], team=self.team1
            ).exists()
        )

    def test_captain_cannot_pick_out_of_turn(self):
        # team2's captain tries to pick when it is team1's turn
        response = self._post_pick(
            self.players[0].pk, captain_token=self.team2.captain_token
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("not your turn", data["error"])

    def test_commissioner_can_make_pick(self):
        response = self._post_pick(
            self.players[0].pk,
            commissioner_token=self.session.commissioner_token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)["success"])

    def test_no_auth_returns_403(self):
        response = self._post_pick(self.players[0].pk)
        self.assertEqual(response.status_code, 403)

    def test_invalid_captain_token_returns_403(self):
        import uuid

        response = self._post_pick(self.players[0].pk, captain_token=uuid.uuid4())
        self.assertEqual(response.status_code, 403)

    def test_draft_not_active_returns_400(self):
        self.session.state = DraftSession.STATE_PAUSED
        self.session.save(update_fields=["state"])
        response = self._post_pick(
            self.players[0].pk,
            commissioner_token=self.session.commissioner_token,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not active", json.loads(response.content)["error"])

    def test_already_drafted_player_returns_400(self):
        self._make_pick(self.team1, self.players[0], 1, 0)
        # Try to pick the same player again (team2's turn now)
        response = self._post_pick(
            self.players[0].pk,
            commissioner_token=self.session.commissioner_token,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already drafted", json.loads(response.content)["error"])

    def test_cannot_draft_another_teams_captain(self):
        # It is team1's turn; team1 tries to draft cap2 (captain of team2)
        response = self._post_pick(self.cap2.pk, captain_token=self.team1.captain_token)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("captain of", data["error"])
        self.assertIn("own team", data["error"])

    def test_can_draft_own_captain_when_no_auto_round_set(self):
        # cap1 has no captain_draft_round, so their own team can pick them manually
        response = self._post_pick(self.cap1.pk, captain_token=self.team1.captain_token)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            DraftPick.objects.filter(
                session=self.session, signup=self.cap1, team=self.team1
            ).exists()
        )

    def test_second_goalie_to_same_team_returns_400(self):
        # Team1 picks goalie1, then tries to pick goalie2
        self._make_pick(self.team1, self.goalie1, 1, 0)
        # Advance to team1's next turn: after round 1 (t1,t2,t3) and round 2
        # reversed (t3,t2,t1), team1's turn is pick index 2 of round 2.
        self._make_pick(self.team2, self.players[0], 1, 1)
        self._make_pick(self.team3, self.players[1], 1, 2)
        self._make_pick(self.team3, self.players[2], 2, 0)
        self._make_pick(self.team2, self.players[3], 2, 1)
        # Now it is team1's turn (round 2, index 2)
        response = self._post_pick(
            self.goalie2.pk, commissioner_token=self.session.commissioner_token
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("goalie", json.loads(response.content)["error"])

    def test_last_pick_sets_state_to_complete(self):
        # Fill all but the final slot manually, then submit the last pick
        all_signups = self.players[:6] + [self.cap1, self.cap2, self.cap3]
        slot = 0
        for r in range(1, 4):
            for p in range(3):
                if r == 3 and p == 2:
                    break  # leave last slot for the view
                self._make_pick(
                    [self.team1, self.team2, self.team3][p],
                    all_signups[slot],
                    r,
                    p,
                )
                slot += 1
        last_signup = all_signups[slot]
        self._post_pick(
            last_signup.pk,
            commissioner_token=self.session.commissioner_token,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, DraftSession.STATE_COMPLETE)


# ---------------------------------------------------------------------------
# Logic: _process_auto_captain_picks
# ---------------------------------------------------------------------------


class AutoCaptainPickTests(DraftTestBase):
    def setUp(self):
        super().setUp()
        self._activate()

    def test_auto_captain_fires_in_designated_round(self):
        # team1's captain is auto-drafted in round 1, pick index 0
        self.team1.captain_draft_round = 1
        self.team1.save(update_fields=["captain_draft_round"])

        auto_picks = _process_auto_captain_picks(self.session)

        self.assertEqual(len(auto_picks), 1)
        self.assertEqual(auto_picks[0].signup, self.cap1)
        self.assertEqual(auto_picks[0].team, self.team1)
        self.assertTrue(auto_picks[0].is_auto_captain)

    def test_auto_captain_does_not_fire_in_wrong_round(self):
        # captain_draft_round=2 but current pick is round 1
        self.team1.captain_draft_round = 2
        self.team1.save(update_fields=["captain_draft_round"])

        auto_picks = _process_auto_captain_picks(self.session)
        self.assertEqual(len(auto_picks), 0)

    def test_auto_captain_skips_if_already_drafted(self):
        self.team1.captain_draft_round = 1
        self.team1.save(update_fields=["captain_draft_round"])
        # Pre-draft the captain manually
        self._make_pick(self.team1, self.cap1, 1, 0, auto=False)

        # Shouldn't try to draft again (would raise unique constraint otherwise)
        auto_picks = _process_auto_captain_picks(self.session)
        self.assertEqual(len(auto_picks), 0)

    def test_consecutive_auto_captain_slots_all_resolved(self):
        # Both team1 (pos 1) and team2 (pos 2) have captain_draft_round=1
        self.team1.captain_draft_round = 1
        self.team1.save(update_fields=["captain_draft_round"])
        self.team2.captain_draft_round = 1
        self.team2.save(update_fields=["captain_draft_round"])

        auto_picks = _process_auto_captain_picks(self.session)

        self.assertEqual(len(auto_picks), 2)
        drafted_signups = {p.signup for p in auto_picks}
        self.assertIn(self.cap1, drafted_signups)
        self.assertIn(self.cap2, drafted_signups)


# ---------------------------------------------------------------------------
# View: undo_last_pick
# ---------------------------------------------------------------------------


class UndoPickViewTests(DraftTestBase):
    def setUp(self):
        super().setUp()
        self._activate()
        self._broadcast_patcher = patch("leagues.draft_views._broadcast_state_change")
        self._broadcast_patcher.start()

    def tearDown(self):
        self._broadcast_patcher.stop()
        super().tearDown()

    def _undo_url(self):
        return reverse(
            "draft_undo_pick",
            args=[self.session.pk, self.session.commissioner_token],
        )

    def test_undo_removes_last_pick(self):
        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        response = self.client.post(self._undo_url())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DraftPick.objects.filter(pk=pick.pk).exists())

    def test_undo_no_picks_returns_400(self):
        response = self.client.post(self._undo_url())
        self.assertEqual(response.status_code, 400)
        self.assertIn("No picks", json.loads(response.content)["error"])

    def test_undo_wrong_token_returns_404(self):
        import uuid

        url = reverse("draft_undo_pick", args=[self.session.pk, uuid.uuid4()])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_undo_auto_captain_chain_removes_consecutive_auto_picks(self):
        # A manual pick followed by two auto-captain picks.
        # Undo should remove the two auto picks and stop at the manual pick.
        manual = self._make_pick(self.team1, self.players[0], 1, 0, auto=False)
        auto1 = self._make_pick(self.team2, self.cap2, 1, 1, auto=True)
        auto2 = self._make_pick(self.team3, self.cap3, 1, 2, auto=True)

        response = self.client.post(self._undo_url())
        self.assertEqual(response.status_code, 200)

        # Both auto picks are removed; the preceding manual pick is preserved.
        self.assertFalse(DraftPick.objects.filter(pk=auto2.pk).exists())
        self.assertFalse(DraftPick.objects.filter(pk=auto1.pk).exists())
        self.assertTrue(DraftPick.objects.filter(pk=manual.pk).exists())


# ---------------------------------------------------------------------------
# View: swap_pick
# ---------------------------------------------------------------------------


class SwapPickViewTests(DraftTestBase):
    def setUp(self):
        super().setUp()
        self._complete()
        self._broadcast_patcher = patch("leagues.draft_views._broadcast_state_change")
        self._broadcast_patcher.start()

    def tearDown(self):
        self._broadcast_patcher.stop()
        super().tearDown()

    def _swap_url(self):
        return reverse(
            "draft_swap_pick",
            args=[self.session.pk, self.session.commissioner_token],
        )

    def _swap(self, pick_id, new_signup_pk):
        return self.client.post(
            self._swap_url(),
            {"pick_id": pick_id, "new_signup_pk": new_signup_pk},
        )

    def test_swap_replaces_undrafted_player_into_slot(self):
        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        response = self._swap(pick.pk, self.players[1].pk)
        self.assertEqual(response.status_code, 200)
        pick.refresh_from_db()
        self.assertEqual(pick.signup, self.players[1])

    def test_swap_exchanges_two_existing_picks(self):
        pick_a = self._make_pick(self.team1, self.players[0], 1, 0)
        self._make_pick(self.team2, self.players[1], 1, 1)

        response = self._swap(pick_a.pk, self.players[1].pk)
        self.assertEqual(response.status_code, 200)

        # pick_a now holds players[1]
        pick_a.refresh_from_db()
        self.assertEqual(pick_a.signup, self.players[1])

        # The slot previously held by pick_b (team2, round 1, index 1)
        # now holds players[0] — looked up by position since pick_b was recreated
        new_pick_b = DraftPick.objects.get(
            session=self.session, team=self.team2, round_number=1, pick_number=1
        )
        self.assertEqual(new_pick_b.signup, self.players[0])

    def test_swap_same_player_is_no_op(self):
        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        response = self._swap(pick.pk, self.players[0].pk)
        self.assertEqual(response.status_code, 200)
        pick.refresh_from_db()
        self.assertEqual(pick.signup, self.players[0])

    def test_swap_cannot_move_captain_to_different_team(self):
        # put cap2 into team1's pick slot — should be rejected
        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        response = self._swap(pick.pk, self.cap2.pk)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("captain of", data["error"])
        self.assertIn("own team", data["error"])

    def test_swap_allows_captain_to_move_within_own_team(self):
        # Swap cap1 into team1's slot — same team, should succeed
        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        response = self._swap(pick.pk, self.cap1.pk)
        self.assertEqual(response.status_code, 200)
        pick.refresh_from_db()
        self.assertEqual(pick.signup, self.cap1)

    def test_swap_requires_draft_complete(self):
        self.session.state = DraftSession.STATE_ACTIVE
        self.session.save(update_fields=["state"])
        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        response = self._swap(pick.pk, self.players[1].pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("complete", json.loads(response.content)["error"])

    def test_swap_wrong_token_returns_404(self):
        import uuid

        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        url = reverse("draft_swap_pick", args=[self.session.pk, uuid.uuid4()])
        response = self.client.post(
            url, {"pick_id": pick.pk, "new_signup_pk": self.players[1].pk}
        )
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# View: reset_draft
# ---------------------------------------------------------------------------


class ResetDraftViewTests(DraftTestBase):
    def setUp(self):
        super().setUp()
        self._activate()
        self._broadcast_patcher = patch("leagues.draft_views._broadcast_state_change")
        self._broadcast_patcher.start()

    def tearDown(self):
        self._broadcast_patcher.stop()
        super().tearDown()

    def _reset_url(self):
        return reverse(
            "draft_reset",
            args=[self.session.pk, self.session.commissioner_token],
        )

    def test_reset_deletes_all_picks(self):
        self._make_pick(self.team1, self.players[0], 1, 0)
        self._make_pick(self.team2, self.players[1], 1, 1)
        self.client.post(self._reset_url())
        self.assertEqual(DraftPick.objects.filter(session=self.session).count(), 0)

    def test_reset_clears_draft_positions(self):
        self.client.post(self._reset_url())
        positions = list(self.session.teams.values_list("draft_position", flat=True))
        self.assertTrue(all(p is None for p in positions))

    def test_reset_returns_session_to_setup(self):
        self.client.post(self._reset_url())
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, DraftSession.STATE_SETUP)

    def test_reset_reopens_signups(self):
        self.session.signups_open = False
        self.session.save(update_fields=["signups_open"])
        self.client.post(self._reset_url())
        self.session.refresh_from_db()
        self.assertTrue(self.session.signups_open)

    def test_reset_from_setup_returns_400(self):
        self.session.state = DraftSession.STATE_SETUP
        self.session.save(update_fields=["state"])
        response = self.client.post(self._reset_url())
        self.assertEqual(response.status_code, 400)
        self.assertIn("not been started", json.loads(response.content)["error"])

    def test_reset_wrong_token_returns_404(self):
        import uuid

        url = reverse("draft_reset", args=[self.session.pk, uuid.uuid4()])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Helper: _session_state_payload
# ---------------------------------------------------------------------------


class SessionStatePayloadTests(DraftTestBase):
    def test_payload_teams_sorted_by_draft_position(self):
        # Assign positions out of natural insertion order
        self.team1.draft_position = 3
        self.team1.save(update_fields=["draft_position"])
        self.team3.draft_position = 1
        self.team3.save(update_fields=["draft_position"])

        payload = _session_state_payload(self.session)
        positions = [t["draft_position"] for t in payload["teams"]]
        self.assertEqual(positions, sorted(positions))

    def test_payload_active_team_pk_matches_expected_turn(self):
        self._activate()
        payload = _session_state_payload(self.session)
        # Round 1, index 0 → team with draft_position=1 = team1
        self.assertEqual(payload["active_team_pk"], self.team1.pk)

    def test_payload_available_players_excludes_drafted(self):
        self._activate()
        self._make_pick(self.team1, self.players[0], 1, 0)
        payload = _session_state_payload(self.session)
        available_ids = {p["id"] for p in payload["available_players"]}
        self.assertNotIn(self.players[0].pk, available_ids)
        self.assertIn(self.players[1].pk, available_ids)

    def test_payload_available_players_excludes_captains(self):
        payload = _session_state_payload(self.session)
        available_ids = {p["id"] for p in payload["available_players"]}
        self.assertNotIn(self.cap1.pk, available_ids)
        self.assertNotIn(self.cap2.pk, available_ids)
        self.assertNotIn(self.cap3.pk, available_ids)
        self.assertIn(self.players[0].pk, available_ids)

    def test_payload_pick_includes_pick_id(self):
        self._activate()
        pick = self._make_pick(self.team1, self.players[0], 1, 0)
        payload = _session_state_payload(self.session)
        team_data = next(t for t in payload["teams"] if t["id"] == self.team1.pk)
        self.assertEqual(team_data["picks"][1]["pick_id"], pick.pk)

    def test_payload_state_matches_session_state(self):
        self._activate()
        payload = _session_state_payload(self.session)
        self.assertEqual(payload["state"], DraftSession.STATE_ACTIVE)

    def test_payload_current_round_and_index_none_when_complete(self):
        # Fill all picks to make draft complete
        all_signups = self.players[:6] + [self.cap1, self.cap2, self.cap3]
        slot = 0
        for r in range(1, 4):
            for p in range(3):
                self._make_pick(
                    [self.team1, self.team2, self.team3][p],
                    all_signups[slot],
                    r,
                    p,
                )
                slot += 1
        payload = _session_state_payload(self.session)
        self.assertIsNone(payload["current_round"])
        self.assertIsNone(payload["current_pick_index"])
        self.assertIsNone(payload["active_team_pk"])
