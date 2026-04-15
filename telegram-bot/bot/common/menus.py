#!/usr/bin/env python3
"""Persistent inline keyboard menus for bot DMs."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_main_menu() -> InlineKeyboardMarkup:
    """Build the main menu shown when user starts bot or types /start."""
    keyboard = [
        [
            InlineKeyboardButton("📋 My Events", callback_data="menu_my_events"),
            InlineKeyboardButton("👤 My Profile", callback_data="menu_my_profile"),
        ],
        [
            InlineKeyboardButton("📜 My History", callback_data="menu_history"),
            InlineKeyboardButton("✏️ Organize", callback_data="menu_organize"),
        ],
        [
            InlineKeyboardButton("🔧 Modify", callback_data="menu_modify"),
            InlineKeyboardButton("👥 Groups", callback_data="menu_groups"),
        ],
        [
            InlineKeyboardButton("🤖 About", callback_data="menu_about"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_events_list_menu(page: int = 0) -> InlineKeyboardMarkup:
    """Build menu for events list with pagination."""
    keyboard = []

    # Events will be added dynamically as buttons
    # This just has navigation and actions

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ Previous", callback_data=f"menu_events_prev_{page}"
            ),
            InlineKeyboardButton("Next ➡️", callback_data=f"menu_events_next_{page}"),
        ]
    )

    keyboard.append(
        [
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_main"),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def build_event_detail_keyboard(
    event_id: int, user_status: str = None, event_state: str = None
) -> InlineKeyboardMarkup:
    """Build keyboard for a specific event detail view.

    Args:
        event_id: The event ID
        user_status: User's participation status (joined/confirmed/not_joined)
        event_state: Event state (proposed/interested/confirmed/locked)
    """
    keyboard = []

    # Primary actions based on user status
    if user_status == "not_joined" or user_status is None:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "✅ Join Event", callback_data=f"event_join_{event_id}"
                ),
            ]
        )
    elif user_status == "joined":
        keyboard.append(
            [
                InlineKeyboardButton(
                    "✅ Confirm", callback_data=f"event_confirm_{event_id}"
                ),
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"event_cancel_{event_id}"
                ),
            ]
        )
    elif user_status == "confirmed":
        keyboard.append(
            [
                InlineKeyboardButton("✅ Confirmed", callback_data="noop"),
                InlineKeyboardButton(
                    "↩️ Uncommit", callback_data=f"event_unconfirm_{event_id}"
                ),
            ]
        )

    # Secondary actions
    keyboard.append(
        [
            InlineKeyboardButton("📊 Status", callback_data=f"event_status_{event_id}"),
            InlineKeyboardButton(
                "📝 Details", callback_data=f"event_details_{event_id}"
            ),
        ]
    )

    # Availability/Constraints
    keyboard.append(
        [
            InlineKeyboardButton(
                "📅 Set Availability", callback_data=f"event_constraints_{event_id}"
            ),
        ]
    )

    # Lock (only for organizers/admins in confirmed state)
    if event_state == "confirmed":
        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔒 Lock Event", callback_data=f"event_lock_{event_id}"
                ),
            ]
        )

    # Navigation
    keyboard.append(
        [
            InlineKeyboardButton(
                "🔙 Back to Events List", callback_data="menu_my_events"
            ),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def build_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Simple keyboard with just back to main menu."""
    keyboard = [
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_help_keyboard() -> InlineKeyboardMarkup:
    """Keyboard with help topics."""
    keyboard = [
        [
            InlineKeyboardButton("📖 Getting Started", callback_data="help_start"),
            InlineKeyboardButton("🎯 How Events Work", callback_data="help_events"),
        ],
        [
            InlineKeyboardButton("📅 Scheduling", callback_data="help_scheduling"),
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
