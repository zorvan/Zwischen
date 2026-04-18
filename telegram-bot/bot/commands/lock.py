#!/usr/bin/env python3
"""Lock event command handler.

PRD v2 Updates:
- Uses RBAC for permission checks
- Enforces min_participants threshold
- Enforces lock_deadline (TODO-022)
- Finalizes all joined participants to confirmed
"""
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from bot.common.event_states import STATE_EXPLANATIONS
from config.settings import settings
from db.connection import get_session
from db.models import Event
from bot.services import EventLifecycleService, ParticipantService
from bot.common.rbac import check_can_lock_event
from bot.services.event_state_transition_service import ThresholdNotMetError

logger = logging.getLogger(__name__)


async def handle_lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /lock command - finalize a confirmed event.

    Requirements:
    - User must be organizer or admin
    - Event must be in 'confirmed' state
    - Confirmed participants >= min_participants
    """
    if not update.message:
        return

    event_id_raw = context.args[0] if context.args else None
    if not event_id_raw:
        await update.message.reply_text(
            "Usage: /lock <event_id>\n\n"
            "Example: /lock 123"
        )
        return

    try:
        event_id = int(event_id_raw)
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return

    if not settings.db_url:
        await update.message.reply_text("❌ Database configuration is unavailable.")
        return

    user_id = update.effective_user.id if update.effective_user else None

    async with get_session(settings.db_url) as session:
        event = (
            await session.execute(
                select(Event).where(Event.event_id == event_id)
            )
        ).scalar_one_or_none()
        if not event:
            await update.message.reply_text("❌ Event not found.")
            return

        # RBAC check
        is_authorized, error_msg = await check_can_lock_event(
            session, event_id, user_id
        )
        if not is_authorized:
            await update.message.reply_text(
                f"❌ Cannot lock event.\n{error_msg}"
            )
            return

        # State check
        if event.state != "confirmed":
            await update.message.reply_text(
                f"❌ Cannot lock event {event_id}.\n"
                f"Current state: {event.state}\n"
                f"Meaning: {STATE_EXPLANATIONS.get(event.state, 'Unavailable')}\n"
                "You can lock only when state is 'confirmed'."
            )
            return

        # Threshold enforcement (PRD v2 Section 2.1)
        min_required = event.min_participants or 2
        participant_service = ParticipantService(session)
        confirmed_count = await participant_service.get_confirmed_count(event_id)

        if confirmed_count < min_required:
            await update.message.reply_text(
                f"❌ Cannot lock event - below minimum participants.\n\n"
                f"Required: {min_required} confirmed\n"
                f"Current: {confirmed_count} confirmed\n\n"
                f"Wait for more participants to confirm, or reduce min_participants."
            )
            return

        # Lock deadline enforcement (TODO-022)
        if event.lock_deadline and datetime.utcnow() > event.lock_deadline:
            await update.message.reply_text(
                f"❌ Cannot lock event - lock deadline has passed.\n\n"
                f"Lock deadline was: {event.lock_deadline.strftime('%Y-%m-%d %H:%M')}\n"
                f"Current time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"Participants can still join, but the event cannot be locked."
            )
            return

        # Use EventLifecycleService for state changes with full integration
        lifecycle_service = EventLifecycleService(context.bot, session)
        try:
            event, transitioned = await lifecycle_service.transition_with_lifecycle(
                event_id=event_id,
                target_state="locked",
                actor_telegram_user_id=user_id,
                source="slash",
                reason="Manual lock command",
                expected_version=event.version,
            )
        except ThresholdNotMetError as e:
            await update.message.reply_text(
                f"❌ Cannot lock event - threshold not met.\n{str(e)}"
            )
            return
        except Exception as e:
            logger.exception("Failed to lock event %s", event_id)
            await update.message.reply_text(f"❌ Failed to lock event: {str(e)}")
            return

        # Finalize commitments - mark all joined participants as confirmed
        finalized_count = await participant_service.finalize_commitments(event_id)

    await update.message.reply_text(
        f"🔒 Event {event_id} locked successfully.\n\n"
        f"State: locked\n"
        f"Confirmed participants: {confirmed_count}\n"
        f"Finalized commitments: {finalized_count}\n"
        f"Meaning: {STATE_EXPLANATIONS['locked']}"
    )
