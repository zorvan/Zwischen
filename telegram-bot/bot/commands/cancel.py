#!/usr/bin/env python3
"""Cancel attendance command handler with nudges."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from db.models import Event, Log
from db.connection import get_session
from db.users import get_or_create_user_id
from config.settings import settings
from datetime import datetime
from bot.common.participant_state_reconcile import (
    reconcile_event_state_after_participant_change,
)
from bot.services import ParticipantService
from bot.common.rbac import check_event_visibility_and_get_event

logger = logging.getLogger(__name__)


def _nudge_message(event_id: int, event_type: str) -> str:
    """Inline nudge message — extracted from dead nudges.py module."""
    return f"Event {event_id} ({event_type}) is upcoming. Your response helps everyone plan."


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel command - cancel attendance with nudges."""
    message = update.effective_message
    if not message:
        return

    user = update.effective_user
    if not user:
        return

    telegram_user_id = user.id
    display_name = user.full_name
    username = user.username
    event_id_str = context.args[0] if context.args else None

   if not event_id_str:
        async with get_session(settings.db_url) as session:
            result = await session.execute(
                select(Event)
                .order_by(Event.created_at.desc())
                .limit(10)
            )
            events = result.scalars().all()

            if not events:
                await message.reply_text(
                    "No events found. Use /cancel <event_id> to cancel attendance."
                )
                return

            event_list = "Recent events:\n\n"
            for event in events:
                event_list += (
                    f"Event #{event.event_id}: {event.event_type}\n"
                    f"  Time: {event.scheduled_time}\n"
                    f"  State: {event.state}\n\n"
                )

            event_list += "Select an event to cancel:"

            keyboard = [
                [
                    InlineKeyboardButton(
                        f"❌ Cancel Event #{event.event_id}",
                        callback_data=f"event_cancel_{event.event_id}",
                    )
                ]
                for event in events
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await message.reply_text(event_list, reply_markup=reply_markup)
        return

    try:
        event_id = int(event_id_str)
    except ValueError:
        await message.reply_text("❌ Event ID must be a number.")
        return

    chat_id = update.effective_chat.id if update.effective_chat else None

    async with get_session(settings.db_url) as session:
        (
            is_visible,
            event,
            group,
            error_msg,
        ) = await check_event_visibility_and_get_event(
            session,
            event_id,
            telegram_user_id,
            telegram_chat_id=chat_id,
            bot=context.bot,
        )

        if not is_visible:
            await message.reply_text(f"❌ {error_msg or 'Event not found.'}")
            return

        if event.state == "locked":
            await message.reply_text(
                f"❌ Cannot cancel event {event_id} - it's already locked."
            )
            return

        # Use ParticipantService to cancel attendance
        participant_service = ParticipantService(session)
        try:
            participant, is_new_cancel = await participant_service.cancel(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
                source="slash",
            )
        except Exception:
            await message.reply_text(
                f"❌ You haven't joined event {event_id} yet. Nothing to cancel."
            )
            return

        user_id = await get_or_create_user_id(
            session,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            username=username,
        )

        log = Log(
            event_id=event_id,
            user_id=user_id,
            action="cancel",
            metadata_dict={"timestamp": datetime.utcnow().isoformat()},
        )
        session.add(log)

        from bot.services import WaitlistService

        waitlist_service = WaitlistService(session, context.bot)
        await waitlist_service.trigger_auto_fill(event_id)

        event = await reconcile_event_state_after_participant_change(
            session=session,
            bot=context.bot,
            event_id=event_id,
            actor_telegram_user_id=telegram_user_id,
            source="slash",
            reason="Participant cancelled attendance",
        )

        await session.commit()

        nudge_msg = _nudge_message(event_id, event.event_type)

        await message.reply_text(
            f"❌ *Attendance cancelled for event {event_id}!*\n\n"
            f"{nudge_msg}\n\n"
            f"Event: {event.event_type}\n"
            f"Time: {event.scheduled_time}"
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for cancel buttons."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data

    if data and data.startswith("event_cancel_"):
        event_id = int(data.replace("event_cancel_", ""))
        # Create an update object from the callback query
        callback_update = Update(update_id=update.update_id, callback_query=query)
        context.args = [str(event_id)]
        await handle(callback_update, context)
        await query.edit_message_text(
            f"❌ *Attendance cancelled for event {event_id}!*\n\n"
            "You can rejoin anytime using /join."
        )
