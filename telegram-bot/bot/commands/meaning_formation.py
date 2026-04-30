#!/usr/bin/env python3
"""DEPRECATED: Use /events instead."""
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
