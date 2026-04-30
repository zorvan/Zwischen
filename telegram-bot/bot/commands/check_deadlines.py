#!/usr/bin/env python3
"""Deadline check command handler."""
from telegram import Update
from telegram.ext import ContextTypes

from bot.common.deadline_check import check_and_lock_expired_events
from config.settings import settings


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /check_deadlines command - check expired events and auto-lock."""
    if not update.message:
        return

    if not settings.db_url:
        await update.message.reply_text("❌ Database configuration is unavailable.")
        return

    results = await check_and_lock_expired_events(context.bot)

    if not results:
        await update.message.reply_text("✅ No expired events to process.")
        return

    locked_count = sum(1 for r in results if r.get("status") == "locked")
    not_locked_count = sum(1 for r in results if r.get("status") == "not_locked")
    error_count = sum(1 for r in results if r.get("status") == "error")

    summary_lines = []
    for result in results:
        event_id = result.get("event_id", "N/A")
        status = result.get("status", "unknown")
        message = result.get("message", "")
        summary_lines.append(f"• Event {event_id}: {status}")
        if message and status != "locked":
            summary_lines.append(f"  {message}")

    summary_text = "\n".join(summary_lines) if summary_lines else "N/A"

    await update.message.reply_text(
        f"⏰ *Deadline Check Complete*\n\n"
        f"Processed: {len(results)} events\n"
        f"Auto-locked: {locked_count}\n"
        f"Not locked (below threshold): {not_locked_count}\n"
        f"Errors: {error_count}\n\n"
        f"Details:\n{summary_text}"
    )


async def run_scheduled_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run scheduled deadline check job."""
    if not settings.db_url:
        return

    results = await check_and_lock_expired_events(context.bot)

    if not results:
        return

    locked_count = sum(1 for r in results if r.get("status") == "locked")

    if locked_count > 0:
        # Log the success
        import logging

        logger = logging.getLogger("coord_bot.deadline")
        logger.info(f"Auto-locked {locked_count} event(s) after deadline reached")
