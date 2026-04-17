#!/usr/bin/env python3
"""Join event command handler - mark attendance intent.

DEPRECATED: v3.4 - Use /events and Join button in event panel instead.

PRD v2 Refactoring:
- Uses ParticipantService as single write path
- Integrates EventLifecycleService for state transitions
- Includes idempotency checking (optional, feature-flagged)
- Triggers materialization announcements via lifecycle service
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from db.models import Event, Log
from db.connection import get_session
from db.users import get_or_create_user_id
from config.settings import settings
from bot.common.scheduling import find_user_event_conflict
from bot.common.rbac import check_event_visibility_and_get_event
from bot.services import (
    ParticipantService,
    EventLifecycleService,
    IdempotencyService,
    ConcurrencyConflictError,
    ThresholdNotMetError,
)

logger = logging.getLogger("coord_bot.commands.join")


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    DEPRECATED: Handle /join command - mark attendance intent.

    Use /events and Join button in event panel instead.

    Flow:
    1. Validate event ID parameter
    2. Fetch event and validate state
    3. Check for scheduling conflicts
    4. Generate idempotency key (if enabled)
    5. Execute join via ParticipantService
    6. Trigger state transition if needed via EventLifecycleService
    7. Log action and respond
    """
    message = update.effective_message
    if not message:
        return

    # Deprecation notice
    await message.reply_text(
        "ℹ️ <code>/join</code> is deprecated.\n\n"
        "Use <code>/events</code> and tap an event to see the Join button.",
        parse_mode="HTML",
    )
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
                select(Event).order_by(Event.created_at.desc()).limit(10)
            )
            events = result.scalars().all()

            if not events:
                await message.reply_text(
                    "No events found. Use /join <event_id> to join an event."
                )
                return

            event_list = "Recent events:\n\n"
            for event in events:
                event_list += (
                    f"Event #{event.event_id}: {event.event_type}\n"
                    f"  Time: {event.scheduled_time}\n"
                    f"  State: {event.state}\n\n"
                )

            event_list += "Select an event to join:"

            keyboard = [
                [
                    InlineKeyboardButton(
                        f"✅ Join Event #{event.event_id}",
                        callback_data=f"event_join_{event.event_id}",
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

    async with get_session(settings.db_url) as session:
        # Check event visibility based on group membership
        chat_id = update.effective_chat.id if update.effective_chat else None
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

        # Validate event state
        if event.state in ["locked", "completed"]:
            await message.reply_text(
                f"❌ Cannot join event {event_id} - it's {event.state}."
            )
            return

        # Check for scheduling conflicts
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

        # Idempotency check (if enabled)
        if settings.enable_idempotency:
            idempotency_service = IdempotencyService(session)
            idempotency_key = IdempotencyService.generate_key(
                "join", telegram_user_id, event_id
            )

            is_dup, status, _ = await idempotency_service.check(idempotency_key)
            if is_dup and status == "completed":
                logger.info(
                    "Duplicate join command detected (idempotent)",
                    extra={"event_id": event_id, "user": telegram_user_id},
                )
                await message.reply_text(f"✅ Already joined event {event_id}!")
                return

            # Register idempotency key
            await idempotency_service.register(
                idempotency_key, "join", telegram_user_id, event_id
            )

        try:
            # Execute join via ParticipantService
            participant_service = ParticipantService(session)
            participant, is_new_join = await participant_service.join(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
                source="slash",
            )

            if is_new_join:
                # Transition state if needed (proposed → interested)
                if event.state == "proposed":
                    lifecycle_service = EventLifecycleService(context.bot, session)
                    try:
                        event, _ = await lifecycle_service.transition_with_lifecycle(
                            event_id=event_id,
                            target_state="interested",
                            actor_telegram_user_id=telegram_user_id,
                            source="slash",
                            reason="First participant joined",
                        )
                    except (ConcurrencyConflictError, ThresholdNotMetError) as e:
                        logger.error(
                            "State transition failed: %s",
                            e,
                            extra={"event_id": event_id},
                        )
                        # Continue anyway - user successfully joined

                # Create user record if needed
                user_id = await get_or_create_user_id(
                    session,
                    telegram_user_id=telegram_user_id,
                    display_name=display_name,
                    username=username,
                )

                # Log action
                log = Log(
                    event_id=event_id,
                    user_id=user_id,
                    action="join",
                    metadata_dict={
                        "timestamp": datetime.utcnow().isoformat(),
                        "source": "slash",
                        "participant_status": participant.status.value,
                    },
                )
                session.add(log)

                # Complete idempotency key if enabled
                if settings.enable_idempotency:
                    await idempotency_service.complete(idempotency_key)

                await session.commit()

            # Build response with action keyboard
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ Commit", callback_data=f"event_confirm_{event_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel", callback_data=f"event_cancel_{event_id}"
                    )
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

await message.reply_text(
        f"✅ <b>Joined event {event_id}!</b>\n\n"
        f"Type: {event.event_type}\n"
        f"Time: {event.scheduled_time}\n"
        f"State: {event.state}\n\n"
        "Please commit attendance.",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )

        except Exception as e:
            logger.exception(
                "Failed to join event %s: %s",
                event_id,
                e,
                extra={"user": telegram_user_id},
            )

            # Mark idempotency key as failed if enabled
            if settings.enable_idempotency:
                await idempotency_service.fail(idempotency_key)

            await message.reply_text(
                f"❌ Failed to join event {event_id}. Please try again."
            )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback queries for join buttons.

    Converts callback to command execution for reuse.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data

    if data and data.startswith("event_join_"):
        event_id = int(data.replace("event_join_", ""))

        # Reuse command handler
        context.args = [str(event_id)]
        await handle(update, context)

        # Update callback message
await query.edit_message_text(
        f"✅ <b>Joined event {event_id}!</b>\n\n"
        f"Use /status {event_id} to view event details.",
        parse_mode="HTML",
    )
