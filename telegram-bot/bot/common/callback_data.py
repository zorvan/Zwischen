#!/usr/bin/env python3
"""Compact callback data encoding for v3.5.

Telegram's inline keyboard callback_data has a 64-byte limit.
This module provides a compact encoding that replaces the fragile
`menu_event_select_{event_id}` format with `ev:{event_id}:{action}`.

Format: ev:<event_id>[:<group_id>]:<action>
Examples:
  - ev:123:view            (view event details)
  - ev:123:join            (join event)
  - ev:123:-4882211102:join (join event with group context)
  - ev:123:enrich          (open enrich sub-menu)

PRD v3.5 Section 6.1: Engineering - Callback Data Limit
"""
from typing import Optional, Tuple


# =============================================================================
# Constants
# =============================================================================

CALLBACK_PREFIX = "ev"
SEPARATOR = ":"

# Standard action names (shortened to save bytes where possible)
CALLBACK_ACTIONS = {
    "view": "view",  # View event details/panel
    "join": "join",  # Join event
    "relinquish": "relinquish",  # Leave/un-join (replaces "back")
    "commit": "commit",  # Confirm/commit (primary action)
    "confirm": "commit",  # Alias for commit (backward compatibility)
    "cancel": "cancel",  # Cancel participation
    "lock": "lock",  # Lock event (organizer)
    "unlock": "unlock",  # Unlock event (organizer)
    "enrich": "enrich",  # Open enrich sub-menu
    "enrich_idea": "enrich_idea",  # Add idea
    "enrich_hashtag": "enrich_hashtag",  # Add hashtag
    "enrich_memory": "enrich_memory",  # Add memory (post-event)
    "enrich_view": "enrich_view",  # View my contributions
    "constraint": "constraint",  # Open constraint sub-menu
    "constraint_add": "constraint_add",  # Add constraint
    "constraint_remove": "constraint_remove",  # Remove constraint
    "suggest_time": "suggest_time",  # Suggest time
    "negotiate_time": "negotiate_time",  # Negotiate time
    "back_to_panel": "back_to_panel",  # Return to main panel
    "back_to_list": "back_to_list",  # Return to event list
    "refresh": "refresh",  # Refresh live card
    "det": "det",  # Event details (shorthand)
}


# =============================================================================
# Encoding Functions
# =============================================================================


def encode_callback(action: str, event_id: int, group_id: Optional[int] = None) -> str:
    """
    Encode action and event ID into compact callback data.

    Format: ev:<event_id>[:<group_id>]:<action>
    group_id is included when provided for RBAC context (needed when button
    is clicked from DM rather than the original group chat).

    Args:
        action: Action name (should be in CALLBACK_ACTIONS)
        event_id: Event ID
        group_id: Optional group Telegram chat ID for RBAC context

    Returns:
        Encoded callback string

    Example:
        >>> encode_callback("join", 123)
        'ev:123:join'
        >>> encode_callback("join", 123, -4882211102)
        'ev:123:-4882211102:join'
    """
    if group_id is not None:
        return f"{CALLBACK_PREFIX}{SEPARATOR}{event_id}{SEPARATOR}{group_id}{SEPARATOR}{action}"
    return f"{CALLBACK_PREFIX}{SEPARATOR}{event_id}{SEPARATOR}{action}"


def decode_callback(callback_data: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Decode compact callback data into action, event ID, and optional group ID.

    Supports both formats:
      - Legacy: ev:<event_id>:<action>       (3 parts, no group_id)
      - New:    ev:<event_id>:<group_id>:<action>  (4 parts, with group_id)

    Returns (None, None, None) for invalid formats.

    Args:
        callback_data: Raw callback data string from Telegram

    Returns:
        Tuple of (action_name, event_id, group_id) or (None, None, None) if invalid

    Example:
        >>> decode_callback("ev:123:join")
        ('join', 123, None)
        >>> decode_callback("ev:123:-4882211102:join")
        ('join', 123, -4882211102)
        >>> decode_callback("invalid_format")
        (None, None, None)
    """
    if not callback_data:
        return None, None, None

    # Must start with correct prefix
    if not callback_data.startswith(f"{CALLBACK_PREFIX}{SEPARATOR}"):
        return None, None, None

    parts = callback_data.split(SEPARATOR)

    if len(parts) < 3 or len(parts) > 4:
        return None, None, None

    prefix = parts[0]

    # Validate prefix
    if prefix != CALLBACK_PREFIX:
        return None, None, None

    # Validate event ID is numeric
    try:
        event_id = int(parts[1])
    except ValueError:
        return None, None, None

    if len(parts) == 3:
        # Legacy format: ev:event_id:action
        action = parts[2]
        group_id = None
    else:
        # New format: ev:event_id:group_id:action
        try:
            group_id = int(parts[2])
        except ValueError:
            return None, None, None
        action = parts[3]

    # Validate action is not empty
    if not action:
        return None, None, None

    return action, event_id, group_id


def is_valid_callback(callback_data: str) -> bool:
    """
    Check if callback data is valid v3.5 format.

    Args:
        callback_data: Raw callback data string

    Returns:
        True if valid format
    """
    action, event_id, _ = decode_callback(callback_data)
    return action is not None and event_id is not None


def extract_event_id(callback_data: str) -> Optional[int]:
    """
    Extract just the event ID from callback data.

    Convenience function for quick event ID extraction.

    Args:
        callback_data: Raw callback data string

    Returns:
        Event ID or None if invalid
    """
    _, event_id, _ = decode_callback(callback_data)
    return event_id


def extract_action(callback_data: str) -> Optional[str]:
    """
    Extract just the action from callback data.

    Convenience function for quick action extraction.

    Args:
        callback_data: Raw callback data string

    Returns:
        Action name or None if invalid
    """
    action, _, _ = decode_callback(callback_data)
    return action


def extract_group_id(callback_data: str) -> Optional[int]:
    """
    Extract just the group ID from callback data.

    Convenience function for quick group ID extraction.

    Args:
        callback_data: Raw callback data string

    Returns:
        Group ID or None if invalid or not present
    """
    _, _, group_id = decode_callback(callback_data)
    return group_id


# =============================================================================
# Builder Functions for Common Patterns
# =============================================================================


def build_event_list_callback(page: int = 0) -> str:
    """
    Build callback for event list pagination.

    Separate from event callbacks as this doesn't include event_id.

    Args:
        page: Page number for pagination

    Returns:
        Callback data string
    """
    return f"{CALLBACK_PREFIX}{SEPARATOR}list{SEPARATOR}{page}"


def build_create_event_callback() -> str:
    """
    Build callback for create event button.

    Returns:
        Callback data string
    """
    return f"{CALLBACK_PREFIX}{SEPARATOR}create{SEPARATOR}new"


def is_event_callback(callback_data: str) -> bool:
    """
    Check if callback is an event-related callback (not list/create).

    Args:
        callback_data: Raw callback data string

    Returns:
        True if this is an event action callback
    """
    action, event_id, _ = decode_callback(callback_data)
    return action is not None and event_id is not None


def is_list_callback(callback_data: str) -> bool:
    """
    Check if callback is an event list callback.

    Args:
        callback_data: Raw callback data string

    Returns:
        True if this is a list navigation callback
    """
    if not callback_data:
        return False

    parts = callback_data.split(SEPARATOR)
    return len(parts) == 3 and parts[0] == CALLBACK_PREFIX and parts[1] == "list"


def is_create_callback(callback_data: str) -> bool:
    """
    Check if callback is a create event callback.

    Args:
        callback_data: Raw callback data string

    Returns:
        True if this is a create event callback
    """
    return callback_data == f"{CALLBACK_PREFIX}{SEPARATOR}create{SEPARATOR}new"


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "CALLBACK_PREFIX",
    "SEPARATOR",
    "CALLBACK_ACTIONS",
    "encode_callback",
    "decode_callback",
    "is_valid_callback",
    "extract_event_id",
    "extract_action",
    "extract_group_id",
    "build_event_list_callback",
    "build_create_event_callback",
    "is_event_callback",
    "is_list_callback",
    "is_create_callback",
]
