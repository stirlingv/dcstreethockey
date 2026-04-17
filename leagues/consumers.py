"""
Django Channels WebSocket consumer for the real-time draft board and chat.

Clients connect to:
  ws://.../ws/draft/<session_pk>/[?role=commissioner&token=...
                                   |?role=captain&token=...
                                   |?display_name=...]

They receive all state updates, position-draw reveals, and chat events.
Picks are submitted via HTTP POST (standard auth/CSRF flow); chat messages
and reactions are sent through the WebSocket.
"""

import json
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

# Emoji reactions allowed on messages.  Keep this small and fun.
ALLOWED_REACTIONS = {"👍", "👎", "😂", "🔥", "😤", "🎯", "👏", "🤙"}

# Maximum chat message body length (characters).
MAX_BODY_LENGTH = 500

# Minimum seconds between chat messages per connection (rate limit).
MIN_MSG_INTERVAL = 1.0

# Number of historical messages sent to a client on connect.
HISTORY_COUNT = 50


class DraftConsumer(AsyncWebsocketConsumer):
    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        self.session_pk = self.scope["url_route"]["kwargs"]["session_pk"]
        self.group_name = f"draft_{self.session_pk}"

        # Resolve identity from query-string params.
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        role = qs.get("role", ["spectator"])[0]
        token = qs.get("token", [""])[0]
        raw_name = qs.get("display_name", [""])[0][:30].strip()

        self.sender_type = "spectator"
        self.sender_name = raw_name or "Spectator"
        self.can_delete = False

        if role == "commissioner" and token:
            resolved = await self._resolve_commissioner(token)
            if resolved:
                self.sender_type = "commissioner"
                self.sender_name = "Commissioner"
                self.can_delete = True

        elif role == "captain" and token:
            team_name = await self._resolve_captain(token)
            if team_name:
                self.sender_type = "captain"
                self.sender_name = team_name

        # Rate-limit state — track the last time this connection sent a message.
        self._last_msg_at = 0.0

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send chat history so the client sees messages posted before joining.
        await self._send_chat_history()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # ------------------------------------------------------------------
    # Incoming messages from the client
    # ------------------------------------------------------------------

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            msg = json.loads(text_data)
        except (json.JSONDecodeError, ValueError):
            return

        msg_type = msg.get("type")

        if msg_type == "chat_message":
            await self._handle_chat(msg)
        elif msg_type == "chat_reaction":
            await self._handle_reaction(msg)
        elif msg_type == "delete_message":
            await self._handle_delete(msg)

    # ------------------------------------------------------------------
    # Handlers for each incoming message type
    # ------------------------------------------------------------------

    async def _handle_chat(self, msg):
        body = str(msg.get("body", "")).strip()
        if not body or len(body) > MAX_BODY_LENGTH:
            return

        # Rate limit: ignore if too soon after last message.
        now = time.monotonic()
        if now - self._last_msg_at < MIN_MSG_INTERVAL:
            return
        self._last_msg_at = now

        # Serialize inside the sync wrapper so reactions.all() doesn't hit
        # the DB from an async context (new message has no reactions anyway).
        message_data = await self._save_chat_message(body)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "draft.chat_message",
                "message": message_data,
            },
        )

    async def _handle_reaction(self, msg):
        message_id = msg.get("message_id")
        emoji = msg.get("emoji")
        if not message_id or emoji not in ALLOWED_REACTIONS:
            return

        result = await self._toggle_reaction(message_id, emoji)
        if result is None:
            return  # message not found or belongs to different session

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "draft.chat_reaction",
                "message_id": message_id,
                "emoji": emoji,
                "reactions": result,
            },
        )

    async def _handle_delete(self, msg):
        if not self.can_delete:
            return
        message_id = msg.get("message_id")
        if not message_id:
            return

        deleted = await self._soft_delete_message(message_id)
        if not deleted:
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "draft.chat_delete",
                "message_id": message_id,
            },
        )

    # ------------------------------------------------------------------
    # Group message handlers — called by channel layer group_send
    # ------------------------------------------------------------------

    async def draft_state_update(self, event):
        """Full state snapshot — sent after every pick, undo, or pause."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "state_update",
                    "state": event["state"],
                    **{k: v for k, v in event.items() if k not in ("type", "state")},
                }
            )
        )

    async def draft_positions_drawn(self, event):
        """Reveal order from the draw phase."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "positions_drawn",
                    "reveal_order": event["reveal_order"],
                }
            )
        )

    async def draft_chat_message(self, event):
        """A new chat message — broadcast to all clients."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat_message",
                    "message": event["message"],
                }
            )
        )

    async def draft_chat_reaction(self, event):
        """Updated reaction counts for a message."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat_reaction",
                    "message_id": event["message_id"],
                    "emoji": event["emoji"],
                    "reactions": event["reactions"],
                }
            )
        )

    async def draft_chat_delete(self, event):
        """Commissioner deleted a message."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat_delete",
                    "message_id": event["message_id"],
                }
            )
        )

    # ------------------------------------------------------------------
    # Database helpers (sync wrapped for async context)
    # ------------------------------------------------------------------

    @database_sync_to_async
    def _resolve_commissioner(self, token):
        from leagues.models import DraftSession

        try:
            return DraftSession.objects.filter(
                pk=self.session_pk, commissioner_token=token
            ).exists()
        except Exception:
            return False

    @database_sync_to_async
    def _resolve_captain(self, token):
        from leagues.models import DraftTeam

        try:
            team = (
                DraftTeam.objects.filter(
                    session_id=self.session_pk, captain_token=token
                )
                .only("team_name")
                .first()
            )
            return team.team_name if team else None
        except Exception:
            return None

    @database_sync_to_async
    def _save_chat_message(self, body):
        from leagues.models import DraftChatMessage

        msg = DraftChatMessage.objects.create(
            session_id=self.session_pk,
            sender_name=self.sender_name,
            sender_type=self.sender_type,
            body=body,
        )
        # Serialize here (sync context) so the caller never touches the ORM
        # from async code.  New messages have no reactions so reactions={}.
        return _serialize_message(msg)

    @database_sync_to_async
    def _toggle_reaction(self, message_id, emoji):
        from leagues.models import DraftChatMessage, DraftChatReaction
        from django.db.models import Count

        try:
            msg = DraftChatMessage.objects.get(
                pk=message_id, session_id=self.session_pk, deleted=False
            )
        except DraftChatMessage.DoesNotExist:
            return None

        obj, created = DraftChatReaction.objects.get_or_create(
            message=msg,
            emoji=emoji,
            sender_name=self.sender_name,
        )
        if not created:
            obj.delete()

        # Return current reaction summary: {emoji: [sender_name, ...], ...}
        reactions = {}
        for r in DraftChatReaction.objects.filter(message=msg).values(
            "emoji", "sender_name"
        ):
            reactions.setdefault(r["emoji"], []).append(r["sender_name"])
        return reactions

    @database_sync_to_async
    def _soft_delete_message(self, message_id):
        from leagues.models import DraftChatMessage

        updated = DraftChatMessage.objects.filter(
            pk=message_id, session_id=self.session_pk
        ).update(deleted=True)
        return updated > 0

    @database_sync_to_async
    def _send_chat_history(self):
        """Fetch recent messages and send them as a chat_history event."""
        pass  # called below as a normal async method

    async def _send_chat_history(self):
        history = await self._load_chat_history()
        await self.send(
            text_data=json.dumps(
                {
                    "type": "chat_history",
                    "messages": history,
                }
            )
        )

    @database_sync_to_async
    def _load_chat_history(self):
        from leagues.models import DraftChatMessage

        msgs = list(
            DraftChatMessage.objects.filter(session_id=self.session_pk, deleted=False)
            .prefetch_related("reactions")
            .order_by("sent_at")[:HISTORY_COUNT]
        )
        return [_serialize_message(m) for m in msgs]


# ------------------------------------------------------------------
# Serialization helper
# ------------------------------------------------------------------


def _serialize_message(msg):
    """Convert a DraftChatMessage instance to a JSON-safe dict."""
    reactions = {}
    # reactions may be prefetched or freshly loaded
    for r in msg.reactions.all():
        reactions.setdefault(r.emoji, []).append(r.sender_name)
    return {
        "id": msg.pk,
        "sender_name": msg.sender_name,
        "sender_type": msg.sender_type,
        "body": msg.body,
        "sent_at": msg.sent_at.isoformat(),
        "reactions": reactions,
    }
