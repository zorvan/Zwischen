"""Shared inline keyboard builders."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_threshold_markup(
    back_callback: str | None = None,
    prefix: str = "event",
) -> InlineKeyboardMarkup:
    """Build compact threshold choices keyboard."""
    options = [
        ("2", f"{prefix}_threshold_2"),
        ("3", f"{prefix}_threshold_3"),
        ("5", f"{prefix}_threshold_5"),
        ("8", f"{prefix}_threshold_8"),
        ("13", f"{prefix}_threshold_13"),
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
    prefix: str = "event",
) -> InlineKeyboardMarkup:
    """
    v3.2: Build min_participants (absolute floor) keyboard.
    """
    options = [
        ("2", f"{prefix}_min_2"),
        ("3", f"{prefix}_min_3"),
        ("4", f"{prefix}_min_4"),
        ("5", f"{prefix}_min_5"),
        ("6", f"{prefix}_min_6"),
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
    prefix: str = "event",
) -> InlineKeyboardMarkup:
    """
    v3.2: Build target_participants (comfortable capacity) keyboard.
    Options start from min_participants + 1.
    """
    options = []
    for val in range(current_min + 1, current_min + 7):
        label = str(val)
        cb = f"{prefix}_target_{val}"
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
