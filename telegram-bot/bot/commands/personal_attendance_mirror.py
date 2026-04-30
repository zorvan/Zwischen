#!/usr/bin/env python3
"""Personal attendance mirror — /how_am_i_doing command.

v3 Design: Causally inert. Shows only factual participation counts.
The system never reads this data for any decision-making.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func

from config.settings import settings
from db.connection import get_session
from db.models import User, EventParticipant


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /how_am_i_doing command — private DM showing attendance counts only."""
    if not update.message or not update.effective_user:
        return

    if not settings.db_url:
        await update.message.reply_text("❌ Database configuration is unavailable.")
        return

    telegram_user_id = update.effective_user.id

    async with get_session(settings.db_url) as session:
        user_result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
        user = user_result.scalar_one_or_none()

        if not user:
            await update.message.reply_text(
                "📊 *Your Participation*\n\n" "No events found yet.\n" "Join an event to see your counts here."
            )
            return

        # Factual counts only — no scores, no trends, no inference
        joined_result = await session.execute(
            select(func.count(EventParticipant.event_id)).where(EventParticipant.telegram_user_id == telegram_user_id)
        )
        joined_count = joined_result.scalar() or 0

        completed_result = await session.execute(
            select(func.count(EventParticipant.event_id)).where(
                EventParticipant.telegram_user_id == telegram_user_id,
                EventParticipant.status == "confirmed",
            )
        )
        completed_count = completed_result.scalar() or 0

        lines = [
            "📊 *Your Participation*",
            "",
            f"Events joined: {joined_count}",
            f"Events completed: {completed_count}",
        ]

        await update.message.reply_text("\n".join(lines))
