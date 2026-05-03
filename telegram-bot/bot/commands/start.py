#!/usr/bin/env python3
"""Start command handler."""
from telegram import Update
from telegram.ext import ContextTypes

from bot.common.i18n import t, get_user_language
from bot.common.menus import build_main_menu


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not update.message:
        return

    args = context.args or []
    payload = args[0] if args else ""
    user_lang = await get_user_language(
        update.effective_user, user_data=context.user_data
    )

    # Handle deep links
    if payload.startswith("avail_"):
        try:
            event_id = int(payload.replace("avail_", ""))
        except ValueError:
            event_id = None
        if event_id is not None:
            await update.message.reply_html(
                t("start_private_availability", lang=user_lang, event_id=event_id),
            )
            return

    # Show main menu with buttons
    display_name = update.effective_user.full_name if update.effective_user else "User"

    await update.message.reply_html(
        t("start_welcome", lang=user_lang, display_name=display_name),
        reply_markup=build_main_menu(),
    )
