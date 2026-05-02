#!/usr/bin/env python3
"""Profile command handler."""
from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from config.settings import settings
from db.connection import get_session
from db.models import User


async def handle(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /profile command."""
    if not update.message:
        return

    if not update.effective_user:
        return
    if not settings.db_url:
        await update.message.reply_text("❌ Database configuration is unavailable.")
        return

    telegram_user_id = update.effective_user.id
    async with get_session(settings.db_url) as session:
        user_result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            await update.message.reply_text(
                "👤 *Your Profile*\n\n"
                "No profile data yet.\n"
                "Join events to build your participation history."
            )
            return

    lines = [
        "👤 *Your Profile*",
        "",
        f"Username: @{user.username}" if user.username else "Username: N/A",
        f"Display Name: {user.display_name or 'N/A'}",
        "",
        "This profile is identity-only.",
        "The bot does not compute reliability, reputation, or scores about you.",
        "Use /how_am_i_doing for your private attendance mirror.",
    ]

    await update.message.reply_text("\n".join(lines))
