#!/usr/bin/env python3
"""Confirm event command handler."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from db.models import Event, Log, EventParticipant
from db.connection import get_session
from db.users import get_or_create_user_id
from config.settings import settings
from bot.common.scheduling import find_user_event_conflict
from bot.common.rbac import check_event_visibility_and_get_event
from bot.services import ParticipantService, EventLifecycleService
from datetime import datetime

logger = logging.getLogger(__name__)


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /confirm|/interested command - mark attendance commitment."""
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
        await _show_event_selector(message, context, telegram_user_id)
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
                f"❌ Cannot confirm event {event_id} - it's already locked."
            )
            return

        if event.state in ["completed", "cancelled"]:
            await message.reply_text(
                f"❌ Cannot confirm event {event_id} - it's {event.state}."
            )
            return

        conflict = await find_user_event_conflict(
            session=session,
            telegram_user_id=telegram_user_id,
            start_time=event.scheduled_time,
            duration_minutes=event.duration_minutes,
            ignore_event_id=event.event_id,
        )
        if conflict:
            await message.reply_text(
                "❌ You have a conflicting event.\n"
                f"Conflicting Event ID: {conflict.event_id}\n"
                f"Time: {conflict.scheduled_time}\n"
                f"Duration: {conflict.duration_minutes or 120} minutes"
            )
            return

        # Use ParticipantService to confirm attendance
        participant_service = ParticipantService(session)
        participant, is_new_confirm = await participant_service.confirm(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            source="slash",
        )

        # Check if we need to transition to confirmed state
        confirmed_count = await participant_service.get_confirmed_count(event_id)
        if event.state != "confirmed" and confirmed_count > 0:
            lifecycle_service = EventLifecycleService(context.bot, session)
            try:
                event, _ = await lifecycle_service.transition_with_lifecycle(
                    event_id=event_id,
                    target_state="confirmed",
                    actor_telegram_user_id=telegram_user_id,
                    source="slash",
                    reason="Participant confirmed via slash command",
                )
            except Exception as e:
                logger.error(f"Failed to transition event {event_id} to confirmed: {e}")

        user_id = await get_or_create_user_id(
            session,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            username=username,
        )

        log = Log(
            event_id=event_id,
            user_id=user_id,
            action="confirm",
            metadata_dict={"timestamp": datetime.utcnow().isoformat()},
        )
        session.add(log)
        await session.commit()

        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "↩️ Uncommit", callback_data=f"event_unconfirm_{event_id}"
                    ),
                    InlineKeyboardButton(
                        "🔒 Lock Event", callback_data=f"event_lock_{event_id}"
                    ),
                ]
            ]
        )
        await message.reply_text(
            f"✅ *Committed to event {event_id}!*\n\n"
            f"Type: {event.event_type}\n"
            f"Time: {event.scheduled_time}\n"
            f"State: {event.state}\n"
            f"Use /back {event_id} to revert commitment before lock.",
            reply_markup=reply_markup,
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for confirm buttons."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data

    if data and data.startswith("event_confirm_"):
        event_id = int(data.replace("event_confirm_", ""))
        # Create an update object from the callback query
        callback_update = Update(update_id=update.update_id, callback_query=query)
        context.args = [str(event_id)]
        await handle(callback_update, context)
        await query.edit_message_text(
            f"✅ *Committed to event {event_id}!*\n\n"
            f"Use /status {event_id} to view event progress."
        )
