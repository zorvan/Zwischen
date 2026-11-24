"""Confirmation invalidation helpers."""

from __future__ import annotations

from db.models import ParticipantStatus


async def _send_dms(context, event, user_ids: list[int], message: str) -> None:
    """DM internal users over Telegram, skipping anyone unreachable there.

    Participant rows carry internal ``users.user_id`` values; using them as
    Telegram chat IDs sends to the wrong chat or fails.
    """
    from sqlalchemy.ext.asyncio import async_object_session

    from db.identity import telegram_chat_ids

    session = async_object_session(event)
    if session is not None:
        chats = await telegram_chat_ids(session, user_ids)
    else:
        from config.settings import settings
        from db.connection import get_session

        async with get_session(settings.db_url or "") as fresh:
            chats = await telegram_chat_ids(fresh, user_ids)

    for user_id in user_ids:
        chat_id = chats.get(int(user_id))
        if chat_id is None:
            continue
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            # User may not have started bot or blocked DM.
            continue


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
    confirmed_ids = [int(participant.user_id) for participant in confirmed_participants]
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
    await _send_dms(context, event, confirmed_ids, message)
    return len(confirmed_ids)


async def notify_attendees_of_modification(
    *,
    context,
    event,
    reason: str,
) -> int:
    """Notify all active attendees of event modification."""
    active_ids = [int(p.user_id) for p in _active_participants(event)]
    if not active_ids:
        return 0

    message = (
        f"📝 Event {event.event_id} has been modified.\n"
        f"Reason: {reason}\n\n"
        "Please review the updated event details."
    )
    await _send_dms(context, event, active_ids, message)
    return len(active_ids)
