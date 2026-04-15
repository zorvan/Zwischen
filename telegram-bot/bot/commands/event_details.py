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
        await show_constraints(query, context, event_id)
    elif data and data.startswith("event_modify_menu_"):
        event_id = int(data.replace("event_modify_menu_", ""))
        await _show_modify_menu(query, context, event_id)
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
                "➕ Add Constraint", callback_data=f"event_constraint_add_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Event", callback_data=f"event_details_{event_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🔧 Manage Constraints", reply_markup=reply_markup)


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
                "⬅️ Back to Event", callback_data=f"event_details_{event_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🛠 Modify Event", reply_markup=reply_markup)


async def _show_availability_options(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show availability selection menu."""
    keyboard = [
        [
            InlineKeyboardButton(
                "⏰ Set Available Times", callback_data=f"avail_set_{event_id}"
            )
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"event_details_{event_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("⏳ Availability Options", reply_markup=reply_markup)


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
                "🔒 Manage Constraints",
                callback_data=f"event_constraints_menu_{event.event_id}",
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

    # Add DM links
    avail_link = build_start_link(bot_username, f"avail_{event.event_id}")
    if avail_link:
        keyboard.append(
            [InlineKeyboardButton("📥 Set Availability in DM", url=avail_link)]
        )

    return InlineKeyboardMarkup(keyboard)
