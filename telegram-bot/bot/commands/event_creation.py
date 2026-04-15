#!/usr/bin/env python3
"""Unified event creation command handler - facade module.

This module provides the public API for event creation commands.
All implementation has been split into specialized submodules.

For implementation details, see the respective submodule modules.
"""

from bot.commands.flow import (
    handle,
    handle_flexible,
    private_handle,
    handle_callback,
    handle_message,
    private_handle_callback,
    private_handle_message,
    start_event_flow_from_prefill,
    ALLOWED_EVENT_TYPES,
    LOCATION_PRESETS,
    BUDGET_PRESETS,
    TRANSPORT_PRESETS,
    DATE_PRESET_LABELS,
    TIME_WINDOWS,
    compute_commit_by_time,
    _normalize_patch_invitees,
)

__all__ = [
    "handle",
    "handle_flexible",
    "private_handle",
    "handle_callback",
    "handle_message",
    "private_handle_callback",
    "private_handle_message",
    "start_event_flow_from_prefill",
    "ALLOWED_EVENT_TYPES",
    "LOCATION_PRESETS",
    "BUDGET_PRESETS",
    "TRANSPORT_PRESETS",
    "DATE_PRESET_LABELS",
    "TIME_WINDOWS",
    "compute_commit_by_time",
    "_normalize_patch_invitees",
]
