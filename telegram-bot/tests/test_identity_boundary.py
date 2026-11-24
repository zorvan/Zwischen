"""Regression tests for the Telegram-ID / internal-ID boundary.

After the contract migration, every ``*.user_id`` column holds an internal
``users.user_id``. Telegram IDs exist only in ``user_identities``. These
tests pin the places that once confused the two:

* RBAC helpers receive a Telegram ID and must resolve it before comparing.
* DMs go to a Telegram chat ID, never to an internal ID.
* Pending modify requests compare the clicking Telegram user with the admin's
  Telegram ID.

Internal IDs and Telegram IDs are deliberately far apart here, so any mix-up
fails loudly instead of matching by coincidence.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config.settings import settings
from db.connection import get_session
from db.identity import (
    AuthProvider,
    resolve_identity,
    resolve_telegram_user,
    telegram_chat_ids,
)
from db.models import Event, EventParticipant, Group, ParticipantStatus

pytestmark = pytest.mark.integration

ORGANIZER_TG = 7_000_000_001
MEMBER_TG = 7_000_000_002


class RecordingBot:
    """Collects outgoing messages; shaped like telegram.Bot where used."""

    username = "zwischen_test_bot"

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: Any) -> Any:
        self.sent.append((int(chat_id), text))
        return SimpleNamespace(message_id=len(self.sent), chat_id=chat_id)


@pytest.fixture
def db_settings(test_db_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    # test_db_connection reloads config.settings, so modules imported before
    # and after that reload can hold different settings objects. Patch every
    # object the code under test can reach.
    import config.settings as settings_module
    import bot.common.event_notifications as notifications
    import bot.handlers.mentions as mentions

    for holder in {
        id(obj): obj
        for obj in (
            settings,
            settings_module.settings,
            notifications.settings,
            mentions.settings,
        )
    }.values():
        monkeypatch.setattr(holder, "db_url", test_db_url)
    return test_db_url


async def _seed(url: str) -> dict[str, int]:
    async with get_session(url) as session:
        organizer = await resolve_telegram_user(
            session, ORGANIZER_TG, display_name="Organizer"
        )
        member = await resolve_telegram_user(session, MEMBER_TG, display_name="Member")
        web_only = await resolve_identity(
            session, AuthProvider.email.value, "web-only@example.com"
        )
        assert web_only is not None
        group = Group(telegram_group_id=-1_009_000_000_001, group_name="Boundary")
        session.add(group)
        await session.flush()
        event = Event(
            group_id=group.group_id,
            event_type="dinner",
            state="confirmed",
            version=0,
            organizer_user_id=organizer.user_id,
            emergency_admin_user_id=organizer.user_id,
        )
        session.add(event)
        await session.flush()
        for user_id, status in (
            (organizer.user_id, ParticipantStatus.confirmed),
            (member.user_id, ParticipantStatus.confirmed),
            (web_only.user_id, ParticipantStatus.confirmed),
        ):
            session.add(
                EventParticipant(
                    event_id=event.event_id, user_id=user_id, status=status
                )
            )
        await session.commit()
        return {
            "event_id": int(event.event_id),
            "organizer": int(organizer.user_id),
            "member": int(member.user_id),
            "web_only": int(web_only.user_id),
        }


async def test_telegram_chat_ids_skips_users_without_telegram(
    db_settings: str,
) -> None:
    ids = await _seed(db_settings)
    async with get_session(db_settings) as session:
        chats = await telegram_chat_ids(
            session, [ids["organizer"], ids["member"], ids["web_only"]]
        )
    assert chats == {ids["organizer"]: ORGANIZER_TG, ids["member"]: MEMBER_TG}


async def test_rbac_resolves_telegram_ids(db_settings: str) -> None:
    from bot.common.rbac import (
        check_event_organizer,
        check_event_participant,
        get_user_event_role,
    )

    ids = await _seed(db_settings)
    async with get_session(db_settings) as session:
        ok, _ = await check_event_organizer(session, ids["event_id"], ORGANIZER_TG)
        assert ok
        ok, _ = await check_event_organizer(session, ids["event_id"], MEMBER_TG)
        assert not ok
        ok, _, participant = await check_event_participant(
            session, ids["event_id"], MEMBER_TG
        )
        assert ok and participant is not None
        # The internal ID must not authorize as if it were a Telegram ID.
        assert (
            await get_user_event_role(session, ids["event_id"], ids["organizer"])
            is None
        )
        assert (
            await get_user_event_role(session, ids["event_id"], ORGANIZER_TG)
            == "organizer"
        )


async def test_invitation_dm_goes_to_telegram_chat(db_settings: str) -> None:
    from bot.common.event_notifications import send_event_invitation_dm

    ids = await _seed(db_settings)
    bot = RecordingBot()
    context: Any = SimpleNamespace(bot=bot)

    sent = await send_event_invitation_dm(
        context,
        ids["member"],
        {"event_type": "dinner", "organizer_user_id": ids["organizer"]},
        ids["event_id"],
    )
    assert sent is True
    assert [chat for chat, _ in bot.sent] == [MEMBER_TG]

    # A web-only user is unreachable over Telegram: skipped, not misdirected.
    assert (
        await send_event_invitation_dm(
            context, ids["web_only"], {"event_type": "dinner"}, ids["event_id"]
        )
        is False
    )
    assert len(bot.sent) == 1


async def test_confirmation_reset_dms_telegram_chats(db_settings: str) -> None:
    from bot.common.confirmation import invalidate_confirmations_and_notify

    ids = await _seed(db_settings)
    bot = RecordingBot()
    async with get_session(db_settings) as session:
        event = (
            await session.execute(
                select(Event)
                .options(selectinload(Event.participants))
                .where(Event.event_id == ids["event_id"])
            )
        ).scalar_one()
        reset = await invalidate_confirmations_and_notify(
            context=SimpleNamespace(bot=bot), event=event, reason="time changed"
        )

    assert reset == 3
    assert sorted(chat for chat, _ in bot.sent) == sorted([ORGANIZER_TG, MEMBER_TG])
    assert ids["organizer"] not in {chat for chat, _ in bot.sent}


async def test_modify_request_stores_admin_telegram_id(db_settings: str) -> None:
    from bot.handlers.mentions import _store_modify_request

    ids = await _seed(db_settings)
    context: Any = SimpleNamespace(bot_data={})
    await _store_modify_request(
        context,
        request_id="abc12345",
        event_id=ids["event_id"],
        admin_user_id=ids["organizer"],
        change_text="move to 8pm",
        requester_id=MEMBER_TG,
        requester_username="member",
    )
    pending = context.bot_data["pending_modify_requests"]["modreq_abc12345"]
    # The approval handler compares this with query.from_user.id.
    assert pending["admin_id"] == ORGANIZER_TG
