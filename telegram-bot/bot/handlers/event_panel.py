#!/usr/bin/env python3
"""v3.5 Event Panel Handler.

Redesigned event interaction with:
- Compact callback format (ev:{id}:act)
- Context-aware buttons (different for organizers, participants, non-participants)
- Enrich sub-menu for ideas, hashtags, memories
- Constraint sub-menu for conditional participation

This is the Level 2 interaction in the v3.5 UX hierarchy:
Level 1: /events list -> Level 2: Event Panel -> Level 3: Sub-menus

PRD v3.5 Section 4.3: Event Panel & Command Consolidation
"""
import asyncio
import uuid
from typing import Optional, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from bot.common.callback_data import encode_callback, CALLBACK_ACTIONS
from bot.common.event_states import get_available_actions
from bot.common.event_presenters import format_user_display
from db.models import ParticipantStatus
from bot.services.participant_service import ParticipantService
from bot.services.event_enrichment_service import EventEnrichmentService
from db.models import Event
from db.connection import get_session
from config.settings import settings


# =============================================================================
# Button Builders - Main Panel
# =============================================================================


def build_main_panel_buttons(
    event_id: int,
    user_status: Optional[ParticipantStatus],
    is_organizer: bool,
    event_state: str,
    participant_count: int = 0,
    confirmed_count: int = 0,
    min_participants: int = 2,
    group_id: Optional[int] = None,
) -> List[List[InlineKeyboardButton]]:
    """
    Build context-aware buttons for the event panel.

    Button visibility is driven by get_available_actions() from event_states.py,
    which is the single source of truth for which actions are available.

    Args:
        event_id: Event being viewed
        user_status: Current user's participation status
        is_organizer: Whether user is the event organizer
        event_state: Current event state
        participant_count: Total interested participants
        confirmed_count: Confirmed participants
        min_participants: Minimum needed to proceed

    Returns:
        2D array of InlineKeyboardButton (rows of buttons)
    """
    buttons = []
    user_status_str = user_status.value if user_status else None

    # Get available actions from centralized state machine
    available = get_available_actions(
        user_status=user_status_str,
        event_state=event_state,
        is_organizer=is_organizer,
        confirmed_count=confirmed_count,
        min_participants=min_participants,
    )

    # Details button (always shown as first row)
    buttons.append(
        [
            InlineKeyboardButton(
                "Details",
                callback_data=encode_callback(CALLBACK_ACTIONS["details"], event_id, group_id),
                style="primary",
            ),
        ]
    )

    # Enrich & Constraint (for joined/confirmed participants)
    if "enrich" in available or "constraint" in available:
        row = []
        if "enrich" in available:
            row.append(
                InlineKeyboardButton(
                    "Enrich",
                    callback_data=encode_callback(CALLBACK_ACTIONS["enrich"], event_id, group_id),
                    style="primary",
                )
            )
        if "constraint" in available:
            row.append(
                InlineKeyboardButton(
                    "Constraint",
                    callback_data=encode_callback(CALLBACK_ACTIONS["constraint"], event_id, group_id),
                    style="primary",
                )
            )
        if row:
            buttons.append(row)

    # Primary action row based on event state and user status
    if "locked" in available or event_state == "locked":
        buttons.append(
            [
                InlineKeyboardButton(
                    "Event Locked", callback_data=encode_callback("view", event_id, group_id), style="primary"
                ),
            ]
        )
    elif "join" in available:
        buttons.append(
            [
                InlineKeyboardButton(
                    "Join", callback_data=encode_callback(CALLBACK_ACTIONS["join"], event_id, group_id), style="success"
                ),
            ]
        )
    elif "commit" in available:
        buttons.append(
            [
                InlineKeyboardButton(
                    "Confirm",
                    callback_data=encode_callback(CALLBACK_ACTIONS["commit"], event_id, group_id),
                    style="success",
                ),
                InlineKeyboardButton(
                    "Relinquish",
                    callback_data=encode_callback(CALLBACK_ACTIONS["relinquish"], event_id, group_id),
                    style="danger",
                ),
            ]
        )
    elif "relinquish" in available:
        if user_status == ParticipantStatus.confirmed:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Confirmed",
                        callback_data=encode_callback(CALLBACK_ACTIONS["relinquish"], event_id, group_id),
                        style="success",
                    ),
                ]
            )
        else:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Relinquish",
                        callback_data=encode_callback(CALLBACK_ACTIONS["relinquish"], event_id, group_id),
                        style="danger",
                    ),
                ]
            )

    # Organizer actions
    if is_organizer:
        if "lock" in available:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Lock Event",
                        callback_data=encode_callback(CALLBACK_ACTIONS["lock"], event_id, group_id),
                        style="primary",
                    ),
                ]
            )
        if "unlock" in available:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Unlock Event",
                        callback_data=encode_callback(CALLBACK_ACTIONS["unlock"], event_id, group_id),
                        style="danger",
                    ),
                ]
            )
        if "complete" in available:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "Complete Event",
                        callback_data=encode_callback(CALLBACK_ACTIONS["complete"], event_id, group_id),
                        style="primary",
                    ),
                ]
            )

    # Navigation row
    buttons.append(
        [
            InlineKeyboardButton(
                "Back to Events",
                callback_data=encode_callback(CALLBACK_ACTIONS["back_to_list"], event_id, group_id),
                style="danger",
            ),
            InlineKeyboardButton(
                "Refresh",
                callback_data=encode_callback(CALLBACK_ACTIONS["refresh"], event_id, group_id),
                style="primary",
            ),
        ]
    )

    return buttons


def build_enrich_submenu(event_id: int, group_id: Optional[int] = None) -> List[List[InlineKeyboardButton]]:
    """
    Build the Enrich sub-menu buttons.

    Allows participants to contribute:
    - Ideas (max 300 chars, private until event locks)
    - Hashtags (max 3 per user, public after 2+ contributors)
    - Memories (post-event, private until mosaic)

    Args:
        event_id: Event being enriched
        group_id: Optional group ID for callback context

    Returns:
        2D array of InlineKeyboardButton
    """
    return [
        [
            InlineKeyboardButton(
                "Add Idea",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_idea"], event_id, group_id),
                style="primary",
            ),
            InlineKeyboardButton(
                "Add Hashtag",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_hashtag"], event_id, group_id),
                style="primary",
            ),
        ],
        [
            InlineKeyboardButton(
                "Add Memory",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_memory"], event_id, group_id),
                style="primary",
            ),
            InlineKeyboardButton(
                "View Contributions",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_view"], event_id, group_id),
                style="primary",
            ),
        ],
        [
            InlineKeyboardButton(
                "Back to Event",
                callback_data=encode_callback(CALLBACK_ACTIONS["back_to_panel"], event_id, group_id),
                style="danger",
            ),
        ],
    ]


def build_constraint_submenu(event_id: int, group_id: Optional[int] = None) -> List[List[InlineKeyboardButton]]:
    """
    Build the Constraint sub-menu buttons.

    Allows participants to set conditional participation:
    - "If X joins, I'll join"
    - "Unless Y comes, I'm in"
    - Suggest/negotiate times

    Args:
        event_id: Event being constrained
        group_id: Optional group ID for callback context

    Returns:
        2D array of InlineKeyboardButton
    """
    return [
        [
            InlineKeyboardButton(
                "✅ If someone joins...",
                callback_data=encode_callback(CALLBACK_ACTIONS["constraint_add"], event_id, group_id),
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Unless someone joins...",
                callback_data=encode_callback(CALLBACK_ACTIONS["constraint_add_unless"], event_id, group_id),
            ),
        ],
        [
            InlineKeyboardButton(
                "🕐 Suggest Time", callback_data=encode_callback(CALLBACK_ACTIONS["suggest_time"], event_id, group_id)
            ),
            InlineKeyboardButton(
                "🤝 Negotiate Time",
                callback_data=encode_callback(CALLBACK_ACTIONS["negotiate_time"], event_id, group_id),
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Event", callback_data=encode_callback(CALLBACK_ACTIONS["back_to_panel"], event_id, group_id)
            ),
        ],
    ]


# =============================================================================
# Main Router
# =============================================================================


async def route_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Route event panel callbacks to appropriate handlers.

    This is the main entry point for all event panel callbacks.
    Decodes the callback and dispatches to the appropriate handler.

    Args:
        update: Telegram update object
        context: Telegram context object
    """
    import asyncio
    from bot.common.callback_data import decode_callback
    import logging

    logger = logging.getLogger("coord_bot.event_panel")

    query = update.callback_query
    if not query:
        return

    logger.info("route_event_callback START: data=%r", query.data)

    # Answer the callback query immediately (with timeout to prevent hanging)
    try:
        await asyncio.wait_for(query.answer(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("query.answer() timed out for callback: %s", query.data)
    except Exception as e:
        logger.warning("query.answer() failed for callback: %s - %s", query.data, e)

    # Decode callback data
    callback_data = query.data
    action, event_id, group_id = decode_callback(callback_data)

    logger.info("route_event_callback decoded: action=%r, event_id=%r, group_id=%r", action, event_id, group_id)

    if action is None or event_id is None:
        # Invalid callback format
        await query.edit_message_text("❌ Invalid callback. Please use /events to see your events.")
        return

    # Route to appropriate handler
    handler_map = {
        CALLBACK_ACTIONS["view"]: _handle_view,
        CALLBACK_ACTIONS["det"]: _handle_details,
        CALLBACK_ACTIONS["join"]: _handle_join,
        CALLBACK_ACTIONS["relinquish"]: _handle_relinquish,
        CALLBACK_ACTIONS["commit"]: _handle_commit,
        CALLBACK_ACTIONS["cancel"]: _handle_cancel,
        CALLBACK_ACTIONS["lock"]: _handle_lock,
        CALLBACK_ACTIONS["unlock"]: _handle_unlock,
        CALLBACK_ACTIONS["enrich"]: handle_enrich_menu,
        CALLBACK_ACTIONS["enrich_idea"]: handle_add_idea_prompt,
        CALLBACK_ACTIONS["enrich_hashtag"]: handle_add_hashtag_prompt,
        CALLBACK_ACTIONS["enrich_memory"]: handle_add_memory_prompt,
        CALLBACK_ACTIONS["enrich_view"]: handle_view_contributions,
        CALLBACK_ACTIONS["constraint"]: handle_constraint_menu,
        CALLBACK_ACTIONS["constraint_add"]: handle_add_constraint_prompt,
        CALLBACK_ACTIONS["constraint_add_unless"]: handle_add_constraint_unless_prompt,
        CALLBACK_ACTIONS["suggest_time"]: handle_suggest_time,
        CALLBACK_ACTIONS["negotiate_time"]: handle_suggest_time,
        CALLBACK_ACTIONS["refresh"]: _handle_refresh,
        CALLBACK_ACTIONS["back_to_panel"]: _handle_view,
        CALLBACK_ACTIONS["back_to_list"]: _handle_back_to_list,
        CALLBACK_ACTIONS["logs"]: _handle_logs,
        CALLBACK_ACTIONS["close"]: _handle_close,
        CALLBACK_ACTIONS["modify"]: handle_modify_event,
    }

    handler = handler_map.get(action)
    if handler:
        logger.info("route_event_callback dispatching to %s", handler.__name__)
        await handler(query, context, event_id, group_id=group_id)
        logger.info("route_event_callback DONE for %s", handler.__name__)
    else:
        # Unknown action
        logger.info("route_event_callback unknown action: %r", action)
        await query.edit_message_text(f"❓ Unknown action: {action}. Please use /events to see your events.")


# =============================================================================
# Main Panel Handlers
# =============================================================================


async def _handle_view(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Display the event panel with full event details."""
    from sqlalchemy import select, func
    from config.settings import settings
    from db.models import EventParticipant
    from bot.services.event_enrichment_service import EventEnrichmentService
    from bot.common.rbac import check_event_visibility_and_get_event

    db_url = settings.db_url or ""
    user_id = query.from_user.id if query.from_user else None

    async with get_session(db_url) as session:
        # Fetch event to get its group (needed for RBAC when callback has no group_id)
        from sqlalchemy.orm import selectinload

        event_result = await session.execute(
            select(Event).options(selectinload(Event.group)).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            await query.edit_message_text("❌ Event not found.")
            return

        # Determine the correct chat_id for RBAC:
        # 1. Use embedded group_id from callback if available
        # 2. Otherwise use the event's group telegram_group_id (handles old callback format)
        # 3. Fall back to message chat_id (original behavior for legacy callbacks)
        if group_id is not None:
            rbac_chat_id = group_id
        elif event.group and event.group.telegram_group_id is not None:
            rbac_chat_id = event.group.telegram_group_id
        else:
            rbac_chat_id = getattr(getattr(query, "message", None), "chat_id", None)

        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
            session,
            event_id,
            user_id,
            telegram_chat_id=rbac_chat_id,
            bot=context.bot,
        )
        if not is_visible:
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        # Get user's participant status
        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(event_id, user_id)

        # Check if user is organizer
        is_organizer = event.organizer_telegram_user_id == user_id or (
            event.emergency_admin_telegram_user_id and event.emergency_admin_telegram_user_id == user_id
        )

        # Get participant counts
        count_result = await session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status.in_([ParticipantStatus.joined, ParticipantStatus.confirmed]),
            )
        )
        participant_count = count_result.scalar() or 0

        confirmed_result = await session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == ParticipantStatus.confirmed,
            )
        )
        confirmed_count = confirmed_result.scalar() or 0

        # Get public hashtags
        enrichment_service = EventEnrichmentService(session)
        hashtags = await enrichment_service.get_public_hashtags(event_id)

        # Get lineage fragment
        from bot.services.event_memory_service import EventMemoryService

        memory_service = EventMemoryService(context.bot, session)
        lineage_fragment = None
        if event.group_id:
            lineage_fragment = await memory_service.get_lineage_door_fragment(event.group_id, event.event_type)

        # Build display text
        state_display = {
            "proposed": "forming",
            "interested": "forming",
            "confirmed": "happening",
            "locked": "locked",
            "completed": "done",
            "cancelled": "cancelled",
        }.get(event.state, event.state)

        type_emoji = {
            "sports": "🏃",
            "social": "🍕",
            "work": "💻",
        }.get(event.event_type, "🎯")

        lines = [f"{type_emoji} *{event.event_type.capitalize()}*", ""]

        if event.description:
            lines.append(f"*{event.description}*")
            lines.append("")

        # Time
        if event.scheduled_time:
            lines.append(f"📅 {event.scheduled_time.strftime('%a %d %b, %H:%M')}")
        else:
            lines.append("📅 Time forming...")

        # State and deadline
        lines.append(f"State: {state_display}")
        if event.lock_deadline:
            lines.append(f"⏳ Deadline: {event.lock_deadline.strftime('%a %d %b, %H:%M')}")

        # Participant count
        min_p = event.min_participants or 2
        lines.append(f"👥 {participant_count} / {min_p} needed")
        lines.append("")

        # Lineage fragment
        if lineage_fragment:
            lines.append(f'↩ Last time: "{lineage_fragment}"')
            lines.append("")

        # Hashtags
        if hashtags:
            lines.append(" ".join(hashtags))
            lines.append("")

        text = "\n".join(lines)

        # Build buttons
        buttons = build_main_panel_buttons(
            event_id=event_id,
            user_status=participant.status if participant else None,
            is_organizer=is_organizer,
            event_state=event.state,
            participant_count=participant_count,
            confirmed_count=confirmed_count,
            min_participants=min_p,
            group_id=rbac_chat_id,
        )

        try:
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="Markdown",
            )
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("ℹ️ Already up to date.")
            else:
                raise


async def _handle_details(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Display the full legacy event detail view from the v3.5 panel."""
    from bot.commands import event_details

    await event_details.show_details(query, context, event_id, group_id=group_id)


async def _handle_join(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle join event action."""
    import logging

    logger = logging.getLogger("coord_bot.event_panel")

    from sqlalchemy import select
    from bot.services import ParticipantService
    from bot.common.rbac import check_event_visibility_and_get_event

    db_url = settings.db_url or ""
    telegram_user_id = query.from_user.id
    bot = context.bot

    logger.info(
        "[JOIN_FLOW] Started | event_id=%s user_id=%s group_id=%s",
        event_id,
        telegram_user_id,
        group_id,
    )

    async with get_session(db_url) as session:
        # Fetch event to get its group (needed for RBAC when callback has no group_id)
        from sqlalchemy.orm import selectinload

        event_result = await session.execute(
            select(Event).options(selectinload(Event.group)).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            logger.warning("[JOIN_FLOW] Event not found | event_id=%s", event_id)
            try:
                await asyncio.wait_for(query.answer("❌ Event not found.", show_alert=True), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            return

        logger.info(
            "[JOIN_FLOW] Event loaded | event_id=%s state=%s organizer_id=%s",
            event_id,
            event.state,
            event.organizer_telegram_user_id,
        )

        if event.state in ["locked", "completed", "cancelled"]:
            logger.warning(
                "[JOIN_FLOW] Cannot join - event in terminal state | event_id=%s state=%s user_id=%s",
                event_id,
                event.state,
                telegram_user_id,
            )
            try:
                await asyncio.wait_for(
                    query.answer(
                        f"❌ Cannot join event {event_id}. Current state: {event.state}",
                        show_alert=True,
                    ),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                pass
            return

        # Determine the correct chat_id for RBAC:
        # 1. Use embedded group_id from callback if available
        # 2. Otherwise use the event's group telegram_group_id (handles old callback format)
        # 3. Fall back to message chat_id (original behavior for legacy callbacks)
        if group_id is not None:
            rbac_chat_id = group_id
        elif event.group and event.group.telegram_group_id is not None:
            rbac_chat_id = event.group.telegram_group_id
        else:
            rbac_chat_id = query.message.chat_id if query.message else None

        logger.info(
            "[JOIN_FLOW] Checking visibility | event_id=%s user_id=%s rbac_chat_id=%s",
            event_id,
            telegram_user_id,
            rbac_chat_id,
        )

        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
            session,
            event_id,
            telegram_user_id,
            telegram_chat_id=rbac_chat_id,
            bot=bot,
        )

        if not is_visible:
            logger.warning(
                "[JOIN_FLOW] Event not visible to user | event_id=%s user_id=%s error=%s",
                event_id,
                telegram_user_id,
                error_msg,
            )
            try:
                await asyncio.wait_for(
                    query.answer(f"❌ {error_msg or 'Event not found.'}", show_alert=True), timeout=5.0
                )
            except asyncio.TimeoutError:
                pass
            return

        logger.info("[JOIN_FLOW] Visibility check passed | event_id=%s user_id=%s", event_id, telegram_user_id)

        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(event_id, telegram_user_id)

        if participant:
            logger.info(
                "[JOIN_FLOW] Existing participant found | event_id=%s user_id=%s status=%s",
                event_id,
                telegram_user_id,
                participant.status.value if participant.status else None,
            )
            if participant.status in [ParticipantStatus.joined, ParticipantStatus.confirmed]:
                try:
                    await asyncio.wait_for(query.answer("ℹ️ You're already joined.", show_alert=True), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return
            elif participant.status == ParticipantStatus.cancelled:
                logger.info(
                    "[JOIN_FLOW] Rejoining after cancellation | event_id=%s user_id=%s",
                    event_id,
                    telegram_user_id,
                )
        else:
            logger.info(
                "[JOIN_FLOW] New participant | event_id=%s user_id=%s",
                event_id,
                telegram_user_id,
            )

        try:
            logger.info(
                "[JOIN_FLOW] Calling participant_service.join | event_id=%s user_id=%s",
                event_id,
                telegram_user_id,
            )
            participant, is_new = await participant_service.join(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
                source="callback",
            )

            if is_new:
                logger.info(
                    "[JOIN_FLOW] Join successful | event_id=%s user_id=%s",
                    event_id,
                    telegram_user_id,
                )

                # Transition to interested if non-organizer joins and event is proposed
                organizer_id = event.organizer_telegram_user_id
                if telegram_user_id != organizer_id and event.state == "proposed":
                    from bot.services import EventLifecycleService

                    lifecycle_service = EventLifecycleService(bot, session)
                    try:
                        event, _ = await lifecycle_service.transition_with_lifecycle(
                            event_id=event_id,
                            target_state="interested",
                            actor_telegram_user_id=telegram_user_id,
                            source="callback",
                            reason="Non-organizer participant joined",
                            expected_version=event.version,
                        )
                        logger.info(
                            "[JOIN_FLOW] State transitioned to interested | event_id=%s",
                            event_id,
                        )
                    except Exception as e:
                        logger.error(
                            "[JOIN_FLOW] State transition failed | event_id=%s error=%s",
                            event_id,
                            str(e),
                            exc_info=True,
                        )

                # Commit session before calling _handle_view to prevent nested session deadlock
                await session.commit()
                logger.info("[JOIN_FLOW] Session committed | event_id=%s", event_id)

                try:
                    await asyncio.wait_for(query.answer("✅ You've joined the event!"), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

                from sqlalchemy import select as sa_select
                from db.models import User

                await session.execute(
                    sa_select(User).where(User.telegram_user_id == event.organizer_telegram_user_id)
                )

                from bot.common.event_notifications import send_join_notification_dm

                try:
                    logger.info(
                        "[JOIN_FLOW] Notifying organizer | event_id=%s user_id=%s organizer_id=%s",
                        event_id,
                        telegram_user_id,
                        event.organizer_telegram_user_id,
                    )

                    # Notify organizer about new join
                    await send_join_notification_dm(
                        context=context,
                        telegram_user_id=event.organizer_telegram_user_id,
                        event=event,
                        joiner_name=query.from_user.full_name if query.from_user else "Someone",
                        group_id=rbac_chat_id,
                    )

                    logger.info(
                        "[JOIN_FLOW] Organizer notification sent | event_id=%s organizer_id=%s",
                        event_id,
                        event.organizer_telegram_user_id,
                    )
                except Exception as notify_err:
                    logger.warning(
                        "[JOIN_FLOW] Organizer notification failed | event_id=%s error=%s",
                        event_id,
                        str(notify_err),
                    )
                    pass

            else:
                try:
                    await asyncio.wait_for(query.answer("ℹ️ You're already joined."), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

            logger.info("[JOIN_FLOW] Refreshing view after join | event_id=%s", event_id)
            await _handle_view(query, context, event_id, group_id=rbac_chat_id)
            logger.info("[JOIN_FLOW] Completed successfully | event_id=%s", event_id)

        except Exception as e:
            logger.error(
                "[JOIN_FLOW] Exception during join | event_id=%s user_id=%s error_type=%s error=%s",
                event_id,
                telegram_user_id,
                type(e).__name__,
                str(e),
                exc_info=True,
            )
            try:
                await asyncio.wait_for(query.answer(f"❌ Error: {str(e)}", show_alert=True), timeout=5.0)
            except asyncio.TimeoutError:
                pass


async def _handle_relinquish(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle relinquish (leave/un-join) event action."""
    from bot.services import ParticipantService

    db_url = settings.db_url or ""
    telegram_user_id = query.from_user.id

    async with get_session(db_url) as session:
        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(event_id, telegram_user_id)

        if not participant:
            await query.answer("ℹ️ You're not joined to this event.", show_alert=True)
            return

        if participant.status == ParticipantStatus.confirmed:
            await query.answer(
                "You must uncommit before leaving. Tap 'You're Confirmed' to uncommit first.",
                show_alert=True,
            )
            return

        try:
            await participant_service.cancel(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
            )
            await session.commit()

            await query.answer("👋 You've left the event.")

            await _handle_view(query, context, event_id, group_id=group_id)

        except Exception as e:
            await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def _handle_commit(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle commit (confirm) event action."""
    from sqlalchemy import select

    from bot.common.event_access import get_event_organizer_telegram_id
    from bot.services.event_lifecycle_service import EventLifecycleService
    from bot.services import ParticipantService

    db_url = settings.db_url or ""
    telegram_user_id = query.from_user.id
    bot = context.bot

    async with get_session(db_url) as session:
        event_result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = event_result.scalar_one_or_none()

        if not event:
            await query.answer("❌ Event not found.", show_alert=True)
            return

        participant_service = ParticipantService(session)
        participant = await participant_service.get_participant(event_id, telegram_user_id)

        if not participant:
            await query.answer("❌ You must join the event before committing.", show_alert=True)
            return

        if participant.status == ParticipantStatus.confirmed:
            await query.answer("ℹ️ You're already committed.", show_alert=True)
            return

        try:
            participant = await participant_service.confirm(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
            )
            await session.flush()

            organizer_id = get_event_organizer_telegram_id(event)
            confirmed_count = await participant_service.get_confirmed_count(event_id)
            if telegram_user_id != organizer_id and event.state != "confirmed" and confirmed_count > 0:
                lifecycle_service = EventLifecycleService(bot, session)
                try:
                    event, _ = await lifecycle_service.transition_with_lifecycle(
                        event_id=event_id,
                        target_state="confirmed",
                        actor_telegram_user_id=telegram_user_id,
                        source="callback",
                        reason="Non-organizer participant confirmed attendance",
                        expected_version=event.version,
                    )
                except Exception as e:
                    await query.answer(f"❌ Error: {str(e)}", show_alert=True)
                    return

            await session.commit()

            await query.answer("✅ You're committed!")

            await _handle_view(query, context, event_id, group_id=group_id)

        except Exception as e:
            await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def _handle_cancel(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle cancel participation action."""
    # Same as relinquish for participants
    await _handle_relinquish(query, context, event_id, group_id=group_id)


async def _handle_lock(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle lock event action (organizer only)."""
    from sqlalchemy import select
    from bot.services.event_lifecycle_service import EventLifecycleService
    from bot.services import ParticipantService

    telegram_user_id = query.from_user.id
    bot = context.bot
    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        # Fetch event to get its group for RBAC
        from sqlalchemy.orm import selectinload

        event_result = await session.execute(
            select(Event).options(selectinload(Event.group)).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            await query.answer("❌ Event not found.", show_alert=True)
            return

        # Determine the correct chat_id for RBAC
        if group_id is not None:
            rbac_chat_id = group_id
        elif event.group and event.group.telegram_group_id is not None:
            rbac_chat_id = event.group.telegram_group_id
        else:
            rbac_chat_id = query.message.chat_id if query.message else None

        from bot.common.rbac import check_event_visibility_and_get_event

        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
            session,
            event_id,
            telegram_user_id,
            telegram_chat_id=rbac_chat_id,
            bot=bot,
        )

        if not is_visible:
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        if event.state != "confirmed":
            await query.answer(
                f"❌ Can only lock when state is 'confirmed'. Current: {event.state}",
                show_alert=True,
            )
            return

        # Check organizer permission
        is_organizer = event.organizer_telegram_user_id == telegram_user_id or (
            event.emergency_admin_telegram_user_id and event.emergency_admin_telegram_user_id == telegram_user_id
        )
        if not is_organizer:
            await query.answer("❌ Only the organizer can lock an event.", show_alert=True)
            return

        lifecycle_service = EventLifecycleService(bot, session)
        try:
            event, _ = await lifecycle_service.transition_with_lifecycle(
                event_id=event_id,
                target_state="locked",
                actor_telegram_user_id=telegram_user_id,
                source="callback",
                reason="Lock via event panel",
                expected_version=event.version,
            )
        except Exception as e:
            await query.answer(f"❌ Failed to lock event: {str(e)}", show_alert=True)
            return

        participant_service = ParticipantService(session)
        await participant_service.finalize_commitments(event_id)
        await session.commit()

        await query.answer("🔒 Event locked!")
        await _handle_view(query, context, event_id, group_id=rbac_chat_id)


async def _handle_unlock(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle unlock event action (organizer only)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from bot.services.event_lifecycle_service import EventLifecycleService

    telegram_user_id = query.from_user.id
    bot = context.bot
    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        # Fetch event to get its group for RBAC
        event_result = await session.execute(
            select(Event).options(selectinload(Event.group)).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            await query.answer("❌ Event not found.", show_alert=True)
            return

        # Determine the correct chat_id for RBAC
        if group_id is not None:
            rbac_chat_id = group_id
        elif event.group and event.group.telegram_group_id is not None:
            rbac_chat_id = event.group.telegram_group_id
        else:
            rbac_chat_id = query.message.chat_id if query.message else None

        from bot.common.rbac import check_event_visibility_and_get_event

        is_visible, event, group, error_msg = await check_event_visibility_and_get_event(
            session,
            event_id,
            telegram_user_id,
            telegram_chat_id=rbac_chat_id,
            bot=bot,
        )

        if not is_visible:
            await query.edit_message_text(f"❌ {error_msg or 'Event not found.'}")
            return

        if event.state != "locked":
            await query.answer(
                f"❌ Can only unlock when state is 'locked'. Current: {event.state}",
                show_alert=True,
            )
            return

        # Check organizer permission
        is_organizer = event.organizer_telegram_user_id == telegram_user_id or (
            event.emergency_admin_telegram_user_id and event.emergency_admin_telegram_user_id == telegram_user_id
        )
        if not is_organizer:
            await query.answer("❌ Only the organizer can unlock an event.", show_alert=True)
            return

        lifecycle_service = EventLifecycleService(bot, session)
        try:
            event, _ = await lifecycle_service.transition_with_lifecycle(
                event_id=event_id,
                target_state="confirmed",
                actor_telegram_user_id=telegram_user_id,
                source="callback",
                reason="Unlock via event panel",
                expected_version=event.version,
            )
        except Exception as e:
            await query.answer(f"❌ Failed to unlock event: {str(e)}", show_alert=True)
            return

        await session.commit()
        await query.answer("🔓 Event unlocked!")
        await _handle_view(query, context, event_id, group_id=rbac_chat_id)


async def _handle_refresh(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle refresh action."""
    await query.answer("🔄 Refreshing...")
    await _handle_view(query, context, event_id, group_id=group_id)


async def _handle_back_to_list(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle back to events list action."""
    # Import here to avoid circular imports
    from bot.commands.events import handle as events_handler

    # Create a fake update to call the events handler
    fake_update = type(
        "obj",
        (object,),
        {
            "effective_user": query.from_user,
            "effective_chat": query.message.chat,
            "message": query.message,
        },
    )()

    await events_handler(fake_update, context)


# =============================================================================
# Enrich Sub-menu Handlers
# =============================================================================


async def handle_enrich_menu(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Show the Enrich sub-menu."""
    text = (
        f"💡 *Enrich Event #{event_id}*\n\n"
        "Add ideas, hashtags, or memories to make this event better.\n\n"
        "- *Ideas*: Suggest activities, locations, or preparations\n"
        "- *Hashtags*: Tag the event for easy discovery\n"
        "- *Memories*: Share moments from past similar events\n\n"
        "Your ideas are visible to the organizer. Hashtags become public "
        "when 2+ people add the same tag."
    )

    buttons = build_enrich_submenu(event_id, group_id)

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def handle_add_idea_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Prompt user to add an idea."""
    await query.edit_message_text(
        text=(
            f"💡 *Add Idea to Event #{event_id}*\n\n"
            "Reply with your idea (max 300 characters).\n\n"
            "Example: 'Bring a portable speaker for music'\n\n"
            "Your idea will be visible to the organizer."
        ),
        parse_mode="Markdown",
    )

    from bot.services.state_store import get_state_store

    store = get_state_store(query.from_user.id, context.user_data)
    store.set_enrichment_session(event_id, "add_idea")
    await query.answer("Type your idea and send it!")


async def handle_add_hashtag_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Prompt user to add a hashtag."""
    await query.edit_message_text(
        text=(
            f"#️⃣ *Add Hashtag to Event #{event_id}*\n\n"
            "Reply with your hashtag (max 3 per event).\n\n"
            "Examples: #hiking, #weekend, #birthday\n\n"
            "Hashtags become public on the live card when 2+ people add the same tag."
        ),
        parse_mode="Markdown",
    )

    from bot.services.state_store import get_state_store

    store = get_state_store(query.from_user.id, context.user_data)
    store.set_enrichment_session(event_id, "add_hashtag")
    await query.answer("Type your hashtag and send it!")


async def handle_add_memory_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Prompt user to add a memory."""
    await query.edit_message_text(
        text=(
            f"📝 *Add Memory to Event #{event_id}*\n\n"
            "Share a memory from a similar past event (max 200 words).\n\n"
            "Memories are private until assembled into a mosaic when the event completes."
        ),
        parse_mode="Markdown",
    )

    from bot.services.state_store import get_state_store

    store = get_state_store(query.from_user.id, context.user_data)
    store.set_enrichment_session(event_id, "add_memory")
    await query.answer("Type your memory and send it!")


async def handle_view_contributions(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Show user's contributions to this event."""
    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        enrichment_service = EventEnrichmentService(session)

        # Get user's contributions
        contributions = await enrichment_service.get_user_contributions(
            event_id=event_id,
            telegram_user_id=query.from_user.id,
        )

    if not contributions:
        text = "You haven't added any contributions to this event yet."
    else:
        text = "*Your Contributions:*\n\n"
        for c in contributions:
            emoji = {"idea": "💡", "hashtag": "#️⃣", "memory": "📝"}.get(c.enrichment_type, "•")
            text += f"{emoji} *{c.enrichment_type.capitalize()}*: {c.content[:50]}...\n\n"

    buttons = [
        [
            InlineKeyboardButton(
                "🔙 Back to Enrich", callback_data=encode_callback(CALLBACK_ACTIONS["enrich"], event_id, group_id)
            ),
        ]
    ]

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


# =============================================================================
# Constraint Sub-menu Handlers
# =============================================================================


async def handle_constraint_menu(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Show the Constraint sub-menu."""
    text = (
        f"📅 *Constraints for Event #{event_id}*\n\n"
        "Set conditions for your participation:\n\n"
        "- *If X joins*: I'll join if specific people do\n"
        "- *Unless X joins*: I'm in unless specific people come\n"
        "- *Time preferences*: Suggest or negotiate the time\n\n"
        "Constraints help coordinate complex group decisions."
    )

    buttons = build_constraint_submenu(event_id, group_id)

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def handle_add_constraint_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Prompt user to add a constraint."""
    await query.edit_message_text(
        text=(
            f"📅 *Add Constraint to Event #{event_id}*\n\n"
            "Reply with the username of who you're waiting for.\n\n"
            "Format: @username\n\n"
            "Example: 'If @alice joins, I'll join too'"
        ),
        parse_mode="Markdown",
    )

    from bot.services.state_store import get_state_store

    store = get_state_store(query.from_user.id, context.user_data)
    store.set_enrichment_session(event_id, "add_constraint")
    await query.answer("Type the username and send it!")


async def handle_add_constraint_unless_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Prompt user to add an 'unless' constraint."""
    await query.edit_message_text(
        text=(
            f"❌ *Add 'Unless' Constraint to Event #{event_id}*\n\n"
            "Reply with the username of who you'd rather not attend.\n\n"
            "Format: @username\n\n"
            "Example: 'Unless @bob comes, I'm in'"
        ),
        parse_mode="Markdown",
    )

    from bot.services.state_store import get_state_store

    store = get_state_store(query.from_user.id, context.user_data)
    store.set_enrichment_session(event_id, "add_constraint_unless")
    await query.answer("Type the username and send it!")


async def handle_suggest_time(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Handle suggest time action."""
    await query.edit_message_text(
        text=(
            f"🕐 *Suggest Time for Event #{event_id}*\n\n"
            "Reply with your preferred time.\n\n"
            "Examples:\n"
            "- 'Saturday at 7pm'\n"
            "- 'Sunday morning'\n"
            "- 'Anytime after 5pm'"
        ),
        parse_mode="Markdown",
    )
    from bot.services.state_store import get_state_store

    store = get_state_store(query.from_user.id, context.user_data)
    store.set_enrichment_session(event_id, "suggest_time")
    await query.answer("Type your preferred time and send it!")


async def _handle_logs(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Display event logs."""
    from db.models import Log as LogModel, User

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(
            select(LogModel, User)
            .join(User, LogModel.user_id == User.user_id, isouter=True)
            .where(LogModel.event_id == event_id)
            .order_by(LogModel.timestamp.desc())
        )
        rows = result.all()
        if not rows:
            await query.edit_message_text(f"Event {event_id} has no logs yet.")
            return
        msg = f"Event {event_id} Logs\n\n"
        for log, user in rows[:20]:
            user_info = ""
            if user:
                user_info = " by " + format_user_display(
                    telegram_user_id=user.telegram_user_id,
                    username=getattr(user, "username", None),
                    display_name=getattr(user, "display_name", None),
                    include_link=False,
                )
            action_text = {
                "join": "joined",
                "confirm": "confirmed",
                "cancel": "cancelled",
                "organize_event": "created the event",
                "suggest_time": "suggested a time",
                "nudge": "was nudged",
                "constraint_update": "updated constraints",
            }.get(log.action, log.action)
            msg += f"- {action_text}{user_info} at {log.timestamp}\n"
        if len(rows) > 20:
            msg += f"... and {len(rows) - 20} more logs"
        back_btn = InlineKeyboardButton(
            "Back",
            callback_data=encode_callback("det", event_id, group_id),
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[back_btn]]))


async def _handle_close(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Close event details view."""
    await query.edit_message_text(f"Event details for #{event_id} closed.")


async def handle_modify_event(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    group_id: Optional[int] = None,
) -> None:
    """Open the event modification dialog."""
    from db.models import Event

    user = query.from_user
    if not settings.db_url:
        await query.edit_message_text("Database configuration is unavailable.")
        return

    async with get_session(settings.db_url) as session:
        result = await session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            await query.edit_message_text("Event not found.")
            return

        from bot.common.event_access import get_event_admin_telegram_id

        admin_id = get_event_admin_telegram_id(event)

        modify_request = {
            "event_id": event_id,
            "event_description": event.description or "",
            "event_scheduled_time": (event.scheduled_time.isoformat() if event and event.scheduled_time else None),
            "admin_id": admin_id,
            "requester_id": user.id if user else None,
            "requester_username": user.username if user else None,
        }
        request_id = uuid4().hex[:8]
        context.user_data[f"pending_modify_request_{request_id}"] = modify_request

        keyboard = [
            [
                InlineKeyboardButton("Write your own", callback_data=f"modinput_{request_id}_write"),
                InlineKeyboardButton("AI suggested", callback_data=f"modinput_{request_id}_ai"),
            ],
            [InlineKeyboardButton("Discard", callback_data=f"modinput_{request_id}_cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "How would you like to modify the event?\n\n"
            "Choose a method to specify the changes you want to make.",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "route_event_callback",
    "build_main_panel_buttons",
    "build_enrich_submenu",
    "build_constraint_submenu",
    "handle_enrich_menu",
    "handle_constraint_menu",
    "handle_add_idea_prompt",
    "handle_add_hashtag_prompt",
    "handle_add_memory_prompt",
    "handle_view_contributions",
]
