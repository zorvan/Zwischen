#!/usr/bin/env python3
"""Fallback messages for v3.5.

Per PRD v3.5 Section 6.8: Define fallback messages as constants.
Use these consistently. Never let the bot go silent on an error.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.common.i18n import t


# =============================================================================
# Fallback Messages
# =============================================================================


def fallback_clarify_text(lang: str = "en") -> str:
    """Get the fallback clarify text for the given language."""
    return t("fallback_clarify", lang=lang)


def fallback_clarify_keyboard(lang: str = "en") -> list[list[InlineKeyboardButton]]:
    """Build fallback clarify keyboard for the given language."""
    return [
        [
            InlineKeyboardButton(
                t("fallback_view_events", lang=lang), callback_data="menu_my_events"
            )
        ],
        [
            InlineKeyboardButton(
                t("fallback_create_event", lang=lang), callback_data="events_create_new"
            )
        ],
        [
            InlineKeyboardButton(
                t("fallback_never_mind", lang=lang), callback_data="noop"
            )
        ],
    ]


def fallback_event_needed_text(lang: str = "en") -> str:
    """Get the fallback event needed text for the given language."""
    return t("fallback_event_needed", lang=lang)


def fallback_general_text(lang: str = "en") -> str:
    """Get the fallback general text for the given language."""
    return t("fallback_general", lang=lang)


# =============================================================================
# Helper Functions
# =============================================================================


def build_fallback_clarify_markup(lang: str = "en") -> InlineKeyboardMarkup:
    """Build keyboard for FALLBACK_CLARIFY."""
    return InlineKeyboardMarkup(fallback_clarify_keyboard(lang))


def build_fallback_general_markup(lang: str = "en") -> InlineKeyboardMarkup:
    """Build a simple keyboard for FALLBACK_GENERAL."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("fallback_view_events", lang=lang), callback_data="menu_my_events"
                )
            ],
        ]
    )
