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
    """Kept for legacy callback patterns (constraint_nl_, event_constraints_)."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    if data and data.startswith("constraint_nl_"):
        from bot.handlers import event_panel
        from bot.common.callback_data import decode_callback

        action, event_id, _ = decode_callback(data)
        if event_id:
            await event_panel.route_event_callback(update, context)
