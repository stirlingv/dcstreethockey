"""
Tests for the draft live-chat feature.

Covers:
  - DraftChatMessage and DraftChatReaction models
  - DraftConsumer handler methods (chat_message, chat_reaction, delete_message)
  - Identity resolution helpers (_resolve_commissioner, _resolve_captain)
  - Rate limiting
  - System messages broadcast on picks
  - Chat cleared on draft reset
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from leagues.models import (
    DraftChatMessage,
    DraftChatReaction,
    DraftSession,
    DraftTeam,
    Season,
    SeasonSignup,
)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_session():
    season = Season.objects.create(
        year=datetime.date.today().year,
        season_type=4,
        is_current_season=False,
    )
    session = DraftSession.objects.create(
        season=season,
        num_teams=2,
        num_rounds=2,
        state=DraftSession.STATE_ACTIVE,
        signups_open=False,
    )
    cap1 = SeasonSignup.objects.create(
        season=season,
        first_name="Alpha",
        last_name="Cap",
        email="alpha@test.com",
        primary_position=SeasonSignup.POSITION_CENTER,
        secondary_position=SeasonSignup.POSITION_WING,
        captain_interest=SeasonSignup.CAPTAIN_YES,
    )
    cap2 = SeasonSignup.objects.create(
        season=season,
        first_name="Beta",
        last_name="Cap",
        email="beta@test.com",
        primary_position=SeasonSignup.POSITION_WING,
        secondary_position=SeasonSignup.POSITION_CENTER,
        captain_interest=SeasonSignup.CAPTAIN_YES,
    )
    team1 = DraftTeam.objects.create(
        session=session, captain=cap1, draft_position=1, team_name="Alphas"
    )
    team2 = DraftTeam.objects.create(
        session=session, captain=cap2, draft_position=2, team_name="Betas"
    )
    return session, team1, team2


def _make_consumer(
    session_pk,
    sender_name="Tester",
    sender_type="spectator",
    can_delete=False,
    last_msg_at=0.0,
):
    """Return a DraftConsumer instance with faked connection state."""
    from leagues.consumers import DraftConsumer

    consumer = DraftConsumer()
    consumer.session_pk = session_pk
    consumer.group_name = f"draft_{session_pk}"
    consumer.sender_name = sender_name
    consumer.sender_type = sender_type
    consumer.can_delete = can_delete
    consumer._last_msg_at = last_msg_at

    # Mock channel layer and send so no real network calls happen.
    consumer.channel_layer = MagicMock()
    consumer.channel_layer.group_send = AsyncMock()
    consumer.send = AsyncMock()
    return consumer


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class DraftChatMessageModelTests(TestCase):
    def setUp(self):
        self.session, self.team1, _ = _make_session()

    def test_create_message(self):
        msg = DraftChatMessage.objects.create(
            session=self.session,
            sender_name="Commissioner",
            sender_type=DraftChatMessage.SENDER_COMMISSIONER,
            body="Welcome to the draft!",
        )
        self.assertEqual(msg.sender_name, "Commissioner")
        self.assertFalse(msg.deleted)

    def test_ordering_by_sent_at(self):
        m1 = DraftChatMessage.objects.create(
            session=self.session, sender_name="A", sender_type="spectator", body="first"
        )
        m2 = DraftChatMessage.objects.create(
            session=self.session,
            sender_name="B",
            sender_type="spectator",
            body="second",
        )
        msgs = list(DraftChatMessage.objects.filter(session=self.session))
        self.assertEqual(msgs[0].pk, m1.pk)
        self.assertEqual(msgs[1].pk, m2.pk)

    def test_str(self):
        msg = DraftChatMessage(sender_name="X", body="Hello world")
        self.assertIn("X", str(msg))
        self.assertIn("Hello", str(msg))

    def test_cascade_delete_from_session(self):
        DraftChatMessage.objects.create(
            session=self.session, sender_name="A", sender_type="spectator", body="hi"
        )
        self.session.delete()
        self.assertEqual(DraftChatMessage.objects.count(), 0)


class DraftChatReactionModelTests(TestCase):
    def setUp(self):
        self.session, _, _ = _make_session()
        self.msg = DraftChatMessage.objects.create(
            session=self.session,
            sender_name="Commissioner",
            sender_type=DraftChatMessage.SENDER_COMMISSIONER,
            body="Go team!",
        )

    def test_reaction_unique_together(self):
        from django.db import IntegrityError

        DraftChatReaction.objects.create(
            message=self.msg, emoji="👍", sender_name="Alice"
        )
        with self.assertRaises(IntegrityError):
            DraftChatReaction.objects.create(
                message=self.msg, emoji="👍", sender_name="Alice"
            )

    def test_same_emoji_different_senders(self):
        DraftChatReaction.objects.create(
            message=self.msg, emoji="👍", sender_name="Alice"
        )
        DraftChatReaction.objects.create(message=self.msg, emoji="👍", sender_name="Bob")
        self.assertEqual(
            DraftChatReaction.objects.filter(message=self.msg, emoji="👍").count(), 2
        )

    def test_different_emojis_same_sender(self):
        DraftChatReaction.objects.create(
            message=self.msg, emoji="👍", sender_name="Alice"
        )
        DraftChatReaction.objects.create(
            message=self.msg, emoji="🔥", sender_name="Alice"
        )
        self.assertEqual(DraftChatReaction.objects.filter(message=self.msg).count(), 2)

    def test_cascade_delete_with_message(self):
        DraftChatReaction.objects.create(
            message=self.msg, emoji="👍", sender_name="Alice"
        )
        self.msg.delete()
        self.assertEqual(DraftChatReaction.objects.count(), 0)


# ---------------------------------------------------------------------------
# Consumer handler tests
# ---------------------------------------------------------------------------


class ConsumerIdentityResolutionTests(TestCase):
    def setUp(self):
        self.session, self.team1, _ = _make_session()

    async def test_resolve_commissioner_valid_token(self):
        from leagues.consumers import DraftConsumer

        consumer = DraftConsumer()
        consumer.session_pk = self.session.pk
        result = await consumer._resolve_commissioner(
            str(self.session.commissioner_token)
        )
        self.assertTrue(result)

    async def test_resolve_commissioner_invalid_token(self):
        from leagues.consumers import DraftConsumer

        consumer = DraftConsumer()
        consumer.session_pk = self.session.pk
        # Valid UUID format but wrong token value — should return False
        result = await consumer._resolve_commissioner(
            "00000000-0000-0000-0000-000000000000"
        )
        self.assertFalse(result)

    async def test_resolve_captain_valid_token(self):
        from leagues.consumers import DraftConsumer

        consumer = DraftConsumer()
        consumer.session_pk = self.session.pk
        team_name = await consumer._resolve_captain(str(self.team1.captain_token))
        self.assertEqual(team_name, self.team1.team_name)

    async def test_resolve_captain_invalid_token(self):
        from leagues.consumers import DraftConsumer

        consumer = DraftConsumer()
        consumer.session_pk = self.session.pk
        result = await consumer._resolve_captain("00000000-0000-0000-0000-000000000000")
        self.assertIsNone(result)


class ConsumerChatHandlerTests(TestCase):
    def setUp(self):
        self.session, self.team1, _ = _make_session()

    async def test_handle_chat_saves_and_broadcasts(self):
        consumer = _make_consumer(self.session.pk, sender_name="Jordan")
        await consumer._handle_chat({"body": "Hello draft!"})

        msg = await DraftChatMessage.objects.filter(
            session_id=self.session.pk, body="Hello draft!"
        ).afirst()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.sender_name, "Jordan")
        consumer.channel_layer.group_send.assert_called_once()
        call_args = consumer.channel_layer.group_send.call_args[0]
        self.assertEqual(call_args[1]["type"], "draft.chat_message")

    async def test_handle_chat_empty_body_ignored(self):
        consumer = _make_consumer(self.session.pk)
        await consumer._handle_chat({"body": "   "})
        consumer.channel_layer.group_send.assert_not_called()
        self.assertEqual(
            await DraftChatMessage.objects.filter(session_id=self.session.pk).acount(),
            0,
        )

    async def test_handle_chat_body_too_long_ignored(self):
        consumer = _make_consumer(self.session.pk)
        await consumer._handle_chat({"body": "x" * 501})
        consumer.channel_layer.group_send.assert_not_called()

    async def test_handle_chat_rate_limited(self):
        import time

        consumer = _make_consumer(
            self.session.pk, last_msg_at=time.monotonic()  # just sent
        )
        await consumer._handle_chat({"body": "Too soon!"})
        consumer.channel_layer.group_send.assert_not_called()

    async def test_handle_reaction_adds(self):
        msg = await DraftChatMessage.objects.acreate(
            session_id=self.session.pk,
            sender_name="Someone",
            sender_type="spectator",
            body="React to me",
        )
        consumer = _make_consumer(self.session.pk, sender_name="Tester")
        await consumer._handle_reaction({"message_id": msg.pk, "emoji": "👍"})

        consumer.channel_layer.group_send.assert_called_once()
        payload = consumer.channel_layer.group_send.call_args[0][1]
        self.assertEqual(payload["type"], "draft.chat_reaction")
        self.assertIn("Tester", payload["reactions"]["👍"])

    async def test_handle_reaction_toggles_off(self):
        msg = await DraftChatMessage.objects.acreate(
            session_id=self.session.pk,
            sender_name="Someone",
            sender_type="spectator",
            body="React to me",
        )
        await DraftChatReaction.objects.acreate(
            message=msg, emoji="👍", sender_name="Tester"
        )
        consumer = _make_consumer(self.session.pk, sender_name="Tester")
        await consumer._handle_reaction({"message_id": msg.pk, "emoji": "👍"})

        payload = consumer.channel_layer.group_send.call_args[0][1]
        self.assertNotIn("👍", payload["reactions"])

    async def test_handle_reaction_invalid_emoji_ignored(self):
        msg = await DraftChatMessage.objects.acreate(
            session_id=self.session.pk,
            sender_name="A",
            sender_type="spectator",
            body="hi",
        )
        consumer = _make_consumer(self.session.pk)
        await consumer._handle_reaction({"message_id": msg.pk, "emoji": "💩"})
        consumer.channel_layer.group_send.assert_not_called()

    async def test_handle_delete_commissioner(self):
        msg = await DraftChatMessage.objects.acreate(
            session_id=self.session.pk,
            sender_name="Rude person",
            sender_type="spectator",
            body="delete me",
        )
        consumer = _make_consumer(
            self.session.pk, sender_type="commissioner", can_delete=True
        )
        await consumer._handle_delete({"message_id": msg.pk})

        refreshed = await DraftChatMessage.objects.aget(pk=msg.pk)
        self.assertTrue(refreshed.deleted)
        consumer.channel_layer.group_send.assert_called_once()
        payload = consumer.channel_layer.group_send.call_args[0][1]
        self.assertEqual(payload["type"], "draft.chat_delete")

    async def test_handle_delete_spectator_blocked(self):
        msg = await DraftChatMessage.objects.acreate(
            session_id=self.session.pk,
            sender_name="Someone",
            sender_type="spectator",
            body="delete me",
        )
        consumer = _make_consumer(
            self.session.pk, sender_type="spectator", can_delete=False
        )
        await consumer._handle_delete({"message_id": msg.pk})

        refreshed = await DraftChatMessage.objects.aget(pk=msg.pk)
        self.assertFalse(refreshed.deleted)
        consumer.channel_layer.group_send.assert_not_called()


# ---------------------------------------------------------------------------
# System message on pick
# ---------------------------------------------------------------------------


class SystemChatMessageOnPickTest(TestCase):
    def setUp(self):
        self.session, self.team1, _ = _make_session()

    @patch(
        "leagues.draft_views._session_state_payload",
        return_value={
            "state": "active",
            "teams": [],
            "current_round": 1,
            "current_pick_index": 0,
            "active_team_pk": None,
        },
    )
    @patch("asgiref.sync.async_to_sync", return_value=lambda *a, **kw: None)
    def test_system_message_created_on_pick(self, mock_a2s, mock_payload):
        from leagues.draft_views import _broadcast_state_change

        extra = {
            "pick": {
                "team_pk": self.team1.pk,
                "team_name": self.team1.team_name,
                "player": {"full_name": "Jordan Smith", "id": 99},
                "round": 1,
                "pick_number": 1,
            }
        }
        _broadcast_state_change(self.session, extra=extra)

        msg = DraftChatMessage.objects.filter(
            session=self.session, sender_type=DraftChatMessage.SENDER_SYSTEM
        ).first()
        self.assertIsNotNone(msg)
        self.assertIn(self.team1.team_name, msg.body)
        self.assertIn("Jordan Smith", msg.body)
        self.assertIn("Round 1", msg.body)


# ---------------------------------------------------------------------------
# Chat cleared on draft reset
# ---------------------------------------------------------------------------


class ChatClearedOnResetTest(TestCase):
    def setUp(self):
        self.session, _, _ = _make_session()
        self.session.state = DraftSession.STATE_ACTIVE
        self.session.save()
        DraftChatMessage.objects.create(
            session=self.session,
            sender_name="Commissioner",
            sender_type=DraftChatMessage.SENDER_COMMISSIONER,
            body="Great draft everyone!",
        )

    @patch("leagues.draft_views._broadcast_state_change")
    def test_reset_clears_chat(self, mock_broadcast):
        from django.test import Client

        client = Client()
        resp = client.post(
            f"/draft/{self.session.pk}/reset/{self.session.commissioner_token}/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            DraftChatMessage.objects.filter(session=self.session).count(), 0
        )
