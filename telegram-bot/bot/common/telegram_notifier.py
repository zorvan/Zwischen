"""Telegram implementation of :class:`core.notifier.Notifier`.

Everything Telegram-specific about outbound delivery lives here: resolving a
domain id to a chat id, building InlineKeyboardMarkup, and interpreting the
error taxonomy. Services above this line know none of it.

Resolution is the interesting part. A domain ``Recipient`` names a user or
group by internal id; Telegram needs a chat id. For users that is the Telegram
identity from ``user_identities``, and for groups ``groups.telegram_group_id``
-- which is now nullable, because a web-created group has no chat. A group
with no chat is not an error here; it simply has nothing to deliver to over
this transport.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from core.notifier import Action, Audience, Message, MessageRef, Recipient
from db.models import AuthProvider, Group, UserIdentity

logger = logging.getLogger("coord_bot.notifier.telegram")

TRANSPORT = "telegram"


def to_markup(actions: list[list[Action]]) -> Optional[InlineKeyboardMarkup]:
    """Render neutral actions as Telegram inline keyboard rows."""
    if not actions:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(action.label, callback_data=action.command)
                for action in row
            ]
            for row in actions
            if row
        ]
    )


class TelegramNotifier:
    """Delivers domain messages over the Telegram Bot API."""

    def __init__(self, bot: Bot, session: AsyncSession, parse_mode: str = "HTML"):
        self._bot = bot
        self._session = session
        self._parse_mode = parse_mode

    # -- resolution --------------------------------------------------------

    async def resolve_chat_id(self, to: Recipient) -> Optional[int]:
        """Map a domain recipient to a Telegram chat id, or None.

        None means "not reachable over Telegram", which is a normal state for
        a web-only user or a group with no chat -- not a failure.
        """
        if to.audience is Audience.group:
            result = await self._session.execute(
                select(Group.telegram_group_id).where(Group.group_id == to.id)
            )
            return result.scalar_one_or_none()

        result = await self._session.execute(
            select(UserIdentity.provider_user_id).where(
                UserIdentity.user_id == to.id,
                UserIdentity.provider == AuthProvider.telegram.value,
            )
        )
        raw = result.scalar_one_or_none()
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("Non-numeric telegram identity for user %s: %r", to.id, raw)
            return None

    # -- Notifier ----------------------------------------------------------

    async def send(self, to: Recipient, message: Message) -> Optional[MessageRef]:
        chat_id = await self.resolve_chat_id(to)
        if chat_id is None:
            logger.debug("No Telegram destination for %s %s", to.audience.value, to.id)
            return None

        try:
            sent = await self._bot.send_message(
                chat_id=chat_id,
                text=message.text,
                reply_markup=to_markup(message.actions),
                parse_mode=self._parse_mode,
            )
        except Forbidden:
            # The user blocked the bot or left the chat. Expected, not an
            # error worth a traceback: nothing upstream can act on it.
            logger.info("Telegram delivery forbidden for chat %s", chat_id)
            return None
        except (BadRequest, RetryAfter, TimedOut) as exc:
            logger.warning("Telegram delivery failed for %s: %s", chat_id, exc)
            return None

        return MessageRef(TRANSPORT, str(chat_id), str(sent.message_id))

    async def edit(self, ref: MessageRef, message: Message) -> bool:
        if ref.transport != TRANSPORT:
            return False
        try:
            await self._bot.edit_message_text(
                chat_id=int(ref.channel_id),
                message_id=int(ref.message_id),
                text=message.text,
                reply_markup=to_markup(message.actions),
                parse_mode=self._parse_mode,
            )
            return True
        except BadRequest as exc:
            # "message is not modified" means the rendered content already
            # matches, which is a success from the caller's point of view.
            if "not modified" in str(exc).lower():
                return True
            logger.info("Telegram edit failed for %s: %s", ref.message_id, exc)
            return False
        except (Forbidden, RetryAfter, TimedOut) as exc:
            logger.warning("Telegram edit failed for %s: %s", ref.message_id, exc)
            return False

    async def delete(self, ref: MessageRef) -> bool:
        if ref.transport != TRANSPORT:
            return False
        try:
            await self._bot.delete_message(
                chat_id=int(ref.channel_id), message_id=int(ref.message_id)
            )
            return True
        except (BadRequest, Forbidden, RetryAfter, TimedOut) as exc:
            logger.info("Telegram delete failed for %s: %s", ref.message_id, exc)
            return False
