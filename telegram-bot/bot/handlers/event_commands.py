#!/usr/bin/env python3
"""Event command callback handlers for unified /event navigation."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.commands import event as event_cmd
from bot.common.event_presenters import format_status_message


async def handle_event_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle all /event callback queries."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    data = query.data

    # Pattern: event_view_<event_id>
    if data.startswith("event_view_"):
        event_id = int(data.replace("event_view_", ""))
        await _show_main_view(query, context, event_id)
    # Pattern: event_tab_<event_id>_<tab>
    elif data.startswith("event_tab_"):
        parts = data.split("_")
        if len(parts) >= 4:
            event_id = int(parts[2])
            tab = parts[3]
            await _show_tab(query, context, event_id, tab)
    # Pattern: event_details_<event_id>
    elif data.startswith("event_details_"):
        event_id = int(data.replace("event_details_", ""))
        await _show_details(query, context, event_id)
    # Pattern: event_status_<event_id>
    elif data.startswith("event_status_"):
        event_id = int(data.replace("event_status_", ""))
        await _show_status(query, context, event_id)
    else:
        # Let other handlers process this
        return


async def _show_main_view(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show event main view with tabs."""
    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": query.message,
            "effective_user": query.from_user,
            "effective_chat": getattr(query.message, "chat", None),
        },
    )()
    context.args = [str(event_id)]
    await event_cmd.handle(fake_update, context)


async def _show_tab(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, tab: str
) -> None:
    """Show specific tab content."""
    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": query.message,
            "effective_user": query.from_user,
            "effective_chat": getattr(query.message, "chat", None),
        },
    )()

    tab_handlers = {
        "details": lambda: _call_handler(
            query, context, event_id, "details", "event_details"
        ),
        "status": lambda: _call_handler(
            query, context, event_id, "status", "event_status"
        ),
        "availability": lambda: _call_handler(
            query, context, event_id, "availability", "constraints"
        ),
        "constraints": lambda: _call_handler(
            query, context, event_id, "constraints", "constraints"
        ),
        "suggest": lambda: _call_handler(
            query, context, event_id, "suggest", "suggest_time"
        ),
        "edit": lambda: _call_handler(query, context, event_id, "edit", "modify_event"),
    }

    handler = tab_handlers.get(tab)
    if handler:
        await handler()


async def _call_handler(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    mode: str,
    handler_name: str,
) -> None:
    """Call appropriate handler for tab."""
    from bot.commands import (
        event_details,
        status,
        constraints,
        suggest_time,
        modify_event,
    )

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": query.message,
            "effective_user": query.from_user,
            "effective_chat": getattr(query.message, "chat", None),
        },
    )()

    context.args = [str(event_id)]

    handlers = {
        "event_details": event_details.handle,
        "event_status": status.handle,
        "constraints": lambda u, c: constraints.handle(u, c),
        "suggest_time": suggest_time.handle,
        "modify_event": modify_event.handle,
    }

    handler = handlers.get(handler_name)
    if handler:
        await handler(fake_update, context)


async def _show_details(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show event details."""
    from bot.commands import event_details

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": query.message,
            "effective_user": query.from_user,
            "effective_chat": getattr(query.message, "chat", None),
        },
    )()

    context.args = [str(event_id)]
    await event_details.handle(fake_update, context)


async def _show_status(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show event status."""
    from bot.commands import status

    fake_update = type(
        "FakeUpdate",
        (),
        {
            "message": query.message,
            "effective_user": query.from_user,
            "effective_chat": getattr(query.message, "chat", None),
        },
    )()

    context.args = [str(event_id)]
    await status.handle(fake_update, context)
