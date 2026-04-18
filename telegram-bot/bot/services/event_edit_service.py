#!/usr/bin/env python3
"""Event editing service using AI-powered patch inference."""

from __future__ import annotations

from ai.llm import LLMClient
from bot.common.confirmation import (
    invalidate_confirmations_and_notify,
    notify_attendees_of_modification,
)
from bot.common.event_access import get_event_admin_telegram_id
from db.models import Event


def _build_event_draft(event: Event) -> dict:
    """Build the current event draft used for LLM patch inference."""
    planning_prefs = (
        dict(event.planning_prefs) if isinstance(event.planning_prefs, dict) else {}
    )
    return {
        "description": event.description or "",
        "event_type": event.event_type,
        "scheduled_time": (
            event.scheduled_time.isoformat(timespec="minutes")
            if event.scheduled_time
            else None
        ),
        "duration_minutes": int(event.duration_minutes or 120),
        "min_participants": int(event.min_participants or 2),
        "target_participants": int(
            event.target_participants or event.min_participants or 2
        ),
        "scheduling_mode": "fixed" if event.scheduled_time else "flexible",
        "location_type": planning_prefs.get("location_type"),
        "budget_level": planning_prefs.get("budget_level"),
        "transport_mode": planning_prefs.get("transport_mode"),
    }


def _apply_inferred_event_patch(
    event: Event,
    patch: dict,
) -> tuple[list[str], list[str]]:
    """Apply inferred patch fields to an event and report what changed."""
    changed_fields: list[str] = []
    reason_parts: list[str] = []

    description = patch.get("description")
    if isinstance(description, str) and description.strip():
        next_description = description.strip()[:500]
        if next_description != (event.description or ""):
            event.description = next_description
            changed_fields.append("description")
            reason_parts.append("description changed")

    event_type = patch.get("event_type")
    if isinstance(event_type, str):
        normalized = event_type.strip().lower()
        if (
            normalized in {"social", "sports", "work"}
            and normalized != event.event_type
        ):
            event.event_type = normalized
            changed_fields.append("event_type")
            reason_parts.append("event type changed")

    min_participants = patch.get("min_participants")
    if min_participants is not None:
        try:
            value = int(min_participants)
            if value >= 1 and value != int(event.min_participants or 0):
                event.min_participants = value
                if int(event.target_participants or 0) < value:
                    event.target_participants = value
                    changed_fields.append("target_participants")
                changed_fields.append("min_participants")
                reason_parts.append("minimum changed")
        except (TypeError, ValueError):
            pass

    target_participants = patch.get("target_participants")
    if target_participants is not None:
        try:
            value = int(target_participants)
            current_min = int(event.min_participants or 1)
            if value >= current_min and value != int(event.target_participants or 0):
                event.target_participants = value
                changed_fields.append("target_participants")
                reason_parts.append("capacity changed")
        except (TypeError, ValueError):
            pass

    duration = patch.get("duration_minutes")
    if duration is not None:
        try:
            value = int(duration)
            if 1 <= value <= 720 and value != int(event.duration_minutes or 120):
                event.duration_minutes = value
                changed_fields.append("duration_minutes")
                reason_parts.append("duration changed")
        except (TypeError, ValueError):
            pass

    if bool(patch.get("clear_time")) and event.scheduled_time is not None:
        event.scheduled_time = None
        changed_fields.append("scheduled_time")
        reason_parts.append("time cleared")

    scheduled_time_iso = patch.get("scheduled_time_iso")
    if scheduled_time_iso is not None:
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(str(scheduled_time_iso).strip())
            if event.scheduled_time != parsed:
                event.scheduled_time = parsed
                changed_fields.append("scheduled_time")
                reason_parts.append("time changed")
        except ValueError:
            pass

    planning_prefs = (
        dict(event.planning_prefs) if isinstance(event.planning_prefs, dict) else {}
    )
    planning_changed = False

    for pref_key in ["location_type", "budget_level", "transport_mode"]:
        new_value = patch.get(pref_key)
        if isinstance(new_value, str) and new_value.strip():
            normalized = new_value.strip().lower()
            old_value = planning_prefs.get(pref_key)
            if old_value != normalized:
                planning_prefs[pref_key] = normalized
                planning_changed = True
                changed_fields.append(pref_key)
                reason_parts.append(f"{pref_key} changed to {normalized}")

    if planning_changed:
        event.planning_prefs = planning_prefs

    return changed_fields, reason_parts


async def process_event_edit(
    event: Event,
    user_input: str,
    *,
    user_id: int | None = None,
    context=None,
) -> tuple[bool, str]:
    """Process AI-based event edit request.

    Args:
        event: The event to edit
        user_input: Natural language description of changes
        user_id: ID of user requesting the edit (for admin check)
        context: Telegram context for sending notifications
        session: Database session for committing changes

    Returns:
        Tuple of (success: bool, message: str)

    Raises:
        PermissionError: If user is not admin and modification is blocked
        ValueError: If event is in a state that doesn't allow editing
    """
    if event.state in {"locked", "completed", "cancelled"}:
        return (
            False,
            f"❌ Event {event.event_id} is {event.state}; modification is not allowed.",
        )

    admin_id = get_event_admin_telegram_id(event)
    if user_id is not None and admin_id is not None and user_id != admin_id:
        return False, "❌ Only the event admin can modify this event."

    draft = _build_event_draft(event)
    llm = LLMClient()
    try:
        patch = await llm.infer_event_draft_patch(draft, user_input)
    finally:
        await llm.close()

    changed_fields, reason_parts = _apply_inferred_event_patch(event, patch)

    if not changed_fields:
        return False, "⚠️ No valid event change inferred from your message."

    if context is not None:
        invalidated = await invalidate_confirmations_and_notify(
            context=context,
            event=event,
            reason=", ".join(reason_parts) or "event details changed",
        )
        await notify_attendees_of_modification(
            context=context,
            event=event,
            reason=", ".join(reason_parts) or "event details changed",
        )

    return True, (
        f"✅ Event updated.\n"
        f"Changed fields: {', '.join(changed_fields)}\n"
        f"Confirmations reset: {invalidated if context else 'N/A'}"
    )


from bot.common.event_access import get_event_admin_telegram_id
from db.models import Event


def _build_event_draft(event: Event) -> dict:
    """Build the current event draft used for LLM patch inference."""
    planning_prefs = (
        dict(event.planning_prefs) if isinstance(event.planning_prefs, dict) else {}
    )
    return {
        "description": event.description or "",
        "event_type": event.event_type,
        "scheduled_time": (
            event.scheduled_time.isoformat(timespec="minutes")
            if event.scheduled_time
            else None
        ),
        "duration_minutes": int(event.duration_minutes or 120),
        "min_participants": int(event.min_participants or 2),
        "target_participants": int(
            event.target_participants or event.min_participants or 2
        ),
        "scheduling_mode": "fixed" if event.scheduled_time else "flexible",
        "location_type": planning_prefs.get("location_type"),
        "budget_level": planning_prefs.get("budget_level"),
        "transport_mode": planning_prefs.get("transport_mode"),
    }


def _apply_inferred_event_patch(
    event: Event,
    patch: dict,
) -> tuple[list[str], list[str]]:
    """Apply inferred patch fields to an event and report what changed."""
    changed_fields: list[str] = []
    reason_parts: list[str] = []

    description = patch.get("description")
    if isinstance(description, str) and description.strip():
        next_description = description.strip()[:500]
        if next_description != (event.description or ""):
            event.description = next_description
            changed_fields.append("description")
            reason_parts.append("description changed")

    event_type = patch.get("event_type")
    if isinstance(event_type, str):
        normalized = event_type.strip().lower()
        if (
            normalized in {"social", "sports", "work"}
            and normalized != event.event_type
        ):
            event.event_type = normalized
            changed_fields.append("event_type")
            reason_parts.append("event type changed")

    min_participants = patch.get("min_participants")
    if min_participants is not None:
        try:
            value = int(min_participants)
            if value >= 1 and value != int(event.min_participants or 0):
                event.min_participants = value
                if int(event.target_participants or 0) < value:
                    event.target_participants = value
                    changed_fields.append("target_participants")
                changed_fields.append("min_participants")
                reason_parts.append("minimum changed")
        except (TypeError, ValueError):
            pass

    target_participants = patch.get("target_participants")
    if target_participants is not None:
        try:
            value = int(target_participants)
            current_min = int(event.min_participants or 1)
            if value >= current_min and value != int(event.target_participants or 0):
                event.target_participants = value
                changed_fields.append("target_participants")
                reason_parts.append("capacity changed")
        except (TypeError, ValueError):
            pass

    duration = patch.get("duration_minutes")
    if duration is not None:
        try:
            value = int(duration)
            if 1 <= value <= 720 and value != int(event.duration_minutes or 120):
                event.duration_minutes = value
                changed_fields.append("duration_minutes")
                reason_parts.append("duration changed")
        except (TypeError, ValueError):
            pass

    if bool(patch.get("clear_time")) and event.scheduled_time is not None:
        event.scheduled_time = None
        changed_fields.append("scheduled_time")
        reason_parts.append("time cleared")

    scheduled_time_iso = patch.get("scheduled_time_iso")
    if scheduled_time_iso is not None:
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(str(scheduled_time_iso).strip())
            if event.scheduled_time != parsed:
                event.scheduled_time = parsed
                changed_fields.append("scheduled_time")
                reason_parts.append("time changed")
        except ValueError:
            pass

    planning_prefs = (
        dict(event.planning_prefs) if isinstance(event.planning_prefs, dict) else {}
    )
    planning_changed = False

    for pref_key in ["location_type", "budget_level", "transport_mode"]:
        new_value = patch.get(pref_key)
        if isinstance(new_value, str) and new_value.strip():
            normalized = new_value.strip().lower()
            old_value = planning_prefs.get(pref_key)
            if old_value != normalized:
                planning_prefs[pref_key] = normalized
                planning_changed = True
                changed_fields.append(pref_key)
                reason_parts.append(f"{pref_key} changed to {normalized}")

    if planning_changed:
        event.planning_prefs = planning_prefs

    return changed_fields, reason_parts



    return changed_fields, reason_parts
