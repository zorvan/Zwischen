#!/usr/bin/env python3
"""DEPRECATED: Use /events instead."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import (
    User,
    Log as LogModel,
    Constraint as ConstraintModel,
)
from bot.common.rbac import check_event_visibility_and_get_event
from bot.common.event_presenters import format_event_details_message, format_user_display


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deprecated: redirects to /events."""
    if not update.message:
        return
    keyboard = [[InlineKeyboardButton("📋 View Events", callback_data="menu_my_events")]]
    await update.message.reply_text(
        "Use /events to view and manage your events.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kept for legacy callback patterns (event_details_, event_status_, etc.)."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data

    if data and data.startswith("event_details_"):
        event_id = int(data.replace("event_details_", ""))
        await _show_details(query, context, event_id)
    elif data and data.startswith("event_status_"):
        event_id = int(data.replace("event_status_", ""))
        await _show_status(query, context, event_id)
    elif data and data.startswith("event_logs_"):
        event_id = int(data.replace("event_logs_", ""))
        await _show_logs(query, event_id)
    elif data and data.startswith("event_constraints_"):
        event_id = int(data.replace("event_constraints_", ""))
        await _show_constraints(query, event_id)
    elif data and data.startswith("event_close_"):
        await query.edit_message_text("✅ Event details closed.")


async def _show_details(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    user_id = query.from_user.id if query.from_user else None
    chat_id = getattr(getattr(query, "message", None), "chat_id", None)
    chat_type = getattr(getattr(getattr(query, "message", None), "chat", None), "type", None)
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
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
        reply_markup = None
        if chat_type == "private":
            reply_markup = await _build_details_markup(event, user_id, bot_username, session)
        await query.edit_message_text(
            await format_event_details_message(event_id, event, logs, constraints, context.bot),
            reply_markup=reply_markup,
        )


async def _show_status(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    from bot.common.event_presenters import format_status_message
    from bot.services import ParticipantService

    user_id = query.from_user.id if query.from_user else None
    chat_id = getattr(getattr(query, "message", None), "chat_id", None)
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
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
        user_participant = None
        if user_id:
            participant_service = ParticipantService(session)
            user_participant = await participant_service.get_participant(event.event_id, user_id)
        bot_username = context.bot.username if context.bot else None
        keyboard = await _build_status_markup(event, user_id, bot_username, session)
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
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


async def _show_logs(query, event_id: int) -> None:
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
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
                user_info = " by " + format_user_display(
                    telegram_user_id=user.telegram_user_id,
                    username=getattr(user, "username", None),
                    display_name=getattr(user, "display_name", None),
                    include_link=False,
                )
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
        keyboard = [[InlineKeyboardButton("Back", callback_data=f"event_details_{event_id}")]]
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("✓ Updated")
            else:
                raise


async def _show_constraints(query, event_id: int) -> None:
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(select(ConstraintModel).where(ConstraintModel.event_id == event_id))
        constraints = result.scalars().all()
        if not constraints:
            await query.edit_message_text(
                f"📅 *Event {event_id} Availability & Constraints*\n\n" f"No constraints or availability set yet.",
                parse_mode="Markdown",
            )
            return
        user_ids = set()
        for c in constraints:
            user_ids.add(c.user_id)
            if c.target_user_id:
                user_ids.add(c.target_user_id)
        users = {}
        if user_ids:
            result = await session.execute(select(User).where(User.user_id.in_(user_ids)))
            for user in result.scalars().all():
                users[user.user_id] = user
        msg = f"🔗 *Event {event_id} Constraints*\n\n"
        for c in constraints:
            user = users.get(c.user_id)
            user_display = (
                format_user_display(
                    telegram_user_id=user.telegram_user_id if user else c.user_id,
                    username=user.username if user and getattr(user, "username", None) else None,
                    display_name=user.display_name if user and getattr(user, "display_name", None) else None,
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
                        telegram_user_id=target_user.telegram_user_id if target_user else c.target_user_id,
                        username=(
                            target_user.username if target_user and getattr(target_user, "username", None) else None
                        ),
                        display_name=(
                            target_user.display_name
                            if target_user and getattr(target_user, "display_name", None)
                            else None
                        ),
                        include_link=False,
                    )
                    if target_user
                    else f"User {c.target_user_id}"
                )
                msg += f"Join if {target_display} joins (confidence: {c.confidence})\n"
            else:
                msg += f"{c.type}\n"
        keyboard = [[InlineKeyboardButton("Back", callback_data=f"event_details_{event_id}")]]
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("✓ Updated")
            else:
                raise


async def _get_event_logs(session, event_id: int) -> list:
    result = await session.execute(select(LogModel).where(LogModel.event_id == event_id))
    return list(result.scalars().all())


async def _get_event_constraints(session, event_id: int) -> list:
    result = await session.execute(select(ConstraintModel).where(ConstraintModel.event_id == event_id))
    return list(result.scalars().all())


async def _get_event_log_count(session, event_id: int) -> int:
    from sqlalchemy import func
    from db.models import Log as LogModel

    result = await session.execute(select(func.count(LogModel.log_id)).where(LogModel.event_id == event_id))
    return result.scalar() or 0


async def _get_event_constraint_count(session, event_id: int) -> int:
    from sqlalchemy import func
    from db.models import Constraint as ConstraintModel

    result = await session.execute(
        select(func.count(ConstraintModel.constraint_id)).where(ConstraintModel.event_id == event_id)
    )
    return result.scalar() or 0


async def _build_status_markup(event, user_id, bot_username, session) -> list:
    keyboard = [[InlineKeyboardButton("📋 Details", callback_data=f"event_details_{event.event_id}")]]
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"event_status_{event.event_id}")])
    return keyboard


async def _build_details_markup(event, user_id, bot_username, session) -> InlineKeyboardMarkup:
    from bot.services import ParticipantService
    from db.models import ParticipantStatus

    user_joined = False
    user_confirmed = False
    if user_id is not None:
        participant_service = ParticipantService(session)
        try:
            participant = await participant_service.get_participant(event.event_id, user_id)
            if participant:
                user_joined = participant.status in [ParticipantStatus.joined, ParticipantStatus.confirmed]
                user_confirmed = participant.status == ParticipantStatus.confirmed
        except Exception:
            user_joined = False
    first_row = []
    if not user_joined:
        first_row = [InlineKeyboardButton("✅ Join", callback_data=f"event_join_{event.event_id}")]
    elif user_confirmed:
        first_row = [
            InlineKeyboardButton("✓ Confirmed", callback_data=f"event_confirm_{event.event_id}"),
            InlineKeyboardButton("↩️ Uncommit", callback_data=f"event_unconfirm_{event.event_id}"),
        ]
    else:
        first_row = [
            InlineKeyboardButton("✅ Confirm", callback_data=f"event_confirm_{event.event_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"event_cancel_{event.event_id}"),
        ]
    keyboard = [
        first_row,
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"event_cancel_{event.event_id}"),
            InlineKeyboardButton("🔒 Lock", callback_data=f"event_lock_{event.event_id}"),
        ],
        [InlineKeyboardButton("📝 View Logs", callback_data=f"event_logs_{event.event_id}")],
        [InlineKeyboardButton("🔒 Manage Constraints", callback_data=f"event_constraints_{event.event_id}")],
        [InlineKeyboardButton("🔄 Update", callback_data=f"event_details_{event.event_id}")],
        [InlineKeyboardButton("🔙 Close", callback_data=f"event_close_{event.event_id}")],
    ]
    if user_joined:
        keyboard.insert(4, [InlineKeyboardButton("🛠 Modify", callback_data=f"event_modify_{event.event_id}")])
    from bot.common.deeplinks import build_start_link

    avail_link = build_start_link(bot_username, f"avail_{event.event_id}")
    if avail_link:
        keyboard.append([InlineKeyboardButton("📥 Set Availability in DM", url=avail_link)])
    return InlineKeyboardMarkup(keyboard)
