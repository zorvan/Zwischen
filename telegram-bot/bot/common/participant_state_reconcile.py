"""Helpers for reconciling event state after participant changes."""

from __future__ import annotations

from sqlalchemy import func, select

from bot.services import EventLifecycleService
from db.models import Event, EventParticipant, ParticipantStatus


async def reconcile_event_state_after_participant_change(
    *,
    session,
    bot,
    event_id: int,
    actor_telegram_user_id: int,
    source: str,
    reason: str,
) -> Event:
    """Step event state down when confirmations/participants drop.

    This keeps slash and callback flows aligned after unconfirm/cancel actions.
    """
    event_result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = event_result.scalar_one_or_none()
    if event is None:
        raise ValueError(f"Event {event_id} not found")

    if event.state in {"locked", "completed", "cancelled"}:
        return event

    active_count_result = await session.execute(
        select(func.count(EventParticipant.telegram_user_id)).where(
            EventParticipant.event_id == event_id,
            EventParticipant.status.in_(
                [
                    ParticipantStatus.joined,
                    ParticipantStatus.confirmed,
                ]
            ),
        )
    )
    active_count = int(active_count_result.scalar_one() or 0)

    confirmed_count_result = await session.execute(
        select(func.count(EventParticipant.telegram_user_id)).where(
            EventParticipant.event_id == event_id,
            EventParticipant.status == ParticipantStatus.confirmed,
        )
    )
    confirmed_count = int(confirmed_count_result.scalar_one() or 0)

    target_state = None
    if event.state == "confirmed" and confirmed_count == 0:
        target_state = "interested" if active_count > 0 else "proposed"
    elif event.state == "interested" and active_count == 0:
        target_state = "proposed"

    if target_state is None or target_state == event.state:
        return event

    lifecycle_service = EventLifecycleService(bot, session)
    event, _ = await lifecycle_service.transition_with_lifecycle(
        event_id=event_id,
        target_state=target_state,
        actor_telegram_user_id=actor_telegram_user_id,
        source=source,
        reason=reason,
        expected_version=event.version,
    )
    return event
