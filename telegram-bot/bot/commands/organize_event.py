#!/usr/bin/env python3
"""DEPRECATED: /organize_event command redirects to /events.

This module re-exports from event_creation.py so that legacy callback
patterns (event_join_, event_lock_, etc.) still work, but the
/organize_event command itself redirects users to /events.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deprecated: redirects to /events creation flow."""
    if not update.message:
        return
    keyboard = [[InlineKeyboardButton("➕ Create New Event", callback_data="events_create_new")]]
    await update.message.reply_text(
        "Use /events to create and manage events.\n\n" "Tap below to create a new event:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_flexible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deprecated: redirects to /events creation flow."""
    await handle(update, context)
