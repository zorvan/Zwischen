#!/usr/bin/env python3
"""Event prefill functionality for auto-suggested events."""

from datetime import datetime
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from bot.commands.flow import (
    start_event_flow,
    build_final_confirmation_markup,
    build_event_summary_text,
    ALLOWED_EVENT_TYPES,
    LOCATION_PRESETS,
    BUDGET_PRESETS,
    TRANSPORT_PRESETS,
    DATE_PRESET_LABELS,
    TIME_WINDOWS,
    _normalize_patch_invitees,
    _escape_md,
)
from bot.commands.parsers.invitee import parse_invitee_handles, parse_invitee_input
from bot.commands.keyboards.keyboard_utils import build_compact_markup


async def handle_from_prefill(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str = "public",
    prefill: dict[str, Any] | None = None,
) -> None:
    """Start event flow from pre-filled draft and jump to confirmation stage."""
    await start_event_flow(update, context, mode=mode)
    if context.user_data is None:
        return

    flow_key = "private_event_flow" if mode == "private" else "event_flow"
    event_flow_raw = context.user_data.get(flow_key)
    if not isinstance(event_flow_raw, dict):
        return
    event_flow: dict[str, Any] = event_flow_raw
    flow_data = event_flow.get("data")
    if not isinstance(flow_data, dict):
        flow_data = {}
        event_flow["data"] = flow_data

    pre = prefill or {}
    flow_data["description"] = str(
        pre.get("description") or "Group planned event"
    ).strip()[:500]
    event_type = str(pre.get("event_type") or "social").strip().lower()
    flow_data["event_type"] = (
        event_type if event_type in ALLOWED_EVENT_TYPES else "social"
    )
    try:
        flow_data["min_participants"] = max(1, int(pre.get("min_participants", 3)))
    except (TypeError, ValueError):
        flow_data["min_participants"] = 3
    try:
        flow_data["target_participants"] = max(
            flow_data["min_participants"],
            int(pre.get("target_participants", max(flow_data["min_participants"], 5))),
        )
    except (TypeError, ValueError):
        flow_data["target_participants"] = max(flow_data["min_participants"], 5)
    try:
        flow_data["duration_minutes"] = max(30, int(pre.get("duration_minutes", 120)))
    except (TypeError, ValueError):
        flow_data["duration_minutes"] = 120

    invite_all = bool(pre.get("invite_all_members", True))
    invitees_raw = pre.get("invitees", [])
    invitees = _normalize_patch_invitees(invitees_raw)
    if invite_all:
        flow_data["invite_all_members"] = True
        flow_data["invitees"] = ["@all"]
    else:
        flow_data["invite_all_members"] = False
        flow_data["invitees"] = invitees
    notes = pre.get("planning_notes", [])
    flow_data["planning_notes"] = (
        [str(x).strip()[:300] for x in notes if str(x).strip()]
        if isinstance(notes, list)
        else []
    )
    location_type = str(pre.get("location_type") or "cafe").strip().lower()
    flow_data["location_type"] = (
        location_type
        if location_type in {value for _, value in LOCATION_PRESETS}
        else "cafe"
    )
    budget_level = str(pre.get("budget_level") or "medium").strip().lower()
    flow_data["budget_level"] = (
        budget_level
        if budget_level in {value for _, value in BUDGET_PRESETS}
        else "medium"
    )
    transport_mode = str(pre.get("transport_mode") or "any").strip().lower()
    flow_data["transport_mode"] = (
        transport_mode
        if transport_mode in {value for _, value in TRANSPORT_PRESETS}
        else "any"
    )
    date_preset = str(pre.get("date_preset") or "custom").strip().lower()
    flow_data["date_preset"] = (
        date_preset if date_preset in DATE_PRESET_LABELS else "custom"
    )
    time_window = str(pre.get("time_window") or "evening").strip().lower()
    flow_data["time_window"] = time_window if time_window in TIME_WINDOWS else "evening"

    scheduled = pre.get("scheduled_time")
    if isinstance(scheduled, str) and scheduled.strip():
        try:
            parsed = datetime.fromisoformat(scheduled.strip())
            flow_data["scheduled_time"] = parsed.isoformat(timespec="minutes")
            if mode == "public":
                flow_data["scheduling_mode"] = "fixed"
        except ValueError:
            if mode == "public":
                flow_data["scheduling_mode"] = "flexible"
            flow_data.pop("scheduled_time", None)
    elif mode == "public":
        flow_data["scheduling_mode"] = "flexible"
        flow_data.pop("scheduled_time", None)

    event_flow["stage"] = "final"
    context.user_data[flow_key] = event_flow
    msg = update.effective_message
    if msg:
        prefix = "private_event" if mode == "private" else "event"
        await msg.reply_text(
            "🤖 I prepared an event draft from recent chat context.\n"
            "Review and confirm or modify:",
            reply_markup=build_final_confirmation_markup(prefix=prefix),
        )
        await msg.reply_text(
            build_event_summary_text(flow_data, is_private=mode == "private"),
            reply_markup=build_final_confirmation_markup(prefix=prefix),
        )
