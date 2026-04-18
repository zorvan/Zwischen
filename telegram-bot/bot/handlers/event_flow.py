#!/usr/bin/env python3
"""Event flow state machine handler."""

from datetime import datetime
import logging
from typing import Optional, List, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.connection import get_session
from db.models import (
    Event,
    EventParticipant,
    ParticipantStatus,
    User,
    Group,
    EventEnrichment,
    Constraint,
)
from bot.common.event_states import STATE_EXPLANATIONS
from bot.common.rbac import check_group_membership
from bot.services.event_enrichment_service import EventEnrichmentService
from bot.services.event_live_card_service import EventLiveCardService
from bot.services.event_memory_service import EventMemoryService
from bot.common.event_access import (
    get_event_admin_telegram_id,
    get_event_organizer_telegram_id,
)
from bot.common.rbac import check_event_visibility_and_get_event
from bot.common.participant_state_reconcile import (
    reconcile_event_state_after_participant_change,
)
from bot.services import ParticipantService, EventLifecycleService
from bot.services.event_live_card_service import EventLiveCardService

logger = logging.getLogger(__name__)


async def handle_event_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main event flow handler - routes to state-specific handlers."""
    query = update.callback_query

    if not query or not query.data:
        return

    await query.answer()

    data = query.data

    if data.startswith("event_"):
        parts = data.split("_")
        if len(parts) >= 3:
            event_id = int(parts[-1])
            action = "_".join(parts[1:-1])

            if action == "join":
                await handle_join(query, context, event_id)
            elif action == "confirm":
                await handle_confirm(query, context, event_id)
            elif action == "back" or action == "unconfirm":
                # Both "back" and "unconfirm" do the same thing - revert confirmation
                await handle_back(query, context, event_id)
            elif action == "cancel":
                await handle_cancel(query, context, event_id)
            elif action == "lock":
                await handle_lock(query, context, event_id)
            elif action == "modify_menu":
                from bot.commands import event_details

                fake_update = type(
                    "FakeUpdate",
                    (),
                    {
                        "callback_query": query,
                        "effective_user": query.from_user,
                        "effective_chat": getattr(query.message, "chat", None),
                    },
                )()
                context.args = [str(event_id)]
                await event_details.handle(fake_update, context)


async def handle_join(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Handle joining an event - transition to interested state."""
    telegram_user_id = query.from_user.id
    display_name = query.from_user.full_name
    username = query.from_user.username
    bot = context.bot

    # Prevent interactions from group chats - all event interactions should be in DMs
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    if chat_type and chat_type != "private":
        await query.answer(
            "Please interact with events in private DM with the bot.", show_alert=True
        )
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
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
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        if event.state in ["locked", "completed", "cancelled"]:
            await query.edit_message_text(
                f"❌ Cannot join event {event_id}.\n"
                f"Current state: {event.state}\n"
                f"Meaning: {STATE_EXPLANATIONS.get(event.state, 'Unavailable')}"
            )
            return

        # Check if user already joined/confirmed
        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(
            event_id, telegram_user_id
        )

        if participant:
            if participant.status == ParticipantStatus.confirmed:
                await query.answer("ℹ️ You've already confirmed", show_alert=True)
                return
            elif participant.status == ParticipantStatus.cancelled:
                # Allow re-joining after cancellation - continue processing
                pass
            # If status is 'joined', user is clicking Join button again but already joined
            # This shouldn't happen with proper UI, but if it does, just update their join time
            elif participant.status == ParticipantStatus.joined:
                # Update join time and show confirm menu
                participant.joined_at = datetime.now(timezone.utc)
                await session.flush()

        conflict = await find_user_event_conflict(
            session=session,
            telegram_user_id=telegram_user_id,
            start_time=event.scheduled_time,
            duration_minutes=event.duration_minutes,
            ignore_event_id=event.event_id,
        )
        if conflict:
            await query.edit_message_text(
                "❌ You have a conflicting event.\n"
                f"Conflicting Event ID: {conflict.event_id}\n"
                f"Time: {conflict.scheduled_time}\n"
                f"Duration: {conflict.duration_minutes or 120} minutes"
            )
            return

        # v3.2: Check if event is at target capacity → offer waitlist
        from sqlalchemy import func as sql_func
        from db.models import EventParticipant

        participant_result = await session.execute(
            select(sql_func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        current_count = participant_result.scalar() or 0
        target = event.target_participants or event.min_participants or 6

        if current_count >= target and not (
            participant
            and participant.status
            in [
                ParticipantStatus.joined,
                ParticipantStatus.confirmed,
                ParticipantStatus.cancelled,
            ]
        ):
            # Event at capacity — offer waitlist
            from bot.services import WaitlistService

            waitlist_service = WaitlistService(session, bot)

            # Check if already on waitlist
            existing_position = await waitlist_service.get_waitlist_position(
                event_id, telegram_user_id
            )
            if existing_position:
                await query.edit_message_text(
                    f"📋 The {event.event_type} is full at the moment. "
                    f"You're #{existing_position} on the list. "
                    f"You'll be notified if a spot opens."
                )
                return

            await query.edit_message_text(
                f"📋 The {event.event_type} is full at the moment. "
                f"Want me to add you to the waitlist? You'll be notified if a spot opens.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Join Waitlist",
                                callback_data=f"waitlist_join_{event_id}",
                            ),
                            InlineKeyboardButton(
                                "❌ No Thanks", callback_data=f"event_close_{event_id}"
                            ),
                        ]
                    ]
                ),
            )
            return

        # Use ParticipantService for join operation
        participant, is_new_join = await participant_service.join(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            source="callback",
        )

        user_id = await get_or_create_user_id(
            session,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            username=username,
        )

        # Check if we need to transition state from proposed to interested
        confirmed_count = await participant_service.get_confirmed_count(event_id)
        if event.state == "proposed" and confirmed_count > 0:
            lifecycle_service = EventLifecycleService(bot, session)
            try:
                event, _ = await lifecycle_service.transition_with_lifecycle(
                    event_id=event_id,
                    target_state="interested",
                    actor_telegram_user_id=telegram_user_id,
                    source="callback",
                    reason="First participant joined",
                )
            except Exception as e:
                logger.error(
                    f"Failed to transition event {event_id} to interested: {e}"
                )

        log = Log(
            event_id=event_id,
            user_id=user_id,
            action="join",
            metadata_dict={"timestamp": datetime.now(timezone.utc).isoformat()},
        )
        session.add(log)
        await session.commit()

        # Phase 3.3: Update live card after participant change
        await update_live_card_on_change(context, event_id)

        # Refresh event to get latest state
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        # Get participant status to determine button text
        participant = await participant_service.get_participant(
            event_id, telegram_user_id
        )
        user_confirmed = (
            participant and participant.status == ParticipantStatus.confirmed
        )
        user_joined = participant and participant.status in [
            ParticipantStatus.joined,
            ParticipantStatus.confirmed,
        ]

        # Build comprehensive event menu with all actions (state-aware)
        # First row based on user status (mutually exclusive actions)
        if not user_joined:
            # User hasn't joined - show Join only
            first_row = [
                InlineKeyboardButton("✅ Join", callback_data=f"event_join_{event_id}"),
            ]
            # Show Cancel + Lock row
            second_row = [
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"event_cancel_{event_id}"
                ),
                InlineKeyboardButton("🔒 Lock", callback_data=f"event_lock_{event_id}"),
            ]
        elif user_confirmed:
            # User is confirmed - show Confirmed + Uncommit
            first_row = [
                InlineKeyboardButton(
                    "✓ Confirmed", callback_data=f"event_confirm_{event_id}"
                ),
                InlineKeyboardButton(
                    "↩️ Uncommit", callback_data=f"event_unconfirm_{event_id}"
                ),
            ]
            # Show Cancel + Lock row
            second_row = [
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"event_cancel_{event_id}"
                ),
                InlineKeyboardButton("🔒 Lock", callback_data=f"event_lock_{event_id}"),
            ]
        else:
            # User joined but not confirmed - show Confirm + Cancel (no separate Cancel row needed)
            first_row = [
                InlineKeyboardButton(
                    "✅ Confirm", callback_data=f"event_confirm_{event_id}"
                ),
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"event_cancel_{event_id}"
                ),
            ]
            # Show Lock + Logs row
            second_row = [
                InlineKeyboardButton("🔒 Lock", callback_data=f"event_lock_{event_id}"),
                InlineKeyboardButton(
                    "📝 View Logs", callback_data=f"event_logs_{event_id}"
                ),
            ]

        keyboard = [
            first_row,
            second_row,
        ]

        # Add remaining rows for all users
        if not user_joined or user_confirmed:
            # Add Logs row if not already added
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "📝 View Logs", callback_data=f"event_logs_{event_id}"
                    )
                ]
            )

        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        "🔒 Manage Constraints",
                        callback_data=f"event_constraints_{event_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📊 Status", callback_data=f"event_status_{event_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔄 Refresh", callback_data=f"event_details_{event_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Close", callback_data=f"event_close_{event_id}"
                    )
                ],
            ]
        )

        # Add Modify button for organizer/admin
        admin_id = get_event_admin_telegram_id(event)
        organizer_id = get_event_organizer_telegram_id(event)
        if telegram_user_id in [admin_id, organizer_id]:
            keyboard.insert(
                4,
                [
                    InlineKeyboardButton(
                        "🛠 Modify", callback_data=f"event_modify_menu_{event_id}"
                    )
                ],
            )

        # Add DM links
        if bot.username:
            avail_link = f"https://t.me/{bot.username}?start=avail_{event_id}"
            keyboard.append(
                [InlineKeyboardButton("📥 Set Availability in DM", url=avail_link)]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Build rich status message
        planning_prefs = event.planning_prefs if event.planning_prefs else {}
        time_str = format_scheduled_time(
            event.scheduled_time, include_flexible_note=False
        )
        location = format_location_type(planning_prefs.get("location_type"))

        # Get attendee counts from participant service
        interested_count = await participant_service.get_interested_count(event_id)
        confirmed_count = await participant_service.get_confirmed_count(event_id)

        await query.edit_message_text(
            f"✅ <b>You joined the event!</b>\n\n"
            f"📋 <b>Event #{event_id}</b>\n"
            f"Type: {event.event_type}\n"
            f"Time: {time_str}\n"
            f"Location: {location}\n"
            f"State: {event.state}\n\n"
            f"👥 <b>Participants:</b>\n"
            f"Interested: {interested_count}\n"
            f"Confirmed: {confirmed_count}\n"
            f"Minimum: {event.min_participants}\n"
            f"Capacity: {event.target_participants}\n\n"
            f"<i>The event is now gathering momentum!</i>\n"
            f"<i>Set your availability, add constraints, and engage with the group.</i>",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


async def handle_confirm(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle confirm action - move participant to confirmed stage."""
    telegram_user_id = query.from_user.id
    display_name = query.from_user.full_name
    username = query.from_user.username
    bot = context.bot

    # Prevent interactions from group chats - all event interactions should be in DMs
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    if chat_type and chat_type != "private":
        await query.answer(
            "Please interact with events in private DM with the bot.", show_alert=True
        )
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
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
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        if event.state in ["locked", "completed", "cancelled"]:
            await query.edit_message_text(
                f"❌ Cannot confirm event {event_id}.\n"
                f"Current state: {event.state}\n"
                f"Meaning: {STATE_EXPLANATIONS.get(event.state, 'Unavailable')}\n"
                "You can confirm only before the event is locked/completed/cancelled."
            )
            return

        # Check if user already confirmed or hasn't joined
        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(
            event_id, telegram_user_id
        )

        if not participant:
            await query.answer("❌ Please join first", show_alert=True)
            return
        elif participant.status == ParticipantStatus.confirmed:
            await query.answer("ℹ️ You've already confirmed", show_alert=True)
            return
        elif participant.status == ParticipantStatus.cancelled:
            await query.answer(
                "❌ You cancelled - contact organizer to rejoin", show_alert=True
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
            await query.edit_message_text(
                "❌ You have a conflicting event.\n"
                f"Conflicting Event ID: {conflict.event_id}\n"
                f"Time: {conflict.scheduled_time}\n"
                f"Duration: {conflict.duration_minutes or 120} minutes"
            )
            return

        # Use ParticipantService for confirm operation
        participant, is_new_confirm = await participant_service.confirm(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            source="callback",
        )

        # Check if we need to transition to confirmed state
        confirmed_count = await participant_service.get_confirmed_count(event_id)
        if event.state != "confirmed" and confirmed_count > 0:
            lifecycle_service = EventLifecycleService(bot, session)
            try:
                event, _ = await lifecycle_service.transition_with_lifecycle(
                    event_id=event_id,
                    target_state="confirmed",
                    actor_telegram_user_id=telegram_user_id,
                    source="callback",
                    reason="Participant confirmed attendance",
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
            metadata_dict={"timestamp": datetime.now(timezone.utc).isoformat()},
        )
        session.add(log)
        await session.commit()

        # Phase 3.3: Update live card after participant change
        await update_live_card_on_change(context, event_id)

        # Refresh event to get latest state
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        # Build comprehensive event menu with all actions
        keyboard = [
            # Primary actions
            [
                InlineKeyboardButton(
                    "↩️ Back (Uncommit)", callback_data=f"event_back_{event_id}"
                ),
                InlineKeyboardButton(
                    "❌ Exit", callback_data=f"event_cancel_{event_id}"
                ),
            ],
            # Event management
            [
                InlineKeyboardButton(
                    "📋 Event Details", callback_data=f"event_details_{event_id}"
                ),
                InlineKeyboardButton(
                    "📊 Status", callback_data=f"event_status_{event_id}"
                ),
            ],
            # Planning & constraints
            [
                InlineKeyboardButton(
                    "📅 Set Availability",
                    url=f"https://t.me/{bot.username}?start=avail_{event_id}",
                ),
                InlineKeyboardButton(
                    "🔒 Constraints", callback_data=f"event_constraints_{event_id}"
                ),
            ],
            # Logs
            [
                InlineKeyboardButton("📝 Logs", callback_data=f"event_logs_{event_id}"),
                InlineKeyboardButton(
                    "🔄 Update", callback_data=f"event_details_{event_id}"
                ),
            ],
        ]

        # Add lock button for organizer/admin
        admin_id = get_event_admin_telegram_id(event)
        organizer_id = get_event_organizer_telegram_id(event)
        if telegram_user_id in [admin_id, organizer_id] and event.state == "confirmed":
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔒 Lock Event", callback_data=f"event_lock_{event_id}"
                    ),
                ]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Build rich status message
        planning_prefs = event.planning_prefs if event.planning_prefs else {}
        time_str = format_scheduled_time(
            event.scheduled_time, include_flexible_note=False
        )
        location = format_location_type(planning_prefs.get("location_type"))

        # Get attendee counts from participant service
        interested_count = await participant_service.get_interested_count(event_id)
        confirmed_count = await participant_service.get_confirmed_count(event_id)

        await query.edit_message_text(
            f"✅ <b>You confirmed to the event!</b>\n\n"
            f"📋 <b>Event #{event_id}</b>\n"
            f"Type: {event.event_type}\n"
            f"Time: {time_str}\n"
            f"Location: {location}\n"
            f"State: {event.state}\n\n"
            f"👥 <b>Participants:</b>\n"
            f"Interested: {interested_count}\n"
            f"Confirmed: {confirmed_count}\n"
            f"Minimum: {event.min_participants}\n"
            f"Capacity: {event.target_participants}\n\n"
            f"<i>Your confirmation helps the event reach critical mass!</i>\n"
            f"<i>You can go back before the event is locked.</i>",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


async def handle_back(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Revert personal confirmation to interested before lock (uncommit)."""
    telegram_user_id = query.from_user.id

    # Prevent interactions from group chats - all event interactions should be in DMs
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    if chat_type and chat_type != "private":
        await query.answer(
            "Please interact with events in private DM with the bot.", show_alert=True
        )
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
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
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        if event.state == "locked":
            await query.edit_message_text("❌ Event is locked. Cannot uncommit.")
            return

        # Use ParticipantService for back operation (new system)
        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(
            event_id, telegram_user_id
        )

        if not participant or participant.status != ParticipantStatus.confirmed:
            await query.edit_message_text("ℹ️ You are not confirmed in this event.")
            return

        await participant_service.unconfirm(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            source="callback",
        )
        event = await reconcile_event_state_after_participant_change(
            session=session,
            bot=context.bot,
            event_id=event_id,
            actor_telegram_user_id=telegram_user_id,
            source="callback",
            reason="Participant unconfirmed attendance",
        )
        await session.commit()

    await query.edit_message_text(
        f"↩️ Confirmation reverted for event {event_id}.\n"
        f"State: {event.state}\n"
        "You are now in interested state (uncommitted)."
    )


async def handle_cancel(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle cancelling attendance for the clicking user.
    v3.2: Triggers waitlist auto-fill if someone is waiting.
    """
    telegram_user_id = query.from_user.id
    display_name = query.from_user.full_name
    username = query.from_user.username
    bot = context.bot

    # Prevent interactions from group chats - all event interactions should be in DMs
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    if chat_type and chat_type != "private":
        await query.answer(
            "Please interact with events in private DM with the bot.", show_alert=True
        )
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
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
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        # Use ParticipantService for cancel operation
        participant_service = ParticipantService(session)
        try:
            participant, is_new_cancel = await participant_service.cancel(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
                source="callback",
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to cancel attendance: {str(e)}")
            return

        # v3.2: Trigger waitlist auto-fill
        from bot.services import WaitlistService

        waitlist_service = WaitlistService(session, bot)
        await waitlist_service.trigger_auto_fill(event_id)

        event = await reconcile_event_state_after_participant_change(
            session=session,
            bot=bot,
            event_id=event_id,
            actor_telegram_user_id=telegram_user_id,
            source="callback",
            reason="Participant cancelled attendance",
        )

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
            metadata_dict={"timestamp": datetime.now(timezone.utc).isoformat()},
        )
        session.add(log)
        await session.commit()

        await query.edit_message_text(
            f"❌ *Attendance cancelled for event {event_id}!*\n\n"
            f"State: {event.state}\n"
            f"Meaning: {STATE_EXPLANATIONS.get(event.state, 'Unknown state')}"
        )


async def handle_lock(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Handle locking an event - transition from confirmed to locked."""
    telegram_user_id = query.from_user.id
    bot = context.bot

    # Prevent interactions from group chats - all event interactions should be in DMs
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    if chat_type and chat_type != "private":
        await query.answer(
            "Please interact with events in private DM with the bot.", show_alert=True
        )
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
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
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        if event.state != "confirmed":
            await query.edit_message_text(
                f"❌ Cannot lock event {event_id}.\n"
                f"Current state: {event.state}\n"
                f"Meaning: {STATE_EXPLANATIONS.get(event.state, 'Unavailable')}\n"
                "You can lock only when state is 'confirmed'."
            )

            return

        # Use EventLifecycleService for state transition with full integration
        lifecycle_service = EventLifecycleService(bot, session)
        try:
            event, _ = await lifecycle_service.transition_with_lifecycle(
                event_id=event_id,
                target_state="locked",
                actor_telegram_user_id=telegram_user_id,
                source="callback",
                reason="Manual lock via callback",
                expected_version=event.version,
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to lock event: {str(e)}")
            return

        # Finalize commitments using ParticipantService (new system)
        participant_service = ParticipantService(session)
        await participant_service.finalize_commitments(event_id)

        await query.edit_message_text(
            f"🔒 *Event {event_id} locked!*\n\n"
            f"State: locked\n"
            f"Meaning: {STATE_EXPLANATIONS['locked']}\n"
            f"Locked at: {event.locked_at}"
        )


async def show_event_details(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show detailed event information."""
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Get participant count from new system
        participant_service = ParticipantService(session)
        counts = await participant_service.get_counts(event_id)
        total_attendees = counts.get("total", 0)

        await query.edit_message_text(
            f"📋 *Event {event_id}*\n\n"
            f"Type: {event.event_type}\n"
            f"Time: {event.scheduled_time}\n"
            f"State: {event.state}\n"
            f"Minimum: {event.min_participants}\n"
            f"Capacity: {event.target_participants}\n"
            f"Attendees: {total_attendees}"
        )


async def update_live_card_on_change(
    context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Update live card after participant change."""
    bot = context.bot
    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        if event and event.group_id:
            service = EventLiveCardService(bot, session)
            await service.update_live_card(event)


# ============================================================================
# V3.4 Progressive Disclosure - Level 2 Event Panel and Level 3 Sub-menus
# ============================================================================


async def handle_event_panel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle Level 2: Event Panel callback."""
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    # Parse callback data: "panel:{event_id}"
    try:
        _, event_id_str = query.data.split(":", 1)
        event_id = int(event_id_str)
    except (ValueError, IndexError):
        logger.warning(f"Invalid panel callback data: {query.data}")
        return

    db_url = settings.db_url or ""
    user_id = update.effective_user.id if update.effective_user else None

    async with get_session(db_url) as session:
        # Get event with full context
        event_result = await session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Get user's participation status
        user_status = None
        is_organizer = False
        if user_id:
            participant_result = await session.execute(
                select(EventParticipant).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.telegram_user_id == user_id,
                )
            )
            participant = participant_result.scalar_one_or_none()

            if participant:
                if participant.status == ParticipantStatus.confirmed:
                    user_status = "confirmed"
                elif participant.status == ParticipantStatus.joined:
                    user_status = "joined"
                else:
                    user_status = "invited"
            else:
                user_status = "not_involved"

            is_organizer = user_id in {
                event.organizer_telegram_user_id,
                event.admin_telegram_user_id,
            }

        # Get participant counts
        confirmed_result = await session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == ParticipantStatus.confirmed,
            )
        )
        confirmed_count = len(confirmed_result.scalars().all())

        total_result = await session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status.in_(
                    [ParticipantStatus.confirmed, ParticipantStatus.joined]
                ),
            )
        )
        total_count = len(total_result.scalars().all())

        # Get enrichments for context
        from bot.services.event_enrichment_service import EventEnrichmentService

        enrichment_service = EventEnrichmentService(session, context.bot)
        enrichments = await enrichment_service.get_event_enrichments(event_id)

        # Get lineage fragment
        from bot.services.event_memory_service import EventMemoryService

        memory_service = EventMemoryService(context.bot, session)
        lineage_fragment = await memory_service.get_lineage_door_fragment(
            event.group_id or 0, event.event_type
        )

        # Build panel message
        text, keyboard = await build_event_panel(
            event,
            user_status,
            is_organizer,
            confirmed_count,
            total_count,
            enrichments,
            lineage_fragment,
        )

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )


async def build_event_panel(
    event: Event,
    user_status: str,
    is_organizer: bool,
    confirmed_count: int,
    total_count: int,
    enrichments: List[EventEnrichment],
    lineage_fragment: Optional[str],
) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """Build Level 2 Event Panel with context-aware action buttons."""

    # Event header
    lines = [
        f"📋 <b>{event.description or 'Event'}</b>",
        f"🏷️ Type: {event.event_type}",
        f"⏰ Time: {event.scheduled_time.strftime('%a %d %b, %H:%M') if event.scheduled_time else 'TBD'}",
        f"👥 Participants: {confirmed_count} / {event.min_participants} min",
        f"📊 Status: {event.state.replace('_', ' ').title()}",
    ]

    # Lineage fragment (V3.4 memory as coordination input)
    if lineage_fragment:
        lines.append("")
        lines.append(f"↩ <i>From last time: {lineage_fragment}</i>")

    # Active hashtags (V3.4 enrichment)
    public_hashtags = [
        e.content for e in enrichments if e.enrichment_type == "hashtag" and e.is_public
    ]
    if public_hashtags:
        lines.append("")
        lines.append(f"🏷️ {' '.join(f'#{tag}' for tag in public_hashtags[:3])}")

    lines.append("")
    lines.append("💡 <b>Available Actions:</b>")

    # Build context-aware action buttons
    keyboard = []

    # Action button logic based on user status and event state
    if user_status == "invited" and event.state in ["proposed", "interested"]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "👋 Join", callback_data=f"action:{event.event_id}:join"
                )
            ]
        )

    if user_status in ["joined", "confirmed"] and event.state in [
        "proposed",
        "interested",
        "confirmed",
    ]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "↩️ Relinquish", callback_data=f"action:{event.event_id}:relinquish"
                )
            ]
        )

        if user_status in ["joined", "confirmed"]:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "✨ Enrich", callback_data=f"action:{event.event_id}:enrich"
                    )
                ]
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "⚡ Constraint",
                        callback_data=f"action:{event.event_id}:constraint",
                    )
                ]
            )

    # Commit button when gravity is met
    if total_count >= event.min_participants and user_status in ["joined", "confirmed"]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "✅ Commit", callback_data=f"action:{event.event_id}:commit"
                )
            ]
        )

    # Organizer actions
    if is_organizer:
        if total_count >= event.min_participants:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔒 Lock", callback_data=f"action:{event.event_id}:lock"
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "✏️ Edit Event", callback_data=f"action:{event.event_id}:edit"
                )
            ]
        )

    # Always available
    keyboard.append(
        [InlineKeyboardButton("🔙 Back to List", callback_data="menu:events")]
    )

    return "\n".join(lines), keyboard


async def handle_event_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle action callbacks from Level 2 Event Panel."""
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    # Parse callback data: "action:{event_id}:{action}"
    try:
        _, event_id_str, action = query.data.split(":", 2)
        event_id = int(event_id_str)
    except (ValueError, IndexError):
        logger.warning(f"Invalid action callback data: {query.data}")
        return

    # Route to appropriate handler based on action
    if action == "join":
        await handle_join(query, context, event_id)
    elif action == "relinquish":
        await handle_back(query, context, event_id)
    elif action == "commit":
        await handle_confirm(query, context, event_id)
    elif action == "lock":
        await handle_lock(query, context, event_id)
    elif action == "edit":
        # Handle edit action - could route to event details handler
        from bot.commands.event_details import handle as handle_event_details

        await handle_event_details(update, context, event_id)
    else:
        logger.warning(f"Unknown action: {action}")


async def handle_enrich_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle Level 3a: Enrich sub-menu callback."""
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    # Parse callback data: "action:{event_id}:enrich"
    try:
        _, event_id_str, action = query.data.split(":", 2)
        event_id = int(event_id_str)
    except (ValueError, IndexError):
        logger.warning(f"Invalid enrich callback data: {query.data}")
        return

    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        event_result = await session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Build enrich sub-menu
        text, keyboard = await build_enrich_menu(event)

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )


async def build_enrich_menu(
    event: Event,
) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """Build Level 3a Enrich sub-menu."""

    lines = [
        f"✨ <b>Enrich Event</b>",
        f"📋 {event.description or 'Event'}",
        "",
        "💡 Choose how you'd like to enrich this event:",
    ]

    keyboard = [
        [
            InlineKeyboardButton(
                "💡 Add an Idea", callback_data=f"enrich:{event.event_id}:idea"
            )
        ],
        [
            InlineKeyboardButton(
                "🏷️ Add a Hashtag", callback_data=f"enrich:{event.event_id}:hashtag"
            )
        ],
        [
            InlineKeyboardButton(
                "📝 Add a Memory", callback_data=f"enrich:{event.event_id}:memory"
            )
        ],
        [
            InlineKeyboardButton(
                "👁️ View My Contributions", callback_data=f"enrich:{event.event_id}:view"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Event", callback_data=f"panel:{event.event_id}"
            )
        ],
    ]

    return "\n".join(lines), keyboard


async def handle_constraint_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle Level 3b: Constraint sub-menu callback."""
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    # Parse callback data: "action:{event_id}:constraint"
    try:
        _, event_id_str, action = query.data.split(":", 2)
        event_id = int(event_id_str)
    except (ValueError, IndexError):
        logger.warning(f"Invalid constraint callback data: {query.data}")
        return

    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        event_result = await session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Build constraint sub-menu
        text, keyboard = await build_constraint_menu(event)

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )


async def build_constraint_menu(
    event: Event,
) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """Build Level 3b Constraint sub-menu."""

    lines = [
        f"⚡ <b>Constraints for {event.description or 'Event'}</b>",
        "",
        "💡 Express your participation conditions:",
    ]

    keyboard = [
        [
            InlineKeyboardButton(
                "👥 I'll join if [person] joins",
                callback_data=f"constraint:{event.event_id}:if_joins",
            )
        ],
        [
            InlineKeyboardButton(
                "✅ I'll join only if [person] attends",
                callback_data=f"constraint:{event.event_id}:if_attends",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ I won't join if [person] joins",
                callback_data=f"constraint:{event.event_id}:unless_joins",
            )
        ],
        [
            InlineKeyboardButton(
                "⏰ My Availability",
                callback_data=f"constraint:{event.event_id}:availability",
            )
        ],
        [
            InlineKeyboardButton(
                "🗑️ View/Remove My Constraints",
                callback_data=f"constraint:{event.event_id}:view",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Event", callback_data=f"panel:{event.event_id}"
            )
        ],
    ]

    return "\n".join(lines), keyboard


async def handle_ev_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ev command messages."""
    if not update.message or not update.effective_user:
        return
    
    # This is a placeholder for /ev command handling
    # The actual logic should be implemented based on requirements
    await update.message.reply_text("🔧 /ev command functionality is being implemented.")


async def handle_ev_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle Level 2: Event flow callback with format ev:{event_id}:{action}."""
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id if update.effective_user else None
    db_url = settings.db_url or ""

    try:
        _, event_id_str, action = query.data.split(":", 2)
        event_id = int(event_id_str)
    except (ValueError, IndexError):
        logger.warning(f"Invalid ev callback data: {query.data}")
        await query.answer("❌ Invalid callback data", show_alert=True)
        return

    async with get_session(db_url) as session:
        event_result = await session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        (
            is_visible,
            _,
            _,
            error_msg,
        ) = await check_event_visibility_and_get_event(
            session,
            event_id,
            user_id,
            telegram_chat_id=chat_id,
            bot=context.bot,
        )

        if not is_visible:
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        user_status = None
        is_organizer = False
        if user_id:
            participant_result = await session.execute(
                select(EventParticipant).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.telegram_user_id == user_id,
                )
            )
            participant = participant_result.scalar_one_or_none()

            if participant:
                if participant.status == ParticipantStatus.confirmed:
                    user_status = "confirmed"
                elif participant.status == ParticipantStatus.joined:
                    user_status = "joined"
                else:
                    user_status = "invited"
            else:
                user_status = "not_involved"

            is_organizer = user_id in {
                event.organizer_telegram_user_id,
                event.admin_telegram_user_id,
            }

        # Route to appropriate handler based on action
        if action == "join":
            await handle_join(query, context, event_id)
        elif action == "relinquish":
            await handle_relinquish(
                query, context, session, event_id, user_id, event, user_status
            )
        elif action == "enrich":
            await handle_enrich_callback(update, context)
        elif action == "constraint":
            await handle_constraint_callback(update, context)
        elif action == "commit":
            await handle_confirm(query, context, event_id)
        elif action == "lock":
            await handle_lock(query, context, event_id)
        elif action == "edit":
            from bot.commands.event_details import handle as handle_event_details

            await handle_event_details(update, context, event_id)
        elif action == "idea":
            await handle_idea_callback(update, context, event_id, event)
        elif action == "hashtag":
            await handle_hashtag_callback(update, context, event_id, event)
        elif action == "memory":
            await handle_memory_callback(update, context, event_id, event)
        elif action == "my_contribs":
            await handle_my_contribs_callback(update, context, event_id, event)
        elif action == "constraint_if_joins":
            await handle_constraint_if_joins(query, context, event_id, event)
        elif action == "constraint_if_attends":
            await handle_constraint_if_attends(query, context, event_id, event)
        elif action == "constraint_unless_joins":
            await handle_constraint_unless_joins(query, context, event_id, event)
        elif action == "availability":
            await handle_availability_callback(update, context, event_id, event)
        elif action == "my_constraints":
            await handle_my_constraints_callback(update, context, event_id, event)
        elif action == "det":
            await show_event_details(query, context, event_id)
        elif action == "list":
            await handle_list_callback(update, context)
        else:
            logger.warning(f"Unknown ev action: {action}")
            await query.answer(f"Unknown action: {action}", show_alert=True)


async def handle_relinquish(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    event_id: int,
    user_id: int,
    event: Event,
    user_status: str,
) -> None:
    """Handle leaving/relinquishing an event."""
    from bot.services import ParticipantService
    from db.models import Log
    from datetime import timezone
    from db.users import get_or_create_user_id

    telegram_user_id = query.from_user.id
    display_name = query.from_user.full_name
    username = query.from_user.username

    if user_status in ["confirmed", "joined"]:
        participant_service = ParticipantService(session)
        try:
            participant, is_new_cancel = await participant_service.cancel(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
                source="callback",
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to relinquish: {str(e)}")
            return

        event = await reconcile_event_state_after_participant_change(
            session=session,
            bot=context.bot,
            event_id=event_id,
            actor_telegram_user_id=telegram_user_id,
            source="callback",
            reason="Participant relinquished attendance",
        )

        user_id_db = await get_or_create_user_id(
            session,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
            username=username,
        )

        log = Log(
            event_id=event_id,
            user_id=user_id_db,
            action="relinquish",
            metadata_dict={"timestamp": datetime.now(timezone.utc).isoformat()},
        )
        session.add(log)
        await session.commit()

        await query.edit_message_text(
            f"❌ *Attendance relinquished for event {event_id}!*\n\n"
            f"State: {event.state}\n"
            f"Meaning: {STATE_EXPLANATIONS.get(event.state, 'Unknown state')}"
        )
    else:
        await query.edit_message_text("ℹ️ You are not participating in this event.")


async def handle_idea_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle adding an idea."""
    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        "💡 Please send your idea as a message.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data=f"ev:{event_id}:enrich")]]
        ),
    )

    context.user_data["pending_idea_event_id"] = event_id
    context.user_data["pending_idea_user_id"] = update.effective_user.id


async def handle_hashtag_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle adding a hashtag."""
    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        "🏷️ Please send your hashtag (without # prefix) as a message.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data=f"ev:{event_id}:enrich")]]
        ),
    )

    context.user_data["pending_hashtag_event_id"] = event_id
    context.user_data["pending_hashtag_user_id"] = update.effective_user.id


async def handle_memory_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle adding a memory."""
    await update.callback_query.answer()

    await update.callback_query.edit_message_text(
        "📜 Please send your memory as a message.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data=f"ev:{event_id}:enrich")]]
        ),
    )

    context.user_data["pending_memory_event_id"] = event_id
    context.user_data["pending_memory_user_id"] = update.effective_user.id


async def handle_my_contribs_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle viewing my contributions."""
    from db.models import EventEnrichment
    from sqlalchemy import select
    from bot.common.event_access import check_event_visibility_and_get_event

    query = update.callback_query
    user_id = update.effective_user.id

    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        result = await session.execute(
            select(EventEnrichment).where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.user_id == user_id,
            )
        )
        contributions = result.scalars().all()

        if not contributions:
            await query.edit_message_text(
                "ℹ️ You haven't made any contributions yet.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Back", callback_data=f"ev:{event_id}:enrich"
                            )
                        ]
                    ]
                ),
            )
            return

        lines = [f"👁️ <b>Your Contributions for {event.description or 'Event'}</b>", ""]

        for i, contrib in enumerate(contributions, 1):
            type_display = {
                "idea": "💡 Idea",
                "hashtag": "🏷️ Hashtag",
                "memory": "📜 Memory",
            }.get(contrib.enrichment_type, contrib.enrichment_type)

            lines.append(f"{type_display}: {contrib.content}")

        lines.append("")
        lines.append("Use /ev to add more contributions.")

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Back", callback_data=f"ev:{event_id}:enrich"
                        )
                    ]
                ]
            ),
            parse_mode="HTML",
        )


async def handle_constraint_if_joins(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle constraint if joins sub-menu."""
    await _show_constraint_target(query, context, event_id, "if_joins")


async def handle_constraint_if_attends(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle constraint if attends sub-menu."""
    await _show_constraint_target(query, context, event_id, "if_attends")


async def handle_constraint_unless_joins(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle constraint unless joins sub-menu."""
    await _show_constraint_target(query, context, event_id, "unless_joins")


async def _show_constraint_target(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, constraint_type: str
) -> None:
    """Prompt user to select a target user for the constraint."""
    from db.models import EventParticipant, User
    from sqlalchemy import select

    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        result = await session.execute(
            select(EventParticipant, User)
            .join(
                User,
                EventParticipant.telegram_user_id == User.telegram_user_id,
                isouter=True,
            )
            .where(EventParticipant.event_id == event_id)
            .limit(20)
        )
        participants = result.all()

        if not participants:
            await query.edit_message_text(
                "❌ No participants found for this event. Join the event first!",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Back", callback_data=f"ev:{event_id}:constraint"
                            )
                        ]
                    ]
                ),
            )
            return

        keyboard = []
        for p, user in participants[:8]:
            user_display = f"User {p.telegram_user_id}"
            if user and user.username:
                user_display = f"@{user.username}"
            elif user and user.display_name:
                user_display = user.display_name

            keyboard.append(
                [
                    InlineKeyboardButton(
                        user_display,
                        callback_data=f"constraint_target_{event_id}_{p.telegram_user_id}_{constraint_type}",
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=f"ev:{event_id}:constraint",
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(keyboard)
    type_display = {
        "if_joins": "joins if target joins",
        "if_attends": "attends if target attends",
        "unless_joins": "won't join if target joins",
    }.get(constraint_type, constraint_type)

    await query.edit_message_text(
        f"🔗 Add Constraint: You {type_display}\n\nSelect a participant:",
        reply_markup=reply_markup,
    )


async def handle_availability_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle availability selection."""
    from bot.services import ParticipantService

    query = update.callback_query
    bot = context.bot

    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        from db.models import Event

        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        avail_link = f"https://t.me/{bot.username}?start=avail_{event_id}"

        await query.edit_message_text(
            "⏳ Set your availability:\n\n"
            "Click the button below to open availability selection in a private message.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📅 Set Availability in DM", url=avail_link)],
                    [
                        InlineKeyboardButton(
                            "⬅️ Back", callback_data=f"ev:{event_id}:constraint"
                        )
                    ],
                ]
            ),
        )


async def handle_my_constraints_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, event: Event
) -> None:
    """Handle viewing/removing my constraints."""
    from db.models import Constraint, EventParticipant, User
    from sqlalchemy import select

    query = update.callback_query
    user_id = update.effective_user.id

    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        result = await session.execute(
            select(Constraint)
            .where(
                Constraint.event_id == event_id,
                Constraint.user_id == user_id,
            )
            .order_by(Constraint.created_at.desc())
        )
        constraints = result.scalars().all()

        if not constraints:
            await query.edit_message_text(
                "ℹ️ You haven't added any constraints yet.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Back", callback_data=f"ev:{event_id}:constraint"
                            )
                        ]
                    ]
                ),
            )
            return

        lines = [f"👁️ <b>Your Constraints for {event.description or 'Event'}</b>", ""]

        for c in constraints:
            target_result = await session.execute(
                select(User).where(User.user_id == c.target_user_id)
            )
            target_user = target_result.scalar_one_or_none()
            target_display = f"User {c.target_user_id}"
            if target_user and target_user.username:
                target_display = f"@{target_user.username}"
            elif target_user and target_user.display_name:
                target_display = target_user.display_name

            type_display = {
                "if_joins": "joins if target joins",
                "if_attends": "attends if target attends",
                "unless_joins": "won't join if target joins",
            }.get(c.type, c.type)

            lines.append(f"• You {type_display}\n  Target: {target_display}")

        lines.append("")
        lines.append("Use constraint buttons above to add more.")

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Back", callback_data=f"ev:{event_id}:constraint"
                        )
                    ]
                ]
            ),
            parse_mode="HTML",
        )


async def handle_list_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle returning to event list."""
    from bot.handlers.menus import _show_my_events

    query = update.callback_query
    user_id = update.effective_user.id

    await _show_my_events(query, context, page=0)
