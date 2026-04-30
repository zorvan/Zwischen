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
) -> None:
    """Send a group message asking participants to confirm via inline button."""
    if not settings.db_url:
        await reply_message.reply_text("❌ Database configuration is unavailable.")
        return

    async with get_session(settings.db_url) as session:
        event = (await session.execute(select(Event).where(Event.event_id == event_id))).scalar_one_or_none()
        if not event:
            await reply_message.reply_text("❌ Event not found.")
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
                (await session.execute(select(User).where(User.telegram_user_id.in_(list(participants)))))
                .scalars()
                .all()
            )
            users_by_tid = {int(u.telegram_user_id): u for u in users}

    pending_labels = (
        ", ".join(_format_user_label(users_by_tid.get(uid), uid) for uid in pending)
        if pending
        else "No pending participants."
    )
    confirmed_labels = (
        ", ".join(_format_user_label(users_by_tid.get(uid), uid) for uid in sorted(confirmed)) if confirmed else "None"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"event_confirm_{event_id}"),
                InlineKeyboardButton("↩️ Uncommit", callback_data=f"event_unconfirm_{event_id}"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"event_cancel_{event_id}"),
                InlineKeyboardButton("🔒 Lock", callback_data=f"event_lock_{event_id}"),
            ],
            [InlineKeyboardButton("📊 Status", callback_data=f"event_details_{event_id}")],
        ]
    )
    await reply_message.reply_text(
        "📣 *Confirmation Request*\n\n"
        f"Event ID: {event_id}\n"
        f"Type: {event.event_type}\n"
        f"Time: {event.scheduled_time or 'TBD'}\n"
        f"State: {event.state}\n\n"
        f"Pending commitments ({len(pending)}): {pending_labels}\n"
        f"Already committed ({len(confirmed)}): {confirmed_labels}\n\n"
        "Participants should click *Confirm* to commit attendance.",
        reply_markup=keyboard,
    )
    # Send final confirmation DM to attendees.
    dm_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Final Confirm", callback_data=f"event_confirm_{event_id}"),
                InlineKeyboardButton("↩️ Uncommit", callback_data=f"event_unconfirm_{event_id}"),
            ]
        ]
    )
    dm_sent = 0
    for tid in sorted(participants):
        try:
            await context.bot.send_message(
                chat_id=tid,
                text=(
                    "📩 *Final Confirmation Required*\n\n"
                    f"Event ID: {event_id}\n"
                    f"Type: {event.event_type}\n"
                    f"Time: {event.scheduled_time or 'TBD'}\n\n"
                    "Please commit or go back."
                ),
                reply_markup=dm_keyboard,
            )
            dm_sent += 1
        except Exception:
            continue

    await reply_message.reply_text(f"ℹ️ Final-confirmation DM sent to {dm_sent}/{len(participants)} attendees.")


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /request_confirmations command."""
    if not update.message:
        return

    event_id_raw = context.args[0] if context.args else None
    if not event_id_raw:
        await update.message.reply_text(
            "Usage: /request_confirmations <event_id>\n\n" "Example: /request_confirmations 123"
        )
        return
    try:
        event_id = int(event_id_raw)
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return

    await send_confirmation_request_message(
        reply_message=update.message,
        context=context,
        event_id=event_id,
    )
