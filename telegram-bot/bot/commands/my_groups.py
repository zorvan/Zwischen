#!/usr/bin/env python3
"""My Groups command handler."""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import Group


async def handle(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /my_groups command."""
    if not update.message or not update.effective_user:
        return

    telegram_user_id = update.effective_user.id

    async with get_session(settings.db_url) as session:
        result = await session.execute(select(Group))
        groups = result.scalars().all()

    user_groups = []
    for group in groups:
        members = group.member_list or []
        if telegram_user_id in members:
            user_groups.append(group)

    if not user_groups:
        await update.message.reply_text(
            "📋 *Your Groups*\n\n" "• No groups yet.\n\n" "Run /organize_event in a group once to register it."
        )
        return

    lines = ["📋 *Your Groups*", ""]
    for group in user_groups:
        group_name = group.group_name or f"Group {group.telegram_group_id}"
        lines.append(f"• {group_name} (`{group.telegram_group_id}`)")

    await update.message.reply_text("\n".join(lines))
