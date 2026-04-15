#!/usr/bin/env python3
"""Plan command - alias for /organize_event with memory-first event creation."""

from bot.commands.meaning_formation import start_meaning_formation


async def handle(update, context):
    """Handle /plan command - start memory-first event creation."""
    await start_meaning_formation(update, context, mode="public")


async def handle_flexible(update, context):
    """Handle /plan_flexible command - flexible event creation with memory."""
    await start_meaning_formation(update, context, mode="public")
