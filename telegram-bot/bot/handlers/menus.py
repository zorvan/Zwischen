#!/usr/bin/env python3
"""Menu callback handlers - respond to inline keyboard button presses."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, update as sa_update

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
    import asyncio

    query = update.callback_query
    if not query:
        return

    try:
        await asyncio.wait_for(query.answer(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

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
        # v3.5: Route to event panel (Level 2) instead of old detail view
        from bot.handlers import event_panel

        await event_panel._handle_view(query, context, event_id)
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
    elif data.startswith("help_"):
        await _show_help_topic(query, context, data.split("_", 1)[1])
    elif data == "noop":
        # No operation button (e.g., "Already Confirmed")
        pass
    # v3.5: Events list Create button handlers
    elif data == "events_create_new":
        await _handle_create_new_event(query, context)
    elif data == "create_specific":
        await _handle_create_specific(query, context)
    elif data == "create_flexible":
        await _handle_create_flexible(query, context)
    elif data == "events_back":
        await _show_my_events(query, context, page=0)
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
            select(EventParticipant.event_id).where(EventParticipant.telegram_user_id == user_id).distinct()
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
                session,
                group.group_id,
                user_id,
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
            try:
                await query.edit_message_text(
                    "ℹ️ *No Events Found*\n\n"
                    "You haven't joined any events yet.\n\n"
                    "Use the menu below to get started!",
                    reply_markup=build_main_menu(),
                    parse_mode="Markdown",
                )
            except Exception:
                await query.answer("ℹ️ No events found.")
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
                try:
                    await query.edit_message_text(
                        "ℹ️ *No Events Found*",
                        reply_markup=build_back_to_menu_keyboard(),
                        parse_mode="Markdown",
                    )
                except Exception:
                    await query.answer("ℹ️ No events found.")
                return

        # Build message with event list
        lines = ["📋 *Your Events*", ""]

        # Add each event as a numbered item
        for idx, (event, group) in enumerate(page_events, start=start_idx + 1):
            group_name = group.group_name[:20] if group and group.group_name else "Private"
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

            lines.append(f"{idx}. {short_desc_escaped}")
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
            keyboard.append(
                [InlineKeyboardButton(f"{idx}. {short_desc}", callback_data=f"menu_event_select_{event.event_id}")]
            )

        # Navigation
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"menu_events_prev_{page}"))
        if end_idx < len(sorted_events):
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"menu_events_next_{page}"))

        if nav_row:
            keyboard.append(nav_row)

        keyboard.append(
            [
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu_main"),
            ]
        )

        try:
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception:
            await query.answer("ℹ️ Events list refreshed.")


async def _show_event_detail(query, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Show detailed view of a specific event."""
    from bot.common.event_presenters import format_status_message

    db_url = settings.db_url or ""
    user_id = query.from_user.id

    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
            session,
            event_id,
            user_id,
            telegram_chat_id=chat_id,
            bot=context.bot,
        )

        if not is_visible:
            try:
                await query.edit_message_text(
                    f"❌ {error_msg or 'Event not found.'}",
                    reply_markup=build_back_to_menu_keyboard(),
                )
            except Exception:
                await query.answer(f"❌ {error_msg or 'Event not found.'}")
            return

        # Get user's participation status
        result = await session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id, EventParticipant.telegram_user_id == user_id
            )
        )
        participant = result.scalar_one_or_none()
        user_status = participant.status.value if participant else None

        # Format event details using existing presenter
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
                try:
                    await query.edit_message_text(
                        status_message.replace("*", "").replace("_", ""),
                        reply_markup=build_event_detail_keyboard(
                            event_id=event_id,
                            user_status=user_status,
                            event_state=event.state,
                        ),
                    )
                except Exception:
                    await query.answer("ℹ️ Event details refreshed.")
            elif "Message is not modified" in str(e):
                await query.answer("ℹ️ Already up to date.")
            else:
                raise


async def _show_help(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help menu."""
    await query.edit_message_text(
        "❓ *Help & Information*\n\n" "Choose a topic below:",
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
        "Your Profile\n\n" "Please use /profile command to view your full profile and stats.",
        reply_markup=build_back_to_menu_keyboard(),
    )


async def _redirect_to_history(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect to history command."""
    await query.edit_message_text(
        "Your History\n\n" "Please use /my_history command to view your event timeline.",
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
        "Your Groups\n\n" "Please use /my_groups command to view your groups.",
        reply_markup=build_back_to_menu_keyboard(),
    )


# =============================================================================
# v3.5: Memory-First Creation Flow Handlers
# =============================================================================


async def _handle_create_new_event(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show memory-first creation intent selection."""
    keyboard = [
        [InlineKeyboardButton("🎯 Plan something specific", callback_data="create_specific")],
        [InlineKeyboardButton("💭 Just exploring ideas", callback_data="create_flexible")],
        [InlineKeyboardButton("🔙 Back to Events", callback_data="events_back")],
    ]

    await query.edit_message_text(
        "🌟 *Let's create something together*\n\n"
        "What brings you here?\n\n"
        "• *Plan something specific* — You have an idea in mind\n"
        "• *Just exploring ideas* — Open to suggestions\n\n"
        "💡 *Your intent shapes what we build*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def _handle_create_specific(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Plan something specific' - structured creation."""
    # Store intent in context for the creation flow
    context.user_data["creation_intent"] = "specific"

    await query.edit_message_text(
        "🎯 *Planning something specific*\n\n"
        "Great! Let's build this together.\n\n"
        "What's the occasion? (e.g., 'hiking', 'dinner', 'meeting')\n\n"
        "💡 *Type your answer or use /cancel to stop*",
        parse_mode="Markdown",
    )

    # Set conversation state for the creation flow
    context.user_data["creation_step"] = "awaiting_event_type"


async def _handle_create_flexible(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Just exploring ideas' - flexible creation."""
    # Store intent in context
    context.user_data["creation_intent"] = "flexible"

    await query.edit_message_text(
        "💭 *Exploring ideas together*\n\n"
        "Perfect! Let's discover what might work.\n\n"
        "Tell me what you're in the mood for, or what constraints you have.\n"
        "(e.g., 'something outdoors this weekend', 'low-key evening with friends')\n\n"
        "💭 *Be as vague or specific as you like*",
        parse_mode="Markdown",
    )

    # Set conversation state
    context.user_data["creation_step"] = "awaiting_flexible_input"


# =============================================================================
# Enrichment Message Handler
# =============================================================================


async def _handle_enrichment_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    action: str,
) -> None:
    """Process user text input for enrichment actions."""
    from db.models import Event
    from db.connection import get_session
    from config.settings import settings
    from bot.services.event_enrichment_service import EventEnrichmentService
    from datetime import datetime, timezone

    if not update.message or not update.effective_user:
        return

    text = update.message.text or ""
    user_id = update.effective_user.id

    async with get_session(settings.db_url) as session:
        enrichment_service = EventEnrichmentService(session)

        try:
            if action == "add_idea":
                await enrichment_service.add_idea(event_id, user_id, text)
                await update.message.reply_text("✅ Idea saved! (visible to organizer until event locks)")

            elif action == "add_hashtag":
                hashtag = text.strip()
                if not hashtag.startswith("#"):
                    hashtag = f"#{hashtag}"
                await enrichment_service.add_hashtag(event_id, user_id, hashtag)
                await update.message.reply_text(
                    "✅ Hashtag saved! Hashtags become public on the live card when 2+ people add the same tag."
                )

            elif action == "add_memory":
                await enrichment_service.add_memory(event_id, user_id, text)
                await update.message.reply_text(
                    "✅ Memory saved! (private until mosaic assembles when event completes)"
                )

            elif action in {"add_constraint", "add_constraint_unless"}:
                event_result = await session.execute(select(Event).where(Event.event_id == event_id))
                event = event_result.scalar_one_or_none()
                planning_prefs = event.planning_prefs.copy() if event and event.planning_prefs else {}
                constraint_key = "member_constraints"
                planning_prefs.setdefault(constraint_key, [])
                planning_prefs[constraint_key].append(
                    {
                        "type": "if_joins" if action == "add_constraint" else "unless_joins",
                        "text": text,
                        "submitted_by": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                await session.execute(
                    sa_update(Event).where(Event.event_id == event_id).values(planning_prefs=planning_prefs)
                )
                await update.message.reply_text("✅ Constraint saved! The organizer will see it on the event.")

            elif action == "suggest_time":
                event_result = await session.execute(select(Event).where(Event.event_id == event_id))
                event = event_result.scalar_one_or_none()
                if event and event.planning_prefs:
                    planning_prefs = event.planning_prefs.copy()
                else:
                    planning_prefs = {}

                if "time_suggestions" not in planning_prefs:
                    planning_prefs["time_suggestions"] = []
                planning_prefs["time_suggestions"].append(
                    {
                        "suggestion": text,
                        "suggested_by": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

                await session.execute(
                    sa_update(Event).where(Event.event_id == event_id).values(planning_prefs=planning_prefs)
                )
                await session.flush()

                await update.message.reply_text(
                    "✅ Time suggestion saved! The organizer will see your preferred time."
                )

            await session.commit()

        except Exception as e:
            logger.error("Enrichment save failed for event %d, action %s: %s", event_id, action, e)
            await update.message.reply_text(f"❌ Failed to save: {str(e)[:200]}")

    # Clear enrichment state
    context.user_data["enrich_event_id"] = None
    context.user_data["enrich_action"] = None


# =============================================================================
# Message Handler for Creation Flow
# =============================================================================


async def handle_creation_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages during memory-first creation flow.

    This handler processes user input when creation_step is set in user_data.
    It bridges the menu-based creation flow to the event creation system.
    Also handles enrichment prompts (idea, hashtag, memory, constraint, suggest_time).
    """
    if not update.message or not update.effective_user:
        return

    # Ensure user_data is a dict we can work with
    if context.user_data is None:
        context.user_data = {}

    # Check if we're in a creation flow
    creation_step = context.user_data.get("creation_step")
    enrich_event_id = context.user_data.get("enrich_event_id")
    enrich_action = context.user_data.get("enrich_action")

    # Check enrichment flow first (it takes priority over creation_step)
    if enrich_event_id and enrich_action:
        await _handle_enrichment_message(update, context, enrich_event_id, enrich_action)
        return

    if not creation_step:
        return  # Not in creation flow, let other handlers process

    try:
        user_id = update.effective_user.id
        text = update.message.text or ""

        if creation_step == "awaiting_event_type":
            # User provided event type for specific creation
            event_type = text.strip()
            if not event_type:
                await update.message.reply_text("❌ Please provide an event type (e.g., 'hiking', 'dinner').")
                return

            # Initialize the event flow in the format expected by event_creation.py
            context.user_data["event_flow"] = {
                "stage": "time",  # Skip description, go straight to scheduling
                "data": {
                    "event_type": event_type,
                    "description": f"Planning {event_type}",
                    "organizer_id": user_id,
                },
                "participants": [user_id],
            }
            context.user_data["creation_step"] = None  # Clear creation step

            # Show scheduling options
            keyboard = [
                [InlineKeyboardButton("📅 Fixed Date/Time", callback_data="event_scheduling_fixed")],
                [InlineKeyboardButton("🤷 Flexible (TBD)", callback_data="event_scheduling_flexible")],
                [InlineKeyboardButton("🔙 Back", callback_data="events_back")],
            ]
            await update.message.reply_text(
                f"✅ *Event type: {event_type}*\n\n" "When would you like to schedule it?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )

        elif creation_step == "awaiting_flexible_input":
            # User provided flexible input
            user_input = text.strip()
            if not user_input:
                await update.message.reply_text("❌ Please tell me what you're looking for.")
                return

            # Initialize flexible event flow
            context.user_data["event_flow"] = {
                "stage": "type",
                "data": {
                    "flexible_input": user_input,
                    "description": user_input,
                    "organizer_id": user_id,
                },
                "participants": [user_id],
            }
            context.user_data["creation_step"] = None  # Clear creation step

            # Show event type selection
            await update.message.reply_text(
                f"💭 *Got it: '{user_input}'*\n\n" "What type of event would best fit?",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🎉 Social", callback_data="event_type_social")],
                        [InlineKeyboardButton("⚽ Sports/Activity", callback_data="event_type_sports")],
                        [InlineKeyboardButton("💼 Work/Meeting", callback_data="event_type_work")],
                        [InlineKeyboardButton("🍽️ Food/Drinks", callback_data="event_type_food")],
                        [InlineKeyboardButton("🎭 Entertainment", callback_data="event_type_entertainment")],
                        [InlineKeyboardButton("🔙 Back", callback_data="events_back")],
                    ]
                ),
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.exception("Error in handle_creation_message: %s", e)
        await update.message.reply_text("❌ Sorry, something went wrong. Please try /events again.")


# =============================================================================
# Scheduling Callback Handlers
# =============================================================================


async def handle_scheduling_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle scheduling option callbacks (fixed vs flexible).

    Transitions to the full event creation flow from event_creation.py.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    # Get the collected data from our creation flow
    event_flow_data = context.user_data.get("event_flow", {})
    flow_data = event_flow_data.get("data", {})

    if not flow_data:
        logger.warning("No event_flow data in user_data")
        await query.edit_message_text("❌ Session expired. Please start again with /events")
        return

    # Extract what we collected
    event_type = flow_data.get("event_type", "General")
    description = flow_data.get("description", f"Planning {event_type}")

    # Get chat info
    chat = query.message.chat if query.message else None
    chat_id = chat.id if chat else None
    chat_title = chat.title if chat else None

    # Look up or create the group to get database group_id
    db_group_id = None
    if chat_id and settings.db_url:
        try:
            async with get_session(settings.db_url) as session:
                result = await session.execute(select(Group).where(Group.telegram_group_id == chat_id))
                group = result.scalar_one_or_none()

                if not group:
                    # Create group if it doesn't exist
                    user_id = query.from_user.id if query.from_user else None
                    group = Group(
                        telegram_group_id=chat_id,
                        group_name=chat_title or str(chat_id),
                        member_list=[user_id] if user_id else [],
                    )
                    session.add(group)
                    await session.commit()
                    await session.refresh(group)

                db_group_id = group.group_id
        except Exception as e:
            logger.warning("Failed to look up/create group: %s", e)

    # Directly create the event flow structure that event_creation.py expects
    # (don't call start_event_flow() as it sends a description prompt)
    full_flow = {
        "stage": "date_preset",
        "data": {
            "event_type": event_type,
            "description": description,
            "creator": query.from_user.id if query.from_user else None,
            "date_preset": "custom",
            "time_window": "evening",
            "location_type": "cafe",
            "budget_level": "medium",
            "transport_mode": "any",
            "planning_notes": [],
            "scheduling_mode": "fixed" if data == "event_scheduling_fixed" else "flexible",
        },
    }

    # Add group info if available (use database group_id, not telegram_group_id)
    if db_group_id:
        full_flow["group_id"] = db_group_id
        full_flow["group_title"] = chat_title
        full_flow["data"]["chat_id"] = chat_id
        full_flow["data"]["chat_title"] = chat_title
    elif chat_id:
        # Fallback: store telegram_group_id for later lookup
        full_flow["data"]["telegram_group_id"] = chat_id
        full_flow["data"]["chat_title"] = chat_title

    context.user_data["event_flow"] = full_flow

    # Show date preset selection
    from bot.commands.event_creation import build_date_preset_markup

    await query.edit_message_text(
        f"✅ *Event: {description}*\n\n"
        f"Type: {event_type}\n"
        f"Mode: {'Fixed date/time' if data == 'event_scheduling_fixed' else 'Flexible (TBD)'}\n\n"
        "📅 *Choose a date preset:*",
        reply_markup=build_date_preset_markup(prefix="event"),
        parse_mode="Markdown",
    )


async def handle_event_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle event type selection for flexible flow.

    Updates the collected data and shows scheduling options.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    # Map callback to event type
    type_map = {
        "event_type_social": "Social",
        "event_type_sports": "Sports/Activity",
        "event_type_work": "Work/Meeting",
        "event_type_food": "Food/Drinks",
        "event_type_entertainment": "Entertainment",
    }

    event_type = type_map.get(data)
    if not event_type:
        logger.warning("Unknown event type callback: %s", data)
        return

    # Get our collected flow data
    event_flow = context.user_data.get("event_flow")
    if event_flow:
        # Update the event type
        event_flow["data"]["event_type"] = event_type
        context.user_data["event_flow"] = event_flow

        # Show scheduling options (same as specific flow)
        keyboard = [
            [InlineKeyboardButton("📅 Fixed Date/Time", callback_data="event_scheduling_fixed")],
            [InlineKeyboardButton("🤷 Flexible (TBD)", callback_data="event_scheduling_flexible")],
            [InlineKeyboardButton("🔙 Back", callback_data="events_back")],
        ]
        await query.edit_message_text(
            f"✅ *Event type: {event_type}*\n\n" "When would you like to schedule it?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
