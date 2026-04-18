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
from typing import Optional, List
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    CallbackQuery, Update, Bot
)
from telegram.ext import ContextTypes

from bot.common.callback_data import (
    encode_callback, decode_callback,
    CALLBACK_ACTIONS, is_valid_callback
)
from bot.common.event_states import get_available_actions
from db.models import ParticipantStatus
from bot.services.participant_service import ParticipantService
from bot.services.event_enrichment_service import EventEnrichmentService
from db.models import Event, EventParticipant, EventEnrichment


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
) -> List[List[InlineKeyboardButton]]:
    """
    Build context-aware buttons for the event panel.
    
    Button visibility depends on:
    - User's current participation status
    - Whether user is organizer
    - Event state (proposed, interested, confirmed, locked)
    - Whether minimum threshold is met
    
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
    
    # Row 1: Enrich & Constraint (available to all participants)
    if user_status in [ParticipantStatus.joined, ParticipantStatus.confirmed]:
        buttons.append([
            InlineKeyboardButton(
                "💡 Enrich",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich"], event_id)
            ),
            InlineKeyboardButton(
                "📅 Constraint",
                callback_data=encode_callback(CALLBACK_ACTIONS["constraint"], event_id)
            ),
        ])
    
    # Row 2: Primary action based on user status
    if event_state == "locked":
        # Locked events - no changes allowed
        buttons.append([
            InlineKeyboardButton(
                "🔒 Event Locked",
                callback_data=encode_callback("view", event_id)  # Just refresh
            ),
        ])
    elif user_status == ParticipantStatus.confirmed:
        # User is confirmed - can relinquish
        buttons.append([
            InlineKeyboardButton(
                "✅ You're Confirmed",
                callback_data=encode_callback(CALLBACK_ACTIONS["relinquish"], event_id)
            ),
        ])
    elif user_status == ParticipantStatus.joined:
        # User is joined - can relinquish or commit if threshold met
        if confirmed_count >= min_participants:
            # Threshold met - show commit button
            buttons.append([
                InlineKeyboardButton(
                    "🎯 Commit",
                    callback_data=encode_callback(CALLBACK_ACTIONS["commit"], event_id)
                ),
                InlineKeyboardButton(
                    "👋 Relinquish",
                    callback_data=encode_callback(CALLBACK_ACTIONS["relinquish"], event_id)
                ),
            ])
        else:
            # Need more people - just show relinquish
            buttons.append([
                InlineKeyboardButton(
                    "👋 Relinquish",
                    callback_data=encode_callback(CALLBACK_ACTIONS["relinquish"], event_id)
                ),
            ])
    elif user_status is None:
        # Not participating - show join button
        buttons.append([
            InlineKeyboardButton(
                "👋 Join Event",
                callback_data=encode_callback(CALLBACK_ACTIONS["join"], event_id)
            ),
        ])
    
    # Row 3: Organizer actions
    if is_organizer:
        if event_state == "confirmed" and confirmed_count >= min_participants:
            # Ready to lock
            buttons.append([
                InlineKeyboardButton(
                    "🔒 Lock Event",
                    callback_data=encode_callback(CALLBACK_ACTIONS["lock"], event_id)
                ),
            ])
        elif event_state == "locked":
            # Can unlock
            buttons.append([
                InlineKeyboardButton(
                    "🔓 Unlock Event",
                    callback_data=encode_callback(CALLBACK_ACTIONS["unlock"], event_id)
                ),
            ])
    
    # Row 4: Navigation
    buttons.append([
        InlineKeyboardButton(
            "🔙 Back to Events",
            callback_data=encode_callback(CALLBACK_ACTIONS["back_to_list"], event_id)
        ),
        InlineKeyboardButton(
            "🔄 Refresh",
            callback_data=encode_callback(CALLBACK_ACTIONS["refresh"], event_id)
        ),
    ])
    
    return buttons


def build_enrich_submenu(event_id: int) -> List[List[InlineKeyboardButton]]:
    """
    Build the Enrich sub-menu buttons.
    
    Allows participants to contribute:
    - Ideas (max 300 chars, private until event locks)
    - Hashtags (max 3 per user, public after 2+ contributors)
    - Memories (post-event, private until mosaic)
    
    Args:
        event_id: Event being enriched
        
    Returns:
        2D array of InlineKeyboardButton
    """
    return [
        [
            InlineKeyboardButton(
                "💡 Add Idea",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_idea"], event_id)
            ),
            InlineKeyboardButton(
                "#️⃣ Add Hashtag",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_hashtag"], event_id)
            ),
        ],
        [
            InlineKeyboardButton(
                "📝 Add Memory",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_memory"], event_id)
            ),
            InlineKeyboardButton(
                "👁 View My Contributions",
                callback_data=encode_callback(CALLBACK_ACTIONS["enrich_view"], event_id)
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Event",
                callback_data=encode_callback(CALLBACK_ACTIONS["back_to_panel"], event_id)
            ),
        ],
    ]


def build_constraint_submenu(event_id: int) -> List[List[InlineKeyboardButton]]:
    """
    Build the Constraint sub-menu buttons.
    
    Allows participants to set conditional participation:
    - "If X joins, I'll join"
    - "Unless Y comes, I'm in"
    - Suggest/negotiate times
    
    Args:
        event_id: Event being constrained
        
    Returns:
        2D array of InlineKeyboardButton
    """
    return [
        [
            InlineKeyboardButton(
                "✅ If someone joins...",
                callback_data=encode_callback(CALLBACK_ACTIONS["constraint_add"], event_id)
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Unless someone joins...",
                callback_data=encode_callback("constraint_add_unless", event_id)
            ),
        ],
        [
            InlineKeyboardButton(
                "🕐 Suggest Time",
                callback_data=encode_callback(CALLBACK_ACTIONS["suggest_time"], event_id)
            ),
            InlineKeyboardButton(
                "🤝 Negotiate Time",
                callback_data=encode_callback(CALLBACK_ACTIONS["negotiate_time"], event_id)
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Event",
                callback_data=encode_callback(CALLBACK_ACTIONS["back_to_panel"], event_id)
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
    query = update.callback_query
    if not query:
        return
    
    # Answer the callback query immediately
    await query.answer()
    
    # Decode callback data
    callback_data = query.data
    action, event_id = decode_callback(callback_data)
    
    if action is None or event_id is None:
        # Invalid callback format
        await query.edit_message_text(
            "❌ Invalid callback. Please use /events to see your events."
        )
        return
    
    # Route to appropriate handler
    handler_map = {
        CALLBACK_ACTIONS["view"]: _handle_view,
        CALLBACK_ACTIONS["det"]: _handle_view,  # Alias
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
        CALLBACK_ACTIONS["suggest_time"]: handle_suggest_time,
        CALLBACK_ACTIONS["refresh"]: _handle_refresh,
        CALLBACK_ACTIONS["back_to_panel"]: _handle_view,
        CALLBACK_ACTIONS["back_to_list"]: _handle_back_to_list,
    }
    
    handler = handler_map.get(action)
    if handler:
        await handler(query, context, event_id)
    else:
        # Unknown action
        await query.edit_message_text(
            f"❓ Unknown action: {action}. Please use /events to see your events."
        )


# =============================================================================
# Main Panel Handlers
# =============================================================================

async def _handle_view(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Display the event panel."""
    session = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("❌ Session error. Please try again.")
        return
    
    # Get event and participant info
    participant_service = ParticipantService(session)
    
    # TODO: Fetch event details and participant status
    # For now, show a placeholder
    
    text = f"📊 *Event #{event_id}*\n\n"
    text += "Loading event details...\n\n"
    text += "Use the buttons below to interact with this event."
    
    buttons = build_main_panel_buttons(
        event_id=event_id,
        user_status=None,  # TODO: Get actual status
        is_organizer=False,  # TODO: Check if organizer
        event_state="proposed",  # TODO: Get actual state
    )
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def _handle_join(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle join event action."""
    session = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("❌ Session error. Please try again.")
        return
    
    participant_service = ParticipantService(session)
    
    try:
        participant, is_new = await participant_service.join(
            event_id=event_id,
            telegram_user_id=query.from_user.id,
            source="callback",
        )
        
        if is_new:
            await query.answer("✅ You've joined the event!")
        else:
            await query.answer("ℹ️ You're already joined.")
        
        # Refresh the panel
        await _handle_view(query, context, event_id)
        
    except Exception as e:
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def _handle_relinquish(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle relinquish (leave/un-join) event action."""
    session = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("❌ Session error. Please try again.")
        return
    
    participant_service = ParticipantService(session)
    
    try:
        await participant_service.cancel(
            event_id=event_id,
            telegram_user_id=query.from_user.id,
        )
        
        await query.answer("👋 You've left the event.")
        
        # Refresh the panel
        await _handle_view(query, context, event_id)
        
    except Exception as e:
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def _handle_commit(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle commit (confirm) event action."""
    session = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("❌ Session error. Please try again.")
        return
    
    participant_service = ParticipantService(session)
    
    try:
        participant = await participant_service.confirm(
            event_id=event_id,
            telegram_user_id=query.from_user.id,
        )
        
        await query.answer("✅ You're committed!")
        
        # Refresh the panel
        await _handle_view(query, context, event_id)
        
    except Exception as e:
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def _handle_cancel(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle cancel participation action."""
    # Same as relinquish for participants
    await _handle_relinquish(query, context, event_id)


async def _handle_lock(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle lock event action (organizer only)."""
    # TODO: Implement lock logic
    await query.answer("🔒 Lock feature coming soon!")
    await _handle_view(query, context, event_id)


async def _handle_unlock(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle unlock event action (organizer only)."""
    # TODO: Implement unlock logic
    await query.answer("🔓 Unlock feature coming soon!")
    await _handle_view(query, context, event_id)


async def _handle_refresh(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle refresh action."""
    await query.answer("🔄 Refreshing...")
    await _handle_view(query, context, event_id)


async def _handle_back_to_list(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle back to events list action."""
    # Import here to avoid circular imports
    from bot.commands.events import handle as events_handler
    
    # Create a fake update to call the events handler
    fake_update = type('obj', (object,), {
        'effective_user': query.from_user,
        'effective_chat': query.message.chat,
        'message': query.message,
    })()
    
    await events_handler(fake_update, context)


# =============================================================================
# Enrich Sub-menu Handlers
# =============================================================================

async def handle_enrich_menu(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
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
    
    buttons = build_enrich_submenu(event_id)
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def handle_add_idea_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
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
    
    # Set conversation state to wait for idea text
    # TODO: Implement conversation handler
    await query.answer("Type your idea and send it!")


async def handle_add_hashtag_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
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
    
    await query.answer("Type your hashtag and send it!")


async def handle_add_memory_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
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
    
    await query.answer("Type your memory and send it!")


async def handle_view_contributions(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Show user's contributions to this event."""
    session = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("❌ Session error. Please try again.")
        return
    
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
    
    buttons = [[
        InlineKeyboardButton(
            "🔙 Back to Enrich",
            callback_data=encode_callback(CALLBACK_ACTIONS["enrich"], event_id)
        ),
    ]]
    
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
    
    buttons = build_constraint_submenu(event_id)
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def handle_add_constraint_prompt(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
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
    
    await query.answer("Type the username and send it!")


async def handle_suggest_time(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
) -> None:
    """Handle suggest time action."""
    await query.answer("⏰ Time suggestion coming soon!")
    await handle_constraint_menu(query, context, event_id)


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
