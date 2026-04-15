#!/usr/bin/env python3
from __future__ import annotations

"""Event details command handler."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from db.models import Event, User, ParticipantStatus
from bot.common.rbac import check_event_visibility_and_get_event
from db.connection import get_session
from config.settings import settings
from bot.common.deeplinks import build_start_link
from bot.common.event_presenters import (
    format_event_details_message,
    format_user_display,
)


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /event_details command - show detailed event information."""
    if not update.message:
        return
    if not settings.db_url:
        await update.message.reply_text("❌ Database configuration is unavailable.")
        return

    user = update.effective_user
    if not user:
        return

    event_id_str = context.args[0] if context.args else None

    if not event_id_str:
        async with get_session(settings.db_url) as session:
            result = await session.execute(
                select(Event).order_by(Event.created_at.desc()).limit(10)
            )
            events = result.scalars().all()

            if not events:
                await update.message.reply_text(
                    "No events found. Use /event_details <event_id> to view event details."
                )
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
                        callback_data=f"event_details_{event.event_id}",
                    )
                ]
                for event in events
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(event_list, reply_markup=reply_markup)
        return

    try:
        event_id = int(event_id_str)
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return

    async with get_session(settings.db_url) as session:
        user_id = user.id if user else None
        chat_id = update.effective_chat.id if update.effective_chat else None
        chat_type = update.effective_chat.type if update.effective_chat else None
        (
            is_visible,
            event,
            group,
            error_msg,
        ) = await check_event_visibility_and_get_event(
            session,
            event_id,
            user_id,
            telegram_chat_id=chat_id,
            bot=context.bot,
        )

        if not is_visible:
            await update.message.reply_text(f"❌ {error_msg or 'Event not found.'}")
            return

        logs = await _get_event_logs(session, event_id)
        constraints = await _get_event_constraints(session, event_id)

        bot_username = context.bot.username if context.bot else None
        user_id = user.id if user else None
        # Don't show interactive keyboard in group chats - only in private chats
        reply_markup = None
        if chat_type == "private":
            reply_markup = await build_event_details_action_markup(
                event, user_id, bot_username, session
            )

        await update.message.reply_text(
            await format_event_details_message(
                event_id, event, logs, constraints, context.bot
            ),
            reply_markup=reply_markup,
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for event detail actions."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data

    if data and data.startswith("event_details_"):
        event_id = int(data.replace("event_details_", ""))
        await show_details(query, context, event_id)
    elif data and data.startswith("event_status_"):
        event_id = int(data.replace("event_status_", ""))
        await show_status(query, context, event_id)
    elif data and data.startswith("event_logs_"):
        event_id = int(data.replace("event_logs_", ""))
        await show_logs(query, event_id)
    elif data and data.startswith("event_constraints_menu_"):
        event_id = int(data.replace("event_constraints_menu_", ""))
        await _show_constraints_menu(query, context, event_id)
    elif data and data.startswith("event_constraints_"):
        event_id = int(data.replace("event_constraints_", ""))
        await _show_constraints_menu(query, context, event_id)
    elif data and data.startswith("constraint_add_"):
        parts = data.split("_")
        if len(parts) >= 5:
            constraint_type = f"{parts[2]}_{parts[3]}"
            event_id = int(parts[4])
            await _prompt_constraint_target(query, context, event_id, constraint_type)
    elif data and data.startswith("constraint_target_"):
        parts = data.split("_")
        if len(parts) >= 6:
            event_id = int(parts[2])
            target_user_id = int(parts[3])
            constraint_type = f"{parts[4]}_{parts[5]}"
            await _confirm_constraint(
                query, context, event_id, target_user_id, constraint_type
            )
    elif data and data.startswith("avail_slot_"):
        parts = data.split("_")
        if len(parts) >= 4:
            event_id = int(parts[2])
            slot_index = int(parts[3])
            await _handle_availability_slot(query, context, event_id, slot_index)
    elif data and data.startswith("avail_confirm_"):
        event_id = int(data.replace("avail_confirm_", ""))
        await _save_availability(query, context, event_id)
    elif data and data.startswith("event_modify_menu_"):
        event_id = int(data.replace("event_modify_menu_", ""))
        await _show_modify_menu(query, context, event_id)
    elif data and data.startswith("event_change_time_"):
        event_id = int(data.replace("event_change_time_", ""))
        await _prompt_change_time(query, context, event_id)
    elif data and data.startswith("event_edit_"):
        event_id = int(data.replace("event_edit_", ""))
        context.user_data["pending_event_edit"] = {"event_id": event_id}
        await query.edit_message_text(
            "✏️ *Edit Event Details*\n\n"
            "Please type the changes you'd like to make. Examples:\n"
            "- Change description to beach party\n"
            "- Set duration to 90 minutes\n"
            "- Increase minimum to 5\n"
            "- Set location to outdoor\n\n"
            "Type 'cancel' to abort.",
            parse_mode="Markdown",
        )
    elif data and data.startswith("avail_add_"):
        event_id = int(data.replace("avail_add_", ""))
        await _show_availability_slots(query, context, event_id)
    elif data and data.startswith("avail_"):
        event_id = int(data.replace("avail_", ""))
        await _show_availability_options(query, context, event_id)
    elif data and data.startswith("event_close_"):
        await query.edit_message_text("✅ Event details closed.")


async def show_details(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show full event details for callback-based navigation."""
    user_id = query.from_user.id if query.from_user else None
    chat_id = getattr(getattr(query, "message", None), "chat_id", None)
    chat_type = getattr(getattr(query, "message", None), "chat", None)
    if chat_type:
        chat_type = getattr(chat_type, "type", None)
    async with get_session(settings.db_url) as session:
        (
            is_visible,
            event,
            group,
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

        logs = await _get_event_logs(session, event_id)
        constraints = await _get_event_constraints(session, event_id)

        bot_username = context.bot.username if context.bot else None
        user_id = query.from_user.id if query.from_user else None
        # Don't show interactive keyboard in group chats - only in private chats
        reply_markup = None
        if chat_type == "private":
            reply_markup = await build_event_details_action_markup(
                event, user_id, bot_username, session
            )

        try:
            await query.edit_message_text(
                await format_event_details_message(
                    event_id, event, logs, constraints, context.bot
                ),
                reply_markup=reply_markup,
            )
        except Exception as e:
            if "Message is not modified" in str(e):
                # Message content hasn't changed, just answer the callback
                await query.answer("✓ Updated")
            else:
                raise


async def show_status(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Show event status for callback-based navigation."""
    user_id = query.from_user.id if query.from_user else None
    chat_id = getattr(getattr(query, "message", None), "chat_id", None)
    async with get_session(settings.db_url) as session:
        (
            is_visible,
            event,
            group,
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

        log_count = await _get_event_log_count(session, event_id)
        constraint_count = await _get_event_constraint_count(session, event_id)

        user_id = query.from_user.id if query.from_user else None
        bot_username = context.bot.username if context.bot else None

        # Get user's participant record for mutual dependence visibility
        user_participant = None
        if user_id:
            from bot.services import ParticipantService

            participant_service = ParticipantService(session)
            user_participant = await participant_service.get_participant(
                event.event_id, user_id
            )

        keyboard = await build_status_action_markup(
            event, user_id, bot_username, session
        )
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        from bot.common.event_presenters import format_status_message

        try:
            await query.edit_message_text(
                await format_status_message(
                    event_id,
                    event,
                    log_count,
                    constraint_count,
                    context.bot,
                    user_participant=user_participant,
                    session=session,
                ),
                reply_markup=reply_markup,
            )
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("✓ Updated")
            else:
                raise


async def _get_event_log_count(session, event_id: int) -> int:
    """Get event log count."""
    from sqlalchemy import func
    from db.models import Log as LogModel

    result = await session.execute(
        select(func.count(LogModel.log_id)).where(LogModel.event_id == event_id)
    )
    return result.scalar() or 0


async def _get_event_constraint_count(session, event_id: int) -> int:
    """Get event constraint count."""
    from sqlalchemy import func
    from db.models import Constraint as ConstraintModel

    result = await session.execute(
        select(func.count(ConstraintModel.constraint_id)).where(
            ConstraintModel.event_id == event_id
        )
    )
    return result.scalar() or 0


async def build_status_action_markup(
    event: Event, user_id: int | None, bot_username: str | None, session
) -> list[list[InlineKeyboardButton]]:
    """Build action keyboard for status view."""
    keyboard = [
        [
            InlineKeyboardButton(
                "📋 Details", callback_data=f"event_details_{event.event_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh", callback_data=f"event_status_{event.event_id}"
            )
        ],
    ]
    return keyboard


async def show_logs(query, event_id: int) -> None:
    """Show event logs."""
    from db.models import Log as LogModel

    async with get_session(settings.db_url) as session:
        result = await session.execute(
            select(LogModel, User)
            .join(User, LogModel.user_id == User.user_id, isouter=True)
            .where(LogModel.event_id == event_id)
            .order_by(LogModel.timestamp.desc())
        )
        rows = result.all()

        if not rows:
            await query.edit_message_text(f"ℹ️ Event {event_id} has no logs yet.")

            return

        msg = f"📝 *Event {event_id} Logs*\n\n"
        for log, user in rows[:10]:
            user_info = ""
            if user:
                user_display = format_user_display(
                    telegram_user_id=user.telegram_user_id,
                    username=getattr(user, "username", None),
                    display_name=getattr(user, "display_name", None),
                    include_link=False,
                )
                user_info = f" by {user_display}"

            # Map action to readable text
            action_text = {
                "join": "joined",
                "confirm": "confirmed",
                "cancel": "cancelled",
                "organize_event": "created the event",
                "suggest_time": "suggested a time",
                "nudge": "was nudged",
                "constraint_update": "updated constraints",
            }.get(log.action, log.action)

            msg += f"- {action_text}{user_info} at {log.timestamp}\n"

        if len(rows) > 10:
            msg += f"\n... and {len(rows) - 10} more logs"

        keyboard = [
            [InlineKeyboardButton("Back", callback_data=f"event_details_{event_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(msg, reply_markup=reply_markup)
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("✓ Updated")
            else:
                raise


async def show_constraints(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show event constraints."""
    from db.models import Constraint as ConstraintModel

    async with get_session(settings.db_url) as session:
        result = await session.execute(
            select(ConstraintModel).where(ConstraintModel.event_id == event_id)
        )
        constraints = result.scalars().all()

        if not constraints:
            await query.edit_message_text(f"ℹ️ Event {event_id} has no constraints.")

            return

        # Fetch all relevant users at once for display names
        user_ids = set()
        for c in constraints:
            user_ids.add(c.user_id)
            if c.target_user_id:
                user_ids.add(c.target_user_id)

        users = {}
        if user_ids:
            result = await session.execute(
                select(User).where(User.user_id.in_(user_ids))
            )
            for user in result.scalars().all():
                users[user.user_id] = user

        msg = f"🔗 *Event {event_id} Constraints*\n\n"
        for c in constraints:
            user = users.get(c.user_id)
            user_display = (
                format_user_display(
                    telegram_user_id=user.telegram_user_id if user else c.user_id,
                    username=user.username
                    if user and getattr(user, "username", None)
                    else None,
                    display_name=user.display_name
                    if user and getattr(user, "display_name", None)
                    else None,
                    include_link=False,
                )
                if user
                else f"User {c.user_id}"
            )

            msg += f"- {user_display}: "
            if c.target_user_id:
                target_user = users.get(c.target_user_id)
                target_display = (
                    format_user_display(
                        telegram_user_id=target_user.telegram_user_id
                        if target_user
                        else c.target_user_id,
                        username=target_user.username
                        if target_user and getattr(target_user, "username", None)
                        else None,
                        display_name=target_user.display_name
                        if target_user and getattr(target_user, "display_name", None)
                        else None,
                        include_link=False,
                    )
                    if target_user
                    else f"User {c.target_user_id}"
                )
                msg += f"Join if {target_display} joins (confidence: {c.confidence})\n"
            else:
                msg += f"{c.type}\n"

        keyboard = [
            [InlineKeyboardButton("Back", callback_data=f"event_details_{event_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(msg, reply_markup=reply_markup)
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("✓ Updated")
            else:
                raise


async def _get_event_logs(session, event_id: int) -> list:
    """Get event logs."""
    from db.models import Log as LogModel

    result = await session.execute(
        select(LogModel).where(LogModel.event_id == event_id)
    )
    return result.scalars().all()


async def _get_event_constraints(session, event_id: int) -> list:
    """Get event constraints."""
    from db.models import Constraint as ConstraintModel

    result = await session.execute(
        select(ConstraintModel).where(ConstraintModel.event_id == event_id)
    )
    return result.scalars().all()


async def _show_constraints_menu(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show constraints management menu."""
    keyboard = [
        [
            InlineKeyboardButton(
                "🔗 If Joins", callback_data=f"constraint_add_if_joins_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ If Attends", callback_data=f"constraint_add_if_attends_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🚫 Unless Joins",
                callback_data=f"constraint_add_unless_joins_{event_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Event", callback_data=f"event_details_{event_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🔗 Add Constraint Type:", reply_markup=reply_markup)


async def _show_modify_menu(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show event modification menu."""
    keyboard = [
        [
            InlineKeyboardButton(
                "✏️ Edit Event Details", callback_data=f"event_edit_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📅 Change Time", callback_data=f"event_change_time_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔗 Manage Constraints",
                callback_data=f"event_constraints_menu_{event_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Event", callback_data=f"event_details_{event_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🛠 Modify Event", reply_markup=reply_markup)


async def _prompt_constraint_target(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, constraint_type: str
) -> None:
    """Prompt user to select a target user for the constraint."""
    from db.models import EventParticipant, User
    from sqlalchemy import select

    async with get_session(settings.db_url) as session:
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
                "❌ No participants found for this event. Join the event first!"
            )
            return

        keyboard = []
        for p, user in participants[:8]:  # Show up to 8 participants
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
                    "⬅️ Back to Constraints",
                    callback_data=f"event_constraints_menu_{event_id}",
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


async def _confirm_constraint(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    target_user_id: int,
    constraint_type: str,
) -> None:
    """Confirm and save constraint."""
    from db.models import Constraint, Event, EventParticipant, User
    from db.users import get_or_create_user_id
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    async with get_session(settings.db_url) as session:
        # Check if user is an attendee
        result = await session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == query.from_user.id,
            )
        )
        participant = result.scalar_one_or_none()

        if not participant:
            await query.edit_message_text(
                "❌ Only event participants can add constraints. Join the event first!"
            )
            return

        # Get or create source user ID
        source_user_id = await get_or_create_user_id(
            session,
            telegram_user_id=query.from_user.id,
            display_name=query.from_user.full_name,
            username=query.from_user.username,
        )

        # Check if constraint already exists
        existing = await session.execute(
            select(Constraint).where(
                Constraint.event_id == event_id,
                Constraint.user_id == source_user_id,
                Constraint.target_user_id == target_user_id,
                Constraint.type == constraint_type,
            )
        )

        if existing.scalar_one_or_none():
            await query.edit_message_text("❌ This constraint already exists!")
            return

        # Create constraint
        constraint = Constraint(
            user_id=source_user_id,
            target_user_id=target_user_id,
            event_id=event_id,
            type=constraint_type,
            confidence=0.8,
        )
        session.add(constraint)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await query.edit_message_text(
                "❌ Failed to save constraint. It may already exist."
            )
            return

        # Get target user display
        target_result = await session.execute(
            select(User).where(User.user_id == target_user_id)
        )
        target_user = target_result.scalar_one_or_none()
        target_display = f"User {target_user_id}"
        if target_user and target_user.username:
            target_display = f"@{target_user.username}"
        elif target_user and target_user.display_name:
            target_display = target_user.display_name

        type_display = {
            "if_joins": "joins if target joins",
            "if_attends": "attends if target attends",
            "unless_joins": "won't join if target joins",
        }.get(constraint_type, constraint_type)

        await query.edit_message_text(
            f"✅ Constraint added!\n\nYou {type_display}\nTarget: {target_display}"
        )


async def _show_availability_options(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show availability selection menu."""
    keyboard = [
        [
            InlineKeyboardButton(
                "📅 Add Availability", callback_data=f"avail_add_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Event", callback_data=f"event_details_{event_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("⏳ Availability Options", reply_markup=reply_markup)


async def _show_availability_slots(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show availability time slot buttons."""
    from bot.services import ParticipantService
    from db.models import Event, EventParticipant, Constraint
    from sqlalchemy import select
    from datetime import datetime, timedelta

    async with get_session(settings.db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Generate time slots around the event time or default to next 7 days
        keyboard = []
        base_time = event.scheduled_time or datetime.utcnow()

        # Generate slots: -2 hours, -1 hour, same time, +1 hour, +2 hours on same day
        time_slots = []
        for offset_hours in [-2, -1, 0, 1, 2]:
            slot_time = base_time + timedelta(hours=offset_hours)
            time_slots.append(slot_time)

        # Also add next 3 days at base time
        for offset_days in [1, 2, 3]:
            slot_time = base_time + timedelta(days=offset_days)
            time_slots.append(slot_time)

        for i, slot in enumerate(time_slots[:9]):  # Limit to 9 slots
            slot_str = slot.strftime("%Y-%m-%d %H:%M")
            callback_data = f"avail_slot_{event_id}_{i}"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📅 {slot.strftime('%b %d, %H:%M')}",
                        callback_data=callback_data,
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "⬅️ Back to Availability", callback_data=f"avail_{event_id}"
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "⏳ Select an available time slot:\n\n"
        "After selecting, use /constraints <event_id> availability <slot> to mark it.",
        reply_markup=reply_markup,
    )


async def _handle_availability_slot(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, slot_index: int
) -> None:
    """Handle availability slot selection."""
    from db.models import Event
    from sqlalchemy import select
    from datetime import datetime, timedelta

    async with get_session(settings.db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            await query.answer("❌ Event not found")
            return

        base_time = event.scheduled_time or datetime.utcnow()
        time_slots = []

        # Generate slots: -2 hours, -1 hour, same time, +1 hour, +2 hours on same day
        for offset_hours in [-2, -1, 0, 1, 2]:
            slot_time = base_time + timedelta(hours=offset_hours)
            time_slots.append(slot_time)

        # Also add next 3 days at base time
        for offset_days in [1, 2, 3]:
            slot_time = base_time + timedelta(days=offset_days)
            time_slots.append(slot_time)

        if slot_index >= len(time_slots):
            await query.answer("❌ Invalid slot selection")
            return

        selected_slot = time_slots[slot_index]
        slot_str = selected_slot.strftime("%Y-%m-%d %H:%M")

        # Store pending availability in context
        context.user_data["pending_availability"] = {
            "event_id": event_id,
            "slot": slot_str,
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Confirm", callback_data=f"avail_confirm_{event_id}"
                ),
                InlineKeyboardButton("❌ Cancel", callback_data=f"avail_{event_id}"),
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⏳ You selected: {slot_str}\n\n"
            "This will add the slot to your availability.\n"
            "Continue?",
            reply_markup=reply_markup,
        )


async def _save_availability(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Save selected availability slot."""
    pending = context.user_data.get("pending_availability")
    if not pending or pending.get("event_id") != event_id:
        await query.edit_message_text("❌ No pending availability selection found.")
        return

    slot_str = pending.get("slot")
    context.user_data.pop("pending_availability", None)

    from db.models import Constraint, Event, EventParticipant
    from db.users import get_or_create_user_id
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    async with get_session(settings.db_url) as session:
        # Get or create source user ID
        source_user_id = await get_or_create_user_id(
            session,
            telegram_user_id=query.from_user.id,
            display_name=query.from_user.full_name,
            username=query.from_user.username,
        )

        # Add the availability constraint
        constraint = Constraint(
            user_id=source_user_id,
            target_user_id=None,
            event_id=event_id,
            type=f"available:{slot_str}",
            confidence=1.0,
        )
        session.add(constraint)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await query.edit_message_text(
                "❌ Failed to save availability. It may already exist."
            )
            return

    await query.edit_message_text(
        f"✅ Availability saved!\n\n"
        f"Slot: {slot_str}\n\n"
        f"Use /suggest_time {event_id} to see suggested times."
    )


async def build_event_details_action_markup(
    event: Event, user_id: int | None, bot_username: str | None, session
) -> InlineKeyboardMarkup:
    """Build standard action keyboard for event details view."""
    # Check if user has joined using ParticipantService
    user_joined = False
    user_confirmed = False
    if user_id is not None:
        from bot.services import ParticipantService

        participant_service = ParticipantService(session)
        try:
            participant = await participant_service.get_participant(
                event.event_id, user_id
            )
            if participant:
                user_joined = participant.status in [
                    ParticipantStatus.joined,
                    ParticipantStatus.confirmed,
                ]
                user_confirmed = participant.status == ParticipantStatus.confirmed
        except Exception:
            user_joined = False

    # Build first row based on user status (mutually exclusive actions)
    first_row = []
    if not user_joined:
        # User hasn't joined - show Join button only
        first_row = [
            InlineKeyboardButton(
                "✅ Join", callback_data=f"event_join_{event.event_id}"
            ),
        ]
    elif user_confirmed:
        # User is confirmed - show disabled confirm + Uncommit
        first_row = [
            InlineKeyboardButton(
                "✓ Confirmed", callback_data=f"event_confirm_{event.event_id}"
            ),
            InlineKeyboardButton(
                "↩️ Uncommit", callback_data=f"event_unconfirm_{event.event_id}"
            ),
        ]
    else:
        # User joined but not confirmed - show Confirm + Cancel (no Uncommit needed)
        first_row = [
            InlineKeyboardButton(
                "✅ Confirm", callback_data=f"event_confirm_{event.event_id}"
            ),
            InlineKeyboardButton(
                "❌ Cancel", callback_data=f"event_cancel_{event.event_id}"
            ),
        ]

    # Common action rows
    keyboard = [
        first_row,
        [
            InlineKeyboardButton(
                "❌ Cancel", callback_data=f"event_cancel_{event.event_id}"
            ),
            InlineKeyboardButton(
                "🔒 Lock", callback_data=f"event_lock_{event.event_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "📝 View Logs", callback_data=f"event_logs_{event.event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Update", callback_data=f"event_details_{event.event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Close", callback_data=f"event_close_{event.event_id}"
            )
        ],
    ]

    # Add Modify button for joined participants
    if user_joined:
        keyboard.insert(
            4,
            [
                InlineKeyboardButton(
                    "🛠 Modify", callback_data=f"event_modify_menu_{event.event_id}"
                )
            ],
        )

    return InlineKeyboardMarkup(keyboard)


async def _prompt_change_time(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Prompt user to provide time change instruction."""
    from db.models import Event
    from sqlalchemy import select

    async with get_session(settings.db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

    # Store pending time change in context
    context.user_data["pending_time_change"] = {
        "event_id": event_id,
    }

    keyboard = [
        [
            InlineKeyboardButton(
                "⬅️ Back to Modify Menu",
                callback_data=f"event_modify_menu_{event_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Event", callback_data=f"event_details_{event_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📅 *Change Event Time*\n\n"
        "Please type the new time for the event. Examples:\n"
        "- March 8, 2026 at 18:00\n"
        "- Next Friday at 7pm\n"
        "- June 15, 2026 14:30\n\n"
        "Type 'cancel' to abort.",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )
