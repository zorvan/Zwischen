#!/usr/bin/env python3
"""TypedDict models and constants for all context.user_data state structures.

This module defines the canonical types for every in-memory state category
used by the bot. All handlers should reference these types rather than
guessing at dict key names or value types.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, NotRequired, TypedDict


# =============================================================================
# Event State Constants (source of truth for stage values)
# =============================================================================

EVENT_FLOW_STAGES = Literal[
    "description",
    "type",
    "date_preset",
    "date",
    "date_options",
    "time_window",
    "time_option",
    "time_manual",
    "min_participants",
    "target_participants",
    "duration",
    "location",
    "budget",
    "transport",
    "invitees",
    "final",
]

EVENT_TYPE_VALUES = Literal["social", "sports", "work"]
DATE_PRESET_VALUES = Literal["today", "tomorrow", "weekend", "nextweek", "custom"]
TIME_WINDOW_VALUES = Literal["morning", "afternoon", "evening", "night"]
SCHEDULING_MODE_VALUES = Literal["fixed", "flexible"]
LOCATION_TYPE_VALUES = Literal["home", "outdoor", "cafe", "office", "gym"]
BUDGET_LEVEL_VALUES = Literal["free", "low", "medium", "high"]
TRANSPORT_MODE_VALUES = Literal["walk", "public_transit", "drive", "any"]


class EventFlowData(TypedDict):
    """The ``data`` sub-dict inside an event flow."""

    creator: int
    description: str
    event_type: EVENT_TYPE_VALUES
    date_preset: DATE_PRESET_VALUES
    scheduled_date: NotRequired[str]
    scheduled_time: NotRequired[str]
    time_window: TIME_WINDOW_VALUES
    scheduling_mode: SCHEDULING_MODE_VALUES
    min_participants: NotRequired[int]
    target_participants: NotRequired[int]
    duration_minutes: NotRequired[int]
    location_type: LOCATION_TYPE_VALUES
    budget_level: BUDGET_LEVEL_VALUES
    transport_mode: TRANSPORT_MODE_VALUES
    invitees: NotRequired[list[str]]
    invite_all_members: NotRequired[bool]
    planning_notes: NotRequired[list[str]]


class EventFlow(TypedDict):
    """Top-level event creation flow stored in context.user_data."""

    stage: EVENT_FLOW_STAGES
    data: EventFlowData
    group_id: NotRequired[int]
    group_title: NotRequired[str]


# =============================================================================
# Private Event Flow (same structure, no group keys)
# =============================================================================

PrivateEventFlow = EventFlow  # Identical structure, distinguished by key name


# =============================================================================
# Creation Intent
# =============================================================================

CREATION_INTENT_VALUES = Literal["specific", "flexible"]


# =============================================================================
# Enrichment State
# =============================================================================

ENRICHMENT_ACTION_VALUES = Literal[
    "add_idea",
    "add_hashtag",
    "add_memory",
    "add_constraint",
    "add_constraint_unless",
    "suggest_time",
]


class EnrichmentState(TypedDict):
    """Isolated enrichment session for a single user."""

    session_id: str
    event_id: int
    action: ENRICHMENT_ACTION_VALUES
    created_at: datetime


# =============================================================================
# Modification Request State
# =============================================================================


class ModifyRequest(TypedDict):
    """Context for a pending modification request."""

    event_id: int
    event_description: str
    event_scheduled_time: NotRequired[str | None]
    admin_id: int
    requester_id: NotRequired[int | None]
    requester_username: NotRequired[str | None]


class ModifyRequestText(TypedDict):
    """Pending text input for a modification request."""

    event_id: int
    admin_id: int
    requester_id: NotRequired[int | None]
    requester_username: NotRequired[str | None]


# =============================================================================
# TTL Constants
# =============================================================================

EVENT_FLOW_TTL: timedelta = timedelta(minutes=30)
ENRICHMENT_TTL: timedelta = timedelta(minutes=10)
MODIFY_REQUEST_TTL: timedelta = timedelta(minutes=15)
