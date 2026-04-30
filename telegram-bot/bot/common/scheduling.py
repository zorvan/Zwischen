"""Shared scheduling helpers for conflict checks."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Event, EventParticipant, ParticipantStatus


DEFAULT_DURATION_MINUTES = 120
ACTIVE_STATES = {"proposed", "interested", "confirmed", "locked"}


async def _user_in_event(session: AsyncSession, event_id: int, telegram_user_id: int) -> bool:
    """Check whether a user is participant in event (new system)."""
    result = await session.execute(
        select(EventParticipant).where(
            EventParticipant.event_id == event_id,
            EventParticipant.telegram_user_id == telegram_user_id,
            EventParticipant.status.in_(
                [
                    ParticipantStatus.joined,
                    ParticipantStatus.confirmed,
                ]
            ),
        )
    )
    return result.scalar_one_or_none() is not None


def events_overlap(
    start_a,
    duration_a: int | None,
    start_b,
    duration_b: int | None,
) -> bool:
    """Check if two event intervals overlap."""
    if start_a is None or start_b is None:
        return False
    dur_a = duration_a or DEFAULT_DURATION_MINUTES
    dur_b = duration_b or DEFAULT_DURATION_MINUTES
    end_a = start_a + timedelta(minutes=dur_a)
    end_b = start_b + timedelta(minutes=dur_b)
    return start_a < end_b and start_b < end_a


async def find_user_event_conflict(
    session: AsyncSession,
    telegram_user_id: int,
    start_time,
    duration_minutes: int | None,
    ignore_event_id: int | None = None,
) -> Event | None:
    """Return first conflicting active event for a user, if any."""
    if start_time is None:
        return None

    result = await session.execute(select(Event).where(Event.state.in_(ACTIVE_STATES)))
    events = result.scalars().all()
    for event in events:
        if ignore_event_id is not None and event.event_id == ignore_event_id:
            continue
        # Check if user is participant using new system
        if not await _user_in_event(session, event.event_id, telegram_user_id):
            continue
        if events_overlap(
            start_time,
            duration_minutes,
            event.scheduled_time,
            event.duration_minutes,
        ):
            return event
    return None
