#!/usr/bin/env python3
"""Start command handler."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.common.menus import build_main_menu
from bot.commands import event_details
from config.settings import settings
from db.connection import get_session
from sqlalchemy import select


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not update.message:
        return

    args = context.args or []
    payload = args[0] if args else ""

    # Handle deep links
    if payload.startswith("avail_"):
        try:
            event_id = int(payload.replace("avail_", ""))
        except ValueError:
            event_id = None
        if event_id is not None:
            async with get_session(settings.db_url) as session:
                from db.models import Event

                result = await session.execute(
                    select(Event).where(Event.event_id == event_id)
                )
                event = result.scalar_one_or_none()

            if not event:
                await update.message.reply_text("❌ Event not found.")
                return

            # Call the availability slots handler directly
            # We need to create a mock query object for the callback
            class MockQuery:
                def __init__(self, message):
                    self.message = message
                    self.from_user = message.from_user
                    self.id = "mock_query"

                async def answer(self, *args, **kwargs):
                    pass

            mock_query = MockQuery(update.message)

            # Show availability options menu
            await event_details._show_availability_options(
                mock_query, context, event_id
            )
            return

    # Show main menu with buttons
    display_name = update.effective_user.full_name if update.effective_user else "User"

    await update.message.reply_text(
        f"👋 *Welcome, {display_name}!*\n\n"
        "I'm your coordination bot. I help organize group events with "
        "AI-powered scheduling.\n\n"
        "💡 *Use the menu buttons below* to navigate instead of typing commands!\n\n"
        "Quick commands:\n"
        "/plan - Start planning an event\n"
        "/organize_event - Create a new event\n"
        "/events - List recent events\n"
        "/my_groups - List your groups\n"
        "/profile - View your profile\n"
        "/how_am_i_doing - See your participation mirror",
        reply_markup=build_main_menu(),
        parse_mode="Markdown",
    )
