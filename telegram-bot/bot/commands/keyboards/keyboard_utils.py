#!/usr/bin/env python3
"""Keyboard building utilities."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
