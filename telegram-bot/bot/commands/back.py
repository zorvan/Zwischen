#!/usr/bin/env python3
"""Back/unconfirm command handler."""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from config.settings import settings
from db.connection import get_session
from db.models import Log
from db.users import get_or_create_user_id
from bot.common.participant_state_reconcile import (
    reconcile_event_state_after_participant_change,
)
from bot.services import ParticipantService
from bot.common.rbac import check_event_visibility_and_get_event
from datetime import datetime

logger = logging.getLogger(__name__)


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /back <event_id> to revert personal confirmation to interested."""
    message = update.effective_message
    if not message or not update.effective_user:
        return
    args = context.args or []
    if not args:
        await message.reply_text("Usage: /back <event_id>")
        return
    try:
        event_id = int(args[0])
    except ValueError:
        await message.reply_text("❌ Event ID must be a number.")
        return

    telegram_user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else None
    async with get_session(settings.db_url) as session:
        is_visible, event, group, error_msg = (
            await check_event_visibility_and_get_event(
                session,
                event_id,
                telegram_user_id,
                telegram_chat_id=chat_id,
                bot=context.bot,
            )
        )
        if not is_visible:
            await message.reply_text(f"❌ {error_msg or 'Event not found.'}")
            return
        if event.state == "locked":
            await message.reply_text("❌ Event is locked. Cannot go back.")
            return

        # Use ParticipantService to unconfirm attendance
        participant_service = ParticipantService(session)
        try:
            participant, is_new_unconfirm = await participant_service.unconfirm(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
                source="slash",
            )
        except Exception:
            await message.reply_text("ℹ️ You are not confirmed in this event.")
            return

        user_id = await get_or_create_user_id(
            session,
            telegram_user_id=telegram_user_id,
            display_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )
        session.add(
            Log(
                event_id=event_id,
                user_id=user_id,
                action="unconfirm",
                metadata_dict={
                    "timestamp": datetime.utcnow().isoformat(),
                    "sub_action": "back_unconfirm",
                },
            )
        )
        event = await reconcile_event_state_after_participant_change(
            session=session,
            bot=context.bot,
            event_id=event_id,
            actor_telegram_user_id=telegram_user_id,
            source="slash",
            reason="Participant unconfirmed attendance",
        )
        await session.commit()

    await message.reply_text(
        f"↩️ Your confirmation for event {event_id} was reverted.\n"
        f"Current event state: {event.state}\n"
        f"You can recommit with /confirm {event_id}."
    )
