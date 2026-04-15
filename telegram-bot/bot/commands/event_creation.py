#!/usr/bin/env python3
"""Unified event creation command handler supporting public/group and private events."""

from calendar import Calendar, month_name
from datetime import date, datetime, timedelta
import logging
import re
from typing import Any
from telegram import (
    Update,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes

from sqlalchemy import select

from ai.llm import LLMClient
from config.settings import settings
from bot.common.event_notifications import (
    DATE_PRESET_LABELS,
    send_event_invitation_dm,
)
from bot.common.event_formatters import (
    format_date_preset,
    format_time_window,
    format_location_type,
    format_budget_level,
    format_transport_mode,
    format_scheduled_time,
    format_commit_by,
    format_duration,
)
from bot.common.keyboards import (
    build_threshold_markup,
    build_min_participants_markup,
    build_target_participants_markup,
)
from bot.common.scheduling import find_user_event_conflict
from bot.services.event_live_card_service import EventLiveCardService
from bot.services.event_hashtag_service import EventHashtagService
from db.connection import get_session
from db.models import Event, Group, User
from db.users import get_user_id_by_username


logger = logging.getLogger("coord_bot.event_creation")


CALENDAR_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
TELEGRAM_HANDLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
ALLOWED_EVENT_TYPES = {"social", "sports", "work"}
DEFAULT_COMMIT_BY_OFFSET_HOURS = 12
TIME_WINDOWS: dict[str, list[str]] = {
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
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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


def build_compact_markup(
    options: list[tuple[str, str]],
    *,
    columns: int = 2,
    footer: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    """Build compact inline keyboard with optional footer rows."""
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for index, (label, callback_data) in enumerate(options):
        current_row.append(InlineKeyboardButton(label, callback_data=callback_data))
        if len(current_row) == columns or index == len(options) - 1:
            rows.append(current_row)
            current_row = []
    for label, callback_data in footer or []:
        rows.append([InlineKeyboardButton(label, callback_data=callback_data)])
    return InlineKeyboardMarkup(rows)


def build_date_preset_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build quick date preset keyboard."""
    options = [
        ("Today", f"{prefix}_date_preset_today"),
        ("Tomorrow", f"{prefix}_date_preset_tomorrow"),
        ("Weekend", f"{prefix}_date_preset_weekend"),
        ("Next Week", f"{prefix}_date_preset_nextweek"),
    ]
    footer = [
        ("📅 Custom Calendar", f"{prefix}_date_preset_custom"),
        ("✏️ Edit Previous", f"{prefix}_edit_type"),
    ]
    return build_compact_markup(options, columns=2, footer=footer)


def build_date_options_markup(
    dates: list[date], preset: str, prefix: str = "event"
) -> InlineKeyboardMarkup:
    """Build date choice keyboard for multi-date presets."""
    options = [
        (
            f"{WEEKDAY_LABELS[d.weekday()]} {d.strftime('%m-%d')}",
            f"{prefix}_date_pick_{d.strftime('%Y%m%d')}",
        )
        for d in dates
    ]
    footer = [("✏️ Edit Previous", f"{prefix}_edit_date_preset")]
    if preset in {"weekend", "nextweek"}:
        footer.insert(0, ("📅 Custom Calendar", f"{prefix}_date_preset_custom"))
    return build_compact_markup(options, columns=2, footer=footer)


def build_time_window_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build quick time-window keyboard."""
    options = [
        ("🌅 Morning", f"{prefix}_time_window_morning"),
        ("🌤 Afternoon", f"{prefix}_time_window_afternoon"),
        ("🌆 Evening", f"{prefix}_time_window_evening"),
        ("🌙 Night", f"{prefix}_time_window_night"),
    ]
    footer = [
        ("📅 Change Date", f"{prefix}_date_preset_custom"),
        ("✏️ Edit Previous", f"{prefix}_edit_date_preset"),
    ]
    return build_compact_markup(options, columns=2, footer=footer)


def build_time_options_markup(
    window: str, prefix: str = "event"
) -> InlineKeyboardMarkup:
    """Build compact keyboard for concrete time options by window."""
    time_options = TIME_WINDOWS.get(window, [])
    options = [
        (time_value, f"{prefix}_time_option_{time_value.replace(':', '')}")
        for time_value in time_options
    ]
    footer = [
        ("⌨️ Enter Time Manually", f"{prefix}_time_manual"),
        ("✏️ Edit Previous", f"{prefix}_edit_time_window"),
    ]
    return build_compact_markup(options, columns=3, footer=footer)


def build_location_type_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build location type presets."""
    options = [
        (label, f"{prefix}_location_{value}") for label, value in LOCATION_PRESETS
    ]
    return build_compact_markup(
        options,
        columns=2,
        footer=[("✏️ Edit Previous", f"{prefix}_edit_duration")],
    )


def build_budget_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build budget presets."""
    options = [(label, f"{prefix}_budget_{value}") for label, value in BUDGET_PRESETS]
    return build_compact_markup(
        options,
        columns=2,
        footer=[("✏️ Edit Previous", f"{prefix}_edit_location")],
    )


def build_transport_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build transport mode presets."""
    options = [
        (label, f"{prefix}_transport_{value}") for label, value in TRANSPORT_PRESETS
    ]
    return build_compact_markup(
        options,
        columns=2,
        footer=[("✏️ Edit Previous", f"{prefix}_edit_budget")],
    )


def build_invitee_mode_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build invitee entry mode keyboard."""
    options = [
        ("👥 Invite All Members", f"{prefix}_invite_all"),
        ("✍️ Enter Handles", f"{prefix}_invite_custom"),
    ]
    return build_compact_markup(
        options,
        columns=1,
        footer=[("✏️ Edit Previous", f"{prefix}_edit_transport")],
    )


def resolve_date_preset(preset: str, now: datetime | None = None) -> list[date]:
    """Resolve date preset into one or more candidate dates."""
    base = (now or datetime.now()).date()
    if preset == "today":
        return [base]
    if preset == "tomorrow":
        return [base + timedelta(days=1)]
    if preset == "weekend":
        days_until_saturday = (5 - base.weekday()) % 7
        saturday = base + timedelta(days=days_until_saturday)
        sunday = saturday + timedelta(days=1)
        return [saturday, sunday]
    if preset == "nextweek":
        days_until_next_monday = (7 - base.weekday()) % 7
        if days_until_next_monday == 0:
            days_until_next_monday = 7
        monday = base + timedelta(days=days_until_next_monday)
        return [monday + timedelta(days=offset) for offset in range(7)]
    return []


def build_calendar_markup(
    year: int, month: int, prefix: str = "event"
) -> InlineKeyboardMarkup:
    """Build month-view inline calendar keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(
                f"{month_name[month]} {year}", callback_data=f"{prefix}_cal_ignore"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(day, callback_data=f"{prefix}_cal_ignore")
            for day in CALENDAR_WEEKDAYS
        ]
    )

    cal = Calendar(firstweekday=0)
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(
                    InlineKeyboardButton(" ", callback_data=f"{prefix}_cal_ignore")
                )
            else:
                row.append(
                    InlineKeyboardButton(
                        str(day),
                        callback_data=f"{prefix}_cal_day_{year}_{month}_{day}",
                    )
                )
        rows.append(row)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    rows.append(
        [
            InlineKeyboardButton(
                "◀️",
                callback_data=f"{prefix}_cal_nav_{prev_year}_{prev_month}",
            ),
            InlineKeyboardButton(" ", callback_data=f"{prefix}_cal_ignore"),
            InlineKeyboardButton(
                "▶️",
                callback_data=f"{prefix}_cal_nav_{next_year}_{next_month}",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "✏️ Edit Previous", callback_data=f"{prefix}_edit_date_preset"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


def parse_invitee_handles(raw_text: str) -> list[str]:
    """Parse comma-separated @handles and return normalized unique handles."""
    handles: list[str] = []
    seen: set[str] = set()
    tokens = [token.strip() for token in raw_text.split(",") if token.strip()]
    if not tokens:
        raise ValueError("No handles provided")

    for token in tokens:
        if not token.startswith("@"):
            raise ValueError("Handle must start with @")

        handle = token[1:]
        if not TELEGRAM_HANDLE_PATTERN.fullmatch(handle):
            raise ValueError("Invalid Telegram handle")

        normalized = f"@{handle.lower()}"
        if normalized not in seen:
            seen.add(normalized)
            handles.append(normalized)

    return handles


def parse_invitee_input(raw_text: str) -> tuple[list[str], bool]:
    """Parse invitee input and support @all shortcut."""
    normalized = raw_text.strip().lower()
    if normalized == "@all":
        return ["@all"], True
    return parse_invitee_handles(raw_text), False


def build_event_type_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build event type selection keyboard."""
    return build_compact_markup(
        [
            ("Social", f"{prefix}_type_social"),
            ("Sports", f"{prefix}_type_sports"),
            ("Work", f"{prefix}_type_work"),
        ],
        columns=2,
        footer=[("✏️ Edit Previous", f"{prefix}_edit_description")],
    )


def build_duration_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build compact duration selection keyboard."""
    options = [
        ("30m", f"{prefix}_duration_30"),
        ("60m", f"{prefix}_duration_60"),
        ("90m", f"{prefix}_duration_90"),
        ("120m", f"{prefix}_duration_120"),
        ("180m", f"{prefix}_duration_180"),
    ]
    return build_compact_markup(
        options,
        columns=2,
        footer=[("✏️ Edit Previous", f"{prefix}_edit_threshold")],
    )


def build_final_confirmation_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build final confirmation keyboard with revision support."""
    if prefix == "event":
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data=f"{prefix}_final_yes")],
            [InlineKeyboardButton("🛠 Modify", callback_data=f"{prefix}_final_edit")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{prefix}_cancel_no")],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Confirm & Lock", callback_data=f"{prefix}_final_yes"
                )
            ],
            [InlineKeyboardButton("🛠 Modify", callback_data=f"{prefix}_final_edit")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{prefix}_cancel_no")],
        ]
    return InlineKeyboardMarkup(keyboard)


def build_event_summary_text(data: dict[str, Any], is_private: bool = False) -> str:
    """Build event draft summary text."""
    # Use human-readable formatters
    scheduled_time = format_scheduled_time(data.get("scheduled_time"))
    invitees = data.get("invitees", [])
    if not isinstance(invitees, list):
        invitees = []
    invite_all = bool(data.get("invite_all_members"))
    invitees_summary = (
        "all group members"
        if invite_all
        else f"{len(invitees)} users ({', '.join(invitees) if invitees else 'none'})"
    )
    notes = data.get("planning_notes", [])

    # Use human-readable formatters for planning preferences
    date_preset_label = format_date_preset(data.get("date_preset"))
    time_window_label = format_time_window(data.get("time_window"))
    location_type_label = format_location_type(data.get("location_type"))
    budget_level_label = format_budget_level(data.get("budget_level"))
    transport_mode_label = format_transport_mode(data.get("transport_mode"))
    commit_by_text = format_commit_by(data.get("commit_by"))

    notes_text = ""
    if isinstance(notes, list) and notes:
        note_lines = [f"- {str(note)}" for note in notes[-5:]]
        notes_text = "\n\nPlanning notes:\n" + "\n".join(note_lines)

    if is_private:
        return (
            f"✨ *Event Summary*\n\n"
            f"Type: {data.get('event_type', 'Not specified')}\n"
            f"Description: {data.get('description', 'Not provided')}\n"
            f"Time: {scheduled_time}\n"
            f"Date Preset: {date_preset_label}\n"
            f"Time Window: {time_window_label}\n"
            f"Commit-By: {commit_by_text}\n"
            f"Duration: {format_duration(data.get('duration_minutes'))}\n"
            f"Location Type: {location_type_label}\n"
            f"Budget: {budget_level_label}\n"
            f"Transport: {transport_mode_label}\n"
            f"Minimum: {data.get('min_participants', 'Not set')}\n"
            f"Capacity: {data.get('target_participants', 'Not set')}\n"
            f"Invitees: {invitees_summary}\n\n"
            "Press *Confirm & Lock* to finalize and lock this event."
        )

    return (
        f"✨ *Event Summary*\n\n"
        f"Type: {data.get('event_type', 'Not specified')}\n"
        f"Description: {data.get('description', 'Not provided')}\n"
        f"Time: {scheduled_time}\n"
        f"Date Preset: {date_preset_label}\n"
        f"Time Window: {time_window_label}\n"
        f"Commit-By: {commit_by_text}\n"
        f"Duration: {format_duration(data.get('duration_minutes'))}\n"
        f"Mode: {data.get('scheduling_mode', 'fixed')}\n"
        f"Location Type: {location_type_label}\n"
        f"Budget: {budget_level_label}\n"
        f"Transport: {transport_mode_label}\n"
        f"Minimum: {data.get('min_participants', 'Not set')}\n"
        f"Capacity: {data.get('target_participants', 'Not set')}\n"
        f"Invitees: {invitees_summary}"
        f"{notes_text}\n\n"
        "Create this event?\n"
        "You can press *Modify* or reply with free-text changes."
    )


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
        if TELEGRAM_HANDLE_PATTERN.fullmatch(handle):
            normalized.append(f"@{handle.lower()}")
    deduped: list[str] = []
    seen: set[str] = set()
    for handle in normalized:
        if handle not in seen:
            seen.add(handle)
            deduped.append(handle)
    return deduped


async def _apply_final_stage_patch(
    flow_data: dict[str, Any],
    message_text: str,
    is_private: bool = False,
) -> tuple[bool, list[str], str | None]:
    """Apply LLM-inferred patch to event draft data."""
    try:
        llm = LLMClient()
        try:
            patch = await llm.infer_event_draft_patch(flow_data, message_text)
        finally:
            await llm.close()
    except Exception:
        if is_private:
            return False, [], "LLM unavailable for modifications"
        return False, [], None

    changes: list[str] = []
    warnings: list[str] = []
    changed = False

    description = patch.get("description")
    if isinstance(description, str) and description.strip():
        next_description = description.strip()[:500]
        if next_description != str(flow_data.get("description", "")):
            flow_data["description"] = next_description
            changes.append("description updated")
            changed = True

    event_type_raw = patch.get("event_type")
    if event_type_raw is not None:
        normalized = str(event_type_raw).strip().lower()
        if normalized in ALLOWED_EVENT_TYPES:
            if normalized != str(flow_data.get("event_type", "")).lower():
                flow_data["event_type"] = normalized
                changes.append(f"type set to {normalized}")
                changed = True
        else:
            warnings.append(
                "Unsupported event type in modification; kept current value."
            )

    min_raw = patch.get("min_participants")
    if min_raw is not None:
        try:
            min_participants = int(min_raw)
            if min_participants < 1:
                warnings.append("Minimum participants must be at least 1.")
            else:
                flow_data["min_participants"] = min_participants
                existing_target = int(
                    flow_data.get("target_participants", min_participants)
                )
                if existing_target < min_participants:
                    flow_data["target_participants"] = min_participants
                changes.append(f"minimum set to {min_participants}")
                changed = True
        except (TypeError, ValueError):
            warnings.append("Invalid minimum participant format; ignored.")

    target_raw = patch.get("target_participants")
    if target_raw is not None:
        try:
            target_participants = int(target_raw)
            min_participants = int(flow_data.get("min_participants", 2))
            if target_participants < min_participants:
                warnings.append("Capacity cannot be below the minimum participants.")
            else:
                flow_data["target_participants"] = target_participants
                changes.append(f"capacity set to {target_participants}")
                changed = True
        except (TypeError, ValueError):
            warnings.append("Invalid capacity format; ignored.")

    duration_raw = patch.get("duration_minutes")
    if duration_raw is not None:
        try:
            duration = int(duration_raw)
            if duration <= 0 or duration > 720:
                warnings.append("Duration must be between 1 and 720 minutes.")
            else:
                flow_data["duration_minutes"] = duration
                changes.append(f"duration set to {duration} minutes")
                changed = True
        except (TypeError, ValueError):
            warnings.append("Invalid duration format; ignored.")

    if not is_private:
        mode_raw = patch.get("scheduling_mode")
        if mode_raw is not None:
            normalized_mode = str(mode_raw).strip().lower()
            if normalized_mode in {"fixed", "flexible"}:
                flow_data["scheduling_mode"] = normalized_mode
                changes.append(f"mode set to {normalized_mode}")
                changed = True
                if normalized_mode == "flexible":
                    flow_data.pop("scheduled_time", None)
                    flow_data.pop("scheduled_date", None)
            else:
                warnings.append("Unsupported scheduling mode; ignored.")

    location_raw = patch.get("location_type")
    if location_raw is not None:
        normalized_location = str(location_raw).strip().lower().replace(" ", "_")
        valid_locations = {value for _, value in LOCATION_PRESETS}
        if normalized_location in valid_locations:
            flow_data["location_type"] = normalized_location
            changes.append(f"location type set to {normalized_location}")
            changed = True
        else:
            warnings.append("Unsupported location type; ignored.")

    budget_raw = patch.get("budget_level")
    if budget_raw is not None:
        normalized_budget = str(budget_raw).strip().lower().replace(" ", "_")
        valid_budgets = {value for _, value in BUDGET_PRESETS}
        if normalized_budget in valid_budgets:
            flow_data["budget_level"] = normalized_budget
            changes.append(f"budget set to {normalized_budget}")
            changed = True
        else:
            warnings.append("Unsupported budget level; ignored.")

    transport_raw = patch.get("transport_mode")
    if transport_raw is not None:
        normalized_transport = str(transport_raw).strip().lower().replace(" ", "_")
        valid_transport = {value for _, value in TRANSPORT_PRESETS}
        if normalized_transport in valid_transport:
            flow_data["transport_mode"] = normalized_transport
            changes.append(f"transport set to {normalized_transport}")
            changed = True
        else:
            warnings.append("Unsupported transport mode; ignored.")

    if not is_private:
        time_window_raw = patch.get("time_window")
        if time_window_raw is not None:
            normalized_window = str(time_window_raw).strip().lower()
            if normalized_window in TIME_WINDOWS:
                flow_data["time_window"] = normalized_window
                changes.append(f"time window set to {normalized_window}")
                changed = True
            else:
                warnings.append("Unsupported time window; ignored.")

        date_preset_raw = patch.get("date_preset")
        if date_preset_raw is not None:
            normalized_preset = str(date_preset_raw).strip().lower()
            if normalized_preset in DATE_PRESET_LABELS or normalized_preset == "custom":
                flow_data["date_preset"] = normalized_preset
                changes.append(f"date preset set to {normalized_preset}")
                changed = True
            else:
                warnings.append("Unsupported date preset; ignored.")

    if not is_private and bool(patch.get("clear_time")):
        flow_data.pop("scheduled_time", None)
        flow_data.pop("scheduled_date", None)
        changes.append("time cleared (now TBD)")
        changed = True

    scheduled_time_iso = patch.get("scheduled_time_iso")
    if scheduled_time_iso is not None:
        try:
            parsed = datetime.fromisoformat(str(scheduled_time_iso).strip())
            flow_data["scheduled_time"] = parsed.isoformat(timespec="minutes")
            if not is_private:
                flow_data["scheduling_mode"] = "fixed"
            changes.append(f"time set to {parsed.strftime('%Y-%m-%d %H:%M')}")
            changed = True
        except ValueError:
            warnings.append("Invalid datetime format; use YYYY-MM-DDTHH:MM.")

    invitees_add = _normalize_patch_invitees(patch.get("invitees_add"))
    if invitees_add:
        if bool(flow_data.get("invite_all_members")):
            flow_data["invite_all_members"] = False
            flow_data["invitees"] = []
        existing = list(flow_data.get("invitees", []))
        for handle in invitees_add:
            if handle not in existing:
                existing.append(handle)
        flow_data["invitees"] = existing
        changes.append(f"added invitees: {', '.join(invitees_add)}")
        changed = True

    invitees_remove = _normalize_patch_invitees(patch.get("invitees_remove"))
    if invitees_remove:
        existing = list(flow_data.get("invitees", []))
        reduced = [h for h in existing if h not in set(invitees_remove)]
        flow_data["invitees"] = reduced
        if flow_data.get("invite_all_members"):
            flow_data["invite_all_members"] = False
        changes.append(f"removed invitees: {', '.join(invitees_remove)}")
        changed = True

    if patch.get("invite_all_members") is True:
        flow_data["invite_all_members"] = True
        flow_data["invitees"] = ["@all"]
        changes.append("invitees set to all group members")
        changed = True
    elif patch.get("invite_all_members") is False and flow_data.get(
        "invite_all_members"
    ):
        flow_data["invite_all_members"] = False
        if flow_data.get("invitees") == ["@all"]:
            flow_data["invitees"] = []
        changes.append("invite-all disabled")
        changed = True

    if not is_private:
        note = patch.get("note")
        if isinstance(note, str) and note.strip():
            notes = flow_data.get("planning_notes")
            if not isinstance(notes, list):
                notes = []
            notes.append(note.strip()[:300])
            flow_data["planning_notes"] = notes[-10:]
            changes.append("added planning note")
            changed = True

    if (
        not is_private
        and str(flow_data.get("scheduling_mode", "fixed")) == "fixed"
        and not flow_data.get("scheduled_time")
    ):
        warnings.append("Fixed mode requires a date/time before final confirm.")

    warning_text = "\n".join(f"- {w}" for w in warnings) if warnings else None
    return changed, changes, warning_text


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
            "invite_all_members": True,  # Default to inviting all group members for public events
        },
    }

    if mode == "public":
        flow_data["group_id"] = group.group_id
        flow_data["group_title"] = chat_title
        flow_data["data"]["scheduling_mode"] = "fixed"

    context.user_data[flow_key] = flow_data

    if mode == "private":
        await message.reply_text(
            "📝 *Event Description*\n\n"
            "Send a short description for the event.\n\n"
            "Example: Friendly football match at the central field.",
        )
    else:
        scheduling_mode = flow_data["data"].get("scheduling_mode", "fixed")
        mode_text = (
            "Fixed date/time"
            if scheduling_mode == "fixed"
            else "Flexible (collect availability first)"
        )
        await message.reply_text(
            "📝 *Event Description*\n\n"
            "Send a short description for the event.\n"
            f"Mode: {mode_text}\n\n"
            "Example: Friendly football match at the central field.\n"
            "Most next steps are one-tap inline options.",
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
    await _handle_callback_common(update, context, mode="public")


async def private_handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle callback queries for private event creation flow."""
    await _handle_callback_common(update, context, mode="private")


async def _handle_callback_common(
    update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str
) -> None:
    """Handle callback queries for event creation flow."""
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
                        reply_markup=build_threshold_markup(f"{prefix}_edit_type"),
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
                reply_markup=build_threshold_markup(back_target),
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
                reply_markup=build_threshold_markup(f"{prefix}_edit_type"),
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
            reply_markup=build_min_participants_markup(f"{prefix}_edit_time_window"),
        )

    # v3.2: Handle min_participants selection
    elif data and data.startswith(f"{prefix}_min_"):
        min_val = int(data.replace(f"{prefix}_min_", ""))
        event_flow["stage"] = "target_participants"
        flow_data["min_participants"] = min_val
        # Default target = ceil(min * 1.5)
        import math

        flow_data["target_participants"] = math.ceil(min_val * 1.5)
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"✅ *Minimum: {min_val}*\n\n"
            f"How many people can this comfortably fit? (Default: {flow_data['target_participants']})",
            reply_markup=build_target_participants_markup(
                min_val, f"{prefix}_min_{min_val}"
            ),
        )

    # v3.2: Handle target_participants selection
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
        # Legacy fallback: if old threshold_ callback is clicked
        threshold = int(data.replace(f"{prefix}_threshold_", ""))
        event_flow["stage"] = "duration"
        flow_data["min_participants"] = threshold
        flow_data["target_participants"] = threshold
        context.user_data[flow_key] = event_flow
        await query.edit_message_text(
            f"✅ *Minimum/Capacity: {threshold}*\n\nSelect event duration:",
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
            await finalize_private_event(query, context)
        else:
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages during public event creation flow."""
    await _handle_message_common(update, context, mode="public")


async def private_handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle text messages during private event creation flow."""
    await _handle_message_common(update, context, mode="private")


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
                reply_markup=build_threshold_markup(
                    "event_edit_time_window"
                    if mode == "public"
                    else "private_event_edit_time_window"
                ),
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


async def finalize_event(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, _mode: str = "public"
) -> None:
    """Finalize and create the public/event in database."""
    if context.user_data is None:
        await query.edit_message_text("❌ User session data is unavailable.")
        return

    event_flow_raw = context.user_data.get("event_flow")
    if not isinstance(event_flow_raw, dict):
        await query.edit_message_text("❌ Event flow not found.")
        return

    event_flow: dict[str, Any] = event_flow_raw
    data_raw = event_flow.get("data")
    if not isinstance(data_raw, dict):
        await query.edit_message_text("❌ Event flow data is invalid.")
        return
    data: dict[str, Any] = data_raw

    scheduled_time_raw = data.get("scheduled_time")
    scheduling_mode = str(data.get("scheduling_mode", "fixed"))
    if scheduling_mode != "flexible" and not isinstance(scheduled_time_raw, str):
        await query.edit_message_text("❌ Event time is missing.")
        return

    group_id = event_flow.get("group_id")
    if not isinstance(group_id, int):
        await query.edit_message_text("❌ Group context is missing.")
        return

    async with get_session(settings.db_url) as session:
        candidate_time = (
            datetime.fromisoformat(scheduled_time_raw)
            if isinstance(scheduled_time_raw, str)
            else None
        )
        commit_by = compute_commit_by_time(candidate_time)
        duration_minutes = int(data.get("duration_minutes", 120))
        creator_id = int(data.get("creator", query.from_user.id))
        conflict = await find_user_event_conflict(
            session=session,
            telegram_user_id=creator_id,
            start_time=candidate_time,
            duration_minutes=duration_minutes,
        )
        if conflict:
            await query.edit_message_text(
                "❌ Creator has a conflicting event.\n"
                f"Conflicting Event ID: {conflict.event_id}\n"
                f"Time: {conflict.scheduled_time}\n"
                f"Duration: {conflict.duration_minutes or 120} minutes"
            )
            return

        event = Event(
            group_id=group_id,
            event_type=data.get("event_type", "general"),
            description=data.get("description"),
            organizer_telegram_user_id=creator_id,
            admin_telegram_user_id=creator_id,
            scheduled_time=candidate_time,
            commit_by=commit_by,
            duration_minutes=duration_minutes,
            min_participants=data.get("min_participants", 2),
            target_participants=data.get(
                "target_participants", max(data.get("min_participants", 2), 5)
            ),
            planning_prefs={
                "date_preset": data.get("date_preset"),
                "time_window": data.get("time_window"),
                "location_type": data.get("location_type"),
                "budget_level": data.get("budget_level"),
                "transport_mode": data.get("transport_mode"),
            },
            state="proposed",
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        # Create participant record for the organizer
        from bot.services import ParticipantService

        participant_service = ParticipantService(session)
        await participant_service.join(
            event_id=event.event_id,
            telegram_user_id=creator_id,
            source="creation",
            role="organizer",
        )

        # Check for event lineage (TODO-013) - prior events of same type
        from bot.services.event_memory_service import EventMemoryService

        memory_service = EventMemoryService(context.bot, session)
        prior_memories = await memory_service.get_recent_memories(group_id, limit=5)

        # Filter for same event type
        lineage_event_ids = []
        lineage_suggestion = None
        for memory in prior_memories:
            if memory.event and memory.event.event_type == event.event_type:
                lineage_event_ids.append(memory.event.event_id)
                if not lineage_suggestion and memory.weave_text:
                    # Use first memory as lineage suggestion
                    lineage_suggestion = {
                        "event_id": memory.event.event_id,
                        "event_type": memory.event.event_type,
                        "weave_preview": (
                            memory.weave_text[:200] if memory.weave_text else None
                        ),
                        "hashtags": memory.hashtags or [],
                    }

        # Store lineage if found
        if lineage_event_ids:
            await memory_service.link_lineage(
                event.event_id, lineage_event_ids[:3]
            )  # Max 3
            logger.info(
                "Linked lineage for event %s: %s",
                event.event_id,
                lineage_event_ids[:3],
            )

        # Phase 3.3: Create hashtag service and assign hashtags if provided
        hashtags = data.get("hashtags", [])
        if hashtags:
            hashtag_service = EventHashtagService(session)
            try:
                event = await hashtag_service.assign_hashtags(event, hashtags)
                logger.info(
                    "Assigned hashtags to event %s: %s",
                    event.event_id,
                    hashtags,
                )
            except ValueError as e:
                logger.warning(f"Failed to assign hashtags: {e}")

        # Phase 3.3: Create live card after commit
        live_card_service = EventLiveCardService(context.bot, session)
        await live_card_service.create_live_card(event, hashtags=hashtags)

    context.user_data.pop("event_flow", None)

    invitees = list(data.get("invitees", []))

    logger.info(
        "Event %s created in group %s: invitees=%s",
        event.event_id,
        group_id,
        invitees,
    )

    async with get_session(settings.db_url) as session:
        # Get organizer's username and display_name for display in invitation
        organizer_user = (
            await session.execute(
                select(User).where(User.telegram_user_id == int(creator_id))
            )
        ).scalar_one_or_none()
        organizer_username = organizer_user.username if organizer_user else None
        organizer_display_name = organizer_user.display_name if organizer_user else None

        group = (
            await session.execute(select(Group).where(Group.group_id == group_id))
        ).scalar_one_or_none()

        # Add organizer info to data for the invitation message
        data["organizer_telegram_user_id"] = int(creator_id)
        data["organizer_username"] = organizer_username
        data["organizer_display_name"] = organizer_display_name

        group_members = group.member_list or []

        # Send DMs - group-organized events notify members privately
        dm_count = 0
        dm_failed = 0

        logger.info(
            "Group event %s: Sending DMs to all %s group members",
            event.event_id,
            len(group_members),
        )
        for telegram_user_id in group_members:
            if telegram_user_id:
                try:
                    sent = await send_event_invitation_dm(
                        context,
                        int(telegram_user_id),
                        data,
                        int(event.event_id),
                    )
                    if sent:
                        logger.info(
                            "DM sent to user %s for event %s (group event, all members)",
                            telegram_user_id,
                            event.event_id,
                        )
                        dm_count += 1
                    else:
                        dm_failed += 1
                except Exception as e:
                    logger.error(
                        "Error sending DM to user %s: %s",
                        telegram_user_id,
                        e,
                        exc_info=True,
                    )
                    dm_failed += 1

        # If no group members were found, still notify the creator in DM
        if dm_count == 0:
            try:
                sent = await send_event_invitation_dm(
                    context,
                    int(creator_id),
                    data,
                    int(event.event_id),
                )
                if sent:
                    logger.info(
                        "DM sent to admin %s for event %s (fallback, no group members)",
                        creator_id,
                        event.event_id,
                    )
                    dm_count += 1
                else:
                    dm_failed += 1
            except Exception as e:
                logger.error(
                    "Error sending DM to admin %s: %s",
                    creator_id,
                    e,
                    exc_info=True,
                )
                dm_failed += 1

        logger.info(
            "Event %s DM distribution complete: %s sent, %s failed",
            event.event_id,
            dm_count,
            dm_failed,
        )
    # Use human-readable formatters
    scheduled_time = format_scheduled_time(data.get("scheduled_time"))
    commit_by_text = format_commit_by(commit_by)
    invitees_summary = (
        "all group members"
        if data.get("invite_all_members")
        else f"{len(data.get('invitees', []))} users"
    )
    location_text = format_location_type(data.get("location_type"))
    budget_text = format_budget_level(data.get("budget_level"))
    transport_text = format_transport_mode(data.get("transport_mode"))
    date_preset_text = format_date_preset(data.get("date_preset"))
    time_window_text = format_time_window(data.get("time_window"))

    # Minimal summary for group - only the announcement + event ID
    group_summary = (
        f"✅ *Event Created!*\n\n"
        f"Event ID: `{event.event_id}`\n"
        f"Description: {_escape_md(data.get('description', 'Not provided'))}\n\n"
        "A private DM has been sent to group members with full event details and next steps."
    )

    await query.edit_message_text(group_summary)

    # Full details in admin's DM
    full_summary = (
        f"✅ *Event Created Successfully!*\n\n"
        f"Event ID: `{event.event_id}`\n"
        f"State: proposed (awaiting confirmations)\n\n"
        f"Type: {_escape_md(data.get('event_type', 'Not specified'))}\n"
        f"Description: {_escape_md(data.get('description', 'Not provided'))}\n"
        f"Time: {_escape_md(scheduled_time)}\n"
        f"Commit-By: {_escape_md(commit_by_text)}\n"
        f"Date Preset: {_escape_md(date_preset_text)}\n"
        f"Time Window: {_escape_md(time_window_text)}\n"
        f"Duration: {_escape_md(format_duration(data.get('duration_minutes')))}\n"
        f"Mode: {_escape_md(scheduling_mode)}\n"
        f"Location Type: {_escape_md(location_text)}\n"
        f"Budget: {_escape_md(budget_text)}\n"
        f"Transport: {_escape_md(transport_text)}\n"
        f"Minimum: {_escape_md(data.get('min_participants', 'Not set'))}\n"
        f"Capacity: {_escape_md(data.get('target_participants', 'Not set'))}\n"
        f"Invitees: {_escape_md(invitees_summary)}\n\n"
        f"✅ Event ready for confirmation. Run /confirm {event.event_id} to lock it."
        + (
            "\n\nFlexible flow tip:\n"
            "Each attendee can add availability slots with:\n"
            f"/constraints {event.event_id} availability <YYYY-MM-DD HH:MM, ...>"
            if scheduling_mode == "flexible"
            else ""
        )
    )

    # Send full details to admin via DM
    dm_keyboard = [
        [
            InlineKeyboardButton(
                "View Event Details", callback_data=f"event_details_{event.event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "Manage Event", callback_data=f"event_admin_{event.event_id}"
            )
        ],
    ]
    dm_reply_markup = InlineKeyboardMarkup(dm_keyboard)

    await context.bot.send_message(
        chat_id=creator_id,
        text=full_summary,
        reply_markup=dm_reply_markup,
        parse_mode="Markdown",
    )
    logger.info(
        "Full event details sent to admin %s via DM for event %s",
        creator_id,
        event.event_id,
    )


async def finalize_private_event(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Finalize and create the private event in database."""
    if context.user_data is None:
        await query.edit_message_text("❌ Session data unavailable.")
        return

    event_flow_raw = context.user_data.get("private_event_flow")
    if not isinstance(event_flow_raw, dict):
        await query.edit_message_text("❌ Event flow not found.")
        return

    event_flow: dict[str, Any] = event_flow_raw
    data_raw = event_flow.get("data")
    if not isinstance(data_raw, dict):
        await query.edit_message_text("❌ Event flow data is invalid.")
        return
    data: dict[str, Any] = data_raw

    scheduled_time_raw = data.get("scheduled_time")
    scheduling_mode = str(data.get("scheduling_mode", "fixed"))
    if scheduling_mode != "flexible" and not isinstance(scheduled_time_raw, str):
        await query.edit_message_text("❌ Event time is missing.")
        return

    creator_id = int(data.get("creator", query.from_user.id))

    async with get_session(settings.db_url) as session:
        candidate_time = (
            datetime.fromisoformat(scheduled_time_raw)
            if isinstance(scheduled_time_raw, str)
            else None
        )
        commit_by = compute_commit_by_time(candidate_time)
        duration_minutes = int(data.get("duration_minutes", 120))

        try:
            conflict = await find_user_event_conflict(
                session=session,
                telegram_user_id=creator_id,
                start_time=candidate_time,
                duration_minutes=duration_minutes,
            )
            if conflict:
                await query.edit_message_text(
                    "❌ Creator has a conflicting event.\n"
                    f"Conflicting Event ID: {conflict.event_id}\n"
                    f"Time: {conflict.scheduled_time}\n"
                    f"Duration: {conflict.duration_minutes or 120} minutes"
                )
                return
        except ImportError:
            pass

        event = Event(
            group_id=0,
            event_type=data.get("event_type", "general"),
            description=data.get("description"),
            organizer_telegram_user_id=creator_id,
            scheduled_time=candidate_time,
            commit_by=commit_by,
            duration_minutes=duration_minutes,
            min_participants=data.get("min_participants", 2),
            target_participants=data.get(
                "target_participants", max(data.get("min_participants", 2), 5)
            ),
            planning_prefs={
                "date_preset": data.get("date_preset"),
                "time_window": data.get("time_window"),
                "location_type": data.get("location_type"),
                "budget_level": data.get("budget_level"),
                "transport_mode": data.get("transport_mode"),
            },
            state="confirmed",
            locked_at=datetime.utcnow(),
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        # Create participant record for the organizer
        from bot.services import ParticipantService

        participant_service = ParticipantService(session)
        await participant_service.join(
            event_id=event.event_id,
            telegram_user_id=creator_id,
            source="creation",
            role="organizer",
        )

        # Phase 3.3: Create hashtag service and assign hashtags if provided
        hashtags = data.get("hashtags", [])
        if hashtags:
            hashtag_service = EventHashtagService(session)
            try:
                event = await hashtag_service.assign_hashtags(event, hashtags)
                logger.info(
                    "Assigned hashtags to private event %s: %s",
                    event.event_id,
                    hashtags,
                )
            except ValueError as e:
                logger.warning(f"Failed to assign hashtags: {e}")

        # Phase 3.3: Create live card after commit
        # For private events, we still create a live card but it won't display in group
        live_card_service = EventLiveCardService(context.bot, session)
        await live_card_service.create_live_card(event, hashtags=hashtags)

    # Send invitations to invitees (private events)
    # Private events: DM ONLY to listed invitees + admin (NOT to all group members)
    invitees = list(data.get("invitees", []))

    organizer_username = None

    async with get_session(settings.db_url) as session:
        # Get organizer's username for display in invitation
        organizer_user = (
            await session.execute(
                select(User).where(User.telegram_user_id == int(creator_id))
            )
        ).scalar_one_or_none()
        organizer_username = organizer_user.username if organizer_user else None

        # Add organizer info to data for the invitation message
        data["organizer_telegram_user_id"] = int(creator_id)
        data["organizer_username"] = organizer_username

        dm_count = 0
        dm_failed = 0

        # Send to all listed invitees
        if invitees:
            logger.info(
                "Private event %s: Sending DMs to %s invitees",
                event.event_id,
                len(invitees),
            )
            for handle in invitees:
                if not handle.startswith("@"):
                    continue
                username = handle[1:]
                try:
                    user_id = await get_user_id_by_username(session, username)
                    if user_id:
                        result = await session.execute(
                            select(User).where(User.user_id == int(user_id))
                        )
                        invitee_user = result.scalar_one_or_none()
                        if invitee_user and invitee_user.telegram_user_id:
                            sent = await send_event_invitation_dm(
                                context,
                                int(invitee_user.telegram_user_id),
                                data,
                                int(event.event_id),
                            )
                            if sent:
                                logger.info(
                                    "DM sent to user %s (@%s) for private event %s (invitee)",
                                    invitee_user.telegram_user_id,
                                    username,
                                    event.event_id,
                                )
                                dm_count += 1
                            else:
                                dm_failed += 1
                        else:
                            logger.warning(
                                "User @%s not found or no telegram_user_id for private event %s",
                                username,
                                event.event_id,
                            )
                            dm_failed += 1
                    else:
                        logger.warning(
                            "No user_id found for handle @%s in private event %s",
                            username,
                            event.event_id,
                        )
                        dm_failed += 1
                except Exception as e:
                    logger.error(
                        "Error sending DM to @%s: %s",
                        username,
                        e,
                        exc_info=True,
                    )
                    dm_failed += 1
        else:
            await query.edit_message_text(
                "❌ For private events, you must specify invitees. Use @username (comma-separated)."
            )
            return

        # Also send to admin/creator
        try:
            sent = await send_event_invitation_dm(
                context, int(creator_id), data, int(event.event_id)
            )
            if sent:
                logger.info(
                    "DM sent to admin %s for private event %s (admin)",
                    creator_id,
                    event.event_id,
                )
                dm_count += 1
            else:
                dm_failed += 1
        except Exception as e:
            logger.error(
                "Error sending DM to admin %s: %s",
                creator_id,
                e,
                exc_info=True,
            )
            dm_failed += 1

        logger.info(
            "Private event %s DM distribution complete: %s sent, %s failed",
            event.event_id,
            dm_count,
            dm_failed,
        )

    context.user_data.pop("private_event_flow", None)

    keyboard = [
        [
            InlineKeyboardButton(
                "View Event", callback_data=f"private_event_details_{event.event_id}"
            )
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Use human-readable formatters
    scheduled_time = format_scheduled_time(data.get("scheduled_time"))
    commit_by_text = format_commit_by(commit_by)
    invitees_summary = (
        "all group members"
        if data.get("invite_all_members")
        else f"{len(invitees)} users"
    )
    location_text = format_location_type(data.get("location_type"))
    budget_text = format_budget_level(data.get("budget_level"))
    transport_text = format_transport_mode(data.get("transport_mode"))
    date_preset_text = format_date_preset(data.get("date_preset"))
    time_window_text = format_time_window(data.get("time_window"))

    await query.edit_message_text(
        f"✅ *Event Created!*\n\n"
        f"Event ID: {event.event_id}\n"
        f"Type: {_escape_md(data.get('event_type', 'Not specified'))}\n"
        f"Description: {_escape_md(data.get('description', 'Not provided'))}\n"
        f"Time: {_escape_md(scheduled_time)}\n"
        f"Commit-By: {_escape_md(commit_by_text)}\n"
        f"Date Preset: {_escape_md(date_preset_text)}\n"
        f"Time Window: {_escape_md(time_window_text)}\n"
        f"Duration: {_escape_md(format_duration(data.get('duration_minutes')))}\n"
        f"Mode: {_escape_md(scheduling_mode)}\n"
        f"Location Type: {_escape_md(location_text)}\n"
        f"Budget: {_escape_md(budget_text)}\n"
        f"Transport: {_escape_md(transport_text)}\n"
        f"Minimum: {_escape_md(data.get('min_participants', 'Not set'))}\n"
        f"Capacity: {_escape_md(data.get('target_participants', 'Not set'))}\n"
        f"Invitees: {_escape_md(invitees_summary)}\n\n"
        f"✅ Event has been automatically locked.\n"
        f"Status: Locked - No further changes allowed.\n\n"
        + (
            f"Event Admin: {organizer_username if organizer_username else creator_id}"
            if organizer_username
            else f"Event Admin: {creator_id}"
        ),
        reply_markup=reply_markup,
    )
