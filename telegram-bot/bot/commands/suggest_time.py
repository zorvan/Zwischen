#!/usr/bin/env python3
"""Suggest time command handler for AI time suggestions."""
from datetime import datetime
from typing import cast
from telegram import (
    Update,
    Message,
    InaccessibleMessage,
    MaybeInaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes
from sqlalchemy import select
from db.models import Event
from db.connection import get_session
from config.settings import settings
from ai.core import AICoordinationEngine
from bot.common.confirmation import invalidate_confirmations_and_notify


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /suggest_time command - request AI time suggestions."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    event_id_raw = args[0] if args else None

    if not event_id_raw:
        await update.message.reply_text(
            "Usage: /suggest_time <event_id>\n\n" "Example: /suggest_time 123"
        )
        return

    try:
        event_id = int(event_id_raw)
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return

    await _send_suggestion(update.message, event_id)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for suggest_time buttons."""
    del context
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data
    if not data or not data.startswith("suggest_time_retry_"):
        return

    try:
        event_id = int(data.replace("suggest_time_retry_", ""))
    except ValueError:
        await query.edit_message_text("❌ Invalid event ID in callback.")
        return

    message = query.message
    if not message or isinstance(message, InaccessibleMessage):
        return

    await query.edit_message_text(
        f"🤖 *Requesting new AI time suggestion for event {event_id}...*"
    )
    await _send_suggestion(message, event_id)


async def _send_suggestion(message: MaybeInaccessibleMessage, event_id: int) -> None:
    """Fetch and send AI time suggestion for an event."""
    if isinstance(message, InaccessibleMessage):
        return
    msg = cast(Message, message)

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            await msg.reply_text("❌ Event not found.")

            return

        session_factory = create_session_factory(db_url)
        engine = AICoordinationEngine(session_factory)
        suggestion = await engine.suggest_event_time(session=session, event_id=event_id)
        if "error" in suggestion:
            await msg.reply_text(f"❌ Error: {suggestion['error']}")

            return

        suggested_time_raw = suggestion.get("suggested_time")
        normalized_suggested = (
            str(suggested_time_raw) if suggested_time_raw is not None else "TBD"
        )
        auto_applied = False
        if event.scheduled_time is None:
            parsed = _parse_suggested_time(normalized_suggested)
            if parsed:
                event.scheduled_time = parsed
                await invalidate_confirmations_and_notify(
                    context=SimpleContextProxy(msg.get_bot()),
                    event=event,
                    reason="event time auto-updated by AI suggestion",
                )
                await session.commit()
                auto_applied = True

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Request New Suggestion",
                    callback_data=f"suggest_time_retry_{event_id}",
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await msg.reply_text(
            f"🤖 *AI Time Suggestion for Event {event_id}*\n\n"
            f"Suggested Time: {normalized_suggested}\n"
            f"Reasoning: {suggestion.get('reasoning', 'N/A')}\n"
            f"Confidence: {suggestion.get('confidence', 0):.2f}\n"
            f"Availability Score: {suggestion.get('availability_score', 0):.2f}"
            + (
                "\n\n✅ Applied this suggested time to the event."
                if auto_applied
                else ""
            ),
            reply_markup=reply_markup,
        )


def create_session_factory(db_url: str):
    """Create session factory for AI coordination engine."""
    from db.connection import create_session
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(db_url)
    return create_session(engine)


def _parse_suggested_time(raw_value: str) -> datetime | None:
    """Parse common suggested time formats into datetime."""
    value = raw_value.strip()
    if not value or value.upper() == "TBD":
        return None

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class SimpleContextProxy:
    """Minimal context proxy exposing `bot` for notification helpers."""

    def __init__(self, bot):
        self.bot = bot
