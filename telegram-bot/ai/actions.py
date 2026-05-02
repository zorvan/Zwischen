#!/usr/bin/env python3
"""Canonical Action Registry for v3.5.

This module provides:
- ACTIONS: Registry of all dispatchable actions with descriptions and params
- ACTION_HANDLERS: Mapping from action to handler module path
- Validation constants and functions for application-layer validation

PRD v3.5 Section 3.2: The Scalable Solution - Canonical Action Registry + Structured Dispatch
"""
from typing import Dict, Any, Set


# =============================================================================
# Canonical Action Registry
# =============================================================================

ACTIONS: Dict[str, Dict[str, Any]] = {
    "view_events": {
        "description": "User wants to see their list of events",
        "required_params": [],
        "optional_params": ["group_id"],
    },
    "view_event_panel": {
        "description": "User wants to see details or act on a specific event",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "join_event": {
        "description": "User wants to join a specific event they were invited to",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "relinquish_event": {
        "description": "User wants to leave or withdraw from an event they joined",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "commit_event": {
        "description": "User wants to confirm/commit to an event that has reached its minimum",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "lock_event": {
        "description": "Organizer wants to lock an event (finalize attendance)",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "create_event": {
        "description": "User wants to organize, plan, or create a new event. Use when message expresses intent to gather, meet, or do something together.",
        "required_params": [],
        "optional_params": ["description", "event_type", "scheduled_time"],
    },
    "add_constraint": {
        "description": "User wants to express a conditional participation constraint (if X joins, unless Y comes, etc.)",
        "required_params": ["event_id", "constraint_type", "target_username"],
        "optional_params": [],
    },
    "suggest_time": {
        "description": "User wants to suggest or negotiate a time for an event",
        "required_params": ["event_id"],
        "optional_params": ["suggested_time"],
    },
    "opinion": {
        "description": "User is asking a general question, chatting, or the intent is unclear — no event action needed",
        "required_params": [],
        "optional_params": ["assistant_response"],
    },
}


# =============================================================================
# Action Handler Mapping
# =============================================================================

ACTION_HANDLERS: Dict[str, str] = {
    "view_events": "bot.commands.events",
    "view_event_panel": "bot.handlers.event_panel",
    "join_event": "bot.handlers.event_panel",
    "relinquish_event": "bot.handlers.event_panel",
    "commit_event": "bot.handlers.event_panel",
    "lock_event": "bot.handlers.event_panel",
    "create_event": "bot.commands.events",
    "add_constraint": "bot.handlers.event_panel",
    "suggest_time": "bot.handlers.event_panel",
    "opinion": "bot.handlers.mentions",
}


# =============================================================================
# Application-Layer Validation Constants (replaces SQL CHECK constraints)
# =============================================================================

VALID_CONSTRAINT_TYPES: Set[str] = {"if_joins", "if_attends", "unless_joins"}

VALID_LOG_ACTIONS: Set[str] = {
    # Legacy actions
    "organize_event",
    "join",
    "confirm",
    "cancel",
    "suggest_time",
    "nudge",
    "constraint_update",
    # v3.5 new actions
    "relinquish",
    "enrich_idea",
    "enrich_hashtag",
    "enrich_memory",
    "lock",
    "complete",
    "collapse",
}

VALID_GROUP_TYPES: Set[str] = {"casual", "gathering", "tournament"}


# =============================================================================
# Validation Exceptions
# =============================================================================


class ValidationError(ValueError):
    """Raised when validation fails for constraint types or log actions."""

    pass


# =============================================================================
# Validation Functions
# =============================================================================


def validate_constraint_type(value: str) -> str:
    """
    Validate and normalize constraint type.

    Replaces SQL CHECK constraint on constraints.type.
    Raises ValidationError if type is not recognized.

    Args:
        value: The constraint type string to validate

    Returns:
        Normalized (lowercase, stripped) constraint type

    Raises:
        ValidationError: If the constraint type is not valid
    """
    if not value or not isinstance(value, str):
        raise ValidationError(
            f"Constraint type must be a non-empty string, got: {value!r}"
        )

    normalized = value.strip().lower()
    if normalized not in VALID_CONSTRAINT_TYPES:
        raise ValidationError(
            f"Unknown constraint type: {value!r}. "
            f"Valid types: {', '.join(sorted(VALID_CONSTRAINT_TYPES))}"
        )
    return normalized


def validate_log_action(value: str) -> str:
    """
    Validate and normalize log action.

    Replaces SQL CHECK constraint on logs.action.
    Raises ValidationError if action is not recognized.

    Args:
        value: The log action string to validate

    Returns:
        Normalized (lowercase, stripped) action name

    Raises:
        ValidationError: If the action is not valid
    """
    if not value or not isinstance(value, str):
        raise ValidationError(f"Log action must be a non-empty string, got: {value!r}")

    normalized = value.strip().lower()
    if normalized not in VALID_LOG_ACTIONS:
        raise ValidationError(
            f"Unknown log action: {value!r}. "
            f"Valid actions: {', '.join(sorted(VALID_LOG_ACTIONS))}"
        )
    return normalized


def validate_group_type(value: str) -> str:
    """
    Validate and normalize group type.

    Replaces SQL CHECK constraint on groups.group_type.
    Note: Unlike the SQL CHECK, this doesn't reject unknown types - it just normalizes.

    Args:
        value: The group type string to validate

    Returns:
        Normalized (lowercase, stripped) group type
    """
    if not value or not isinstance(value, str):
        return "casual"  # Default

    normalized = value.strip().lower()
    return normalized if normalized in VALID_GROUP_TYPES else normalized


def get_action_schema(action_name: str) -> Dict[str, Any]:
    """
    Get the schema definition for an action.

    Args:
        action_name: Name of the action to look up

    Returns:
        Action schema dict with description, required_params, optional_params

    Raises:
        KeyError: If action is not in the registry
    """
    if action_name not in ACTIONS:
        raise KeyError(f"Unknown action: {action_name!r}")
    return ACTIONS[action_name].copy()


def get_handler_path(action_name: str) -> str:
    """
    Get the handler module path for an action.

    Args:
        action_name: Name of the action to look up

    Returns:
        Module path string for the handler

    Raises:
        KeyError: If action is not in the registry
    """
    if action_name not in ACTION_HANDLERS:
        raise KeyError(f"No handler registered for action: {action_name!r}")
    return ACTION_HANDLERS[action_name]


def list_actions() -> list:
    """Return a list of all registered action names."""
    return list(ACTIONS.keys())


def is_valid_action(action_name: str) -> bool:
    """Check if an action name is registered."""
    return action_name in ACTIONS


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "ACTIONS",
    "ACTION_HANDLERS",
    "VALID_CONSTRAINT_TYPES",
    "VALID_LOG_ACTIONS",
    "VALID_GROUP_TYPES",
    "ValidationError",
    "validate_constraint_type",
    "validate_log_action",
    "validate_group_type",
    "get_action_schema",
    "get_handler_path",
    "list_actions",
    "is_valid_action",
]
