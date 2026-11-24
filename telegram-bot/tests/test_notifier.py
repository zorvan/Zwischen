"""Tests for the transport-neutral notifier and its Telegram adapter."""

from __future__ import annotations

import pytest

from core.notifier import (
    Action,
    Audience,
    Message,
    MessageRef,
    Notifier,
    NullNotifier,
    Recipient,
)


def test_core_notifier_module_does_not_import_telegram() -> None:
    """The whole point of the abstraction.

    If `core` ever imports telegram, the domain is coupled again and a web
    process has to install the bot library to send a notification.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent / "core" / "notifier.py"
    ).read_text()
    assert "import telegram" not in source
    assert "from telegram" not in source


def test_null_notifier_satisfies_the_protocol() -> None:
    assert isinstance(NullNotifier(), Notifier)


async def test_null_notifier_records_what_it_was_asked_to_send() -> None:
    notifier = NullNotifier()
    await notifier.send(Recipient.user(7), Message("hello"))

    assert len(notifier.sent) == 1
    recipient, message = notifier.sent[0]
    assert recipient.audience is Audience.user
    assert recipient.id == 7
    assert message.text == "hello"


def test_recipient_constructors() -> None:
    assert Recipient.user(1) == Recipient(Audience.user, 1)
    assert Recipient.group(2) == Recipient(Audience.group, 2)


def test_flat_actions_flattens_rows() -> None:
    message = Message(
        "pick",
        actions=[
            [Action("Yes", "ev:1:join"), Action("No", "ev:1:skip")],
            [Action("Later", "ev:1:defer")],
        ],
    )
    assert [a.command for a in message.flat_actions()] == [
        "ev:1:join",
        "ev:1:skip",
        "ev:1:defer",
    ]


# ---------------------------------------------------------------------------
# Telegram adapter
# ---------------------------------------------------------------------------


def test_actions_render_as_inline_keyboard_rows() -> None:
    from bot.common.telegram_notifier import to_markup

    markup = to_markup(
        [
            [Action("Join", "ev:42:join"), Action("Skip", "ev:42:skip")],
            [Action("Details", "ev:42:view")],
        ]
    )
    assert markup is not None
    rows = markup.inline_keyboard
    assert [len(row) for row in rows] == [2, 1]
    assert rows[0][0].text == "Join"
    assert rows[0][0].callback_data == "ev:42:join"
    assert rows[1][0].callback_data == "ev:42:view"


def test_no_actions_means_no_markup() -> None:
    """Telegram rejects an empty keyboard; None is the correct absence."""
    from bot.common.telegram_notifier import to_markup

    assert to_markup([]) is None


def test_empty_rows_are_dropped() -> None:
    from bot.common.telegram_notifier import to_markup

    markup = to_markup([[], [Action("Only", "x")]])
    assert markup is not None
    assert len(markup.inline_keyboard) == 1


class _FakeBot:
    """Records calls; stands in for telegram.Bot."""

    def __init__(self, fail_with: Exception | None = None):
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.deleted: list[dict] = []
        self._fail_with = fail_with

    async def send_message(self, **kwargs):
        if self._fail_with:
            raise self._fail_with
        self.sent.append(kwargs)

        class _Sent:
            message_id = 999

        return _Sent()

    async def edit_message_text(self, **kwargs):
        if self._fail_with:
            raise self._fail_with
        self.edited.append(kwargs)
        return True

    async def delete_message(self, **kwargs):
        if self._fail_with:
            raise self._fail_with
        self.deleted.append(kwargs)
        return True


pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
async def test_send_resolves_a_user_to_their_telegram_identity(
    test_db_url: str,
) -> None:
    """A domain user id becomes a chat id via user_identities."""
    from typing import cast

    from telegram import Bot

    from bot.common.telegram_notifier import TelegramNotifier
    from db.connection import get_session
    from db.identity import resolve_telegram_user

    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 777001)
        await session.commit()

        bot = _FakeBot()
        notifier = TelegramNotifier(cast(Bot, bot), session)
        ref = await notifier.send(
            Recipient.user(user.user_id), Message("hi", [[Action("Go", "c")]])
        )

    assert ref is not None
    assert ref.channel_id == "777001"
    assert ref.message_id == "999"
    assert bot.sent[0]["chat_id"] == 777001
    assert bot.sent[0]["text"] == "hi"
    assert bot.sent[0]["reply_markup"] is not None


@pytest.mark.integration
async def test_a_user_without_telegram_is_simply_unreachable(
    test_db_url: str,
) -> None:
    """Not an error: a web-only user has no chat, and delivery is skipped.

    This is the case that did not exist before -- every user was a Telegram
    user by construction.
    """
    from typing import cast

    from telegram import Bot

    from bot.common.telegram_notifier import TelegramNotifier
    from db.connection import get_session
    from db.identity import AuthProvider, resolve_identity

    async with get_session(test_db_url) as session:
        user = await resolve_identity(
            session, AuthProvider.email.value, "web@example.com"
        )
        await session.commit()
        assert user is not None

        bot = _FakeBot()
        notifier = TelegramNotifier(cast(Bot, bot), session)
        ref = await notifier.send(Recipient.user(user.user_id), Message("hi"))

    assert ref is None
    assert bot.sent == []


@pytest.mark.integration
async def test_a_group_without_a_chat_is_unreachable(test_db_url: str) -> None:
    """A web-created group has no telegram_group_id."""
    from typing import cast

    from telegram import Bot

    from bot.common.telegram_notifier import TelegramNotifier
    from db.connection import get_session
    from db.models import Group

    async with get_session(test_db_url) as session:
        group = Group(group_name="Web Only", telegram_group_id=None)
        session.add(group)
        await session.flush()

        bot = _FakeBot()
        notifier = TelegramNotifier(cast(Bot, bot), session)
        ref = await notifier.send(Recipient.group(group.group_id), Message("hi"))

    assert ref is None


@pytest.mark.integration
async def test_blocked_user_is_swallowed_not_raised(test_db_url: str) -> None:
    """A user who blocked the bot must not fail the caller's transaction."""
    from typing import cast

    from telegram import Bot
    from telegram.error import Forbidden

    from bot.common.telegram_notifier import TelegramNotifier
    from db.connection import get_session
    from db.identity import resolve_telegram_user

    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 777002)
        await session.commit()

        bot = _FakeBot(fail_with=Forbidden("bot was blocked by the user"))
        notifier = TelegramNotifier(cast(Bot, bot), session)
        ref = await notifier.send(Recipient.user(user.user_id), Message("hi"))

    assert ref is None


async def test_edit_treats_not_modified_as_success() -> None:
    """Re-rendering identical content is a no-op, not a failure.

    Live cards refresh on every participant change and frequently produce
    identical text; treating that as an error would log noise on the hottest
    path.
    """
    from typing import cast
    from unittest.mock import MagicMock

    from telegram import Bot
    from telegram.error import BadRequest

    from bot.common.telegram_notifier import TelegramNotifier

    bot = _FakeBot(fail_with=BadRequest("Message is not modified"))
    notifier = TelegramNotifier(cast(Bot, bot), MagicMock())

    assert await notifier.edit(MessageRef("telegram", "1", "2"), Message("x")) is True


async def test_refs_from_another_transport_are_rejected() -> None:
    """A web-delivered message must not be edited through Telegram."""
    from typing import cast
    from unittest.mock import MagicMock

    from telegram import Bot

    from bot.common.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier(cast(Bot, _FakeBot()), MagicMock())
    ref = MessageRef("web", "room", "42")

    assert await notifier.edit(ref, Message("x")) is False
    assert await notifier.delete(ref) is False
