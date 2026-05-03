#!/usr/bin/env python3
"""Menu callback handlers - respond to inline keyboard button presses."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, update as sa_update

from bot.common.i18n import t, get_user_language
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


async def handle_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle all menu callback queries."""
    import asyncio

    query = update.callback_query
    if not query:
        return

    user_lang = await get_user_language(query.from_user, user_data=context.user_data)

    try:
        await asyncio.wait_for(query.answer(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    data = query.data

    # Route to appropriate handler
    if data == "menu_main":
        await _show_main_menu(query, context, user_lang)
    elif data == "menu_my_events":
        await _show_my_events(query, context, page=0, user_lang=user_lang)
    elif data.startswith("menu_events_prev_"):
        page = int(data.split("_")[-1])
        await _show_my_events(
            query, context, page=max(0, page - 1), user_lang=user_lang
        )
    elif data.startswith("menu_events_next_"):
        page = int(data.split("_")[-1])
        await _show_my_events(query, context, page=page + 1, user_lang=user_lang)
    elif data.startswith("menu_event_select_"):
        event_id = int(data.split("_")[-1])
        # v3.5: Route to event panel (Level 2) instead of old detail view
        from bot.handlers import event_panel

        await event_panel._handle_view(query, context, event_id)
    elif data == "menu_my_profile":
        await _redirect_to_profile(query, context, user_lang)
    elif data == "menu_history":
        await _redirect_to_history(query, context, user_lang)
    elif data == "menu_organize":
        await _redirect_to_organize(query, context, user_lang)
    elif data == "organize_public":
        await _handle_organize_public(query, context)
    elif data == "organize_private":
        await _handle_organize_private(query, context)
    elif data == "menu_modify":
        await _redirect_to_modify(query, context, user_lang)
    elif data == "menu_groups":
        await _redirect_to_groups(query, context, user_lang)
    elif data == "menu_help":
        await _show_help(query, context, user_lang)
    elif data.startswith("help_"):
        await _show_help_topic(query, context, data.split("_", 1)[1], user_lang)
    elif data == "noop":
        # No operation button (e.g., "Already Confirmed")
        pass
    # v3.5: Events list Create button handlers
    elif data == "events_create_new":
        await _handle_create_new_event(query, context, user_lang)
    elif data == "create_specific":
        await _handle_create_specific(query, context)
    elif data == "create_flexible":
        await _handle_create_flexible(query, context)
    elif data == "events_back":
        await _show_my_events(query, context, page=0, user_lang=user_lang)
    else:
        logger.warning(f"Unknown menu callback: {data}")


async def _show_main_menu(
    query, context: ContextTypes.DEFAULT_TYPE, user_lang: str
) -> None:
    """Show the main menu."""
    await query.edit_message_text(
        t("main_menu_welcome", lang=user_lang),
        reply_markup=build_main_menu(lang=user_lang),
        parse_mode="HTML",
    )


async def _show_my_events(
    query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, user_lang: str = "en"
) -> None:
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
                    t("menu_my_events_no_events", lang=user_lang),
                    reply_markup=build_main_menu(lang=user_lang),
                    parse_mode="HTML",
                )
            except Exception:
                await query.answer(t("menu_my_events_no_events", lang=user_lang))
            return

        # Paginate
        start_idx = page * EVENTS_PER_PAGE
        end_idx = start_idx + EVENTS_PER_PAGE
        page_events = sorted_events[start_idx:end_idx]

        if not page_events:
            # Page is empty, go back to last page
            max_page = (len(sorted_events) - 1) // EVENTS_PER_PAGE
            if page > 0:
                await _show_my_events(
                    query, context, page=max_page, user_lang=user_lang
                )
                return
            else:
                try:
                    await query.edit_message_text(
                        t("menu_my_events_no_events", lang=user_lang),
                        reply_markup=build_back_to_menu_keyboard(lang=user_lang),
                        parse_mode="HTML",
                    )
                except Exception:
                    await query.answer(t("menu_my_events_no_events", lang=user_lang))
                return

        # Build message with event list
        lines = [t("menu_my_events_title", lang=user_lang), ""]

        # Add each event as a numbered item
        for idx, (event, group) in enumerate(page_events, start=start_idx + 1):
            group_name = (
                group.group_name[:20] if group and group.group_name else "Private"
            )
            time_str = (
                event.scheduled_time.strftime("%m-%d %H:%M")
                if event.scheduled_time
                else "TBD"
            )
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
            lines.append(
                f"   {time_str_escaped} | {state_escaped} | {group_name_escaped}"
            )
            lines.append("")

        # Add instruction
        lines.append(t("menu_my_events_tap_hint", lang=user_lang))
        lines.append(
            f"📄 Page {page + 1} of {(len(sorted_events) - 1) // EVENTS_PER_PAGE + 1}"
        )

        # Build keyboard with event selection buttons
        keyboard = []
        for idx, (event, group) in enumerate(page_events, start=start_idx + 1):
            words = (event.description or "Event").split()[:3]
            short_desc = " ".join(words)
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{idx}. {short_desc}",
                        callback_data=f"menu_event_select_{event.event_id}",
                    )
                ]
            )

        # Navigation
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    t("menu_my_events_prev", lang=user_lang),
                    callback_data=f"menu_events_prev_{page}",
                )
            )
        if end_idx < len(sorted_events):
            nav_row.append(
                InlineKeyboardButton(
                    t("menu_my_events_next", lang=user_lang),
                    callback_data=f"menu_events_next_{page}",
                )
            )

        if nav_row:
            keyboard.append(nav_row)

        keyboard.append(
            [
                InlineKeyboardButton(
                    t("menu_my_events_back", lang=user_lang), callback_data="menu_main"
                ),
            ]
        )

        try:
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception:
            await query.answer(t("menu_my_events_title", lang=user_lang))


async def _show_event_detail(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show detailed view of a specific event."""
    from bot.common.event_presenters import format_status_message

    db_url = settings.db_url or ""
    user_id = query.from_user.id
    user_lang = await get_user_language(query.from_user, user_data=context.user_data)

    async with get_session(db_url) as session:
        # Check event visibility based on group membership
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = (
            await check_event_visibility_and_get_event(
                session,
                event_id,
                user_id,
                telegram_chat_id=chat_id,
                bot=context.bot,
            )
        )

        if not is_visible:
            try:
                await query.edit_message_text(
                    t(
                        "event_details_event_not_visible",
                        lang=user_lang,
                        error_msg=error_msg or "",
                    ),
                    reply_markup=build_back_to_menu_keyboard(lang=user_lang),
                )
            except Exception:
                await query.answer(
                    t(
                        "event_details_event_not_visible",
                        lang=user_lang,
                        error_msg=error_msg or "",
                    )
                )
            return

        # Get user's participation status
        result = await session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == user_id,
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
        status_message += "\n\n" + t("menu_event_detail_hint", lang=user_lang)

        try:
            await query.edit_message_text(
                status_message,
                reply_markup=build_event_detail_keyboard(
                    event_id=event_id,
                    user_status=user_status,
                    event_state=event.state,
                    lang=user_lang,
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
                            lang=user_lang,
                        ),
                    )
                except Exception:
                    await query.answer(t("menu_my_events_title", lang=user_lang))
            elif "Message is not modified" in str(e):
                await query.answer(
                    t("event_details_already_up_to_date", lang=user_lang)
                )
            else:
                raise


async def _show_help(query, context: ContextTypes.DEFAULT_TYPE, user_lang: str) -> None:
    """Show help menu."""
    await query.edit_message_text(
        t("menu_help_title", lang=user_lang),
        reply_markup=build_help_keyboard(lang=user_lang),
        parse_mode="HTML",
    )


async def _show_help_topic(
    query, context: ContextTypes.DEFAULT_TYPE, topic: str, user_lang: str
) -> None:
    """Show specific help topic."""
    topics = {
        "start": "menu_help_start",
        "events": "menu_help_events",
        "scheduling": "menu_help_scheduling",
    }

    key = topics.get(topic, "menu_help_topic_not_found")
    text = t(key, lang=user_lang)

    await query.edit_message_text(
        text,
        reply_markup=build_help_keyboard(lang=user_lang),
        parse_mode="HTML",
    )


# Redirect handlers - these show a message telling user to use the command
async def _redirect_to_profile(
    query, context: ContextTypes.DEFAULT_TYPE, user_lang: str
) -> None:
    """Redirect to profile command."""
    await query.edit_message_text(
        t("menu_redirect_profile", lang=user_lang),
        reply_markup=build_back_to_menu_keyboard(lang=user_lang),
    )


async def _redirect_to_history(
    query, context: ContextTypes.DEFAULT_TYPE, user_lang: str
) -> None:
    """Redirect to history command."""
    await query.edit_message_text(
        t("menu_redirect_history", lang=user_lang),
        reply_markup=build_back_to_menu_keyboard(lang=user_lang),
    )


async def _redirect_to_organize(
    query, context: ContextTypes.DEFAULT_TYPE, user_lang: str
) -> None:
    """Redirect to organize command."""
    keyboard = [
        [
            InlineKeyboardButton(
                t("menu_organize_public", lang=user_lang),
                callback_data="organize_public",
            )
        ],
        [
            InlineKeyboardButton(
                t("menu_organize_private", lang=user_lang),
                callback_data="organize_private",
            )
        ],
        [
            InlineKeyboardButton(
                t("menu_my_events_back", lang=user_lang), callback_data="menu_main"
            )
        ],
    ]

    await query.edit_message_text(
        t("menu_redirect_organize", lang=user_lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def _handle_organize_public(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle public/group event creation."""
    from bot.commands.event_creation import start_event_flow

    await start_event_flow(
        context=context,
        mode="public",
        callback_query=query,
    )


async def _handle_organize_private(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle private event creation."""
    from bot.commands.event_creation import start_event_flow

    await start_event_flow(
        context=context,
        mode="private",
        callback_query=query,
    )


async def _redirect_to_modify(
    query, context: ContextTypes.DEFAULT_TYPE, user_lang: str
) -> None:
    """Redirect to modify command."""
    await query.edit_message_text(
        t("menu_redirect_modify", lang=user_lang),
        reply_markup=build_back_to_menu_keyboard(lang=user_lang),
    )


async def _redirect_to_groups(
    query, context: ContextTypes.DEFAULT_TYPE, user_lang: str
) -> None:
    """Redirect to groups command."""
    await query.edit_message_text(
        t("menu_redirect_groups", lang=user_lang),
        reply_markup=build_back_to_menu_keyboard(lang=user_lang),
    )


# =============================================================================
# v3.5: Memory-First Creation Flow Handlers
# =============================================================================


async def _handle_create_new_event(
    query, context: ContextTypes.DEFAULT_TYPE, user_lang: str
) -> None:
    """Show memory-first creation intent selection."""
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
        parse_mode="HTML",
    )


async def _handle_create_specific(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Plan something specific' - structured creation."""
    from bot.commands.event_creation import start_event_flow

    # Store intent in context
    context.user_data["creation_intent"] = "specific"

    # Get the event type from the message
    event_type = (
        query.message.text.strip() if query.message and query.message.text else ""
    )

    # Start the unified event creation flow via callback_query
    await start_event_flow(
        context=context,
        mode="public",
        callback_query=query,
    )

    # Pre-fill the event type in the flow data
    if context.user_data:
        flow = context.user_data.get("event_flow")
        if isinstance(flow, dict) and isinstance(flow.get("data"), dict):
            flow["data"]["event_type"] = event_type if event_type else "social"
            flow["data"]["description"] = f"Planning {event_type}" if event_type else ""
            context.user_data["event_flow"] = flow


async def _handle_create_flexible(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Just exploring ideas' - flexible creation."""
    from bot.commands.event_creation import start_event_flow

    # Store intent in context
    context.user_data["creation_intent"] = "flexible"

    # Start the unified event creation flow via callback_query
    await start_event_flow(
        context=context,
        mode="public",
        callback_query=query,
    )


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
    from bot.services.state_store import get_state_store
    from datetime import datetime, timezone

    if not update.message or not update.effective_user:
        return

    text = update.message.text or ""
    user_id = update.effective_user.id
    user_lang = await get_user_language(
        update.effective_user, user_data=context.user_data
    )

    async with get_session(settings.db_url) as session:
        enrichment_service = EventEnrichmentService(session)

        try:
            if action == "add_idea":
                await enrichment_service.add_idea(event_id, user_id, text)
                keyboard = [
                    [
                        InlineKeyboardButton(
                            t("event_details_back_to_panel", lang=user_lang),
                            callback_data=f"ev:{event_id}:view",
                        )
                    ]
                ]
                await update.message.reply_text(
                    t("enrichment_idea_saved", lang=user_lang),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )

            elif action == "add_hashtag":
                hashtag = text.strip()
                if not hashtag.startswith("#"):
                    hashtag = f"#{hashtag}"
                await enrichment_service.add_hashtag(event_id, user_id, hashtag)
                keyboard = [
                    [
                        InlineKeyboardButton(
                            t("event_details_back_to_panel", lang=user_lang),
                            callback_data=f"ev:{event_id}:view",
                        )
                    ]
                ]
                await update.message.reply_text(
                    t("enrichment_hashtag_saved", lang=user_lang),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )

            elif action == "add_memory":
                await enrichment_service.add_memory(event_id, user_id, text)
                keyboard = [
                    [
                        InlineKeyboardButton(
                            t("event_details_back_to_panel", lang=user_lang),
                            callback_data=f"ev:{event_id}:view",
                        )
                    ]
                ]
                await update.message.reply_text(
                    t("enrichment_memory_saved", lang=user_lang),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )

            elif action in {"add_constraint", "add_constraint_unless"}:
                event_result = await session.execute(
                    select(Event).where(Event.event_id == event_id)
                )
                event = event_result.scalar_one_or_none()
                planning_prefs = (
                    event.planning_prefs.copy()
                    if event and event.planning_prefs
                    else {}
                )
                constraint_key = "member_constraints"
                planning_prefs.setdefault(constraint_key, [])
                planning_prefs[constraint_key].append(
                    {
                        "type": (
                            "if_joins" if action == "add_constraint" else "unless_joins"
                        ),
                        "text": text,
                        "submitted_by": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                await session.execute(
                    sa_update(Event)
                    .where(Event.event_id == event_id)
                    .values(planning_prefs=planning_prefs)
                )
                keyboard = [
                    [
                        InlineKeyboardButton(
                            t("event_details_back_to_panel", lang=user_lang),
                            callback_data=f"ev:{event_id}:view",
                        )
                    ]
                ]
                await update.message.reply_text(
                    t("enrichment_constraint_saved", lang=user_lang),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )

            elif action == "suggest_time":
                event_result = await session.execute(
                    select(Event).where(Event.event_id == event_id)
                )
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
                    sa_update(Event)
                    .where(Event.event_id == event_id)
                    .values(planning_prefs=planning_prefs)
                )
                await session.flush()

                keyboard = [
                    [
                        InlineKeyboardButton(
                            t("event_details_back_to_panel", lang=user_lang),
                            callback_data=f"ev:{event_id}:view",
                        )
                    ]
                ]
                await update.message.reply_text(
                    t("enrichment_time_saved", lang=user_lang),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )

            await session.commit()

        except Exception as e:
            logger.error(
                "Enrichment save failed for event %d, action %s: %s",
                event_id,
                action,
                e,
            )
            keyboard = [
                [
                    InlineKeyboardButton(
                        t("event_details_back_to_panel", lang=user_lang),
                        callback_data=f"ev:{event_id}:view",
                    )
                ]
            ]
            await update.message.reply_text(
                t("enrichment_save_failed", lang=user_lang, error=str(e)[:200]),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    # Clear enrichment state
    store = get_state_store(user_id, context.user_data)
    store.clear_enrichment_session()


# =============================================================================
# Message Handler for Creation Flow
# =============================================================================


async def handle_creation_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle text messages during enrichment prompts.

    This handler processes user input for enrichment prompts only.
    The creation flow is now handled by event_creation.py.
    """
    if not update.message or not update.effective_user:
        return

    # Ensure user_data is a dict we can work with
    if context.user_data is None:
        context.user_data = {}

    # Check if we're in an enrichment flow (using session-based state)
    from bot.services.state_store import get_state_store

    store = get_state_store(update.effective_user.id, context.user_data)
    session = store.get_enrichment_session()

    if not session:
        return  # Not in enrichment flow, let other handlers process

    enrich_event_id = session["event_id"]
    enrich_action = session["action"]

    try:
        await _handle_enrichment_message(
            update, context, enrich_event_id, enrich_action
        )
    except Exception as e:
        logger.exception("Error in handle_creation_message: %s", e)
        user_lang = await get_user_language(
            update.effective_user, user_data=context.user_data
        )
        await update.message.reply_text(t("enrichment_error", lang=user_lang))
