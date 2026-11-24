"""
RBAC (Role-Based Access Control) helpers for event operations.
PRD v2: Organizer control, permission checks, and group membership enforcement.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.services.membership_service import MembershipService
from db.identity import get_user_by_identity
from db.models import AuthProvider, Event, EventParticipant, Group

if TYPE_CHECKING:
    from db.models import Event as EventType, Group as GroupType

logger = logging.getLogger("coord_bot.rbac")


async def _internal_user_id(
    session: AsyncSession, telegram_user_id: int
) -> Optional[int]:
    """Resolve a Telegram provider ID to the internal users.user_id."""
    user = await get_user_by_identity(
        session, AuthProvider.telegram.value, telegram_user_id
    )
    return int(user.user_id) if user is not None else None


def _sep():
    return "━" * 52


def _pass(step: str, detail: str = ""):
    logger.info("✅ %s  %s", step, detail)


def _fail(step: str, detail: str = ""):
    logger.info("❌ %s  %s", step, detail)


def _info(label: str, value: str):
    logger.info("   %s: %s", label, value)


async def check_group_membership(
    session: AsyncSession,
    group_id: int,
    user_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Check persisted membership without consulting a transport API.
    """
    logger.info("")
    logger.info("%s", _sep())
    logger.info("🔍 check_group_membership")
    logger.info("   group_id=%d  user_id=%d", group_id, user_id)

    result = await session.execute(select(Group).where(Group.group_id == group_id))
    group = result.scalar_one_or_none()

    if not group:
        _fail("Group not found", f"group_id={group_id}")
        return False, "Group not found"

    _info("Group", f"{group.group_name or 'unnamed'} (tg_id={group.telegram_group_id})")
    internal_user_id = await _internal_user_id(session, user_id)
    if internal_user_id is None:
        _info("Result", "DENIED — Telegram identity is not registered")
        return False, "You are not a member of this group"

    if await MembershipService(session).is_member(group_id, internal_user_id):
        _pass("Membership PASS", "active group_members row")
        return True, None
    _info("Result", "DENIED — not a member of this group")
    logger.info("%s", _sep())
    return False, "You are not a member of this group"


async def check_event_visibility_and_get_event(
    session: AsyncSession,
    event_id: int,
    user_id: int,
    telegram_chat_id: Optional[int] = None,
    bot: object = None,
) -> Tuple[bool, Optional["EventType"], Optional["GroupType"], Optional[str]]:
    """
    Check if an event is visible to the user based on group membership.

    Organizers and emergency admins are always allowed. Everyone else must
    have an active persisted group-membership row.
    """
    logger.info("")
    logger.info("%s", _sep())
    logger.info("🔍 check_event_visibility_and_get_event")
    logger.info(
        "   event_id=%d  user_id=%d  chat_id=%r", event_id, user_id, telegram_chat_id
    )

    result = await session.execute(
        select(Event, Group)
        .options(selectinload(Event.participants))
        .join(Group, Event.group_id == Group.group_id, isouter=True)
        .where(Event.event_id == event_id)
    )
    row = result.one_or_none()

    if not row:
        _fail("Event not found", f"event_id={event_id}")
        return False, None, None, "Event not found"

    event, group = row
    uid = await _internal_user_id(session, user_id)
    if uid is None:
        _info("Result", "DENIED — Telegram identity is not registered")
        return False, None, None, "You do not have access to this event"

    _info("Event", f"{event.event_type} (state={event.state}, id={event.event_id})")
    _info("Organizer", str(event.organizer_user_id))
    _info("Admin", str(event.emergency_admin_user_id))

    # ── Check 1: Organizer / Admin ───────────────────────────
    _info("Check 1", "Organizer / Admin check")
    _info("  event.organizer_user_id", str(event.organizer_user_id))
    _info(
        "  event.emergency_admin_user_id",
        str(event.emergency_admin_user_id),
    )
    _info("  requesting user_id", str(uid))

    if event.organizer_user_id == uid:
        _pass("Check 1 PASS", "User is event organizer")
        return True, event, group, None

    if event.emergency_admin_user_id == uid:
        _pass("Check 1 PASS", "User is event admin")
        return True, event, group, None

    _fail("Check 1 FAIL", "Not organizer or admin")

    # ── Orphaned event ───────────────────────────────────────
    if not group:
        _fail("Orphaned event", "Event has no group → denied")
        return False, None, None, "Event not found"

    if await MembershipService(session).is_member(group.group_id, uid):
        _pass("Membership PASS", "active group_members row")
        return True, event, group, None

    _info("Result", "DENIED — no access to this event")
    logger.info("%s", _sep())
    return False, None, None, "You do not have access to this event"


async def check_event_organizer(
    session: AsyncSession,
    event_id: int,
    telegram_user_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Check if user is the event organizer.

    Returns:
        (is_authorized, error_message)
    """
    result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()

    if not event:
        return False, "Event not found"

    internal_user_id = await _internal_user_id(session, telegram_user_id)
    if event.organizer_user_id != internal_user_id:
        return False, "Only the event organizer can perform this action"

    return True, None


async def check_event_admin(
    session: AsyncSession,
    event_id: int,
    telegram_user_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Check if user is an event admin (organizer or group admin).

    Returns:
        (is_authorized, error_message)
    """
    result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()

    if not event:
        return False, "Event not found"

    internal_user_id = await _internal_user_id(session, telegram_user_id)

    # Check if user is organizer or admin
    if event.organizer_user_id == internal_user_id:
        return True, None

    if event.emergency_admin_user_id == internal_user_id:
        return True, None

    return False, "Only event organizer or admin can perform this action"


async def check_event_participant(
    session: AsyncSession,
    event_id: int,
    telegram_user_id: int,
) -> Tuple[bool, Optional[str], Optional[EventParticipant]]:
    """
    Check if user is a participant of the event.

    Returns:
        (is_authorized, error_message, participant_record)
    """
    internal_user_id = await _internal_user_id(session, telegram_user_id)
    if internal_user_id is None:
        return False, "You are not a participant of this event", None

    result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == internal_user_id,
        )
    )
    participant = result.scalar_one_or_none()

    if not participant:
        return False, "You are not a participant of this event", None

    return True, None, participant


async def check_can_modify_event(
    session: AsyncSession,
    event_id: int,
    telegram_user_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Check if user can modify the event.

    Permissions:
    - Organizer: Always can modify
    - Admin: Can modify
    - Confirmed participants: Can modify in emergencies (logged)

    Returns:
        (is_authorized, error_message)
    """
    result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()

    if not event:
        return False, "Event not found"

    internal_user_id = await _internal_user_id(session, telegram_user_id)
    if internal_user_id is None:
        return (
            False,
            "Only organizer, admin, or confirmed participants can modify this event",
        )

    # Organizer or admin can always modify
    if event.organizer_user_id == internal_user_id:
        return True, None

    if event.emergency_admin_user_id == internal_user_id:
        return True, None

    # Confirmed participants can modify in emergencies
    participant_result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == internal_user_id,
            EventParticipant.status == "confirmed",
        )
    )
    participant = participant_result.scalar_one_or_none()

    if participant:
        return True, None  # Will be logged as emergency modification

    return (
        False,
        "Only organizer, admin, or confirmed participants can modify this event",
    )


async def check_can_submit_private_note(
    session: AsyncSession,
    event_id: int,
    telegram_user_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Check if user can submit private attendee notes.

    Rules:
    - Only active participants (joined or confirmed) can submit
    - Organizer is allowed if they are also an active participant

    Returns:
        (is_authorized, error_message)
    """
    event_result = await session.execute(
        select(Event).where(Event.event_id == event_id)
    )
    event = event_result.scalar_one_or_none()

    if not event:
        return False, "Event not found"

    internal_user_id = await _internal_user_id(session, telegram_user_id)
    if internal_user_id is None:
        return False, "Only joined or confirmed participants can submit private notes"

    # Check if user is a participant
    participant_result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == internal_user_id,
            EventParticipant.status.in_(["joined", "confirmed"]),
        )
    )
    participant = participant_result.scalar_one_or_none()

    if not participant:
        return False, "Only joined or confirmed participants can submit private notes"

    return True, None


async def check_can_lock_event(
    session: AsyncSession,
    event_id: int,
    telegram_user_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Check if user can lock the event.

    Permissions:
    - Organizer: Can lock
    - Admin: Can lock

    Returns:
        (is_authorized, error_message)
    """
    return await check_event_admin(session, event_id, telegram_user_id)


async def get_user_event_role(
    session: AsyncSession,
    event_id: int,
    telegram_user_id: int,
) -> Optional[str]:
    """
    Get user's role for an event.

    Returns:
        'organizer', 'admin', 'participant', or None
    """
    result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()

    if not event:
        return None

    internal_user_id = await _internal_user_id(session, telegram_user_id)
    if internal_user_id is None:
        return None

    if event.organizer_user_id == internal_user_id:
        return "organizer"

    if event.emergency_admin_user_id == internal_user_id:
        return "admin"

    participant_result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == internal_user_id,
        )
    )
    participant = participant_result.scalar_one_or_none()

    if participant:
        return "participant"

    return None
