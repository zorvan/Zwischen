#!/usr/bin/env python3
"""Selection keyboard builders for event metadata."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .keyboard_utils import build_compact_markup

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
