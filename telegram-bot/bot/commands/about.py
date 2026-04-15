#!/usr/bin/env python3
"""About command handler - show bot information, version, creator, and purpose."""

from telegram import Update
from telegram.ext import ContextTypes


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /about command - show bot information."""
    if not update.message or not update.effective_user:
        return

    await update.message.reply_text(
        "*🤖 Zwischen Bot*\n\n"
        "A Telegram coordination bot for organizing events, gatherings, and activities.\n\n"
        "*📖 Introduction*\n\n"
        "Zwischen (German for 'between' or 'intermediate') helps groups plan and coordinate "
        "events with minimal friction. Whether you're organizing a game night, sports match, "
        "or work session, the bot guides you through the process with AI-powered suggestions.\n\n"
        "*🎯 Purpose & Intention*\n\n"
        "• *Simplify event organization* - Create events with simple natural language\n"
        "• *Smart scheduling* - AI suggests optimal times based on participant availability\n"
        "• *Conflicts detection* - Prevents scheduling conflicts automatically\n"
        "• *Flexible participation* - Choose between 'interested' and 'confirmed' statuses\n"
        "• *Group coordination* - Works in Telegram groups for community events\n\n"
        "*✨ Key Features*\n\n"
        "• /events - Browse all events\n"
        "• /join \\u003Cid\\u003E - Join an event\n"
        "• /confirm \\u003Cid\\u003E - Confirm attendance\n"
        "• /status \\u003Cid\\u003E - Check event status\n"
        "• /organize_event - Create new event\n"
        "• /suggest_time \\u003Cid\\u003E - AI time suggestions\n"
        "• /modify_event \\u003Cid\\u003E - Modify existing event\n\n"
        "*👤 Creator*\n\n"
        "Developed by Zwischen team\n"
        "An open-source project for better group coordination\n\n"
        "*ℹ️ Version*\n\n"
        "v3.2 - Production Hardening\n"
        "- Schema validation\n"
        "- Type safety improvements\n"
        "- Enhanced UX with inline menus\n"
        "- Natural language date parsing\n\n"
        "*💬 Need Help?*\n\n"
        "Use /start for main menu\n"
        "Use /help for detailed guidance\n"
        "Or mention the bot with your request!",
        parse_mode="Markdown",
    )
