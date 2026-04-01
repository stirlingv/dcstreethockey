"""
Django Channels WebSocket consumer for the real-time draft board.

Clients connect to:
  ws://.../ws/draft/<session_pk>/

They receive all state updates and position-draw reveals.
They do NOT send picks through the WebSocket — picks are HTTP POST endpoints
so they benefit from Django's standard auth/CSRF flow.
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class DraftConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_pk = self.scope["url_route"]["kwargs"]["session_pk"]
        self.group_name = f"draft_{self.session_pk}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Clients don't send messages through the WebSocket.
    async def receive(self, text_data=None, bytes_data=None):
        pass

    # -----------------------------------------------------------------------
    # Group message handlers (called by draft_views.py via group_send)
    # -----------------------------------------------------------------------

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
