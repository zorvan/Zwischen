"""Shared inline keyboard builders."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_threshold_markup(
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """Build compact threshold choices keyboard."""
    options = [
        ("2", "event_threshold_2"),
        ("3", "event_threshold_3"),
        ("5", "event_threshold_5"),
        ("8", "event_threshold_8"),
        ("13", "event_threshold_13"),
    ]
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, (label, callback_data) in enumerate(options):
        row.append(InlineKeyboardButton(label, callback_data=callback_data))
        if len(row) == 2 or index == len(options) - 1:
            keyboard.append(row)
            row = []
    if back_callback:
        keyboard.append([InlineKeyboardButton("✏️ Edit Previous", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)


def build_min_participants_markup(
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """
    v3.2: Build min_participants (absolute floor) keyboard.
    """
    options = [
        ("2", "event_min_2"),
        ("3", "event_min_3"),
        ("4", "event_min_4"),
        ("5", "event_min_5"),
        ("6", "event_min_6"),
    ]
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, (label, callback_data) in enumerate(options):
        row.append(InlineKeyboardButton(label, callback_data=callback_data))
        if len(row) == 2 or index == len(options) - 1:
            keyboard.append(row)
            row = []
    if back_callback:
        keyboard.append([InlineKeyboardButton("✏️ Edit Previous", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)


def build_target_participants_markup(
    current_min: int,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """
    v3.2: Build target_participants (comfortable capacity) keyboard.
    Options start from min_participants + 1.
    """
    options = []
    for val in range(current_min + 1, current_min + 7):
        label = str(val)
        cb = f"event_target_{val}"
        options.append((label, cb))

    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, (label, callback_data) in enumerate(options):
        row.append(InlineKeyboardButton(label, callback_data=callback_data))
        if len(row) == 2 or index == len(options) - 1:
            keyboard.append(row)
            row = []
    if back_callback:
        keyboard.append([InlineKeyboardButton("✏️ Edit Previous", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)
