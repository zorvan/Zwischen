#!/usr/bin/env python3
"""Event details and status views for the v3.5 event panel."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, func

from config.settings import settings
from db.connection import get_session
from db.models import (
    User,
    Log as LogModel,
    Constraint as ConstraintModel,
)
from bot.common.rbac import check_event_visibility_and_get_event
from bot.common.event_presenters import (
    format_event_details_message,
    format_user_display,
)
from bot.services import ParticipantService
from db.models import ParticipantStatus
from bot.common.i18n import t, get_user_language


async def show_details(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: int | None = None,
) -> None:
    user_id = query.from_user.id if query.from_user else None
    user_lang = get_user_language(query.from_user) if query.from_user else "en"
    chat_id = getattr(getattr(query, "message", None), "chat_id", None)
    chat_type = getattr(
        getattr(getattr(query, "message", None), "chat", None), "type", None
    )
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        is_visible, event, group, error_msg = (
            await check_event_visibility_and_get_event(
                session,
                event_id,
                user_id,
                telegram_chat_id=group_id if group_id is not None else chat_id,
                bot=context.bot,
            )
        )
        if not is_visible:
            await query.edit_message_text(
                t(
                    "event_details_event_not_visible",
                    lang=user_lang,
                    error_msg=error_msg
                    or t("event_details_event_not_found", lang=user_lang),
                )
            )
            return
        logs = await _get_event_logs(session, event_id)
        constraints = await _get_event_constraints(session, event_id)
        bot_username = context.bot.username if context.bot else None
        reply_markup = None
        if chat_type == "private":
            reply_markup = await _build_details_markup(
                event, user_id, bot_username, session, lang=user_lang
            )
        elif group_id is not None:
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            t("event_details_back", lang=user_lang),
                            callback_data=f"ev:{event_id}:{group_id}:view",
                        )
                    ]
                ]
            )
        else:
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            t("event_details_back", lang=user_lang),
                            callback_data=f"ev:{event_id}:view",
                        )
                    ]
                ]
            )
        await query.edit_message_text(
            await format_event_details_message(
                event_id, event, logs, constraints, context.bot
            ),
            reply_markup=reply_markup,
        )


async def _show_status(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    from bot.common.event_presenters import format_status_message

    user_id = query.from_user.id if query.from_user else None
    user_lang = get_user_language(query.from_user) if query.from_user else "en"
    chat_id = getattr(getattr(query, "message", None), "chat_id", None)
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        is_visible, event, group, error_msg = (
            await check_event_visibility_and_get_event(
                session,
                event_id,
                user_id,
                telegram_chat_id=chat_id,
                bot=context.bot,
            )
        )
        if not is_visible:
            await query.edit_message_text(
                t(
                    "event_details_event_not_visible",
                    lang=user_lang,
                    error_msg=error_msg
                    or t("event_details_event_not_found", lang=user_lang),
                )
            )
            return
        log_count = await _get_event_log_count(session, event_id)
        constraint_count = await _get_event_constraint_count(session, event_id)
        user_participant = None
        if user_id:
            participant_service = ParticipantService(session)
            user_participant = await participant_service.get_participant(
                event.event_id, user_id
            )
        bot_username = context.bot.username if context.bot else None
        keyboard = await _build_status_markup(
            event, user_id, bot_username, session, lang=user_lang
        )
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


async def _show_logs(query, event_id: int, lang: str = "en") -> None:
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
            await query.edit_message_text(
                t("event_logs_empty", lang=lang, event_id=event_id)
            )
            return
        msg = t("event_logs_title", lang=lang, event_id=event_id) + "\n\n"
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
                "join": t("event_logs_action_join", lang=lang),
                "confirm": t("event_logs_action_confirm", lang=lang),
                "cancel": t("event_logs_action_cancel", lang=lang),
                "organize_event": t("event_logs_action_organize_event", lang=lang),
                "suggest_time": t("event_logs_action_suggest_time", lang=lang),
                "nudge": t("event_logs_action_nudge", lang=lang),
                "constraint_update": t(
                    "event_logs_action_constraint_update", lang=lang
                ),
            }.get(log.action, log.action)
            msg += f"- {action_text}{user_info} at {log.timestamp}\n"
        if len(rows) > 10:
            msg += t("event_logs_more", lang=lang, count=len(rows) - 10)
        keyboard = [
            [
                InlineKeyboardButton(
                    t("panel_back", lang=lang), callback_data=f"ev:{event_id}:det"
                )
            ]
        ]
        try:
            await query.edit_message_text(
                msg, reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("Updated")
            else:
                raise


async def _show_constraints(query, event_id: int, lang: str = "en") -> None:
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(
            select(ConstraintModel).where(ConstraintModel.event_id == event_id)
        )
        constraints = result.scalars().all()
        if not constraints:
            await query.edit_message_text(
                t("event_constraints_title", lang=lang, event_id=event_id)
                + "\n\n"
                + t("event_constraints_empty", lang=lang),
            )
            return
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
        msg = t("event_constraints_title", lang=lang, event_id=event_id) + " (Raw)\n\n"
        for c in constraints:
            user = users.get(c.user_id)
            user_display = (
                format_user_display(
                    telegram_user_id=user.telegram_user_id if user else c.user_id,
                    username=(
                        user.username
                        if user and getattr(user, "username", None)
                        else None
                    ),
                    display_name=(
                        user.display_name
                        if user and getattr(user, "display_name", None)
                        else None
                    ),
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
                        telegram_user_id=(
                            target_user.telegram_user_id
                            if target_user
                            else c.target_user_id
                        ),
                        username=(
                            target_user.username
                            if target_user and getattr(target_user, "username", None)
                            else None
                        ),
                        display_name=(
                            target_user.display_name
                            if target_user
                            and getattr(target_user, "display_name", None)
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
        keyboard = [
            [
                InlineKeyboardButton(
                    t("panel_back", lang=lang), callback_data=f"ev:{event_id}:det"
                )
            ]
        ]
        try:
            await query.edit_message_text(
                msg, reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("Updated")
            else:
                raise


async def _get_event_logs(session, event_id: int) -> list:
    result = await session.execute(
        select(LogModel).where(LogModel.event_id == event_id)
    )
    return list(result.scalars().all())


async def _get_event_constraints(session, event_id: int) -> list:
    result = await session.execute(
        select(ConstraintModel).where(ConstraintModel.event_id == event_id)
    )
    return list(result.scalars().all())


async def _get_event_log_count(session, event_id: int) -> int:
    result = await session.execute(
        select(func.count(LogModel.log_id)).where(LogModel.event_id == event_id)
    )
    return result.scalar() or 0


async def _get_event_constraint_count(session, event_id: int) -> int:
    result = await session.execute(
        select(func.count(ConstraintModel.constraint_id)).where(
            ConstraintModel.event_id == event_id
        )
    )
    return result.scalar() or 0


async def _build_status_markup(
    event, user_id, bot_username, session, lang: str = "en"
) -> list:
    keyboard = [
        [
            InlineKeyboardButton(
                t("event_details_view", lang=lang),
                callback_data=f"ev:{event.event_id}:det",
            )
        ]
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                t("event_details_refresh", lang=lang),
                callback_data=f"ev:{event.event_id}:refresh",
            )
        ]
    )
    return keyboard


async def _build_details_markup(
    event, user_id, bot_username, session, lang: str = "en"
) -> InlineKeyboardMarkup:
    user_joined = False
    user_confirmed = False
    if user_id is not None:
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
    first_row = []
    if not user_joined:
        first_row = [
            InlineKeyboardButton(
                t("event_details_join", lang=lang),
                callback_data=f"ev:{event.event_id}:join",
            )
        ]
    elif user_confirmed:
        first_row = [
            InlineKeyboardButton(
                t("event_details_confirmed", lang=lang),
                callback_data=f"ev:{event.event_id}:commit",
            ),
            InlineKeyboardButton(
                t("event_details_uncommit", lang=lang),
                callback_data=f"ev:{event.event_id}:cancel",
            ),
        ]
    else:
        first_row = [
            InlineKeyboardButton(
                t("event_details_confirm", lang=lang),
                callback_data=f"ev:{event.event_id}:commit",
            ),
            InlineKeyboardButton(
                t("event_details_step_back", lang=lang),
                callback_data=f"ev:{event.event_id}:cancel",
            ),
        ]
    keyboard = [
        first_row,
        [
            InlineKeyboardButton(
                t("event_details_lock", lang=lang),
                callback_data=f"ev:{event.event_id}:lock",
            ),
        ],
        [
            InlineKeyboardButton(
                t("event_details_logs", lang=lang),
                callback_data=f"ev:{event.event_id}:logs",
            )
        ],
        [
            InlineKeyboardButton(
                t("event_details_constraints", lang=lang),
                callback_data=f"ev:{event.event_id}:constraint",
            )
        ],
        [
            InlineKeyboardButton(
                t("event_details_update", lang=lang),
                callback_data=f"ev:{event.event_id}:det",
            )
        ],
    ]
    if user_joined:
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("event_details_modify", lang=lang),
                    callback_data=f"ev:{event.event_id}:modify",
                )
            ]
        )
    from bot.common.deeplinks import build_start_link

    avail_link = build_start_link(bot_username, f"avail_{event.event_id}")
    if avail_link:
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("event_details_set_availability", lang=lang), url=avail_link
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton(
                t("event_details_step_back", lang=lang),
                callback_data=f"ev:{event.event_id}:cancel",
            )
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                t("event_details_close", lang=lang),
                callback_data=f"ev:{event.event_id}:close",
            )
        ]
    )
    return InlineKeyboardMarkup(keyboard)


_show_details = show_details
