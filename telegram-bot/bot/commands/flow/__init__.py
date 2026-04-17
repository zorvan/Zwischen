#!/usr/bin/env python3
"""Event creation entry points and flow control.

This module provides the main entry points for event creation commands:
- handle: /organize_event - public/group event creation
- handle_flexible: /organize_event_flexible - flexible mode
- private_handle: /private_organize_event - private event creation

This module contains the core event creation logic delegated from event_creation.py.
"""

from typing import Any

from telegram import Update, CallbackQuery
from telegram.ext import ContextTypes

from sqlalchemy import select
from datetime import datetime, timedelta

from ai.llm import LLMClient
from config.settings import settings
from bot.common.event_notifications import send_event_invitation_dm
from bot.common.event_formatters import format_date_preset, format_time_window
from bot.common.scheduling import find_user_event_conflict
from bot.services.event_live_card_service import EventLiveCardService
from bot.services.event_hashtag_service import EventHashtagService
from db.connection import get_session
from db.models import Event, Group, User
from db.users import get_user_id_by_username

from bot.commands.parsers.invitee import parse_invitee_handles, parse_invitee_input
from bot.commands.keyboards.keyboard_utils import build_compact_markup
from bot.commands.keyboards.date_picker import (
    build_date_preset_markup,
    build_date_options_markup,
    build_calendar_markup,
    resolve_date_preset,
)
from bot.commands.keyboards.time_picker import (
    build_time_window_markup,
    build_time_options_markup,
)
from bot.commands.keyboards.selection import (
    build_location_type_markup,
    build_budget_markup,
    build_transport_markup,
    build_invitee_mode_markup,
    build_event_type_markup,
    build_duration_markup,
)
from bot.commands.finalize import (
    build_event_summary_text,
    build_final_confirmation_markup,
    _apply_final_stage_patch,
)


CALENDAR_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIME_WINDOWS = {
    "early-morning": ["04:00", "05:00", "06:00", "07:00"],
    "morning": ["08:00", "09:00", "10:00", "11:00"],
    "afternoon": ["12:00", "13:00", "14:00", "15:00"],
    "evening": ["17:00", "18:00", "19:00", "20:00"],
    "night": ["21:00", "22:00", "23:00"],
}
LOCATION_PRESETS = [
    ("🏠 Home", "home"),
    ("🌳 Outdoor", "outdoor"),
    ("☕ Cafe", "cafe"),
    ("🏢 Office", "office"),
    ("🏋️ Gym", "gym"),
]
BUDGET_PRESETS = [
    ("🆓 Free", "free"),
    ("💸 Low", "low"),
    ("💰 Medium", "medium"),
    ("💎 High", "high"),
]
TRANSPORT_PRESETS = [
    ("🚶 Walk", "walk"),
    ("🚌 Public Transit", "public_transit"),
    ("🚗 Drive", "drive"),
    ("🤝 Any", "any"),
]
ALLOWED_EVENT_TYPES = {"social", "sports", "work"}
DATE_PRESET_LABELS = {
    "today": "Today",
    "tomorrow": "Tomorrow",
    "weekend": "Weekend",
    "nextweek": "Next Week",
    "custom": "Custom",
}
DEFAULT_COMMIT_BY_OFFSET_HOURS = 12


def _escape_md(text: str) -> str:
    """Escape text for safe Telegram Markdown parsing."""
    return (
        str(text)
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def compute_commit_by_time(scheduled_time: datetime | None) -> datetime | None:
    """Derive default commit-by deadline from scheduled time."""
    if scheduled_time is None:
        return None
    return scheduled_time - timedelta(hours=DEFAULT_COMMIT_BY_OFFSET_HOURS)


def _normalize_patch_invitees(values: Any) -> list[str]:
    """Normalize invitee list from patch values."""
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        if not text.startswith("@"):
            text = f"@{text}"
        handle = text[1:]
        if handle and len(handle) >= 4 and len(handle) <= 31:
            normalized.append(f"@{handle.lower()}")
    deduped: list[str] = []
    seen: set[str] = set()
    for handle in normalized:
        if handle not in seen:
            seen.add(handle)
            deduped.append(handle)
    return deduped


async def start_event_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str = "public",
) -> None:
    """Initialize event creation flow for public/group or private events."""
    message = update.effective_message
    if not message or not update.effective_chat:
        return

    chat = update.effective_chat
    chat_type = chat.type
    if mode == "public" and chat_type not in {"group", "supergroup"}:
        await message.reply_text(
            "❌ This command can only be used in a Telegram group."
        )
        return

    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    telegram_user_id = update.effective_user.id if update.effective_user else None

    if not settings.db_url:
        await message.reply_text("❌ Database configuration is unavailable.")
        return

    if mode == "public":
        async with get_session(settings.db_url) as session:
            result = await session.execute(
                select(Group).where(Group.telegram_group_id == chat_id)
            )
            group = result.scalar_one_or_none()

            if not group:
                group = Group(
                    telegram_group_id=chat_id,
                    group_name=chat_title,
                    member_list=[telegram_user_id] if telegram_user_id else [],
                )
                session.add(group)
                await session.commit()
                await session.refresh(group)
            else:
                changed = False
                if chat_title and group.group_name != chat_title:
                    group.group_name = chat_title
                    changed = True

                current_members = group.member_list or []
                if telegram_user_id and telegram_user_id not in current_members:
                    group.member_list = [*current_members, telegram_user_id]
                    changed = True

                if changed:
                    await session.commit()

    if context.user_data is None:
        await message.reply_text("❌ User session data is unavailable.")
        return

    flow_key = "private_event_flow" if mode == "private" else "event_flow"

    flow_data = {
        "stage": "description",
        "data": {
            "creator": telegram_user_id,
            "date_preset": "custom",
            "time_window": "evening",
            "location_type": "cafe",
            "budget_level": "medium",
            "transport_mode": "any",
            "planning_notes": [],
            "invite_all_members": True,
        },
    }

    if mode == "public":
        flow_data["group_id"] = group.group_id
        flow_data["group_title"] = chat_title
        flow_data["data"]["scheduling_mode"] = "fixed"

    context.user_data[flow_key] = flow_data

    if mode == "private":
        await message.reply_text(
            "<b>📝 Event Description</b>\n\n"
            "Send a short description for the event.\n\n"
            "Example: Friendly football match at the central field.",
            parse_mode="HTML",
        )
    else:
        scheduling_mode = flow_data["data"].get("scheduling_mode", "fixed")
        mode_text = (
            "Fixed date/time"
            if scheduling_mode == "fixed"
            else "Flexible (collect availability first)"
        )
        await message.reply_text(
            "<b>📝 Event Description</b>\n\n"
            "Send a short description for the event.\n"
            f"Mode: {mode_text}\n\n"
            "Example: Friendly football match at the central field.\n"
            "Most next steps are one-tap inline options.",
            parse_mode="HTML",
        )


async def start_event_flow_from_prefill(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str = "public",
    prefill: dict[str, Any] | None = None,
) -> None:
    """Start organize flow from inferred draft and jump to confirmation stage."""
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


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /organize_event command - start public event creation flow."""
    await start_event_flow(update, context, mode="public")


async def handle_flexible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /organize_event_flexible command - no initial date/time."""
    await start_event_flow(update, context, mode="public")


async def private_handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /private_organize_event command - start private event creation flow."""
    await start_event_flow(update, context, mode="private")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for public event creation flow."""
    from telegram import CallbackQuery

    await _handle_callback_common(update, context, mode="public")


async def private_handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle callback queries for private event creation flow."""
    from telegram import CallbackQuery

    await _handle_callback_common(update, context, mode="private")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages during public event creation flow."""
    await _handle_message_common(update, context, mode="public")


async def private_handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle text messages during private event creation flow."""
    if not update.message or not update.effective_user:
        return

    if context.user_data is None:
        return

    flow_key = "private_event_flow"
    event_flow_raw = context.user_data.get(flow_key)
    if not isinstance(event_flow_raw, dict) or not event_flow_raw:
        return

    event_flow: dict[str, Any] = event_flow_raw
    flow_data = event_flow.get("data")
    if not isinstance(flow_data, dict):
        flow_data = {}
        event_flow["data"] = flow_data

    stage = event_flow.get("stage")
    user_id = update.effective_user.id

    if stage == "description":
        text = update.message.text
        if not text or not text.strip():
            await update.message.reply_text(
                "❌ Description cannot be empty. Please send a short description."
            )
            return
        description = text.strip()
        if len(description) > 500:
            await update.message.reply_text(
                "❌ Description is too long. Keep it under 500 characters."
            )
            return

        flow_data["description"] = description
        event_flow["stage"] = "type"
        context.user_data[flow_key] = event_flow
        await update.message.reply_text(
            "📋 *Event Type*\n\nWhat type of event would you like to organize?",
            reply_markup=build_event_type_markup(prefix="private_event"),
        )

    elif stage == "time_manual":
        text = update.message.text
        if text is None:
            await update.message.reply_text(
                "❌ Please send time as text in format: HH:MM"
            )
            return

        scheduled_date = flow_data.get("scheduled_date")
        if not isinstance(scheduled_date, str):
            await update.message.reply_text(
                "❌ Event date is missing. Please reselect date from calendar."
            )
            return

        try:
            parsed_time = datetime.strptime(text.strip(), "%H:%M").time()
            parsed_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            scheduled_time = datetime.combine(parsed_date, parsed_time)
            event_flow["stage"] = "threshold"
            flow_data["scheduled_time"] = scheduled_time.isoformat()
            context.user_data[flow_key] = event_flow

            await update.message.reply_text(
                f"⏱️ *Time: {scheduled_time.strftime('%Y-%m-%d %H:%M')}*\n\n"
                "What is the minimum attendance threshold?",
                reply_markup=None,
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid time format. Please use: HH:MM")

    elif stage == "invitees":
        text = update.message.text
        if text is None:
            await update.message.reply_text(
                "❌ Invalid input. Please enter comma-separated handles like @alice, @bob."
            )
            return

        try:
            invitees, invite_all = parse_invitee_input(text)
            event_flow["stage"] = "final"
            flow_data["invitees"] = invitees
            flow_data["invite_all_members"] = invite_all
            flow_data["creator"] = user_id
            context.user_data[flow_key] = event_flow

            data = flow_data
            prefix = "private_event"
            await update.message.reply_text(
                build_event_summary_text(data, is_private=True),
                reply_markup=build_final_confirmation_markup(prefix=prefix),
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid handle list. Use comma-separated @handles.\n"
                "Example: @alice, @bob_builder\n"
                "Or use: @all",
                reply_markup=build_compact_markup(
                    [],
                    columns=1,
                    footer=[("✏️ Edit Previous", f"{prefix}_edit_transport")],
                ),
            )

    elif stage == "final":
        text = (update.message.text or "").strip()
        if not text:
            await update.message.reply_text(
                "❌ Send text modifications, or press Confirm/Cancel."
            )
            return

        changed, changes, warning_text = await _apply_final_stage_patch(
            flow_data=flow_data,
            message_text=text,
            is_private=True,
        )
        context.user_data[flow_key] = event_flow
        if not changed:
            await update.message.reply_text(
                "⚠️ I could not apply any clear modification.\n"
                "Try specific edits like: `set time to 2026-03-10 19:30`."
            )
            return

        revision_lines = "\n".join(f"- {item}" for item in changes)
        warning_block = f"\nWarnings:\n{warning_text}\n" if warning_text else ""

        prefix = "private_event"
        await update.message.reply_text(
            "🔁 *Draft Updated*\n"
            f"{revision_lines}\n"
            f"{warning_block}\n"
            f"{build_event_summary_text(flow_data, is_private=True)}",
            reply_markup=build_final_confirmation_markup(prefix=prefix),
        )


async def _handle_callback_common(
    update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str
) -> None:
    """Handle callback queries for event creation flow."""
    if not update.callback_query:
        return

    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data
    flow_key = "private_event_flow" if mode == "private" else "event_flow"
    prefix = "private_event" if mode == "private" else "event"

    if context.user_data is None:
        await query.edit_message_text("❌ User session data is unavailable.")
        return

    event_flow_raw = context.user_data.get(flow_key)
    event_flow: dict[str, Any] = (
        event_flow_raw if isinstance(event_flow_raw, dict) else {}
    )
    if not event_flow:
        await query.edit_message_text(
            "❌ Event setup session expired. Please run /organize_event again."
        )
        return
    flow_data = event_flow.get("data")
    if not isinstance(flow_data, dict):
        flow_data = {}
        event_flow["data"] = flow_data

    if data and data.startswith(f"{prefix}_edit_"):
        target = data.replace(f"{prefix}_edit_", "")
        scheduling_mode = str(flow_data.get("scheduling_mode", "fixed"))

        if target == "description":
            event_flow["stage"] = "description"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                "📝 *Edit Description*\n\nSend a new event description."
            )
        elif target == "type":
            event_flow["stage"] = "type"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                "📋 *Event Type*\n\nChoose event type:",
                reply_markup=build_compact_markup(
                    [
                        ("Social", f"{prefix}_type_social"),
                        ("Sports", f"{prefix}_type_sports"),
                        ("Work", f"{prefix}_type_work"),
                    ],
                    columns=2,
                    footer=[("✏️ Edit Previous", f"{prefix}_edit_description")],
                ),
            )
        elif target == "date_preset":
            if mode == "private" or scheduling_mode == "flexible":
                if mode == "public" and scheduling_mode == "flexible":
                    event_flow["stage"] = "threshold"
                    context.user_data[flow_key] = event_flow
                    await query.edit_message_text(
                        "Flexible mode skips fixed date selection.\n"
                        "Set the minimum people needed:",
                        reply_markup=None,
                    )
                else:
                    event_flow["stage"] = "date_preset"
                    context.user_data[flow_key] = event_flow
                    await query.edit_message_text(
                        "📅 *Quick Date Selection*\n\nChoose a date preset:",
                        reply_markup=build_date_preset_markup(prefix=prefix),
                    )
            else:
                event_flow["stage"] = "date_preset"
                context.user_data[flow_key] = event_flow
                await query.edit_message_text(
                    "📅 *Quick Date Selection*\n\nChoose a date preset:",
                    reply_markup=build_date_preset_markup(prefix=prefix),
                )
        elif target == "time_window":
            event_flow["stage"] = "time_window"
            context.user_data[flow_key] = event_flow
            selected_date = flow_data.get("scheduled_date", "N/A")
            await query.edit_message_text(
                f"⏰ *Time Window*\n\nDate: {selected_date}\nChoose a window:",
                reply_markup=build_time_window_markup(prefix=prefix),
            )
        elif target == "threshold":
            event_flow["stage"] = "threshold"
            context.user_data[flow_key] = event_flow
            back_target = (
                f"{prefix}_edit_time_window"
                if not (mode == "public" and scheduling_mode == "flexible")
                else f"{prefix}_edit_type"
            )
            await query.edit_message_text(
                "👥 *Participation Minimum*\n\nSet the minimum people needed:",
                reply_markup=None,
            )
        elif target == "duration":
            event_flow["stage"] = "duration"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                "⏳ *Duration*\n\nSelect event duration:",
                reply_markup=build_duration_markup(prefix=prefix),
            )
        elif target == "location":
            event_flow["stage"] = "location"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                "📍 *Location Type*\n\nPick one option:",
                reply_markup=build_location_type_markup(prefix=prefix),
            )
        elif target == "budget":
            event_flow["stage"] = "budget"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                "💳 *Budget*\n\nPick one option:",
                reply_markup=build_budget_markup(prefix=prefix),
            )
        elif target == "transport":
            event_flow["stage"] = "transport"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                "🚗 *Transport Mode*\n\nPick one option:",
                reply_markup=build_transport_markup(prefix=prefix),
            )
        elif target == "invitees":
            event_flow["stage"] = "invitees"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                "👥 *Invitees*\n\nChoose invite mode:",
                reply_markup=build_invitee_mode_markup(prefix=prefix),
            )
        elif target == "final":
            event_flow["stage"] = "final"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                build_event_summary_text(flow_data, is_private=mode == "private"),
                reply_markup=build_final_confirmation_markup(prefix=prefix),
            )

    elif data and data.startswith(f"{prefix}_type_"):
        event_type = data.replace(f"{prefix}_type_", "")
        scheduling_mode = str(flow_data.get("scheduling_mode", "fixed"))
        flow_data["event_type"] = event_type
        context.user_data[flow_key] = event_flow
        if mode == "public" and scheduling_mode == "flexible":
            event_flow["stage"] = "threshold"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                f"📅 *Event Type: {event_type}*\n\n"
                "Flexible mode selected.\n"
                "No fixed date/time now. Attendees can add availability slots later with:\n"
                "/constraints <event_id> availability <YYYY-MM-DD HH:MM, ...>\n\n"
                "Set the minimum people needed:",
                reply_markup=None,
            )
        else:
            event_flow["stage"] = "date_preset"
            context.user_data[flow_key] = event_flow
            await query.edit_message_text(
                f"📅 *Event Type: {event_type}*\n\nChoose a quick date preset:",
                reply_markup=build_date_preset_markup(prefix=prefix),
            )

    elif data and data.startswith(f"{prefix}_date_preset_"):
        preset = data.replace(f"{prefix}_date_preset_", "")
        flow_data["date_preset"] = preset
        if preset == "custom":
            event_flow["stage"] = "date"
            context.user_data[flow_key] = event_flow
            now = datetime.now()
            await query.edit_message_text(
                "📅 *Custom Date*\n\nSelect a date from the inline calendar:",
                reply_markup=build_calendar_markup(now.year, now.month, prefix=prefix),
            )
        else:
            choices = resolve_date_preset(preset)
            if not choices:
                await query.edit_message_text(
                    "❌ Could not resolve that date preset. Please try again.",
                    reply_markup=build_date_preset_markup(prefix=prefix),
                )
                return
            if len(choices) == 1:
                selected_date = choices[0].strftime("%Y-%m-%d")
                flow_data["scheduled_date"] = selected_date
                event_flow["stage"] = "time_window"
                context.user_data[flow_key] = event_flow
                await query.edit_message_text(
                    f"📆 *Date selected: {selected_date}*\n\nChoose a time window:",
                    reply_markup=build_time_window_markup(prefix=prefix),
                )
            else:
                event_flow["stage"] = "date_options"
                context.user_data[flow_key] = event_flow
                label = DATE_PRESET_LABELS.get(preset, preset.title())
                await query.edit_message_text(
                    f"📆 *{label}*\n\nPick a specific date:",
                    reply_markup=build_date_options_markup(
                        choices, preset, prefix=prefix
                    ),
                )

    elif data and data.startswith(f"{prefix}_date_pick_"):
        token = data.replace(f"{prefix}_date_pick_", "")
        try:
            picked = datetime.strptime(token, "%Y%m%d").date()
        except ValueError:
            await query.edit_message_text("❌ Invalid date option selected.")
            return
        selected_date = picked.strftime("%Y-%m-%d")
        flow_data["scheduled_date"] = selected_date
        event_flow["stage"] = "time_window"
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"📆 *Date selected: {selected_date}*\n\nChoose a time window:",
            reply_markup=build_time_window_markup(prefix=prefix),
        )

    elif data and data.startswith(f"{prefix}_cal_"):
        await _handle_calendar_callback(
            query, context, event_flow, flow_data, prefix=prefix
        )

    elif data and data.startswith(f"{prefix}_time_window_"):
        window = data.replace(f"{prefix}_time_window_", "")
        if window not in TIME_WINDOWS:
            await query.edit_message_text("❌ Unsupported time window.")
            return
        flow_data["time_window"] = window
        event_flow["stage"] = "time_option"
        context.user_data[flow_key] = event_flow
        selected_date = flow_data.get("scheduled_date", "N/A")
        await query.edit_message_text(
            f"⏰ *{window.title()} window*\n\nDate: {selected_date}\nPick a start time:",
            reply_markup=build_time_options_markup(window, prefix=prefix),
        )

    elif data == f"{prefix}_time_manual":
        event_flow["stage"] = "time_manual"
        context.user_data[flow_key] = event_flow
        selected_date = flow_data.get("scheduled_date", "N/A")
        await query.edit_message_text(
            f"⌨️ *Manual Time Entry*\n\nDate: {selected_date}\n"
            "Send time in format `HH:MM` (e.g., `18:30`)."
        )

    elif data and data.startswith(f"{prefix}_time_option_"):
        option = data.replace(f"{prefix}_time_option_", "")
        if len(option) != 4 or not option.isdigit():
            await query.edit_message_text("❌ Invalid time option.")
            return
        hour = int(option[:2])
        minute = int(option[2:])
        scheduled_date = flow_data.get("scheduled_date")
        if not isinstance(scheduled_date, str):
            await query.edit_message_text(
                "❌ Event date is missing. Please pick date again.",
                reply_markup=build_date_preset_markup(prefix=prefix),
            )
            return
        try:
            parsed_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            scheduled_time = datetime.combine(
                parsed_date,
                datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time(),
            )
        except ValueError:
            await query.edit_message_text("❌ Failed to parse selected time.")
            return
        flow_data["scheduled_time"] = scheduled_time.isoformat(timespec="minutes")
        event_flow["stage"] = "min_participants"
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"⏱️ *Time: {scheduled_time.strftime('%Y-%m-%d %H:%M')}*\n\n"
            "What's the minimum number of people this needs to happen?",
            reply_markup=None,
        )

    elif data and data.startswith(f"{prefix}_min_"):
        min_val = int(data.replace(f"{prefix}_min_", ""))
        event_flow["stage"] = "target_participants"
        flow_data["min_participants"] = min_val
        import math

        flow_data["target_participants"] = math.ceil(min_val * 1.5)
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"✅ *Minimum: {min_val}*\n\n"
            f"How many people can this comfortably fit? (Default: {flow_data['target_participants']})",
            reply_markup=None,
        )

    elif data and data.startswith(f"{prefix}_target_"):
        target_val = int(data.replace(f"{prefix}_target_", ""))
        event_flow["stage"] = "duration"
        flow_data["target_participants"] = target_val
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"✅ *Capacity: {target_val}* (min: {flow_data.get('min_participants', '?')})\n\n"
            f"Select event duration:",
            reply_markup=build_duration_markup(prefix=prefix),
        )

    elif data and data.startswith(f"{prefix}_threshold_"):
        threshold = int(data.replace(f"{prefix}_threshold_", ""))
        event_flow["stage"] = "duration"
        flow_data["min_participants"] = threshold
        flow_data["target_participants"] = threshold
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f           "✅ <b>Minimum/Capacity: {threshold}</b>\n\nSelect event duration:",
            reply_markup=build_duration_markup(prefix=prefix),
        )

    elif data and data.startswith(f"{prefix}_duration_"):
        duration = int(data.replace(f"{prefix}_duration_", ""))
        event_flow["stage"] = "location"
        flow_data["duration_minutes"] = duration
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"⏳ *Duration: {duration} minutes*\n\nSelect location type:",
            reply_markup=build_location_type_markup(prefix=prefix),
        )

    elif data and data.startswith(f"{prefix}_location_"):
        location_type = data.replace(f"{prefix}_location_", "")
        flow_data["location_type"] = location_type
        event_flow["stage"] = "budget"
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"📍 *Location: {location_type.replace('_', ' ').title()}*\n\nSelect budget:",
            reply_markup=build_budget_markup(prefix=prefix),
        )

    elif data and data.startswith(f"{prefix}_budget_"):
        budget_level = data.replace(f"{prefix}_budget_", "")
        flow_data["budget_level"] = budget_level
        event_flow["stage"] = "transport"
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"💳 *Budget: {budget_level.title()}*\n\nSelect transport mode:",
            reply_markup=build_transport_markup(prefix=prefix),
        )

    elif data and data.startswith(f"{prefix}_transport_"):
        transport_mode = data.replace(f"{prefix}_transport_", "")
        flow_data["transport_mode"] = transport_mode
        event_flow["stage"] = "invitees"
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"🚗 *Transport: {transport_mode.replace('_', ' ').title()}*\n\nChoose invite mode:",
            reply_markup=build_invitee_mode_markup(prefix=prefix),
        )

    elif data == f"{prefix}_invite_all":
        event_flow["stage"] = "final"
        flow_data["invitees"] = ["@all"]
        flow_data["invite_all_members"] = True
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            build_event_summary_text(flow_data, is_private=mode == "private"),
            reply_markup=build_final_confirmation_markup(prefix=prefix),
        )

    elif data == f"{prefix}_invite_custom":
        event_flow["stage"] = "invitees"
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            "✍️ *Custom Invitees*\n\n"
            "Enter comma-separated handles.\n"
            "Example: @alice, @bob_builder\n"
            "Or send @all",
            reply_markup=build_compact_markup(
                [],
                columns=1,
                footer=[("✏️ Edit Previous", f"{prefix}_edit_transport")],
            ),
        )

    elif data == f"{prefix}_final_yes":
        if mode == "private":
            from bot.commands.finalize import finalize_private_event

            await finalize_private_event(query, context)
        else:
            from bot.commands.finalize import finalize_event

            await finalize_event(query, context)
    elif data == f"{prefix}_final_edit":
        await query.edit_message_text(
            "🛠 Send your modification in natural language.\n\n"
            "Examples:\n"
            "- Change time to 2026-03-10 19:30\n"
            "- Make duration 90 minutes\n"
            "- Increase the minimum to 5\n"
            "- Set location to outdoor and budget to low\n"
            "- Add @alice and remove @bob"
        )

    elif data and data.startswith(f"{prefix}_cancel_"):
        context.user_data.pop(flow_key, None)
        await query.edit_message_text("❌ Event creation cancelled.")


async def _handle_calendar_callback(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_flow: dict[str, Any],
    flow_data: dict[str, Any],
    prefix: str = "event",
) -> None:
    """Handle inline calendar callbacks for date selection."""
    from telegram import CallbackQuery

    data = query.data
    if not data:
        return

    if data == f"{prefix}_cal_ignore":
        return

    if data.startswith(f"{prefix}_cal_nav_") or data.startswith(f"{prefix}_cal_open_"):
        parts = data.split("_")
        if len(parts) < 5:
            return
        try:
            year = int(parts[-2])
            month = int(parts[-1])
            if month < 1 or month > 12:
                return
        except ValueError:
            return

        event_type = str(flow_data.get("event_type", "N/A"))
        await query.edit_message_text(
            f"📅 *Event Type: {event_type}*\n\nSelect a date from the inline calendar:",
            reply_markup=build_calendar_markup(year, month, prefix=prefix),
        )
        return

    if data.startswith(f"{prefix}_cal_day_"):
        parts = data.split("_")
        if len(parts) != 6:
            return
        try:
            year = int(parts[3])
            month = int(parts[4])
            day = int(parts[5])
            selected = datetime(year, month, day)
        except ValueError:
            return

        selected_date = selected.strftime("%Y-%m-%d")
        flow_data["scheduled_date"] = selected_date
        flow_data["date_preset"] = "custom"
        event_flow["stage"] = "time_window"
        context.user_data[
            "event_flow" if prefix == "event" else "private_event_flow"
        ] = event_flow

        await query.edit_message_text(
            f"📆 *Date selected: {selected_date}*\n\nChoose a time window:",
            reply_markup=build_time_window_markup(prefix=prefix),
        )


async def _handle_message_common(
    update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str
) -> None:
    """Handle text messages during event creation flow."""
    if not update.message or not update.effective_user:
        return

    if context.user_data is None:
        return

    flow_key = "private_event_flow" if mode == "private" else "event_flow"
    event_flow_raw = context.user_data.get(flow_key)
    if not isinstance(event_flow_raw, dict) or not event_flow_raw:
        return

    event_flow: dict[str, Any] = event_flow_raw
    flow_data = event_flow.get("data")
    if not isinstance(flow_data, dict):
        flow_data = {}
        event_flow["data"] = flow_data

    stage = event_flow.get("stage")
    user_id = update.effective_user.id

    if stage == "description":
        text = update.message.text
        if not text or not text.strip():
            await update.message.reply_text(
                "❌ Description cannot be empty. Please send a short description."
            )
            return
        description = text.strip()
        if len(description) > 500:
            await update.message.reply_text(
                "❌ Description is too long. Keep it under 500 characters."
            )
            return

        flow_data["description"] = description
        event_flow["stage"] = "type"
        context.user_data[flow_key] = event_flow
        scheduling_mode = (
            str(flow_data.get("scheduling_mode", "fixed"))
            if mode == "public"
            else "fixed"
        )
        scheduling_mode_text = (
            "Fixed date/time"
            if scheduling_mode == "fixed"
            else "Flexible (collect availability first)"
        )

        if mode == "private":
            await update.message.reply_text(
                "📋 *Event Type*\n\nWhat type of event would you like to organize?",
                reply_markup=build_event_type_markup(prefix="private_event"),
            )
        else:
            await update.message.reply_text(
                "📋 *Event Type*\n\n"
                "What type of event would you like to organize?\n"
                f"Mode: {scheduling_mode_text}",
                reply_markup=build_event_type_markup(prefix="event"),
            )

    elif stage == "time_manual":
        text = update.message.text
        if text is None:
            await update.message.reply_text(
                "❌ Please send time as text in format: HH:MM"
            )
            return

        scheduled_date = flow_data.get("scheduled_date")
        if not isinstance(scheduled_date, str):
            await update.message.reply_text(
                "❌ Event date is missing. Please reselect date from calendar."
            )
            return

        try:
            parsed_time = datetime.strptime(text.strip(), "%H:%M").time()
            parsed_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            scheduled_time = datetime.combine(parsed_date, parsed_time)
            event_flow["stage"] = "threshold"
            flow_data["scheduled_time"] = scheduled_time.isoformat()
            context.user_data[flow_key] = event_flow

            await update.message.reply_text(
                f"⏱️ *Time: {scheduled_time.strftime('%Y-%m-%d %H:%M')}*\n\n"
                "What is the minimum attendance threshold?",
                reply_markup=None,
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid time format. Please use: HH:MM")

    elif stage == "invitees":
        text = update.message.text
        if text is None:
            await update.message.reply_text(
                "❌ Invalid input. Please enter comma-separated handles like @alice, @bob."
            )
            return

        try:
            invitees, invite_all = parse_invitee_input(text)
            event_flow["stage"] = "final"
            flow_data["invitees"] = invitees
            flow_data["invite_all_members"] = invite_all
            flow_data["creator"] = user_id
            context.user_data[flow_key] = event_flow

            data = flow_data
            prefix = "private_event" if mode == "private" else "event"
            await update.message.reply_text(
                build_event_summary_text(data, is_private=mode == "private"),
                reply_markup=build_final_confirmation_markup(prefix=prefix),
            )
        except ValueError:
            prefix = "private_event" if mode == "private" else "event"
            await update.message.reply_text(
                "❌ Invalid handle list. Use comma-separated @handles.\n"
                "Example: @alice, @bob_builder\n"
                "Or use: @all",
                reply_markup=build_compact_markup(
                    [],
                    columns=1,
                    footer=[("✏️ Edit Previous", f"{prefix}_edit_transport")],
                ),
            )

    elif stage == "min_participants":
        text = update.message.text
        if text is None:
            await update.message.reply_text(
                "❌ Please send a number for the minimum participants."
            )
            return

        try:
            min_val = int(text.strip())
            if min_val < 1:
                await update.message.reply_text(
                    "❌ Minimum participants must be at least 1."
                )
                return
            event_flow["stage"] = "target_participants"
            flow_data["min_participants"] = min_val
            import math

            flow_data["target_participants"] = math.ceil(min_val * 1.5)
            context.user_data[flow_key] = event_flow
            await update.message.reply_text(
                f"✅ *Minimum: {min_val}*\n\n"
                f"How many people can this comfortably fit? (Default: {flow_data['target_participants']})",
                reply_markup=None,
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid number. Please send a valid number for minimum participants."
            )

    elif stage == "final":
        text = (update.message.text or "").strip()
        if not text:
            await update.message.reply_text(
                "❌ Send text modifications, or press Confirm/Cancel."
            )
            return

        changed, changes, warning_text = await _apply_final_stage_patch(
            flow_data=flow_data,
            message_text=text,
            is_private=(mode == "private"),
        )
        context.user_data[flow_key] = event_flow
        if not changed:
            await update.message.reply_text(
                "⚠️ I could not apply any clear modification.\n"
                "Try specific edits like: `set time to 2026-03-10 19:30`."
            )
            return

        revision_lines = "\n".join(f"- {item}" for item in changes)
        warning_block = f"\nWarnings:\n{warning_text}\n" if warning_text else ""

        if mode == "private":
            prefix = "private_event"
            await update.message.reply_text(
                "🔁 *Draft Updated*\n"
                f"{revision_lines}\n"
                f"{warning_block}\n"
                f"{build_event_summary_text(flow_data, is_private=True)}",
                reply_markup=build_final_confirmation_markup(prefix=prefix),
            )
        else:
            prefix = "event"
            await update.message.reply_text(
                "🔁 *Draft Updated*\n"
                f"{revision_lines}\n"
                f"{warning_block}\n"
                f"{build_event_summary_text(flow_data, is_private=False)}",
                reply_markup=build_final_confirmation_markup(prefix=prefix),
            )
