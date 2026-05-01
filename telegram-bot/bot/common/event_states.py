"""Shared event state definitions.

Event State Machine
===================

```mermaid
stateDiagram-v2
    [*] --> proposed

    proposed --> interested: first non-organizer joins
    proposed --> confirmed: direct confirmation
    proposed --> cancelled: any participant

    interested --> confirmed: participant confirms
    interested --> proposed: last participant leaves
    interested --> cancelled: any participant

    confirmed --> interested: last confirmation removed
    confirmed --> proposed: all participants leave
    confirmed --> locked: organizer locks (threshold met)
    confirmed --> cancelled: any participant

    locked --> completed: organizer completes
    locked --> cancelled: organizer cancels
    locked --> confirmed: organizer unlocks

    cancelled --> [*]
    completed --> [*]

    note right of proposed
        Event created
        Participants can join
    end note

    note right of interested
        People joined
        Gathering momentum
    end note

    note right of confirmed
        At least one confirmed
        Organizer can lock
    end note

    note right of locked
        Finalized
        Attendance closed
        Unlock or complete
    end note
```

State Transition Rules
----------------------
- **proposed → interested**: First non-organizer participant joins
- **interested → confirmed**: Any participant confirms attendance
- **confirmed → locked**: Organizer locks when min_participants threshold is met
- **locked → confirmed**: Organizer unlocks (reopens participation)
- **locked → completed**: Event finishes
- **any → cancelled**: Any participant can cancel
- **Downgrades** (confirmed→interested, confirmed→proposed, interested→proposed):
  Only triggered automatically when participants leave, or by the organizer.
"""

from typing import Dict, List, Optional

EVENT_STATE_TRANSITIONS: Dict[str, List[str]] = {
    "proposed": ["interested", "confirmed", "cancelled"],
    "interested": ["confirmed", "cancelled"],
    "confirmed": ["interested", "proposed", "locked", "cancelled"],
    "locked": ["completed", "cancelled", "confirmed"],
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

# Mapping from event state to the set of allowed next states (for reference)
ALLOWED_NEXT_STATES: Dict[str, set] = {k: set(v) for k, v in EVENT_STATE_TRANSITIONS.items()}


def can_transition(current_state: str, target_state: str) -> bool:
    """Check if a state transition is valid."""
    return target_state in EVENT_STATE_TRANSITIONS.get(current_state, [])


def get_available_actions(
    user_status: Optional[str],
    event_state: str,
    is_organizer: bool = False,
    confirmed_count: int = 0,
    min_participants: int = 0,
) -> List[str]:
    """
    Get list of available actions for a user based on their status and event state.

    PRD v3.5 Section 2.1: Helper for context-aware button visibility.
    This is the single source of truth for which buttons to show in the event panel.

    Args:
        user_status: Current participation status (joined, confirmed, None if not participating)
        event_state: Current event state (proposed, interested, confirmed, locked, cancelled, completed)
        is_organizer: Whether the user is the event organizer
        confirmed_count: Number of confirmed participants (used for lock eligibility)
        min_participants: Minimum participants required to lock

    Returns:
        List of action names that should be visible to this user
    """
    actions = []

    # Always available
    actions.append("view")
    actions.append("back_to_list")
    actions.append("refresh")

    # Terminal states: very limited actions
    if event_state in ("cancelled", "completed"):
        return actions

    # Locked state: organizer can unlock or complete; participants can only view
    if event_state == "locked":
        if is_organizer:
            actions.append("unlock")
            actions.append("complete")
        return actions

    # Not participating
    if user_status is None:
        actions.append("join")
        return actions

    # Joined participant
    if user_status == "joined":
        actions.extend(["enrich", "constraint", "relinquish", "commit"])
        return actions

    # Confirmed participant
    if user_status == "confirmed":
        actions.extend(["enrich", "constraint", "relinquish"])
        return actions

    # Organizer-specific actions
    if is_organizer:
        # Can lock if confirmed state and threshold met
        if event_state == "confirmed" and confirmed_count >= min_participants:
            actions.append("lock")

    return actions


def build_event_panel_actions(
    user_status: Optional[str],
    event_state: str,
    is_organizer: bool = False,
    confirmed_count: int = 0,
    min_participants: int = 0,
) -> Dict[str, bool]:
    """
    Build a dict mapping action names to visibility booleans.

    This is a convenience wrapper around get_available_actions that returns
    a complete action map, useful for template-driven UI building.

    Args:
        user_status: Current participation status
        event_state: Current event state
        is_organizer: Whether the user is the organizer
        confirmed_count: Number of confirmed participants
        min_participants: Minimum participants required to lock

    Returns:
        Dict mapping all known action names to True/False visibility flags
    """
    available = set(get_available_actions(
        user_status, event_state, is_organizer, confirmed_count, min_participants
    ))

    # All known actions in the system
    all_actions = {
        "view", "join", "commit", "relinquish", "enrich", "constraint",
        "lock", "unlock", "complete", "back_to_list", "refresh",
        "enrich_idea", "enrich_hashtag", "enrich_memory", "enrich_contributions",
        "enrich_add_idea", "enrich_add_hashtag", "enrich_add_memory",
        "enrich_add_constraint", "enrich_add_constraint_unless", "enrich_suggest_time",
        "waitlist",
    }

    return {action: action in available for action in all_actions}
