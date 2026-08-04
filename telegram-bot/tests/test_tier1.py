"""Tier 1 provider-neutral domain acceptance tests."""

import pytest

from bot.services.membership_service import MembershipService
from bot.services.participant_service import ParticipantService
from db.connection import get_session
from db.identity import AuthProvider, resolve_identity
from db.models import Event, Group, GroupMemberStatus


pytestmark = pytest.mark.integration


async def test_web_only_user_can_participate_end_to_end(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        user = await resolve_identity(
            session, AuthProvider.email.value, "web-participant@example.com"
        )
        assert user is not None
        event = Event(event_type="web-only", state="proposed", version=0)
        session.add(event)
        await session.flush()

        participant, created = await ParticipantService(session).join(
            event.event_id, user.user_id, source="web"
        )
        await session.flush()

        assert created is True
        assert participant.user_id == user.user_id
        assert (
            await ParticipantService(session).get_participant(
                event.event_id, user.user_id
            )
            is participant
        )


async def test_membership_status_and_web_only_user(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        user = await resolve_identity(
            session, AuthProvider.email.value, "web-member@example.com"
        )
        assert user is not None
        group = Group(group_name="Web group")
        session.add(group)
        await session.flush()
        memberships = MembershipService(session)

        assert not await memberships.is_member(group.group_id, user.user_id)
        await memberships.add_member(group.group_id, user.user_id)
        assert await memberships.is_member(group.group_id, user.user_id)
        await memberships.remove_member(group.group_id, user.user_id)
        assert not await memberships.is_member(group.group_id, user.user_id)
        removed = await memberships.list_members(
            group.group_id, GroupMemberStatus.removed
        )
        assert [row.user_id for row in removed] == [user.user_id]


async def test_waitlist_service_uses_null_notifier(test_db_url: str) -> None:
    from bot.services.waitlist_service import WaitlistService
    from core.notifier import NullNotifier

    async with get_session(test_db_url) as session:
        user = await resolve_identity(
            session, AuthProvider.email.value, "waitlist@example.com"
        )
        assert user is not None
        event = Event(event_type="picnic", state="proposed", version=0)
        session.add(event)
        await session.flush()
        notifier = NullNotifier()
        service = WaitlistService(session, notifier)
        await service.add_to_waitlist(event.event_id, user.user_id)
        await service.offer_spot(event.event_id, user.user_id, 30)

        assert notifier.sent
        recipient, message = notifier.sent[0]
        assert recipient.id == user.user_id
        assert [action.command for action in message.flat_actions()] == [
            f"waitlist_accept_{event.event_id}",
            f"waitlist_decline_{event.event_id}",
        ]
