#!/usr/bin/env python3
"""Suggest time command handler with calendar selector."""

from calendar import Calendar, month_name
from datetime import datetime, timedelta
from typing import cast
from telegram import (
    Update,
    Message,
    InaccessibleMessage,
    MaybeInaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import ContextTypes, CallbackQueryHandler
from sqlalchemy import select
from db.models import Event, Constraint
from db.connection import get_session
from config.settings import settings
from ai.core import AICoordinationEngine
from bot.common.confirmation import invalidate_confirmations_and_notify

CALENDAR_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
TIME_WINDOWS = {
    "early-morning": ["04:00", "05:00", "06:00", "07:00"],
    "morning": ["08:00", "09:00", "10:00", "11:00"],
    "afternoon": ["12:00", "13:00", "14:00", "15:00"],
    "evening": ["17:00", "18:00", "19:00", "20:00"],
    "night": ["21:00", "22:00", "23:00"],
}


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /suggest_time command - request AI time suggestions with calendar selector."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    event_id_raw = args[0] if args else None

    if not event_id_raw:
        # Show event selector with inline keyboard (as fallback for now)
        await _show_event_selector_message(update.message, context)
        return

    try:
        event_id = int(event_id_raw)
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return

    await _show_event_time_options(update.message, context, event_id)


async def _show_event_selector_message(
    message: Message, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show event selector keyboard."""
    async with get_session(settings.db_url) as session:
        result = await session.execute(
            select(Event)
            .where(Event.scheduled_time.isnot(None))
            .order_by(Event.created_at.desc())
            .limit(10)
        )
        events = result.scalars().all()

        if not events:
            await message.reply_text(
                "No events with scheduled times found. Use /suggest_time <event_id> for flexible events."
            )
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"{event.event_type} • {event.scheduled_time.strftime('%d %b %H:%M') if event.scheduled_time else 'TBD'}",
                    callback_data=f"suggest_time_select_{event.event_id}",
                )
            ]
            for event in events
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.reply_text(
            "Select an event to get AI time suggestions:",
            reply_markup=reply_markup,
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for suggest_time buttons."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data

    if data.startswith("suggest_time_select_"):
        # Event selection callback
        try:
            event_id = int(data.replace("suggest_time_select_", ""))
        except ValueError:
            await query.edit_message_text("❌ Invalid event selection.")
            return

        await query.edit_message_text(
            f"🤖 *Requesting AI time suggestion for event {event_id}...*",
            parse_mode="Markdown",
        )
        await _send_suggestion(query.message, event_id)

    elif data.startswith("st_date_"):
        # Change date for fixed event
        event_id = int(data.replace("st_date_", ""))
        await _handle_calendar_request(query, context, event_id, "fixed")

    elif data.startswith("st_intervals_"):
        # Set availability intervals for flexible event
        event_id = int(data.replace("st_intervals_", ""))
        await _handle_calendar_request(query, context, event_id, "flexible")

    elif data.startswith("st_suggest_"):
        # AI suggestion
        event_id = int(data.replace("st_suggest_", ""))
        await query.edit_message_text(
            f"🤖 *Requesting AI time suggestion for event {event_id}...*",
            parse_mode="Markdown",
        )
        await _send_suggestion(query.message, event_id)

    elif data.startswith("st_cancel_"):
        # Cancel
        await query.edit_message_text("✅ Operation cancelled.")

    elif data.startswith(f"st_fixed_") or data.startswith(f"st_flexible_"):
        # Calendar navigation/day selection
        await _handle_calendar_callback(update, context, data)

    elif data.startswith("st_time_window_"):
        # Time window selection
        await _handle_time_window_selection(update, context, data)

    elif data.startswith("st_time_option_"):
        # Specific time option selection
        await _handle_time_option_selection(update, context, data)


async def _show_event_time_options(
    message: Message, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show time selection options based on event state."""
    async with get_session(settings.db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        if not event:
            await message.reply_text("❌ Event not found.")
            return

        if event.scheduled_time:
            # Fixed event: offer calendar to override time
            await _show_fixed_event_options(message, context, event)
        else:
            # Flexible event: offer calendar + interval selection
            await _show_flexible_event_options(message, context, event)


async def _show_fixed_event_options(
    message: Message, context: ContextTypes.DEFAULT_TYPE, event: Event
) -> None:
    """For events with scheduled_time, show calendar to change time."""
    now = datetime.now()
    keyboard = [
        [
            InlineKeyboardButton(
                "📅 Change Date", callback_data=f"st_date_{event.event_id}"
            ),
            InlineKeyboardButton(
                "🔄 AI Suggestion", callback_data=f"st_suggest_{event.event_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel", callback_data=f"st_cancel_{event.event_id}"
            ),
        ],
    ]

    await message.reply_text(
        f"📅 *Event {event.event_id} has scheduled time: {event.scheduled_time.strftime('%Y-%m-%d %H:%M')}*\n\n"
        "What would you like to do?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _show_flexible_event_options(
    message: Message, context: ContextTypes.DEFAULT_TYPE, event: Event
) -> None:
    """For flexible events, show calendar for interval selection."""
    now = datetime.now()
    keyboard = [
        [
            InlineKeyboardButton(
                "📅 Set Availability Intervals",
                callback_data=f"st_intervals_{event.event_id}",
            ),
            InlineKeyboardButton(
                "🔄 AI Suggestion", callback_data=f"st_suggest_{event.event_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel", callback_data=f"st_cancel_{event.event_id}"
            ),
        ],
    ]

    await message.reply_text(
        f"📅 *Event {event.event_id} is flexible (no fixed time yet)*\n\n"
        "Set availability intervals for optimal AI scheduling:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ============================================================================
# Calendar & Time Picker UI Functions
# ============================================================================


def build_calendar_markup(
    year: int, month: int, event_id: int, mode: str = "fixed"
) -> InlineKeyboardMarkup:
    """Build month-view inline calendar keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    prefix = f"st_{mode}_{event_id}_cal"

    rows.append(
        [
            InlineKeyboardButton(
                f"{month_name[month]} {year}", callback_data=f"{prefix}_ignore"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(day, callback_data=f"{prefix}_ignore")
            for day in CALENDAR_WEEKDAYS
        ]
    )

    cal = Calendar(firstweekday=0)
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data=f"{prefix}_ignore"))
            else:
                row.append(
                    InlineKeyboardButton(
                        str(day),
                        callback_data=f"{prefix}_day_{year}_{month}_{day}",
                    )
                )
        rows.append(row)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    rows.append(
        [
            InlineKeyboardButton(
                "◀️",
                callback_data=f"{prefix}_nav_{prev_year}_{prev_month}",
            ),
            InlineKeyboardButton(" ", callback_data=f"{prefix}_ignore"),
            InlineKeyboardButton(
                "▶️",
                callback_data=f"{prefix}_nav_{next_year}_{next_month}",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"st_cancel_{event_id}"),
        ]
    )

    return InlineKeyboardMarkup(rows)


def build_time_window_markup(event_id: int, mode: str) -> InlineKeyboardMarkup:
    """Build quick time-window keyboard."""
    prefix = f"st_{mode}_{event_id}_time"
    options = [
        ("🌅 Morning", f"{prefix}_window_morning"),
        ("🌤 Afternoon", f"{prefix}_window_afternoon"),
        ("🌆 Evening", f"{prefix}_window_evening"),
        ("🌙 Night", f"{prefix}_window_night"),
    ]
    footer = [
        ("📅 Change Date", f"st_{mode}_{event_id}_cal_open"),
    ]

    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for index, (label, callback_data) in enumerate(options):
        current_row.append(InlineKeyboardButton(label, callback_data=callback_data))
        if len(current_row) == 2 or index == len(options) - 1:
            rows.append(current_row)
            current_row = []
    for label, callback_data in footer:
        rows.append([InlineKeyboardButton(label, callback_data=callback_data)])

    return InlineKeyboardMarkup(rows)


def build_time_options_markup(
    window: str, event_id: int, mode: str
) -> InlineKeyboardMarkup:
    """Build compact keyboard for concrete time options by window."""
    time_options = TIME_WINDOWS.get(window, [])
    prefix = f"st_{mode}_{event_id}_time"
    options = [
        (time_value, f"{prefix}_option_{time_value.replace(':', '')}")
        for time_value in time_options
    ]
    footer = [
        ("⌨️ Enter Time Manually", f"{prefix}_manual"),
        ("📅 Change Date", f"st_{mode}_{event_id}_cal_open"),
    ]

    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for index, (label, callback_data) in enumerate(options):
        current_row.append(InlineKeyboardButton(label, callback_data=callback_data))
        if len(current_row) == 3 or index == len(options) - 1:
            rows.append(current_row)
            current_row = []
    for label, callback_data in footer:
        rows.append([InlineKeyboardButton(label, callback_data=callback_data)])

    return InlineKeyboardMarkup(rows)


# ============================================================================
# Calendar Callback Handlers
# ============================================================================


async def _handle_calendar_request(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, mode: str
) -> None:
    """Handle calendar request for event."""
    now = datetime.now()
    await query.edit_message_text(
        f"📅 *Select date for event {event_id}:*",
        reply_markup=build_calendar_markup(now.year, now.month, event_id, mode),
        parse_mode="Markdown",
    )


async def _handle_calendar_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> None:
    """Handle calendar navigation/day selection."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    parts = data.split("_")
    if len(parts) < 5:
        return

    mode = parts[1]
    event_id = int(parts[2])

    if data.endswith("_ignore"):
        return

    if data.startswith(f"st_{mode}_{event_id}_cal_nav_"):
        try:
            year = int(parts[-2])
            month = int(parts[-1])
        except ValueError:
            return

        await query.edit_message_text(
            f"📅 *Select date for event {event_id}:*",
            reply_markup=build_calendar_markup(year, month, event_id, mode),
            parse_mode="Markdown",
        )
        return

    if data.startswith(f"st_{mode}_{event_id}_cal_day_"):
        try:
            year = int(parts[5])
            month = int(parts[6])
            day = int(parts[7])
            selected = datetime(year, month, day)
        except ValueError:
            return

        selected_date = selected.strftime("%Y-%m-%d")

        if mode == "fixed":
            await query.edit_message_text(
                f"📆 *Date selected: {selected_date}*\n\nChoose a time window:",
                reply_markup=build_time_window_markup(event_id, mode),
                parse_mode="Markdown",
            )
        else:
            # For flexible events, go directly to intervals
            await query.edit_message_text(
                f"✅ *Date selected: {selected_date}*\n\n"
                f"Now set availability intervals with confidence scores:\n\n"
                f"1. Select time windows\n2. Assign confidence (0.0-1.0)\n3. AI infers optimal time from weighted data",
                reply_markup=build_time_window_markup(event_id, mode),
                parse_mode="Markdown",
            )


async def _handle_time_window_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> None:
    """Handle time window selection."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    parts = data.split("_")
    if len(parts) < 6:
        return

    mode = parts[1]
    event_id = int(parts[2])
    window = parts[5]

    await query.edit_message_text(
        f"*time_window_{window}*",
        reply_markup=build_time_options_markup(window, event_id, mode),
        parse_mode="Markdown",
    )


async def _handle_time_option_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> None:
    """Handle specific time option selection."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    parts = data.split("_")
    if len(parts) < 7:
        return

    mode = parts[1]
    event_id = int(parts[2])
    time_value = parts[6]

    await query.edit_message_text(
        f"✅ *Time selected: {time_value}*\n\n"
        f"Now set confidence score for this interval (0.0-1.0):\n"
        f"Example: `0.8` means 80% confidence you're available.",
        parse_mode="Markdown",
    )


async def _send_suggestion(message: MaybeInaccessibleMessage, event_id: int) -> None:
    """Fetch and send AI time suggestion for an event."""
    if isinstance(message, InaccessibleMessage):
        return
    msg = cast(Message, message)

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            await msg.reply_text("❌ Event not found.")
            return

        session_factory = create_session_factory(db_url)
        engine = AICoordinationEngine(session_factory)
        suggestion = await engine.suggest_event_time(session=session, event_id=event_id)
        if "error" in suggestion:
            await msg.reply_text(f"❌ Error: {suggestion['error']}")
            return

        suggested_time_raw = suggestion.get("suggested_time")
        normalized_suggested = (
            str(suggested_time_raw) if suggested_time_raw is not None else "TBD"
        )
        auto_applied = False
        if event.scheduled_time is None:
            parsed = _parse_suggested_time(normalized_suggested)
            if parsed:
                event.scheduled_time = parsed
                await invalidate_confirmations_and_notify(
                    context=SimpleContextProxy(msg.get_bot()),
                    event=event,
                    reason="event time auto-updated by AI suggestion",
                )
                await session.commit()
                auto_applied = True

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Request New Suggestion",
                    callback_data=f"st_suggest_{event_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📅 Change Time",
                    callback_data=f"st_date_{event_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data=f"st_cancel_{event_id}",
                )
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
            f"🤖 *AI Time Suggestion for Event {event_id}*\n\n"
            f"Suggested Time: {normalized_suggested}\n"
            f"Reasoning: {suggestion.get('reasoning', 'N/A')}\n"
            f"Confidence: {suggestion.get('confidence', 0):.2f}\n"
            f"Availability Score: {suggestion.get('availability_score', 0):.2f}"
        )
        if auto_applied:
            text += "\n\n✅ Applied this suggested time to the event."

        await msg.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


def create_session_factory(db_url: str):
    """Create session factory for AI coordination engine."""
    from db.connection import create_session
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(db_url)
    return create_session(engine)


def _parse_suggested_time(raw_value: str) -> datetime | None:
    """Parse common suggested time formats into datetime."""
    value = raw_value.strip()
    if not value or value.upper() == "TBD":
        return None

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class SimpleContextProxy:
    """Minimal context proxy exposing `bot` for notification helpers."""

    def __init__(self, bot):
        self.bot = bot
