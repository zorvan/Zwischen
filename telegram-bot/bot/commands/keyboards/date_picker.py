#!/usr/bin/env python3
"""Date picker keyboard builders and preset resolution."""

from calendar import Calendar, month_name
from datetime import date, datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .keyboard_utils import build_compact_markup

# Constants
CALENDAR_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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
