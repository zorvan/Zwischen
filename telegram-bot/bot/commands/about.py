#!/usr/bin/env python3
"""About command handler - show bot information, version, creator, and purpose."""

from telegram import Update
from telegram.ext import ContextTypes


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /about command - show bot information."""
    if not update.message or not update.effective_user:
        return

    await update.message.reply_text(
        "<b>🤖 Zwischen Bot</b>\n\n"
        "A Telegram coordination bot for organizing events, gatherings, and activities.\n\n"
        "<b>📖 Introduction</b>\n\n"
        "Zwischen (German for 'between' or 'intermediate') helps groups plan and coordinate "
        "events with minimal friction. Whether you're organizing a game night, sports match, "
        "or work session, the bot guides you through the process with AI-powered suggestions.\n\n"
        "<b>🎯 Purpose & Intention</b>\n\n"
        "• <b>Simplify event organization</b> - Create events with simple natural language\n"
        "• <b>Smart scheduling</b> - AI suggests optimal times based on participant availability\n"
        "• <b>Conflicts detection</b> - Prevents scheduling conflicts automatically\n"
        "• <b>Flexible participation</b> - Choose between 'interested' and 'confirmed' statuses\n"
        "• <b>Group coordination</b> - Works in Telegram groups for community events\n\n"
        "<b>✨ Key Features</b>\n\n"
        "• /events - Browse all events\n"
        "• /join <id> - Join an event\n"
        "• /confirm <id> - Confirm attendance\n"
        "• /status <id> - Check event status\n"
        "• /organize_event - Create new event\n"
        "• /suggest_time <id> - AI time suggestions\n"
        "• /modify_event <id> - Modify existing event\n\n"
        "<b>👤 Creator</b>\n\n"
        "Developed by Zwischen team\n"
        "An open-source project for better group coordination\n\n"
        "<b>ℹ️ Version</b>\n\n"
        "v3.2 - Production Hardening\n"
        "- Schema validation\n"
        "- Type safety improvements\n"
        "- Enhanced UX with inline menus\n"
        "- Natural language date parsing\n\n"
        "<b>💬 Need Help?</b>\n\n"
        "Use /start for main menu\n"
        "Use /help for detailed guidance\n"
        "Or mention the bot with your request!",
        parse_mode="HTML",
    )
