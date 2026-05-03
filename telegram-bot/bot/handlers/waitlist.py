#!/usr/bin/env python3
"""Waitlist flow handlers for the active v3.2 waitlist contract."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import Event, User, Group
from bot.services import WaitlistService
from bot.common.i18n import t, get_user_language

logger = logging.getLogger("coord_bot.handlers.waitlist")


async def handle_accept(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle waitlist spot acceptance."""
    query = update.callback_query
    if not query:
        return
    telegram_user_id = query.from_user.id

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        waitlist_service = WaitlistService(session, context.bot)

        # Accept the offer
        accepted = await waitlist_service.accept_offer(event_id, telegram_user_id)
        if not accepted:
            await query.edit_message_text(
                "❌ This offer has expired or is no longer available."
            )
            return

        # Get event info for confirmation message
        event_result = await session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()
        if not event:
            await query.edit_message_text("✅ You're in! (Event details unavailable)")
            return

        await query.edit_message_text(
            f"✅ You're in for the {event.event_type}!\n"
            f"{event.scheduled_time.strftime('%a %d %b, %H:%M') if event.scheduled_time else 'Time TBD'}."
        )


async def handle_decline(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle waitlist spot decline."""
    query = update.callback_query
    if not query:
        return
    telegram_user_id = query.from_user.id

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        waitlist_service = WaitlistService(session, context.bot)

        declined = await waitlist_service.decline_offer(event_id, telegram_user_id)
        if declined:
            await query.edit_message_text("👍 Thanks for letting us know.")
        else:
            await query.edit_message_text("✅ Already handled.")


async def handle_extend_deadline(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle organizer extending collapse deadline."""
    query = update.callback_query
    if not query:
        return
    telegram_user_id = query.from_user.id

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        event_result = await session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()
        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Verify organizer/admin
        if telegram_user_id not in {
            event.organizer_telegram_user_id,
            event.emergency_admin_telegram_user_id,
        }:
            await query.edit_message_text(
                "❌ Only the organizer can extend the deadline."
            )
            return

        # Extend collapse_at by 24 hours
        if event.collapse_at:
            event.collapse_at = event.collapse_at + timedelta(hours=24)
        else:
            # If no collapse_at was set, set one 24h from now
            event.collapse_at = datetime.utcnow() + timedelta(hours=24)

        await session.commit()

        user_lang = (
            await get_user_language(query.from_user, user_data=context.user_data)
            if query.from_user
            else "en"
        )
        await query.edit_message_text(
            t(
                "waitlist_deadline_extended",
                lang=user_lang,
                type=event.event_type,
                time=event.collapse_at.strftime("%a %d %b, %H:%M"),
            )
        )

        # Notify group with neutral state update only
        group_result = await session.execute(
            select(Group.telegram_group_id).where(Group.group_id == event.group_id)
        )
        group_chat_id = group_result.scalar_one_or_none()
        if group_chat_id:
            await context.bot.send_message(
                chat_id=group_chat_id,
                text=t(
                    "waitlist_deadline_extended_group",
                    lang=user_lang,
                    type=event.event_type,
                    time=event.collapse_at.strftime("%a %d %b, %H:%M"),
                ),
            )


async def handle_view_waitlist(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle organizer viewing waitlist."""
    query = update.callback_query
    if not query:
        return
    telegram_user_id = query.from_user.id

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        event_result = await session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        user_lang = (
            await get_user_language(query.from_user, user_data=context.user_data)
            if query.from_user
            else "en"
        )
        event = event_result.scalar_one_or_none()
        if not event:
            await query.edit_message_text(t("waitlist_event_not_found", lang=user_lang))
            return

        # Verify organizer/admin
        if telegram_user_id not in {
            event.organizer_telegram_user_id,
            event.emergency_admin_telegram_user_id,
        }:
            await query.edit_message_text(t("waitlist_only_organizer", lang=user_lang))
            return

        waitlist_service = WaitlistService(session, context.bot)
        waitlist = await waitlist_service.get_waitlist(event_id)

        if not waitlist:
            await query.edit_message_text(
                t("waitlist_view_empty", lang=user_lang, type=event.event_type)
            )
            return

        lines = [t("waitlist_header", lang=user_lang, type=event.event_type)]
        for i, entry in enumerate(waitlist, 1):
            user_result = await session.execute(
                select(User).where(User.telegram_user_id == entry.telegram_user_id)
            )
            user = user_result.scalar_one_or_none()
            name = f"User #{entry.telegram_user_id}"
            if user:
                name = user.display_name or user.username or name
            lines.append(f"{i}. {name}")

        await query.edit_message_text("\n".join(lines))


async def handle_join_waitlist(
    update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle user joining the waitlist."""
    query = update.callback_query
    if not query:
        return
    telegram_user_id = query.from_user.id

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        waitlist_service = WaitlistService(session, context.bot)

        try:
            position = await waitlist_service.add_to_waitlist(
                event_id, telegram_user_id
            )
            await query.edit_message_text(
                f"✅ You're on the waitlist for the event (position #{position}). "
                f"You'll be notified if a spot opens."
            )
        except ValueError as e:
            await query.edit_message_text(f"❌ {str(e)}")


async def handle_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Route waitlist callback queries to the right handler."""
    import asyncio

    query = update.callback_query
    if not query or not query.data:
        return

    try:
        await asyncio.wait_for(query.answer(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    data = query.data
    if data.startswith("waitlist_join_"):
        event_id = int(data.split("_")[-1])
        await handle_join_waitlist(update, context, event_id)
    elif data.startswith("waitlist_accept_"):
        event_id = int(data.split("_")[-1])
        await handle_accept(update, context, event_id)
    elif data.startswith("waitlist_decline_"):
        event_id = int(data.split("_")[-1])
        await handle_decline(update, context, event_id)
    elif data.startswith("extend_deadline_"):
        event_id = int(data.split("_")[-1])
        await handle_extend_deadline(update, context, event_id)
    elif data.startswith("view_waitlist_"):
        event_id = int(data.split("_")[-1])
        await handle_view_waitlist(update, context, event_id)
