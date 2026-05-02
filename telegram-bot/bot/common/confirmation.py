"""Confirmation invalidation helpers."""

from __future__ import annotations

from db.models import ParticipantStatus


def _active_participants(event) -> list:
    """Return participants still considered active for event coordination."""
    return [
        participant
        for participant in (getattr(event, "participants", None) or [])
        if participant.status in {ParticipantStatus.joined, ParticipantStatus.confirmed}
    ]


async def invalidate_confirmations_and_notify(
    *,
    context,
    event,
    reason: str,
) -> int:
    """Reset confirmations to interested state and notify previously confirmed users."""
    confirmed_participants = [
        participant
        for participant in _active_participants(event)
        if participant.status == ParticipantStatus.confirmed
    ]
    confirmed_ids = [
        int(participant.telegram_user_id) for participant in confirmed_participants
    ]
    if not confirmed_ids:
        return 0

    for participant in confirmed_participants:
        participant.status = ParticipantStatus.joined
        participant.confirmed_at = None

    event.state = "interested" if _active_participants(event) else "proposed"

    message = (
        f"🔁 Event {event.event_id} modified.\n"
        f"Reason: {reason}\n\n"
        "The event details have been updated. "
        f"Please check the event details again."
    )
    for telegram_user_id in confirmed_ids:
        try:
            await context.bot.send_message(chat_id=telegram_user_id, text=message)
        except Exception:
            # User may not have started bot or blocked DM.
            continue
    return len(confirmed_ids)


async def notify_attendees_of_modification(
    *,
    context,
    event,
    reason: str,
) -> int:
    """Notify all active attendees of event modification."""
    active_ids = [int(p.telegram_user_id) for p in _active_participants(event)]
    if not active_ids:
        return 0

    message = (
        f"📝 Event {event.event_id} has been modified.\n"
        f"Reason: {reason}\n\n"
        "Please review the updated event details."
    )
    for telegram_user_id in active_ids:
        try:
            await context.bot.send_message(chat_id=telegram_user_id, text=message)
        except Exception:
            # User may not have started bot or blocked DM.
            continue
    return len(active_ids)
