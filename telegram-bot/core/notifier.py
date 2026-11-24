"""Transport-neutral outbound messaging.

Ten modules under ``bot/`` import ``telegram.Bot`` directly and call
``bot.send_message`` with Telegram markup. That is what pins the domain
services to one client: an HTTP request handler has no Bot, and a mobile push
has no chat id.

The surface those services actually use is small -- send, edit, delete -- so
it fits behind a protocol. Services depend on :class:`Notifier`;
:class:`TelegramNotifier` adapts it to python-telegram-bot, and a web or push
implementation slots in beside it without the services changing.

Two things are deliberately *not* modelled here:

- Chat-membership queries. Those were Telegram asking who is in a chat, which
  no other client can answer; membership is now the ``group_members`` table.
- Markup strings. Content crosses this boundary as text plus structured
  actions, so each transport renders in its own idiom (HTML for Telegram,
  JSON for an API) instead of the domain emitting `<b>` tags it cannot escape.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("coord_bot.notifier")


class Audience(str, Enum):
    """Who a message is addressed to, in domain terms."""

    user = "user"
    group = "group"


@dataclass(frozen=True)
class Recipient:
    """A destination expressed in domain ids, not platform ids.

    ``user_id`` / ``group_id`` are internal keys. Turning those into a chat
    id, a device token or a WebSocket connection is the transport's job -- the
    thing that differs per client and must not leak into services.
    """

    audience: Audience
    id: int

    @classmethod
    def user(cls, user_id: int) -> "Recipient":
        return cls(Audience.user, user_id)

    @classmethod
    def group(cls, group_id: int) -> "Recipient":
        return cls(Audience.group, group_id)


@dataclass(frozen=True)
class Action:
    """One offered action.

    ``label`` is display text the caller has already localized. ``command`` is
    the neutral identifier the client sends back -- Telegram puts it in
    callback_data, an HTTP client POSTs it. Keeping it a plain string means
    the routing table is shared across transports.
    """

    label: str
    command: str


@dataclass(frozen=True)
class Message:
    """Content to deliver, independent of how it will be rendered."""

    text: str
    # Rows of actions, so a transport that cares about layout keeps it.
    actions: list[list[Action]] = field(default_factory=list)
    # Set when this message replaces an earlier one (live cards).
    replaces: Optional["MessageRef"] = None

    def flat_actions(self) -> list[Action]:
        return [action for row in self.actions for action in row]


@dataclass(frozen=True)
class MessageRef:
    """A handle to something already delivered, so it can be edited later.

    ``channel_id`` and ``message_id`` are opaque to the domain: Telegram fills
    them with chat and message ids, a web transport with a room and record id.
    Storing them as strings keeps the column usable for both.
    """

    transport: str
    channel_id: str
    message_id: str


@runtime_checkable
class Notifier(Protocol):
    """What a domain service is allowed to ask of the outside world."""

    async def send(self, to: Recipient, message: Message) -> Optional[MessageRef]:
        """Deliver a message. Returns a handle if the transport supports edits."""
        ...

    async def edit(self, ref: MessageRef, message: Message) -> bool:
        """Replace previously delivered content. False if it is gone."""
        ...

    async def delete(self, ref: MessageRef) -> bool:
        """Remove previously delivered content. False if it is already gone."""
        ...


class NullNotifier:
    """Discards everything. For tests and for running with delivery disabled.

    Records what it was asked to send so tests can assert on it without
    standing up a transport.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[Recipient, Message]] = []
        self.edited: list[tuple[MessageRef, Message]] = []
        self.deleted: list[MessageRef] = []

    async def send(self, to: Recipient, message: Message) -> Optional[MessageRef]:
        self.sent.append((to, message))
        return MessageRef("null", str(to.id), str(len(self.sent)))

    async def edit(self, ref: MessageRef, message: Message) -> bool:
        self.edited.append((ref, message))
        return True

    async def delete(self, ref: MessageRef) -> bool:
        self.deleted.append(ref)
        return True
