#!/usr/bin/env python3
"""Status command handler to show event progress."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Event, Log, Constraint
from db.connection import get_session
from config.settings import settings
from bot.common.event_presenters import format_status_message


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - DEPRECATED: Use /events instead."""
    if not update.message or not update.effective_user:
        return

    # Deprecation notice
    await update.message.reply_text(
        "ℹ️ `/status` is deprecated.\n\n"
        "Use `/events` to view all your events with progressive disclosure.",
        parse_mode="Markdown",
    )

    args = context.args or []
    event_id_raw = args[0] if args else None

    if not event_id_raw:
        async with get_session(settings.db_url) as session:
            result = await session.execute(
                select(Event).order_by(Event.created_at.desc()).limit(10)
            )
            events = result.scalars().all()

            if not events:
                try:
                    await update.message.reply_text(
                        "No events found. Use /status <event_id> to view an event."
                    )
                except Exception:
                    pass
                return

            event_list = "Recent events:\n\n"
            for event in events:
                event_list += (
                    f"Event #{event.event_id}: {event.event_type}\n"
                    f"  Time: {event.scheduled_time}\n"
                    f"  State: {event.state}\n\n"
                )

            event_list += "Select an event to view:"

            keyboard = [
                [
                    InlineKeyboardButton(
                        f"📋 View Event #{event.event_id}",
                        callback_data=f"event_status_{event.event_id}",
                    )
                ]
                for event in events
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await update.message.reply_text(event_list, reply_markup=reply_markup)
            except Exception:
                pass
            return

    try:
        event_id = int(event_id_raw)
    except ValueError:
        try:
            await update.message.reply_text("❌ Event ID must be a number.")
        except Exception:
            pass
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        if not event:
            try:
                await update.message.reply_text("❌ Event not found.")
            except Exception:
                pass

            return

        log_count = await _get_log_count(session, event_id)
        constraint_count = await _get_constraint_count(session, event_id)
        try:
            await update.message.reply_text(
                await format_status_message(
                    event_id, event, log_count, constraint_count, context.bot
                )
            )
        except Exception:
            pass


async def _get_log_count(session: AsyncSession, event_id: int) -> int:
    """Get log count for an event."""
    from sqlalchemy import func

    result = await session.execute(
        func.count(Log.__table__.c.log_id).select().where(Log.event_id == event_id)
    )
    return int(result.scalar_one())


async def _get_constraint_count(session: AsyncSession, event_id: int) -> int:
    """Get constraint count for an event."""
    from sqlalchemy import func

    result = await session.execute(
        func.count(Constraint.__table__.c.constraint_id)
        .select()
        .where(Constraint.event_id == event_id)
    )
    return int(result.scalar_one())
