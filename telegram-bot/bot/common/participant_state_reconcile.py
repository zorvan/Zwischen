"""Helpers for reconciling event state after participant changes."""

from __future__ import annotations

from sqlalchemy import func, select

from bot.common.event_access import get_event_organizer_telegram_id
from bot.services import EventLifecycleService
from db.models import Event, EventParticipant, ParticipantStatus

# States that represent "downgrades" (moving backward in the lifecycle)
# These transitions require organizer permission to prevent accidental state loss
DOWNGRADE_TRANSITIONS = {
    ("confirmed", "interested"),
    ("confirmed", "proposed"),
    ("interested", "proposed"),
}


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
    If only the organizer remains, event goes back to proposed.

    Downgrade transitions (confirmed→interested, confirmed→proposed,
    interested→proposed) are only allowed when triggered by participant
    departure (not by a manual organizer action).
    """
    event_result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = event_result.scalar_one_or_none()
    if event is None:
        raise ValueError(f"Event {event_id} not found")

    if event.state in {"locked", "completed", "cancelled"}:
        return event

    organizer_id = get_event_organizer_telegram_id(event)

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

    # Check if only organizer remains among active participants
    organizer_remains_only = False
    if active_count > 0:
        organizer_participant_result = await session.execute(
            select(EventParticipant.telegram_user_id).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status.in_([ParticipantStatus.joined, ParticipantStatus.confirmed]),
                EventParticipant.telegram_user_id == organizer_id,
            )
        )
        organizer_is_active = organizer_participant_result.scalar_one() is not None
        if organizer_is_active and active_count == 1:
            organizer_remains_only = True

    confirmed_count_result = await session.execute(
        select(func.count(EventParticipant.telegram_user_id)).where(
            EventParticipant.event_id == event_id,
            EventParticipant.status == ParticipantStatus.confirmed,
        )
    )
    confirmed_count = int(confirmed_count_result.scalar_one() or 0)

    target_state = None
    if organizer_remains_only:
        target_state = "proposed"
    elif event.state == "confirmed" and confirmed_count == 0:
        target_state = "interested" if active_count > 0 else "proposed"
    elif event.state == "interested" and active_count == 0:
        target_state = "proposed"

    if target_state is None or target_state == event.state:
        return event

    # Check if this is a downgrade transition
    is_downgrade = (event.state, target_state) in DOWNGRADE_TRANSITIONS

    # Downgrade transitions are only allowed when triggered by participant
    # departure (source indicates automatic reconciliation), not by manual
    # organizer action. This prevents accidental state loss.
    if is_downgrade and source not in {"cancel", "unconfirm", "system"}:
        # Non-participant-departure downgrade: require organizer permission
        if actor_telegram_user_id != organizer_id:
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
