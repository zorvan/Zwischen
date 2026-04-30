#!/usr/bin/env python3
"""Fallback messages for v3.5.

Per PRD v3.5 Section 6.8: Define fallback messages as constants.
Use these consistently. Never let the bot go silent on an error.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# =============================================================================
# Fallback Messages
# =============================================================================

FALLBACK_CLARIFY_TEXT = "I didn't quite get that. What did you want to do?"

FALLBACK_CLARIFY_KEYBOARD = [
    [
        InlineKeyboardButton("📋 View Events", callback_data="menu_my_events"),
    ],
    [
        InlineKeyboardButton("➕ Create Event", callback_data="events_create_new"),
    ],
    [
        InlineKeyboardButton("Never mind", callback_data="noop"),
    ],
]

FALLBACK_EVENT_NEEDED_TEXT = "Which event are you referring to? Here are your active events:"

FALLBACK_GENERAL_TEXT = "Type /events to see what's happening in your group."


# =============================================================================
# Helper Functions
# =============================================================================


def build_fallback_clarify_markup() -> InlineKeyboardMarkup:
    """Build keyboard for FALLBACK_CLARIFY."""
    return InlineKeyboardMarkup(FALLBACK_CLARIFY_KEYBOARD)


def build_fallback_general_markup() -> InlineKeyboardMarkup:
    """Build a simple keyboard for FALLBACK_GENERAL."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 View Events", callback_data="menu_my_events")],
        ]
    )
