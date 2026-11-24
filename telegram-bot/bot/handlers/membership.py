#!/usr/bin/env python3
"""Group membership/user sync handler."""
import logging
from telegram import Update, User
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from bot.services.membership_service import MembershipService
from db.identity import resolve_telegram_user
from db.models import Group, GroupMemberStatus


logger = logging.getLogger("coord_bot.membership")


async def track_group_members(
    update: Update, _context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Sync users/groups from group messages and new member events."""
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message:
        return
    if chat.type not in {"group", "supergroup"}:
        return
    if not settings.db_url:
        return

    users_to_sync: dict[int, tuple[User, GroupMemberStatus]] = {}
    if update.effective_user:
        users_to_sync[update.effective_user.id] = (
            update.effective_user,
            GroupMemberStatus.active,
        )
    for member in message.new_chat_members or []:
        users_to_sync[member.id] = (member, GroupMemberStatus.active)
    if message.left_chat_member:
        users_to_sync[message.left_chat_member.id] = (
            message.left_chat_member,
            GroupMemberStatus.left,
        )
    if not users_to_sync:
        return

    chat_id = chat.id
    chat_title = chat.title or str(chat_id)

    try:
        async with get_session(settings.db_url) as session:
            result = await session.execute(
                select(Group).where(Group.telegram_group_id == chat_id)
            )
            group = result.scalar_one_or_none()

            if not group:
                group = Group(
                    telegram_group_id=chat_id,
                    group_name=chat_title,
                )
                session.add(group)
                await session.flush()
            else:
                if group.group_name != chat_title:
                    group.group_name = chat_title
                    session.add(group)

            memberships = MembershipService(session)
            for user, status in users_to_sync.values():
                resolved = await resolve_telegram_user(
                    session,
                    user.id,
                    display_name=user.full_name,
                    username=user.username,
                )
                if status is GroupMemberStatus.active:
                    await memberships.add_member(
                        int(group.group_id), int(resolved.user_id)
                    )
                else:
                    await memberships.remove_member(
                        int(group.group_id), int(resolved.user_id), status=status
                    )

            await session.commit()
    except Exception as e:
        logger.error(
            "Failed to sync group members for group %s (%s): %s",
            chat_id,
            chat_title,
            type(e).__name__,
            exc_info=True,
        )
        # Don't propagate the error - let the update continue without sync
        # The bot will still function, just won't sync membership data
        return
