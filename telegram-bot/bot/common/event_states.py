"""Shared event state definitions."""

from typing import Dict, List, Optional

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


def get_available_actions(user_status: str, event_state: str) -> List[str]:
    """
    Get list of available actions for a user based on their status and event state.
    
    PRD v3.5 Section 2.1: Helper for context-aware button visibility.
    
    Args:
        user_status: Current participation status (joined, confirmed, etc.)
        event_state: Current event state (proposed, confirmed, locked, etc.)
        
    Returns:
        List of action names that should be visible to this user
    """
    actions = []
    
    # Can always view details
    actions.append("view")
    
    # If event is locked, limited actions
    if event_state == "locked":
        return actions  # Just view for locked events
    
    # Based on user status
    if user_status is None:
        # Not participating - can join
        actions.append("join")
    elif user_status == "joined":
        # Joined - can enrich, constrain, relinquish, commit
        actions.extend(["enrich", "constraint", "relinquish"])
        if event_state in ["confirmed", "interested"]:
            actions.append("commit")
    elif user_status == "confirmed":
        # Confirmed - can enrich, constrain, relinquish
        actions.extend(["enrich", "constraint", "relinquish"])
    
    return actions
