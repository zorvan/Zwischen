#!/usr/bin/env python3
"""Time selection keyboard builders."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .keyboard_utils import build_compact_markup

TIME_WINDOWS: dict[str, list[str]] = {
    "early-morning": ["04:00", "05:00", "06:00", "07:00"],
    "morning": ["08:00", "09:00", "10:00", "11:00"],
    "afternoon": ["12:00", "13:00", "14:00", "15:00"],
    "evening": ["17:00", "18:00", "19:00", "20:00"],
    "night": ["21:00", "22:00", "23:00"],
}


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
