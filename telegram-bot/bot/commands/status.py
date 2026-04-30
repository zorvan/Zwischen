#!/usr/bin/env python3
"""DEPRECATED: Use /events instead."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deprecated: redirects to /events."""
    if not update.message:
        return
    keyboard = [[InlineKeyboardButton("📋 View Events", callback_data="menu_my_events")]]
    await update.message.reply_text(
        "Use /events to view and manage your events.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
