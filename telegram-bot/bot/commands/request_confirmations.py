#!/usr/bin/env python3
"""Request confirmation command handler."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import Event, User
from bot.services import ParticipantService
from bot.common.callback_data import encode_callback
from bot.common.i18n import t, get_user_language


def _format_user_label(user: User | None, telegram_user_id: int) -> str:
    """Format a user mention/label for status output."""
    if user and user.username:
        return f"@{user.username}"
    if user and user.display_name:
        return user.display_name
    return str(telegram_user_id)


async def send_confirmation_request_message(
    reply_message,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    user_lang: str = "en",
) -> None:
    """Send a group message asking participants to confirm via inline button."""
    if not settings.db_url:
        await reply_message.reply_text(t("error_db_unavailable", lang=user_lang))
        return

    async with get_session(settings.db_url) as session:
        event = (
            await session.execute(select(Event).where(Event.event_id == event_id))
        ).scalar_one_or_none()
        if not event:
            await reply_message.reply_text(
                t("request_confirmations_event_not_found", lang=user_lang)
            )
            return

        # Get participants using ParticipantService
        participant_service = ParticipantService(session)
        all_participants = await participant_service.get_all_participants(event_id)

        participants = set()
        confirmed = set()
        for p in all_participants:
            participants.add(p.telegram_user_id)
            if p.status == "confirmed":
                confirmed.add(p.telegram_user_id)

        pending = sorted(participants - confirmed)

        users_by_tid: dict[int, User] = {}
        if participants:
            users = (
                (
                    await session.execute(
                        select(User).where(
                            User.telegram_user_id.in_(list(participants))
                        )
                    )
                )
                .scalars()
                .all()
            )
            users_by_tid = {int(u.telegram_user_id): u for u in users}

    pending_labels = (
        ", ".join(_format_user_label(users_by_tid.get(uid), uid) for uid in pending)
        if pending
        else t("request_confirmations_no_pending", lang=user_lang)
    )
    confirmed_labels = (
        ", ".join(
            _format_user_label(users_by_tid.get(uid), uid) for uid in sorted(confirmed)
        )
        if confirmed
        else t("request_confirmations_none", lang=user_lang)
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("request_confirmations_confirm", lang=user_lang),
                    callback_data=encode_callback("commit", event_id),
                ),
                InlineKeyboardButton(
                    t("request_confirmations_uncommit", lang=user_lang),
                    callback_data=encode_callback("cancel", event_id),
                ),
            ],
            [
                InlineKeyboardButton(
                    t("request_confirmations_step_back", lang=user_lang),
                    callback_data=encode_callback("cancel", event_id),
                ),
                InlineKeyboardButton(
                    t("request_confirmations_lock", lang=user_lang),
                    callback_data=encode_callback("lock", event_id),
                ),
            ],
            [
                InlineKeyboardButton(
                    t("request_confirmations_status", lang=user_lang),
                    callback_data=encode_callback("det", event_id),
                )
            ],
        ]
    )
    await reply_message.reply_text(
        t(
            "request_confirmations_message",
            lang=user_lang,
            event_id=event_id,
            type=event.event_type,
            time=event.scheduled_time or "TBD",
            state=event.state,
            count=len(pending),
            pending=pending_labels,
            confirmed_count=len(confirmed),
            confirmed=confirmed_labels,
        ),
        reply_markup=keyboard,
    )
    # Send final confirmation DM to attendees.
    dm_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("request_confirmations_final_confirm", lang=user_lang),
                    callback_data=encode_callback("commit", event_id),
                ),
                InlineKeyboardButton(
                    t("request_confirmations_uncommit", lang=user_lang),
                    callback_data=encode_callback("cancel", event_id),
                ),
            ]
        ]
    )
    dm_sent = 0
    for tid in sorted(participants):
        try:
            await context.bot.send_message(
                chat_id=tid,
                text=t(
                    "request_confirmations_final_dm",
                    lang=user_lang,
                    event_id=event_id,
                    type=event.event_type,
                    time=event.scheduled_time or "TBD",
                ),
                reply_markup=dm_keyboard,
            )
            dm_sent += 1
        except Exception:
            continue

    await reply_message.reply_text(
        t(
            "request_confirmations_dm_sent",
            lang=user_lang,
            sent=dm_sent,
            total=len(participants),
        )
    )


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /request_confirmations command."""
    if not update.message:
        return

    user_lang = (
        await get_user_language(update.message.from_user)
        if update.message.from_user
        else "en"
    )
    event_id_raw = context.args[0] if context.args else None
    if not event_id_raw:
        await update.message.reply_text(
            t("request_confirmations_usage", lang=user_lang)
        )
        return
    try:
        event_id = int(event_id_raw)
    except ValueError:
        await update.message.reply_text(
            t("request_confirmations_event_id_invalid", lang=user_lang)
        )
        return

    await send_confirmation_request_message(
        reply_message=update.message,
        context=context,
        event_id=event_id,
        user_lang=user_lang,
    )
