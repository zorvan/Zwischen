"""Shared event state definitions."""

from typing import Dict, List

EVENT_STATE_TRANSITIONS: Dict[str, List[str]] = {
    "proposed": ["interested", "cancelled"],
    "interested": ["confirmed", "cancelled"],
    "confirmed": ["interested", "proposed", "locked", "cancelled"],
    "locked": ["completed", "cancelled"],
    "cancelled": [],
    "completed": [],
}

STATE_EXPLANATIONS = {
    "proposed": "Event created; participants should join.",
    "interested": "People joined; waiting for commitments.",
    "confirmed": "At least one participant committed attendance.",
    "locked": "Event is finalized; attendance is closed.",
    "cancelled": "Event was cancelled.",
    "completed": "Event finished.",
}


def can_transition(current_state: str, target_state: str) -> bool:
    """Check if a state transition is valid."""
    return target_state in EVENT_STATE_TRANSITIONS.get(current_state, [])


def get_available_actions(
    user_status: str, event_state: str, is_organizer: bool = False
) -> list[str]:
    """
    Phase 2: Get context-aware available actions for a user.

    Returns list of action names that should be visible as buttons.
    Only returns actions that would actually work - no disabled buttons.
    """
    actions = []

    # Back to list (always available when viewing an event)
    actions.append("back")

    # Join action (if invited but not joined, event in forming state)
    if user_status == "invited" and event_state in ["proposed", "interested"]:
        actions.append("join")

    # If user has joined, show different options
    if user_status in ["joined", "confirmed"]:
        actions.append("relinquish")
        actions.append("enrich")
        actions.append("constraint")

        # Commit button (if gravity met)
        if event_state in ["proposed", "interested"]:
            actions.append("commit")

    # Organizer-specific actions
    if is_organizer:
        actions.append("lock")
        actions.append("edit_event")

    return actions
