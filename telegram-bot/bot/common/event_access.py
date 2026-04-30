"""Access helpers for event organizer/attendee checks."""

from __future__ import annotations


def get_event_organizer_telegram_id(event) -> int | None:
    """Resolve organizer ID from explicit event field."""
    organizer = getattr(event, "organizer_telegram_user_id", None)
    if organizer:
        return int(organizer)
    return None


def get_event_admin_telegram_id(event) -> int | None:
    """Resolve admin ID from explicit field or fallback to organizer."""
    admin = getattr(event, "emergency_admin_telegram_user_id", None)
    if admin:
        return int(admin)
    return get_event_organizer_telegram_id(event)


def is_attendee(event, telegram_user_id: int) -> bool:
    """Check whether user is a participant in the normalized participant table."""
    tid = int(telegram_user_id)
    participants = getattr(event, "participants", None)
    return any(p.telegram_user_id == tid for p in (participants or []))
