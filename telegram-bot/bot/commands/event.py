#!/usr/bin/env python3
"""Unified event command - single entry point for all event operations."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from db.models import Event
from bot.common.rbac import check_event_visibility_and_get_event
from db.connection import get_session
from config.settings import settings
from bot.common.event_presenters import format_status_message


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /event command - unified event operations."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    event_id_raw = args[0] if args else None
    mode = args[1] if len(args) > 1 else None

    if not event_id_raw:
        async with get_session(settings.db_url) as session:
            result = await session.execute(
                select(Event).order_by(Event.created_at.desc()).limit(10)
            )
            events = result.scalars().all()

            if not events:
                await update.message.reply_text(
                    "No events found. Use /event <event_id> to view an event."
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
                        callback_data=f"event_view_{event.event_id}",
                    )
                ]
                for event in events
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await update.message.reply_text(event_list, reply_markup=reply_markup)
            except Exception:
                pass
            return

    try:
        event_id = int(event_id_raw)
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return

    # Route to mode handlers
    if mode == "details":
        await _show_details(update, event_id, context)
    elif mode == "status":
        await _show_status(update, event_id, context)
    elif mode == "availability":
        await _show_availability(update, event_id, context)
    elif mode == "constraints":
        await _show_constraints(update, event_id, context)
    elif mode == "suggest":
        await _show_suggest_time(update, event_id, context)
    elif mode == "edit":
        # Edit requires additional text - check if provided
        edit_text = " ".join(args[2:]).strip() if len(args) > 2 else None
        if edit_text:
            await _handle_edit(update, event_id, edit_text, context)
        else:
            await _show_edit_menu(update, event_id, context)
    else:
        # Default: show main view with tabs
        await _show_main_view(update, event_id, context)


async def _show_main_view(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show event main view with tab selection."""
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else None

        (
            is_visible,
            event,
            group,
            error_msg,
        ) = await check_event_visibility_and_get_event(
            session, event_id, user_id, telegram_chat_id=chat_id, bot=context.bot
        )

        if not is_visible:
            try:
                await update.message.reply_text(f"❌ {error_msg or 'Event not found.'}")
            except Exception:
                pass
            return

        from bot.services import ParticipantService
        from sqlalchemy.ext.asyncio import AsyncSession

        participant_service = ParticipantService(session)  # type: ignore
        participant = await participant_service.get_participant(event_id, user_id)
        user_status = participant.status if participant else None

        log_count = await _get_log_count(session, event_id)
        constraint_count = await _get_constraint_count(session, event_id)

        status_msg = await format_status_message(
            event_id,
            event,
            log_count,
            constraint_count,
            context.bot,
            user_participant=participant,
            session=session,  # type: ignore
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "📝 Details", callback_data=f"event_tab_{event_id}_details"
                ),
                InlineKeyboardButton(
                    "📊 Status", callback_data=f"event_tab_{event_id}_status"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔗 Constraints", callback_data=f"event_tab_{event_id}_constraints"
                ),
                InlineKeyboardButton(
                    "⏱ Suggest Time", callback_data=f"event_tab_{event_id}_suggest"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🛠 Edit", callback_data=f"event_tab_{event_id}_edit"
                ),
            ],
        ]

        try:
            await update.message.reply_text(
                status_msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception:
            try:
                await update.message.reply_text(
                    status_msg.replace("*", ""),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception:
                pass


async def _show_details(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show event details tab."""
    from bot.commands.event_details import handle as details_handle

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": update.message,
            "effective_user": update.effective_user,
            "effective_chat": update.effective_chat,
        },
    )()

    context.args = [str(event_id)]
    await details_handle(fake_update, context)


async def _show_status(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show event status tab."""
    from bot.commands.status import handle as status_handle

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": update.message,
            "effective_user": update.effective_user,
            "effective_chat": update.effective_chat,
        },
    )()

    context.args = [str(event_id)]
    await status_handle(fake_update, context)


async def _show_availability(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show availability management tab."""
    from bot.commands.constraints import handle as constraints_handle

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": update.message,
            "effective_user": update.effective_user,
            "effective_chat": update.effective_chat,
        },
    )()

    context.args = [str(event_id), "availability"]
    await constraints_handle(fake_update, context)


async def _show_constraints(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show constraints management tab."""
    from bot.commands.constraints import handle as constraints_handle

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": update.message,
            "effective_user": update.effective_user,
            "effective_chat": update.effective_chat,
        },
    )()

    context.args = [str(event_id), "view"]
    await constraints_handle(fake_update, context)


async def _show_suggest_time(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show suggest time tab."""
    from bot.commands.suggest_time import handle as suggest_handle

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": update.message,
            "effective_user": update.effective_user,
            "effective_chat": update.effective_chat,
        },
    )()

    context.args = [str(event_id)]
    await suggest_handle(fake_update, context)


async def _show_edit_menu(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show edit action selection menu."""
    from bot.commands.modify_event import handle as modify_handle

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": update.message,
            "effective_user": update.effective_user,
            "effective_chat": update.effective_chat,
        },
    )()

    context.args = [
        str(event_id),
        "What would you like to change? (e.g., change time to Friday 7pm)",
    ]
    await modify_handle(fake_update, context)


async def _handle_edit(
    update: Update, event_id: int, edit_text: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle event edit with provided text."""
    from bot.commands.modify_event import handle as modify_handle

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": update.message,
            "effective_user": update.effective_user,
            "effective_chat": update.effective_chat,
        },
    )()

    context.args = [str(event_id), edit_text]
    await modify_handle(fake_update, context)


async def _get_log_count(session, event_id: int) -> int:
    """Get event log count."""
    from sqlalchemy import func
    from db.models import Log as LogModel

    result = await session.execute(
        select(func.count(LogModel.log_id)).where(LogModel.event_id == event_id)
    )
    return result.scalar() or 0


async def _get_constraint_count(session, event_id: int) -> int:
    """Get event constraint count."""
    from sqlalchemy import func
    from db.models import Constraint as ConstraintModel

    result = await session.execute(
        select(func.count(ConstraintModel.constraint_id)).where(
            ConstraintModel.event_id == event_id
        )
    )
    return result.scalar() or 0
