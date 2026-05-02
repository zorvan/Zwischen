#!/usr/bin/env python3
"""Persistent inline keyboard menus for bot DMs."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.common.callback_data import encode_callback
from bot.common.i18n import t


def build_main_menu(lang: str = "en") -> InlineKeyboardMarkup:
    """Build the main menu shown when user starts bot or types /start."""
    keyboard = [
        [
            InlineKeyboardButton(
                t("menu_my_events", lang=lang), callback_data="menu_my_events"
            ),
            InlineKeyboardButton(
                t("menu_my_profile", lang=lang), callback_data="menu_my_profile"
            ),
        ],
        [
            InlineKeyboardButton(
                t("menu_my_history", lang=lang), callback_data="menu_history"
            ),
            InlineKeyboardButton(
                t("menu_organize", lang=lang), callback_data="menu_organize"
            ),
        ],
        [
            InlineKeyboardButton(
                t("menu_modify", lang=lang), callback_data="menu_modify"
            ),
            InlineKeyboardButton(
                t("menu_groups", lang=lang), callback_data="menu_groups"
            ),
        ],
        [
            InlineKeyboardButton(t("menu_help", lang=lang), callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_events_list_menu(page: int = 0, lang: str = "en") -> InlineKeyboardMarkup:
    """Build menu for events list with pagination."""
    from bot.common.i18n import t

    keyboard = []

    # Events will be added dynamically as buttons
    # This just has navigation and actions

    keyboard.append(
        [
            InlineKeyboardButton(
                t("keyboard_previous", lang=lang),
                callback_data=f"menu_events_prev_{page}",
            ),
            InlineKeyboardButton(
                t("keyboard_next", lang=lang), callback_data=f"menu_events_next_{page}"
            ),
        ]
    )

    keyboard.append(
        [
            InlineKeyboardButton(
                t("keyboard_back_to_main_menu", lang=lang), callback_data="menu_main"
            ),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def build_event_detail_keyboard(
    event_id: int, user_status: str = None, event_state: str = None, lang: str = "en"
) -> InlineKeyboardMarkup:
    """Build keyboard for a specific event detail view.

    Args:
        event_id: The event ID
        user_status: User's participation status (joined/confirmed/not_joined)
        event_state: Event state (proposed/interested/confirmed/locked)
    """
    from bot.common.i18n import t

    keyboard = []

    # Primary actions based on user status
    if user_status == "not_joined" or user_status is None:
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("keyboard_join_event", lang=lang),
                    callback_data=encode_callback("join", event_id),
                ),
            ]
        )
    elif user_status == "joined":
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("keyboard_confirm", lang=lang),
                    callback_data=encode_callback("commit", event_id),
                ),
                InlineKeyboardButton(
                    t("keyboard_step_back", lang=lang),
                    callback_data=encode_callback("cancel", event_id),
                ),
            ]
        )
    elif user_status == "confirmed":
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("event_details_confirmed", lang=lang), callback_data="noop"
                ),
                InlineKeyboardButton(
                    t("keyboard_uncommit", lang=lang),
                    callback_data=encode_callback("cancel", event_id),
                ),
            ]
        )

    # Secondary actions
    keyboard.append(
        [
            InlineKeyboardButton(
                t("keyboard_status", lang=lang),
                callback_data=encode_callback("det", event_id),
            ),
            InlineKeyboardButton(
                t("keyboard_details", lang=lang),
                callback_data=encode_callback("det", event_id),
            ),
        ]
    )

    # Availability/Constraints
    keyboard.append(
        [
            InlineKeyboardButton(
                t("keyboard_set_availability", lang=lang),
                callback_data=encode_callback("constraint", event_id),
            ),
        ]
    )

    # Lock (only for organizers/admins in confirmed state)
    if event_state == "confirmed":
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("keyboard_lock_event", lang=lang),
                    callback_data=encode_callback("lock", event_id),
                ),
            ]
        )

    # Navigation
    keyboard.append(
        [
            InlineKeyboardButton(
                t("keyboard_back_to_events_list", lang=lang),
                callback_data="menu_my_events",
            ),
            InlineKeyboardButton(
                t("keyboard_main_menu", lang=lang), callback_data="menu_main"
            ),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def build_back_to_menu_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Simple keyboard with just back to main menu."""
    from bot.common.i18n import t

    keyboard = [
        [
            InlineKeyboardButton(
                t("keyboard_main_menu", lang=lang), callback_data="menu_main"
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_help_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard with help topics."""
    from bot.common.i18n import t

    keyboard = [
        [
            InlineKeyboardButton(
                t("keyboard_getting_started", lang=lang), callback_data="help_start"
            ),
            InlineKeyboardButton(
                t("keyboard_how_events_work", lang=lang), callback_data="help_events"
            ),
        ],
        [
            InlineKeyboardButton(
                t("keyboard_scheduling", lang=lang), callback_data="help_scheduling"
            ),
            InlineKeyboardButton(
                t("keyboard_back_to_main_menu", lang=lang), callback_data="menu_main"
            ),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
