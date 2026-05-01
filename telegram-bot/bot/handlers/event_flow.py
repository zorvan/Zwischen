#!/usr/bin/env python3
"""Event flow state machine handler."""
from datetime import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from db.models import Event, Log, ParticipantStatus
from db.connection import get_session
from db.users import get_or_create_user_id
from config.settings import settings
from bot.common.event_states import (
    STATE_EXPLANATIONS,
)
from bot.common.event_formatters import (
    format_location_type,
    format_scheduled_time,
)
from bot.common.scheduling import find_user_event_conflict
from bot.common.event_access import get_event_admin_telegram_id, get_event_organizer_telegram_id
from bot.common.rbac import check_event_visibility_and_get_event
from bot.common.participant_state_reconcile import reconcile_event_state_after_participant_change
from bot.services import ParticipantService, EventLifecycleService

logger = logging.getLogger(__name__)


async def handle_event_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main event flow handler - routes to state-specific handlers."""
    import asyncio

    query = update.callback_query

    if not query or not query.data:
        return

    try:
        await asyncio.wait_for(query.answer(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

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

    elif data.startswith("lock_approve_"):
        parts = data.split("_")
        if len(parts) >= 3:
            event_id = int(parts[-1])
            await handle_lock_approval(query, context, event_id, approved=True)

    elif data.startswith("lock_reject_"):
        parts = data.split("_")
        if len(parts) >= 3:
            event_id = int(parts[-1])
            await handle_lock_approval(query, context, event_id, approved=False)


async def handle_join(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Handle joining an event - transition to interested state."""
    telegram_user_id = query.from_user.id
    display_name = query.from_user.full_name
    username = query.from_user.username
    bot = context.bot

    logger.info(
        "[EVENT_FLOW] Join handler started | event_id=%s user_id=%s username=%s",
        event_id,
        telegram_user_id,
        username,
    )

    # Prevent interactions from group chats - all event interactions should be in DMs
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    if chat_type and chat_type != "private":
        await query.answer("Please interact with events in private DM with the bot.", show_alert=True)
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
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
        participant = await participant_service.get_participant(event_id, telegram_user_id)

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
                participant.joined_at = datetime.utcnow()
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
        # Bug 5 fix: Only count confirmed participants against capacity (not joined/interested)
        from sqlalchemy import func as sql_func
        from db.models import EventParticipant

        participant_result = await session.execute(
            select(sql_func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == ParticipantStatus.confirmed,
            )
        )
        current_count = participant_result.scalar() or 0
        target = event.target_participants or event.min_participants or 6

        if current_count >= target and not (
            participant
            and participant.status
            in [ParticipantStatus.joined, ParticipantStatus.confirmed, ParticipantStatus.cancelled]
        ):
            # Event at capacity — offer waitlist
            from bot.services import WaitlistService

            waitlist_service = WaitlistService(session, bot)

            # Check if already on waitlist
            existing_position = await waitlist_service.get_waitlist_position(event_id, telegram_user_id)
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
                            InlineKeyboardButton("✅ Join Waitlist", callback_data=f"waitlist_join_{event_id}"),
                            InlineKeyboardButton("❌ No Thanks", callback_data=f"event_close_{event_id}"),
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
        # Only non-organizer joins trigger the state change
        organizer_id = get_event_organizer_telegram_id(event)
        if telegram_user_id != organizer_id and event.state == "proposed":
            lifecycle_service = EventLifecycleService(bot, session)
            try:
                logger.info(
                    "[EVENT_FLOW] Triggering state transition | event_id=%s from=proposed to=interested",
                    event_id,
                )
                event, _ = await lifecycle_service.transition_with_lifecycle(
                    event_id=event_id,
                    target_state="interested",
                    actor_telegram_user_id=telegram_user_id,
                    source="callback",
                    reason="Non-organizer participant joined",
                    expected_version=event.version,
                )
                logger.info(
                    "[EVENT_FLOW] State transition successful | event_id=%s new_state=interested",
                    event_id,
                )
            except Exception as e:
                logger.error(
                    "[EVENT_FLOW] State transition failed | event_id=%s target_state=interested error=%s",
                    event_id,
                    str(e),
                    exc_info=True,
                )

        log = Log(
            event_id=event_id,
            user_id=user_id,
            action="join",
            metadata_dict={"timestamp": datetime.utcnow().isoformat()},
        )
        session.add(log)
        await session.commit()
        logger.info(
            "[EVENT_FLOW] Join committed to database | event_id=%s user_id=%s log_id=%s",
            event_id,
            telegram_user_id,
            log.log_id if hasattr(log, 'log_id') else 'pending',
        )

        # Refresh event to get latest state
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        # Get participant status to determine button text
        participant = await participant_service.get_participant(event_id, telegram_user_id)
        user_confirmed = participant and participant.status == ParticipantStatus.confirmed
        user_joined = participant and participant.status in [ParticipantStatus.joined, ParticipantStatus.confirmed]

        # Build comprehensive event menu with all actions (state-aware)
        # First row based on user status (mutually exclusive actions)
        if not user_joined:
            # User hasn't joined - show Join only
            first_row = [
                InlineKeyboardButton("Join", callback_data=f"event_join_{event_id}", style="success"),
            ]
            # Show Cancel + Lock row
            second_row = [
                InlineKeyboardButton("Cancel", callback_data=f"event_cancel_{event_id}", style="danger"),
                InlineKeyboardButton("Lock", callback_data=f"event_lock_{event_id}", style="primary"),
            ]
        elif user_confirmed:
            # User is confirmed - show Confirmed + Uncommit
            first_row = [
                InlineKeyboardButton("Confirmed", callback_data=f"event_confirm_{event_id}", style="success"),
                InlineKeyboardButton("Uncommit", callback_data=f"event_unconfirm_{event_id}", style="danger"),
            ]
            # Show Cancel + Lock row
            second_row = [
                InlineKeyboardButton("Cancel", callback_data=f"event_cancel_{event_id}", style="danger"),
                InlineKeyboardButton("Lock", callback_data=f"event_lock_{event_id}", style="primary"),
            ]
        else:
            # User joined but not confirmed - show Confirm + Cancel (no separate Cancel row needed)
            first_row = [
                InlineKeyboardButton("Confirm", callback_data=f"event_confirm_{event_id}", style="success"),
                InlineKeyboardButton("Cancel", callback_data=f"event_cancel_{event_id}", style="danger"),
            ]
            # Show Lock + Logs row
            second_row = [
                InlineKeyboardButton("Lock", callback_data=f"event_lock_{event_id}", style="primary"),
                InlineKeyboardButton("View Logs", callback_data=f"event_logs_{event_id}", style="primary"),
            ]

        keyboard = [
            first_row,
            second_row,
        ]

        # Add remaining rows for all users
        if not user_joined or user_confirmed:
            # Add Logs row if not already added
            keyboard.append([InlineKeyboardButton("View Logs", callback_data=f"event_logs_{event_id}", style="primary")])

        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        "Manage Constraints",
                        callback_data=f"event_constraints_{event_id}",
                        style="primary",
                    )
                ],
                [InlineKeyboardButton("Status", callback_data=f"event_status_{event_id}", style="primary")],
                [InlineKeyboardButton("Refresh", callback_data=f"event_details_{event_id}", style="primary")],
                [InlineKeyboardButton("Close", callback_data=f"event_close_{event_id}", style="danger")],
            ]
        )

        # Add Modify button for organizer/admin
        admin_id = get_event_admin_telegram_id(event)
        organizer_id = get_event_organizer_telegram_id(event)
        if telegram_user_id in [admin_id, organizer_id]:
            keyboard.insert(4, [InlineKeyboardButton("Modify", callback_data=f"event_modify_{event_id}", style="primary")])

        # Add DM links
        if bot.username:
            avail_link = f"https://t.me/{bot.username}?start=avail_{event_id}"
            keyboard.append([InlineKeyboardButton("📥 Set Availability in DM", url=avail_link)])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Build rich status message
        planning_prefs = event.planning_prefs if event.planning_prefs else {}
        time_str = format_scheduled_time(event.scheduled_time, include_flexible_note=False)
        location = format_location_type(planning_prefs.get("location_type"))

        # Get attendee counts from participant service
        interested_count = await participant_service.get_interested_count(event_id)
        confirmed_count = await participant_service.get_confirmed_count(event_id)

        await query.edit_message_text(
            f"✅ *You joined the event!*\n\n"
            f"📋 *Event #{event_id}*\n"
            f"Type: {event.event_type}\n"
            f"Time: {time_str}\n"
            f"Location: {location}\n"
            f"State: {event.state}\n\n"
            f"👥 *Participants:*\n"
            f"Interested: {interested_count}\n"
            f"Confirmed: {confirmed_count}\n"
            f"Minimum: {event.min_participants}\n"
            f"Capacity: {event.target_participants}\n\n"
            f"_The event is now gathering momentum!_\n"
            f"_Set your availability, add constraints, and engage with the group._",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )


async def handle_confirm(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
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
        await query.answer("Please interact with events in private DM with the bot.", show_alert=True)
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
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
        participant = await participant_service.get_participant(event_id, telegram_user_id)

        if not participant:
            await query.answer("❌ Please join first", show_alert=True)
            return
        elif participant.status == ParticipantStatus.confirmed:
            await query.answer("ℹ️ You've already confirmed", show_alert=True)
            return
        elif participant.status == ParticipantStatus.cancelled:
            await query.answer("❌ You cancelled - contact organizer to rejoin", show_alert=True)
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

        # Flush to persist the status change before counting confirmed participants.
        # Without this, get_confirmed_count() queries the DB before the update is visible,
        # causing the first confirmation to be missed and the event never transitions
        # from "proposed"/"interested" to "confirmed".
        await session.flush()

        # Check if we need to transition to confirmed state
        # Only non-organizer confirmations trigger the state change
        organizer_id = get_event_organizer_telegram_id(event)
        confirmed_count = await participant_service.get_confirmed_count(event_id)
        if telegram_user_id != organizer_id and event.state != "confirmed" and confirmed_count > 0:
            lifecycle_service = EventLifecycleService(bot, session)
            try:
                event, _ = await lifecycle_service.transition_with_lifecycle(
                    event_id=event_id,
                    target_state="confirmed",
                    actor_telegram_user_id=telegram_user_id,
                    source="callback",
                    reason="Non-organizer participant confirmed attendance",
                    expected_version=event.version,
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

        # Refresh event to get latest state
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        # Build comprehensive event menu with all actions
        keyboard = [
            # Primary actions
            [
                InlineKeyboardButton("Back", callback_data=f"event_back_{event_id}", style="danger"),
                InlineKeyboardButton("Exit", callback_data=f"event_cancel_{event_id}", style="danger"),
            ],
            # Event management
            [
                InlineKeyboardButton("Event Details", callback_data=f"event_details_{event_id}", style="primary"),
                InlineKeyboardButton("Status", callback_data=f"event_status_{event_id}", style="primary"),
            ],
            # Planning & constraints
            [
                InlineKeyboardButton("Set Availability", url=f"https://t.me/{bot.username}?start=avail_{event_id}"),
                InlineKeyboardButton("Constraints", callback_data=f"event_constraints_{event_id}", style="primary"),
            ],
            # Logs
            [
                InlineKeyboardButton("Logs", callback_data=f"event_logs_{event_id}", style="primary"),
                InlineKeyboardButton("Update", callback_data=f"event_details_{event_id}", style="primary"),
            ],
        ]

        # Add lock button for organizer/admin
        admin_id = get_event_admin_telegram_id(event)
        organizer_id = get_event_organizer_telegram_id(event)
        if telegram_user_id in [admin_id, organizer_id] and event.state == "confirmed":
            keyboard.append(
                [
                    InlineKeyboardButton("Lock Event", callback_data=f"event_lock_{event_id}", style="primary"),
                ]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Build rich status message
        planning_prefs = event.planning_prefs if event.planning_prefs else {}
        time_str = format_scheduled_time(event.scheduled_time, include_flexible_note=False)
        location = format_location_type(planning_prefs.get("location_type"))

        # Get attendee counts from participant service
        interested_count = await participant_service.get_interested_count(event_id)
        confirmed_count = await participant_service.get_confirmed_count(event_id)

        await query.edit_message_text(
            f"✅ *You confirmed to the event!*\n\n"
            f"📋 *Event #{event_id}*\n"
            f"Type: {event.event_type}\n"
            f"Time: {time_str}\n"
            f"Location: {location}\n"
            f"State: {event.state}\n\n"
            f"👥 *Participants:*\n"
            f"Interested: {interested_count}\n"
            f"Confirmed: {confirmed_count}\n"
            f"Minimum: {event.min_participants}\n"
            f"Capacity: {event.target_participants}\n\n"
            f"_Your confirmation helps the event reach critical mass!_\n"
            f"_You can go back before the event is locked._",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )


async def handle_back(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Revert personal confirmation to interested before lock (uncommit)."""
    telegram_user_id = query.from_user.id

    # Prevent interactions from group chats - all event interactions should be in DMs
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    if chat_type and chat_type != "private":
        await query.answer("Please interact with events in private DM with the bot.", show_alert=True)
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
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
        participant = await participant_service.get_participant(event_id, telegram_user_id)

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


async def handle_cancel(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
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
        await query.answer("Please interact with events in private DM with the bot.", show_alert=True)
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
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
            await query.edit_message_text("❌ Event is locked. Cannot cancel attendance.")
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
            metadata_dict={"timestamp": datetime.utcnow().isoformat()},
        )
        session.add(log)
        await session.commit()

        await query.edit_message_text(
            f"❌ *Attendance cancelled for event {event_id}!*\n\n"
            f"State: {event.state}\n"
            f"Meaning: {STATE_EXPLANATIONS.get(event.state, 'Unknown state')}"
        )


async def _execute_lock(bot, session, event, event_id, telegram_user_id, query):
    """Execute the lock transition."""
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

    participant_service = ParticipantService(session)
    await participant_service.finalize_commitments(event_id)

    await query.edit_message_text(
        f"🔒 *Event {event_id} locked!*\n\n"
        f"State: locked\n"
        f"Meaning: {STATE_EXPLANATIONS['locked']}\n"
        f"Locked at: {event.locked_at}"
    )


async def _request_lock_approval(bot, session, event, group, event_id, requester_id, query):
    """Send a lock approval request to the organizer."""
    organizer_id = get_event_organizer_telegram_id(event)
    requester_user = await bot.get_user_profile_ids(requester_id)
    requester_name = requester_user[0].first_name if requester_user else f"User {requester_id}"

    # Send approval request to organizer in group chat
    group_chat_id = None
    if group and hasattr(group, "telegram_group_id"):
        group_chat_id = group.telegram_group_id
    elif hasattr(event, "group") and event.group and hasattr(event.group, "telegram_group_id"):
        group_chat_id = event.group.telegram_group_id

    if not group_chat_id:
        await query.edit_message_text("❌ Could not determine group chat for approval request.")
        return

    approval_message = (
        f"🔒 *Lock Request for Event {event_id}*\n\n"
        f"*Requested by:* @{requester_id} ({requester_name})\n"
        f"*Event:* {event.event_type}\n"
        f"*State:* {event.state}\n\n"
        f"Does the organizer approve locking this event?"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("Approve Lock", callback_data=f"lock_approve_{event_id}", style="success"),
                InlineKeyboardButton("Reject", callback_data=f"lock_reject_{event_id}", style="danger"),
            ]
        ]
    )

    try:
        approval_msg = await bot.send_message(
            chat_id=group_chat_id,
            text=approval_message,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Failed to send lock approval request: {e}")
        await query.edit_message_text(f"❌ Failed to send approval request: {str(e)}")
        return

    await query.edit_message_text(
        f"📩 Lock request sent to organizer for approval.\n"
        f"Event ID: {event_id}\n\n"
        f"Waiting for organizer decision..."
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
        await query.answer("Please interact with events in private DM with the bot.", show_alert=True)
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
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

        # Check if user is confirmed
        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(event_id, telegram_user_id)
        if not participant or participant.status != ParticipantStatus.confirmed:
            await query.edit_message_text("❌ You must be confirmed to lock this event.")
            return

        # Check minimum attendance
        confirmed_count = await participant_service.get_confirmed_count(event_id)
        min_required = event.min_participants or 2
        if confirmed_count < min_required:
            await query.edit_message_text(
                f"❌ Cannot lock event {event_id}.\n"
                f"Only {confirmed_count} confirmed, need {min_required}."
            )
            return

        organizer_id = get_event_organizer_telegram_id(event)

        # Organizer can lock directly
        if telegram_user_id == organizer_id:
            await _execute_lock(bot, session, event, event_id, telegram_user_id, query)
            return

        # Non-organizer lock request - send approval request to organizer
        await _request_lock_approval(bot, session, event, group, event_id, telegram_user_id, query)


async def handle_lock_approval(query, context: ContextTypes.DEFAULT_TYPE, event_id: int, approved: bool) -> None:
    """Handle lock approval/rejection callbacks."""
    telegram_user_id = query.from_user.id
    bot = context.bot

    # Only organizer can approve/reject
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        event_result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = event_result.scalar_one_or_none()

        if not event:
            await query.answer("❌ Event not found.", show_alert=True)
            return

        organizer_id = get_event_organizer_telegram_id(event)
        if telegram_user_id != organizer_id:
            await query.answer("❌ Only the organizer can approve/reject lock requests.", show_alert=True)
            return

        if event.state != "confirmed":
            await query.answer("❌ Event is no longer in confirmed state.", show_alert=True)
            return

        if approved:
            await _execute_lock(bot, session, event, event_id, telegram_user_id, query)
        else:
            await query.edit_message_text(
                f"❌ Lock request for event {event_id} has been rejected by the organizer."
            )


async def show_event_details(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
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
