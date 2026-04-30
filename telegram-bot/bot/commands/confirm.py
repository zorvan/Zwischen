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


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kept for legacy callback patterns (event_confirm_, event_interested_)."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    if data and data.startswith("event_confirm_"):
        from bot.handlers import event_flow

        await event_flow.handle_event_flow(update, context)
