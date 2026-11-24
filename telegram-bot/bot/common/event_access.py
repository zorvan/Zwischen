"""Access helpers for event organizer/attendee checks.

Every ID these helpers return or accept is an internal ``users.user_id``.
The ``*_telegram_id`` names predate the identity migration and are kept as
aliases; to reach a user over Telegram, resolve through
``db.identity.telegram_chat_id``.
"""

from __future__ import annotations


def get_event_organizer_user_id(event) -> int | None:
    """Organizer's internal user ID."""
    organizer = getattr(event, "organizer_user_id", None)
    if organizer:
        return int(organizer)
    return None


def get_event_admin_user_id(event) -> int | None:
    """Admin's internal user ID, falling back to the organizer."""
    admin = getattr(event, "emergency_admin_user_id", None)
    if admin:
        return int(admin)
    return get_event_organizer_user_id(event)


# Backward-compatible names. They never returned Telegram IDs after the
# contract migration, which is exactly the confusion the new names remove.
get_event_organizer_telegram_id = get_event_organizer_user_id
get_event_admin_telegram_id = get_event_admin_user_id


def is_attendee(event, user_id: int) -> bool:
    """Check whether an internal user is in the event's participant rows."""
    uid = int(user_id)
    participants = getattr(event, "participants", None)
    return any(p.user_id == uid for p in (participants or []))
