"""
RBAC (Role-Based Access Control) helpers for event operations.
PRD v2: Organizer control, permission checks, and group membership enforcement.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db.models import Event, EventParticipant, Group

if TYPE_CHECKING:
    from db.models import Event as EventType, Group as GroupType

logger = logging.getLogger("coord_bot.rbac")


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
    telegram_chat_id: Optional[int] = None,
    bot: object = None,
) -> Tuple[bool, Optional[str]]:
    """
    Check if a user is a member of the given group.

    Checks in order:
    1. If telegram_chat_id matches the group's telegram_group_id → implicit member
    2. If user has participated in ANY event in this group → proven member
    3. Explicit check of Group.member_list
    4. Final fallback: query Telegram API for actual group membership
    """
    logger.info("")
    logger.info("%s", _sep())
    logger.info("🔍 check_group_membership")
    logger.info(
        "   group_id=%d  user_id=%d  chat_id=%r", group_id, user_id, telegram_chat_id
    )

    result = await session.execute(select(Group).where(Group.group_id == group_id))
    group = result.scalar_one_or_none()

    if not group:
        _fail("Group not found", f"group_id={group_id}")
        return False, "Group not found"

    _info("Group", f"{group.group_name or 'unnamed'} (tg_id={group.telegram_group_id})")
    _info("Stored members", str(group.member_list or []))

    uid = int(user_id)

    # ── Step 1: Same group chat ──────────────────────────────
    _info("Step 1", "Same group chat check")
    _info("  group.telegram_group_id", str(group.telegram_group_id))
    _info("  incoming telegram_chat_id", str(telegram_chat_id))

    if telegram_chat_id is not None and int(group.telegram_group_id) == int(
        telegram_chat_id
    ):
        member_list = group.member_list or []
        if uid not in [int(m) for m in member_list]:
            group.member_list = [*member_list, uid]
            await session.flush()
        _pass("Step 1 PASS", "Same group chat → implicit member")
        return True, None

    _fail("Step 1 FAIL", "Chat IDs do not match")

    # ── Step 2: Prior event participation ────────────────────
    _info("Step 2", "Prior event participation in group")
    participant_check = await session.execute(
        select(EventParticipant.event_id)
        .join(Event, EventParticipant.event_id == Event.event_id)
        .where(
            Event.group_id == group_id,
            EventParticipant.telegram_user_id == uid,
        )
        .limit(1)
    )
    prior = participant_check.scalar_one_or_none()
    if prior is not None:
        member_list = group.member_list or []
        if uid not in [int(m) for m in member_list]:
            group.member_list = [*member_list, uid]
            await session.flush()
        _pass("Step 2 PASS", f"Participated in event {prior}")
        return True, None

    _fail("Step 2 FAIL", "No prior event participation in this group")

    # ── Step 3: member_list cache ────────────────────────────
    _info("Step 3", "member_list cache check")
    member_list = group.member_list or []
    _info("  checking user_id", str(uid))
    _info("  member_list int values", str([int(m) for m in member_list]))

    if uid in [int(m) for m in member_list]:
        _pass("Step 3 PASS", "User found in cached member_list")
        return True, None

    _fail("Step 3 FAIL", "User not in member_list")

    # ── Step 4: Telegram API fallback ────────────────────────
    _info("Step 4", "Telegram API get_chat_member")
    if bot is not None:
        try:
            _info(
                "  calling get_chat_member",
                f"chat_id={group.telegram_group_id} user_id={uid}",
            )
            member = await asyncio.wait_for(
                bot.get_chat_member(
                    chat_id=group.telegram_group_id,
                    user_id=uid,
                ),
                timeout=10.0,
            )
            _info("  API returned", f"status={member.status}")
            if member.status in {"member", "administrator", "creator"}:
                group.member_list = [*member_list, uid]
                await session.flush()
                _pass("Step 4 PASS", f"Telegram API confirms: status={member.status}")
                return True, None
            _fail("Step 4 FAIL", f"Telegram API says: status={member.status}")
        except asyncio.TimeoutError:
            _fail("Step 4 FAIL", "Telegram API call timed out after 10s")
        except Exception as e:
            _fail("Step 4 FAIL", f"API error: {type(e).__name__}: {e}")
    else:
        _fail("Step 4 FAIL", "Bot not provided — cannot query Telegram API")

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

    Checks in order:
    1. Organizer/admin → always allowed
    2. Same group chat → implicit member
    3. Participant in THIS event → allowed
    4. Participant in ANY event in group → proven member
    5. member_list cache
    6. Telegram API get_chat_member (final fallback)
    7. DM invitation (callback with matching group_id) → allowed
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
    uid = int(user_id)

    _info("Event", f"{event.event_type} (state={event.state}, id={event.event_id})")
    _info("Organizer", str(event.organizer_telegram_user_id))
    _info("Admin", str(event.emergency_admin_telegram_user_id))

    # ── Check 1: Organizer / Admin ───────────────────────────
    _info("Check 1", "Organizer / Admin check")
    _info("  event.organizer_telegram_user_id", str(event.organizer_telegram_user_id))
    _info(
        "  event.emergency_admin_telegram_user_id",
        str(event.emergency_admin_telegram_user_id),
    )
    _info("  requesting user_id", str(uid))

    if event.organizer_telegram_user_id == uid:
        _pass("Check 1 PASS", "User is event organizer")
        return True, event, group, None

    if event.emergency_admin_telegram_user_id == uid:
        _pass("Check 1 PASS", "User is event admin")
        return True, event, group, None

    _fail("Check 1 FAIL", "Not organizer or admin")

    # ── Orphaned event ───────────────────────────────────────
    if not group:
        _fail("Orphaned event", "Event has no group → denied")
        return False, None, None, "Event not found"

    _info("Group", f"{group.group_name or 'unnamed'} (tg_id={group.telegram_group_id})")
    _info("Stored members", str(group.member_list or []))

    # ── Check 2: Same group chat ─────────────────────────────
    _info("Check 2", "Same group chat check")
    _info("  group.telegram_group_id", str(group.telegram_group_id))
    _info("  incoming telegram_chat_id", str(telegram_chat_id))

    if telegram_chat_id is not None and int(group.telegram_group_id) == int(
        telegram_chat_id
    ):
        member_list = group.member_list or []
        if uid not in [int(m) for m in member_list]:
            group.member_list = [*member_list, uid]
            await session.flush()
        _pass("Check 2 PASS", "Same group chat → implicit member")
        return True, event, group, None

    _fail("Check 2 FAIL", "Chat IDs do not match")

    # ── Check 3: Participant in THIS event ───────────────────
    _info("Check 3", "Participant in THIS event")
    _info("  event_id", str(event_id))
    _info("  user_id", str(uid))

    participant_check = await session.execute(
        select(EventParticipant.event_id)
        .where(
            EventParticipant.event_id == event_id,
            EventParticipant.telegram_user_id == uid,
        )
        .limit(1)
    )
    this_event = participant_check.scalar_one_or_none()
    if this_event is not None:
        _pass("Check 3 PASS", f"Already participant in event {this_event}")
        return True, event, group, None

    _fail("Check 3 FAIL", "Not a participant in this event")

    # ── Check 4: Participant in ANY event in group ───────────
    _info("Check 4", "Participant in ANY event in group")
    group_participant_check = await session.execute(
        select(EventParticipant.event_id)
        .join(Event, EventParticipant.event_id == Event.event_id)
        .where(
            Event.group_id == group.group_id,
            EventParticipant.telegram_user_id == uid,
        )
        .limit(1)
    )
    prior = group_participant_check.scalar_one_or_none()
    if prior is not None:
        member_list = group.member_list or []
        if uid not in [int(m) for m in member_list]:
            group.member_list = [*member_list, uid]
            await session.flush()
        _pass("Check 4 PASS", f"Participated in prior event {prior}")
        return True, event, group, None

    _fail("Check 4 FAIL", "No prior event participation in group")

    # ── Check 5: member_list cache ───────────────────────────
    _info("Check 5", "member_list cache check")
    member_list = group.member_list or []
    _info("  checking user_id", str(uid))
    _info("  member_list int values", str([int(m) for m in member_list]))

    if uid in [int(m) for m in member_list]:
        _pass("Check 5 PASS", "User found in cached member_list")
        return True, event, group, None

    _fail("Check 5 FAIL", "User not in member_list")

    # ── Check 6: Telegram API fallback ───────────────────────
    _info("Check 6", "Telegram API get_chat_member")
    if bot is not None:
        try:
            _info(
                "  calling get_chat_member",
                f"chat_id={group.telegram_group_id} user_id={uid}",
            )
            member = await asyncio.wait_for(
                bot.get_chat_member(
                    chat_id=group.telegram_group_id,
                    user_id=uid,
                ),
                timeout=10.0,
            )
            _info("  API returned", f"status={member.status}")
            if member.status in {"member", "administrator", "creator"}:
                group.member_list = [*member_list, uid]
                await session.flush()
                _pass("Check 6 PASS", f"Telegram API confirms: status={member.status}")
                return True, event, group, None
            _fail("Check 6 FAIL", f"Telegram API says: status={member.status}")
        except asyncio.TimeoutError:
            _fail("Check 6 FAIL", "Telegram API call timed out after 10s")
        except Exception as e:
            _fail("Check 6 FAIL", f"API error: {type(e).__name__}: {e}")
    else:
        _fail("Check 6 FAIL", "Bot not provided — cannot query Telegram API")

    # ── Check 7: DM/group invitation (callback from bot) ─────
    _info("Check 7", "Invitation callback context")
    _info("  telegram_chat_id", str(telegram_chat_id))
    _info("  group.telegram_group_id", str(group.telegram_group_id))

    # If the user clicked a callback from the bot (DM or group),
    # they received an invitation and should be allowed access.
    if telegram_chat_id is not None:
        if uid not in [int(m) for m in member_list]:
            group.member_list = [*member_list, uid]
            await session.flush()
        _pass("Check 7 PASS", "Invitation callback — user has access")
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

    if event.organizer_telegram_user_id != telegram_user_id:
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

    # Check if user is organizer or admin
    if event.organizer_telegram_user_id == telegram_user_id:
        return True, None

    if event.emergency_admin_telegram_user_id == telegram_user_id:
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
    result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.telegram_user_id == telegram_user_id,
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

    # Organizer or admin can always modify
    if event.organizer_telegram_user_id == telegram_user_id:
        return True, None

    if event.emergency_admin_telegram_user_id == telegram_user_id:
        return True, None

    # Confirmed participants can modify in emergencies
    participant_result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.telegram_user_id == telegram_user_id,
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

    # Check if user is a participant
    participant_result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.telegram_user_id == telegram_user_id,
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

    if event.organizer_telegram_user_id == telegram_user_id:
        return "organizer"

    if event.emergency_admin_telegram_user_id == telegram_user_id:
        return "admin"

    participant_result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.telegram_user_id == telegram_user_id,
        )
    )
    participant = participant_result.scalar_one_or_none()

    if participant:
        return "participant"

    return None
