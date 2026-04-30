#!/usr/bin/env python3
"""About command — bot info, version, creator."""
from telegram import Update
from telegram.ext import ContextTypes


BOT_NAME = "Zwischen"
BOT_USERNAME = "xoord_bot"
VERSION = "v3.5.0"
CREATOR = "@Humbanapir"


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /about command."""
    if not update.message:
        return

    await update.message.reply_html(
        f"<b>🤖 {BOT_NAME} — Coordination Bot</b>\n\n"
        f"<i>{VERSION}</i>\n\n"
        "Help your group organize events with AI-powered scheduling.\n"
        "No more back-and-forth DMs. Just tap, join, and show up.\n\n"
        "<b>How it works:</b>\n"
        "• Create events with /events → Create New Event\n"
        "• Tap buttons to join, commit, or enrich\n"
        "• Set constraints privately (if X joins, I join)\n"
        "• Memories accumulate across events — the group remembers\n\n"
        f"<b>Creator:</b> {CREATOR}\n"
        f"<b>Username:</b> @{BOT_USERNAME}\n\n"
        "Built with care for groups that value real connection over noise.",
    )
