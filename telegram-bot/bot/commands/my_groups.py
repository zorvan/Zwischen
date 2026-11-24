#!/usr/bin/env python3
"""My Groups command handler."""
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.identity import resolve_telegram_user
from db.models import Group, GroupMember, GroupMemberStatus


async def handle(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /my_groups command."""
    if not update.message or not update.effective_user:
        return

    telegram_user_id = update.effective_user.id

    async with get_session(settings.db_url) as session:
        user = await resolve_telegram_user(
            session,
            telegram_user_id,
            display_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )
        result = await session.execute(
            select(Group)
            .join(GroupMember, GroupMember.group_id == Group.group_id)
            .where(
                GroupMember.user_id == user.user_id,
                GroupMember.status == GroupMemberStatus.active.value,
            )
        )
        groups = result.scalars().all()

    if not groups:
        await update.message.reply_text(
            "📋 *Your Groups*\n\n"
            "• No groups yet.\n\n"
            "Run /organize_event in a group once to register it."
        )
        return

    lines = ["📋 *Your Groups*", ""]
    for group in groups:
        group_name = group.group_name or f"Group {group.telegram_group_id}"
        lines.append(f"• {group_name} (`{group.telegram_group_id}`)")

    await update.message.reply_text("\n".join(lines))
