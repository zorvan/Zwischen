"""
Canonical Action Registry - Phase 1: LLM Infrastructure
v3.4 Rebuild Specification Section 3.2

This module defines a single source of truth for all actions the LLM can infer.
Each action includes:
- description: What the action does (for LLM reasoning)
- required_params: Parameters that MUST be present
- optional_params: Parameters that MAY be present
- validation_rules: Custom validation logic (optional)

The registry replaces fragmented prompt patterns with a unified contract.
"""

from typing import Any, Dict, List, Optional


class ActionsRegistry:
    """
    Canonical action registry for LLM action inference.

    v3.4 Design:
    - Single source of truth for all actions
    - LLM receives descriptions, not just names
    - Application-layer validation before dispatch
    - Consistent output contract across all LLM calls
    """

    @staticmethod
    def get_actions() -> Dict[str, Dict[str, Any]]:
        """
        Returns the complete action registry.

        Each action defines:
        - description: Explains WHEN to use this action (for LLM reasoning)
        - required_params: Must be present for valid dispatch
        - optional_params: May be present
        - validation_rules: Custom validation logic per action
        """
        return {
            "view_events": {
                "description": (
                    "User wants to see their events list. "
                    "Use when user asks for 'events', 'my events', 'what events', "
                    "'list events', or similar. Do NOT use for creating or managing events."
                ),
                "required_params": [],
                "optional_params": ["group_id", "filter_state"],
            },
            "create_event": {
                "description": (
                    "User wants to create a new event. "
                    "Use when message expresses intent to organize, plan, gather, "
                    "schedule, or start an event. This is the PRIMARY creation path. "
                    "If user mentions 'organize', 'plan', 'schedule', 'start event', etc., "
                    "use this action."
                ),
                "required_params": [],
                "optional_params": [
                    "description",
                    "event_type",
                    "scheduled_time",
                    "duration_minutes",
                    "min_participants",
                    "target_participants",
                ],
            },
            "edit_event": {
                "description": (
                    "User wants to modify an existing event. "
                    "Use when user says 'edit', 'change', 'modify', 'update' event. "
                    "Requires event_id to identify which event to edit."
                ),
                "required_params": ["event_id"],
                "optional_params": [
                    "description",
                    "scheduled_time",
                    "duration_minutes",
                    "min_participants",
                ],
            },
            "join_event": {
                "description": (
                    "User wants to join a specific event. "
                    "Use when user says 'join', 'participate', 'attend', 'sign up' "
                    "for an event. Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "relinquish_event": {
                "description": (
                    "User wants to leave/cancel their participation in an event. "
                    "Use when user says 'leave', 'cancel', 'remove myself', 'don't join', "
                    "'opt out' of an event. Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "commit_event": {
                "description": (
                    "User wants to formally commit to an event (confirmed participation). "
                    "Use when user says 'confirm', 'commit', 'final', 'locked in' for an event. "
                    "Requires event_id. Only show this button when gravity threshold is met."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "unconfirm_event": {
                "description": (
                    "User wants to unconfirm their participation. "
                    "Use when user says 'unconfirm', 'retract commitment', 'not sure anymore'. "
                    "Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "lock_event": {
                "description": (
                    "User (organizer) wants to lock the event. "
                    "Use when organizer says 'lock', 'finalize', 'close registrations' "
                    "for an event. Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "unlock_event": {
                "description": (
                    "User (organizer) wants to unlock a locked event. "
                    "Use when organizer says 'unlock', 'reopen', 'make changes' for a locked event. "
                    "Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "cancel_event": {
                "description": (
                    "User (organizer) wants to cancel an event. "
                    "Use when organizer says 'cancel', 'call off', 'postpone', 'scraps' an event. "
                    "Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": ["reason"],
            },
            "complete_event": {
                "description": (
                    "User (organizer) wants to mark an event as completed. "
                    "Use when organizer says 'complete', 'finish', 'ended' an event. "
                    "Triggers memory collection flow. Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "add_idea": {
                "description": (
                    "User wants to contribute an idea during event formation. "
                    "Ideas are planning suggestions (location, activity, timing) visible "
                    "only to organizer until event locks. Requires event_id and content."
                ),
                "required_params": ["event_id", "content"],
                "optional_params": [],
            },
            "add_hashtag": {
                "description": (
                    "User wants to contribute a hashtag during event formation. "
                    "Hashtags attach to the live card after 2+ exist. Requires event_id and content. "
                    "Up to 3 hashtags per member per event."
                ),
                "required_params": ["event_id", "content"],
                "optional_params": [],
            },
            "add_memory": {
                "description": (
                    "User wants to contribute a memory after event completion. "
                    "Memories are stored privately until mosaic assembles. "
                    "Max 200 words. Requires event_id and content."
                ),
                "required_params": ["event_id", "content"],
                "optional_params": [],
            },
            "view_contributions": {
                "description": (
                    "User wants to see their own contributions (ideas, hashtags, memories) "
                    "for a specific event. Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": ["contribution_type"],
            },
            "add_constraint_if_joins": {
                "description": (
                    "User wants to set a constraint: 'I'll join IF [person] joins'. "
                    "This constraint type means the user will only join if the target user "
                    "also joins. Requires event_id and target_username."
                ),
                "required_params": ["event_id", "target_username"],
                "optional_params": [],
            },
            "add_constraint_if_attends": {
                "description": (
                    "User wants to set a constraint: 'I'll join ONLY IF [person] attends'. "
                    "This constraint type means the user commits only if the target user "
                    "attends (post-join confirmation). Requires event_id and target_username."
                ),
                "required_params": ["event_id", "target_username"],
                "optional_params": [],
            },
            "add_constraint_unless_joins": {
                "description": (
                    "User wants to set a constraint: 'I won't join UNLESS [person] joins'. "
                    "This constraint type means the user will NOT join if the target user "
                    "joins. Requires event_id and target_username."
                ),
                "required_params": ["event_id", "target_username"],
                "optional_params": [],
            },
            "add_availability": {
                "description": (
                    "User wants to set availability time slots for flexible events. "
                    "Requires event_id and time_slots (list of ISO datetime ranges)."
                ),
                "required_params": ["event_id", "time_slots"],
                "optional_params": [],
            },
            "remove_constraint": {
                "description": (
                    "User wants to remove an existing constraint. "
                    "Requires constraint_id to identify which constraint to remove."
                ),
                "required_params": ["constraint_id"],
                "optional_params": [],
            },
            "view_constraints": {
                "description": (
                    "User wants to see their constraints for a specific event. "
                    "Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "view_event_details": {
                "description": (
                    "User wants to see detailed information about a specific event. "
                    "Includes header, lineage fragment, hashtags, and action buttons. "
                    "Requires event_id."
                ),
                "required_params": ["event_id"],
                "optional_params": ["tab"],
            },
            "list_my_events": {
                "description": (
                    "User wants to see all events they participate in across all groups. "
                    "No group_id filter. Return events sorted by pending actions first."
                ),
                "required_params": [],
                "optional_params": [],
            },
            "back_to_events_list": {
                "description": (
                    "User wants to return from an event panel to the main events list. "
                    "No parameters needed. This is a navigation action."
                ),
                "required_params": [],
                "optional_params": [],
            },
            "opinion": {
                "description": (
                    "User message is chat/conversation with no action required. "
                    "Use when user is asking a question, making a comment, or chatting. "
                    "The LLM should generate a helpful assistant_response. "
                    "This is the fallback for ambiguous or conversational messages."
                ),
                "required_params": [],
                "optional_params": ["assistant_response"],
            },
            "help": {
                "description": (
                    "User explicitly asks for help or guidance. "
                    "Use when user says 'help', 'what can I do', 'how does this work'. "
                    "Generate a helpful response with available commands/options."
                ),
                "required_params": [],
                "optional_params": [],
            },
            "clarify": {
                "description": (
                    "User intent is too ambiguous to determine action. "
                    "Use when the message could map to multiple actions or is unclear. "
                    "The LLM should ask a clarifying question. "
                    "This is NOT for missing params - use recoverable validation for that."
                ),
                "required_params": [],
                "optional_params": ["question"],
            },
        }

    @staticmethod
    def get_action_names() -> List[str]:
        """Returns a list of all action names."""
        return list(ActionsRegistry.get_actions().keys())

    @staticmethod
    def get_action_description(action_name: str) -> str:
        """Returns the description for a specific action."""
        actions = ActionsRegistry.get_actions()
        if action_name not in actions:
            return "Unknown action"
        return actions[action_name]["description"]

    @staticmethod
    def get_required_params(action_name: str) -> List[str]:
        """Returns required parameters for an action."""
        actions = ActionsRegistry.get_actions()
        if action_name not in actions:
            return []
        return actions[action_name].get("required_params", [])

    @staticmethod
    def get_optional_params(action_name: str) -> List[str]:
        """Returns optional parameters for an action."""
        actions = ActionsRegistry.get_actions()
        if action_name not in actions:
            return []
        return actions[action_name].get("optional_params", [])
