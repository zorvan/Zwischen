#!/usr/bin/env python3
"""Menu callback handlers - respond to inline keyboard button presses."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from bot.common.menus import (
    build_main_menu,
    build_event_detail_keyboard,
    build_back_to_menu_keyboard,
    build_help_keyboard,
)
from bot.common.rbac import check_group_membership, check_event_visibility_and_get_event
from config.settings import settings
from db.connection import get_session
from db.models import Event, Group, EventParticipant

logger = logging.getLogger("coord_bot.menus")

EVENTS_PER_PAGE = 5


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all menu callback queries."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data

    # Route to appropriate handler
    if data == "menu_main":
        await _show_main_menu(query, context)
    elif data == "menu_my_events":
        await _show_my_events(query, context, page=0)
    elif data.startswith("menu_events_prev_"):
        page = int(data.split("_")[-1])
        await _show_my_events(query, context, page=max(0, page - 1))
    elif data.startswith("menu_events_next_"):
        page = int(data.split("_")[-1])
        await _show_my_events(query, context, page=page + 1)
    elif data.startswith("menu_event_select_"):
        event_id = int(data.split("_")[-1])
        await _show_event_detail(query, context, event_id)
    elif data == "menu_my_profile":
        await _redirect_to_profile(query, context)
    elif data == "menu_history":
        await _redirect_to_history(query, context)
    elif data == "menu_organize":
        await _redirect_to_organize(query, context)
    elif data == "menu_modify":
        await _redirect_to_modify(query, context)
    elif data == "menu_groups":
        await _redirect_to_groups(query, context)
    elif data == "menu_help":
        await _show_help(query, context)
    elif data == "menu_about":
        await _redirect_to_about(query, context)
    elif data.startswith("help_"):
        await _show_help_topic(query, context, data.split("_", 1)[1])
    elif data == "noop":
        # No operation button (e.g., "Already Confirmed")
        pass
    else:
        logger.warning(f"Unknown menu callback: {data}")


async def _show_main_menu(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the main menu."""
    await query.edit_message_text(
        "🏠 *Main Menu*\n\n"
        "Choose an option below:\n\n"
        "📋 *My Events* - View and manage your events\n"
        "👤 *My Profile* - Check your stats\n"
        "📜 *History* - Browse your event history\n"
        "✏️ *Organize* - Create a new event\n"
        "🔧 *Modify* - Modify an existing event\n"
        "👥 *Groups* - View your groups\n"
        "❓ *Help* - Get help and tips",
        reply_markup=build_main_menu(),
        parse_mode="Markdown",
    )


async def _show_my_events(query, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """Show user's events with clickable buttons."""
    user_id = query.from_user.id
    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        # Get events where user is a participant
        result = await session.execute(
            select(EventParticipant.event_id)
            .where(EventParticipant.telegram_user_id == user_id)
            .distinct()
        )
        participant_event_ids = [row[0] for row in result.all()]

        # Get recent events (prioritize user's events)
        query_events = (
            select(Event, Group)
            .join(Group, Event.group_id == Group.group_id, isouter=True)
            .order_by(Event.created_at.desc())
            .limit(20)
        )

        result = await session.execute(query_events)
        all_events = result.all()

        # Filter by group membership and sort: user's events first, then others
        user_events = []
        other_events = []
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        for event, group in all_events:
            # Skip events with no group
            if not group:
                continue

            # Check group membership
            is_member, _ = await check_group_membership(
                session, group.group_id, user_id,
                telegram_chat_id=chat_id,
                bot=context.bot,
            )
            if not is_member:
                # Non-member: skip this event
                continue

            if event.event_id in participant_event_ids:
                user_events.append((event, group))
            else:
                other_events.append((event, group))

        # Combine and paginate
        sorted_events = user_events + other_events

        if not sorted_events:
            await query.edit_message_text(
                "ℹ️ *No Events Found*\n\n"
                "You haven't joined any events yet.\n\n"
                "Use the menu below to get started!",
                reply_markup=build_main_menu(),
                parse_mode="Markdown",
            )
            return

        # Paginate
        start_idx = page * EVENTS_PER_PAGE
        end_idx = start_idx + EVENTS_PER_PAGE
        page_events = sorted_events[start_idx:end_idx]

        if not page_events:
            # Page is empty, go back to last page
            max_page = (len(sorted_events) - 1) // EVENTS_PER_PAGE
            if page > 0:
                await _show_my_events(query, context, page=max_page)
                return
            else:
                await query.edit_message_text(
                    "ℹ️ *No Events Found*",
                    reply_markup=build_back_to_menu_keyboard(),
                    parse_mode="Markdown",
                )
                return

        # Build message with event list
        lines = ["📋 *Your Events*", ""]

        # Add each event as a numbered item
        for idx, (event, group) in enumerate(page_events, start=start_idx + 1):
            group_name = (
                group.group_name[:20]
                if group and group.group_name
                else "Private"
            )
            time_str = event.scheduled_time.strftime("%m-%d %H:%M") if event.scheduled_time else "TBD"
            desc = (event.description or "No description")[:40]
            if len(desc) == 40:
                desc += "..."

            # Three-word description + ID as requested
            words = (event.description or "Event").split()[:3]
            short_desc = " ".join(words)

            # Escape any underscores in descriptions and group names
            short_desc_escaped = short_desc.replace("_", "\\_")
            group_name_escaped = group_name.replace("_", "\\_")
            time_str_escaped = time_str.replace("_", "\\_")
            state_escaped = event.state.replace("_", "\\_")

            lines.append(f"{idx}. ID `{event.event_id}` - {short_desc_escaped}")
            lines.append(f"   {time_str_escaped} | {state_escaped} | {group_name_escaped}")
            lines.append("")

        # Add instruction
        lines.append("💡 *Tap a button below to view event details*")
        lines.append(f"📄 Page {page + 1} of {(len(sorted_events) - 1) // EVENTS_PER_PAGE + 1}")

        # Build keyboard with event selection buttons
        keyboard = []
        for idx, (event, group) in enumerate(page_events, start=start_idx + 1):
            words = (event.description or "Event").split()[:3]
            short_desc = " ".join(words)
            keyboard.append([
                InlineKeyboardButton(
                    f"{idx}. {short_desc} (#{event.event_id})",
                    callback_data=f"menu_event_select_{event.event_id}"
                )
            ])

        # Navigation
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"menu_events_prev_{page}"))
        if end_idx < len(sorted_events):
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"menu_events_next_{page}"))

        if nav_row:
            keyboard.append(nav_row)

        keyboard.append([
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_main"),
        ])

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )


async def _show_event_detail(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Show detailed view of a specific event."""
    from bot.common.event_presenters import format_status_message
    from bot.services import ParticipantService

    db_url = settings.db_url or ""
    user_id = query.from_user.id

    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = (
            await check_event_visibility_and_get_event(
                session, event_id, user_id,
                telegram_chat_id=chat_id,
                bot=context.bot,
            )
        )

        if not is_visible:
            await query.edit_message_text(
                f"❌ {error_msg or 'Event not found.'}",
                reply_markup=build_back_to_menu_keyboard(),
            )
            return

        # Get user's participation status
        result = await session.execute(
            select(EventParticipant)
            .where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == user_id
            )
        )
        participant = result.scalar_one_or_none()
        user_status = participant.status.value if participant else None

        # Format event details using existing presenter
        _participant_service = ParticipantService(session)  # noqa: F841
        status_message = await format_status_message(
            event_id=event_id,
            event=event,
            log_count=0,  # Would need to fetch
            constraint_count=0,  # Would need to fetch
            bot=context.bot,
            user_participant=participant,
            session=session,
        )

        # Add instruction text
        status_message += "\n\n💡 Use the buttons below to interact with this event"

        try:
            await query.edit_message_text(
                status_message,
                reply_markup=build_event_detail_keyboard(
                    event_id=event_id,
                    user_status=user_status,
                    event_state=event.state,
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            if "Can't parse entities" in str(e):
                # Fallback to plain text if Markdown parsing fails
                await query.edit_message_text(
                    status_message.replace("*", "").replace("_", ""),
                    reply_markup=build_event_detail_keyboard(
                        event_id=event_id,
                        user_status=user_status,
                        event_state=event.state,
                    ),
                )
            else:
                raise


async def _show_help(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help menu."""
    await query.edit_message_text(
        "❓ *Help & Information*\n\n"
        "Choose a topic below:",
        reply_markup=build_help_keyboard(),
        parse_mode="Markdown",
    )


async def _show_help_topic(query, context: ContextTypes.DEFAULT_TYPE, topic: str) -> None:
    """Show specific help topic."""
    topics = {
        "start": (
            "📖 *Getting Started*\n\n"
            "Welcome to the Coordination Bot!\n\n"
            "• Use *Organize Event* to create events\n"
            "• Browse *My Events* to see your events\n"
            "• Tap an event to join or manage it\n"
            "• Set your *Availability* to help scheduling\n\n"
            "The bot uses AI to find optimal times for everyone!"
        ),
        "events": (
            "🎯 *How Events Work*\n\n"
            "1. *Proposed* - Event is gathering interest\n"
            "2. *Interested* - People have joined\n"
            "3. *Confirmed* - Enough people committed\n"
            "4. *Locked* - Event is finalized\n"
            "5. *Completed* - Event happened!\n\n"
            "You need to reach the *threshold* number of confirmations to lock an event."
        ),
        "scheduling": (
            "📅 *Scheduling*\n\n"
            "• Events can have *fixed* or *flexible* times\n"
            "• Use *Set Availability* to share your free slots\n"
            "• The bot suggests optimal times\n"
            "• More availability = better scheduling!"
        ),
    }

    text = topics.get(topic, "❓ Help topic not found.")

    await query.edit_message_text(
        text,
        reply_markup=build_help_keyboard(),
        parse_mode="Markdown",
    )


# Redirect handlers - these show a message telling user to use the command
async def _redirect_to_profile(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect to profile command."""
    await query.edit_message_text(
        "Your Profile\n\n"
        "Please use /profile command to view your full profile and stats.",
        reply_markup=build_back_to_menu_keyboard(),
    )


async def _redirect_to_history(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect to history command."""
    await query.edit_message_text(
        "Your History\n\n"
        "Please use /my_history command to view your event timeline.",
        reply_markup=build_back_to_menu_keyboard(),
    )


async def _redirect_to_organize(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect to organize command."""
    await query.edit_message_text(
        "Organize Event\n\n"
        "Please use /organize_event command in a group chat to create an event.\n\n"
        "Or use /private_organize_event to create a private locked event.",
        reply_markup=build_back_to_menu_keyboard(),
    )


async def _redirect_to_modify(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect to modify command."""
    await query.edit_message_text(
        "Modify Event\n\n"
        "Please use /modify_event <event_id> command to modify an event.\n\n"
        "Or select an event from My Events and use the Modify button.",
        reply_markup=build_back_to_menu_keyboard(),
    )


async def _redirect_to_groups(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect to groups command."""
    await query.edit_message_text(
        "Your Groups\n\n"
        "Please use /my_groups command to view your groups.",
        reply_markup=build_back_to_menu_keyboard(),
    )


async def _redirect_to_about(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect to about command."""
    await query.edit_message_text(
        "🤖 About\n\n"
        "Please use /about command to learn more about the bot.",
        reply_markup=build_back_to_menu_keyboard(),
    )
