#!/usr/bin/env python3
"""Deadline and auto-lock utilities."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import Event


async def check_and_lock_expired_events(bot=None) -> list[dict]:
    """Check for events that have reached their deadline and auto-lock if threshold is met.

    Returns:
        List of dicts with event_id and status for each processed event
    """
    if not settings.db_url:
        return []

    results = []
    now = datetime.now(timezone.utc)

    async with get_session(settings.db_url) as session:
        events_to_check = (
            (
                await session.execute(
                    select(Event).where(
                        Event.state == "confirmed",
                        Event.commit_by.isnot(None),
                        Event.commit_by <= now,
                        Event.locked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        for event in events_to_check:
            try:
                result = await _try_auto_lock_event(session, event, now, bot)
                results.append(result)
            except Exception as e:
                results.append(
                    {
                        "event_id": int(event.event_id) if event.event_id else 0,
                        "status": "error",
                        "message": str(e),
                    }
                )

    return results


async def _try_auto_lock_event(session, event, now: datetime, bot=None) -> dict:
    """Try to auto-lock a single event.

    Returns:
        Dict with event_id, status, and message
    """
    try:
        from bot.services import ParticipantService

        # Use ParticipantService to get confirmed count
        participant_service = ParticipantService(session)
        current_confirmed = await participant_service.get_confirmed_count(
            event.event_id
        )
        threshold = int(event.min_participants or 2)

        if current_confirmed >= threshold:
            from bot.services import EventLifecycleService

            # Use EventLifecycleService for proper state transition
            if bot:
                lifecycle_service = EventLifecycleService(bot, session)
                try:
                    event, _ = await lifecycle_service.transition_with_lifecycle(
                        event_id=event.event_id,
                        target_state="locked",
                        actor_telegram_user_id=0,  # System actor
                        source="auto_lock",
                        reason="Auto-locked after deadline",
                        expected_version=event.version,
                    )
                except Exception as e:
                    return {
                        "event_id": int(event.event_id) if event.event_id else 0,
                        "status": "error",
                        "message": f"Failed to transition to locked: {str(e)}",
                    }
            else:
                # Fallback to direct transition if no bot available
                from bot.services import EventStateTransitionService

                transition_service = EventStateTransitionService(session)
                event, _ = await transition_service.transition(
                    event_id=event.event_id,
                    target_state="locked",
                    actor_telegram_user_id=0,
                    source="auto_lock",
                    reason="Auto-locked after deadline",
                    expected_version=event.version,
                )

            return {
                "event_id": int(event.event_id) if event.event_id else 0,
                "status": "locked",
                "message": (
                    f"Auto-locked event {event.event_id} after deadline reached "
                    f"with {current_confirmed}/{threshold} confirmed"
                ),
            }
        else:
            return {
                "event_id": int(event.event_id) if event.event_id else 0,
                "status": "not_locked",
                "message": f"Event {event.event_id} not locked: only {current_confirmed}/{threshold} confirmed",
            }
    except Exception as e:
        return {
            "event_id": int(event.event_id) if event.event_id else 0,
            "status": "error",
            "message": str(e),
        }


async def check_deadline_status(event_id: int) -> Optional[dict]:
    """Get deadline status for a specific event.

    Returns:
        Dict with deadline info or None if event not found
    """
    if not settings.db_url:
        return None

    async with get_session(settings.db_url) as session:
        event = (
            await session.execute(select(Event).where(Event.event_id == event_id))
        ).scalar_one_or_none()

        if not event:
            return None

        now = datetime.now(timezone.utc)
        commit_by = event.commit_by
        state = str(event.state or "")
        locked_at = event.locked_at

        time_remaining = None
        deadline_reached = False
        is_locked = state == "locked"

        if commit_by:
            time_remaining = commit_by - now
            deadline_reached = time_remaining.total_seconds() <= 0

        return {
            "event_id": int(event.event_id) if event.event_id else 0,
            "state": state,
            "commit_by": commit_by.isoformat() if commit_by else None,
            "deadline_reached": deadline_reached,
            "time_remaining_seconds": (
                int(time_remaining.total_seconds()) if time_remaining else None
            ),
            "is_locked": is_locked,
            "locked_at": locked_at.isoformat() if locked_at else None,
        }
