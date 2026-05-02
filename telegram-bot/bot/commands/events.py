#!/usr/bin/env python3
"""Events command handler - list recent events as clickable buttons."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import Event, Group
from bot.common.rbac import check_group_membership
from bot.common.i18n import t, get_user_language


async def handle(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /events command - list recent events as clickable buttons."""
    if not update.message or not update.effective_chat:
        return

    user_lang = (
        get_user_language(update.message.from_user)
        if update.message.from_user
        else "en"
    )
    chat = update.effective_chat
    is_group_chat = chat.type in {"group", "supergroup"}
    db_url = settings.db_url or ""
    user_id = update.effective_user.id if update.effective_user else None

    async with get_session(db_url) as session:
        query = (
            select(Event, Group)
            .join(Group, Event.group_id == Group.group_id, isouter=True)
            .order_by(Event.created_at.desc())
            .limit(20)
        )

        if is_group_chat:
            query = query.where(Group.telegram_group_id == chat.id)

        result = await session.execute(query)
        rows = result.all()

        if not rows:
            # v3.5: Show Create button even when no events exist
            keyboard = [
                [
                    InlineKeyboardButton(
                        t("events_create_new", lang=user_lang),
                        callback_data="events_create_new",
                    )
                ],
                [
                    InlineKeyboardButton(
                        t("events_main_menu", lang=user_lang), callback_data="menu_main"
                    )
                ],
            ]
            await update.message.reply_text(
                t("events_no_events", lang=user_lang),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        # Filter events by group membership for group chats
        if is_group_chat and user_id:
            filtered_rows = []
            for event, group in rows:
                if group:
                    is_member, _ = await check_group_membership(
                        session, group.group_id, user_id, telegram_chat_id=chat.id
                    )
                    if is_member:
                        filtered_rows.append((event, group))
                else:
                    # Events without group: skip in group chat
                    continue
            rows = filtered_rows

        if not rows:
            await update.message.reply_text(
                t("events_no_events_in_group", lang=user_lang)
            )
            return

        title = (
            t("events_title", lang=user_lang, group_name=chat.title or "this group")
            if is_group_chat
            else t("events_title_private", lang=user_lang)
        )

        # Build message text with brief event info
        lines = [title, ""]

        # Build keyboard with event buttons
        keyboard = []

        for event, group in rows:
            time_str = (
                event.scheduled_time.strftime("%m-%d %H:%M")
                if event.scheduled_time
                else "TBD"
            )

            # Three-word description for button text
            words = (event.description or "Event").split()[:3]
            short_desc = " ".join(words)

            # Escape underscores for safe Markdown
            short_desc_escaped = short_desc.replace("_", "\\_")
            state_escaped = event.state.replace("_", "\\_")

            # Add brief info to message text (no event IDs per v3.5 spec)
            lines.append(f"• {short_desc_escaped} | {time_str} | {state_escaped}")

            # Add button for this event
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📅 {short_desc}", callback_data=f"ev:{event.event_id}:view"
                    )
                ]
            )

        # Add Create New Event button (v3.5: always visible)
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("events_create_new", lang=user_lang),
                    callback_data="events_create_new",
                ),
            ]
        )

        # Add back to menu button
        keyboard.append(
            [
                InlineKeyboardButton(
                    t("events_main_menu", lang=user_lang), callback_data="menu_main"
                ),
            ]
        )

        lines.append("")
        lines.append(t("events_tap_hint", lang=user_lang))

        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )


async def handle_create_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the 'Create New Event' button callback.

    v3.5: Memory-first creation flow - starts with collecting intent
    before asking for explicit event details.
    """
    query = update.callback_query
    if not query:
        return

    user_lang = get_user_language(query.from_user) if query.from_user else "en"
    await query.answer()

    # Memory-first: Ask user what they want to do
    # This starts the creation flow by collecting intent
    keyboard = [
        [
            InlineKeyboardButton(
                t("menu_create_specific", lang=user_lang),
                callback_data="create_specific",
            )
        ],
        [
            InlineKeyboardButton(
                t("menu_create_flexible", lang=user_lang),
                callback_data="create_flexible",
            )
        ],
        [
            InlineKeyboardButton(
                t("menu_back_to_events", lang=user_lang), callback_data="events_back"
            )
        ],
    ]

    await query.edit_message_text(
        t("menu_create_new_event", lang=user_lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
