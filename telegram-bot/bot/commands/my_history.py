#!/usr/bin/env python3
"""
My History command - Personal event timeline (DM only).
PRD v2 Section 4.3: Privacy-preserving personal history (TODO-032).

Design principles:
- Only accessible via DM (not in group chat)
- Shows user's own participation history
- No comparison with others
- Focus on personal journey, not scores

Commands:
- /my_history - View personal event timeline
- /my_history [event_type] - Filter by event type
"""
import logging
from typing import List, Dict, Optional, Any
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func, desc

from config.settings import settings
from db.connection import get_session
from db.models import User, Event, EventParticipant, ParticipantStatus, EventMemory
from config.logging import set_correlation_context, clear_correlation_context

logger = logging.getLogger("coord_bot.commands.my_history")


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /my_history command - show personal event timeline.

    PRD Design rule: Privacy-preserving, DM only.
    No comparison with others - just personal journey.
    """
    set_correlation_context(
        correlation_id=f"my_history_{update.effective_user.id}",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
    )

    try:
        if not update.message:
            return

        # Check if in DM (privacy requirement)
        if update.effective_chat.type != "private":
            await update.message.reply_text(
                "🔒 This command is only available in direct messages.\n\n"
                "Please message me privately for your personal history."
            )
            return

        if not settings.db_url:
            await update.message.reply_text("❌ Database configuration is unavailable.")
            return

        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return

        # Parse optional event_type filter
        event_type_filter = None
        if context.args and len(context.args) > 0:
            event_type_filter = context.args[0].lower()

        async with get_session(settings.db_url) as session:
            # Get user
            result = await session.execute(select(User).where(User.telegram_user_id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                await update.message.reply_text("You're not registered yet.\n" "Use /start to register.")
                return

            # Get participation history
            history = await _get_participation_history(session, user.user_id, event_type_filter)

            if not history:
                if event_type_filter:
                    await update.message.reply_text(
                        f"No {event_type_filter} events in your history yet.\n\n" f"Use /my_history to see all events."
                    )
                else:
                    await update.message.reply_text(
                        "📜 Your Event History\n\n"
                        "No events yet! Join your first event to start building your story.\n\n"
                        "Use /events to see upcoming events."
                    )
                return

            # Build response
            response = await _format_history_response(user, history, event_type_filter, session)

            await update.message.reply_text(response, parse_mode="HTML")

            logger.info(
                "User viewed personal history",
                extra={
                    "user": user.user_id,
                    "event_count": len(history),
                    "filter": event_type_filter,
                },
            )

    finally:
        clear_correlation_context()


async def _get_participation_history(
    session,
    user_id: int,
    event_type_filter: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Get user's participation history.

    Returns list of dicts with event and participation details.
    """
    query = (
        select(Event, EventParticipant)
        .join(EventParticipant, Event.event_id == EventParticipant.event_id)
        .where(EventParticipant.telegram_user_id == user_id)
        .order_by(desc(Event.scheduled_time))
        .limit(limit)
    )

    if event_type_filter:
        query = query.where(Event.event_type == event_type_filter)

    result = await session.execute(query)
    rows = result.all()

    history = []
    for event, participant in rows:
        # Check if event has memory weave
        memory_result = await session.execute(select(EventMemory).where(EventMemory.event_id == event.event_id))
        memory = memory_result.scalar_one_or_none()

        history.append(
            {
                "event": event,
                "participant": participant,
                "has_memory": memory is not None and memory.weave_text is not None,
                "memory_weave": memory.weave_text if memory else None,
            }
        )

    return history


async def _format_history_response(
    user: User,
    history: List[Dict[str, Any]],
    event_type_filter: Optional[str],
    session,
) -> str:
    """Format history as Telegram message."""
    # Header
    if event_type_filter:
        header = f"📜 Your {event_type_filter.title()} History\n"
    else:
        header = "📜 Your Event History\n"

    # Summary stats
    total = len(history)
    confirmed = sum(1 for h in history if h["participant"].status == ParticipantStatus.confirmed)
    no_shows = sum(1 for h in history if h["participant"].status == ParticipantStatus.no_show)
    with_memories = sum(1 for h in history if h["has_memory"])

    header += (
        f"\n<b>Total events:</b> {total}\n"
        f"<b>Confirmed:</b> {confirmed}\n"
        f"<b>Memories shared:</b> {with_memories}\n"
    )

    if no_shows > 0:
        # Gentle framing - not shaming
        header += f"<b>Couldn't make it:</b> {no_shows}\n"

    header += "\n" + "─" * 30 + "\n"

    # Event list
    events_list = []
    for i, h in enumerate(history[:10], 1):  # Show max 10
        event = h["event"]
        participant = h["participant"]

        # Date
        if event.scheduled_time:
            date_str = event.scheduled_time.strftime("%d %b %Y")
        else:
            date_str = "TBD"

        # Status emoji
        status_emoji = {
            ParticipantStatus.confirmed: "✅",
            ParticipantStatus.joined: "👀",
            ParticipantStatus.cancelled: "❌",
            ParticipantStatus.no_show: "⏸️",
        }.get(participant.status, "•")

        # Event title
        event_title = f"{event.event_type.title()}"
        if event.description:
            desc_preview = event.description[:40]
            if len(event.description) > 40:
                desc_preview += "..."
            event_title += f": {desc_preview}"

        # Memory indicator
        memory_indicator = " 📿" if h["has_memory"] else ""

        events_list.append(f"{i}. {status_emoji} <b>{event_title}</b>{memory_indicator}\n" f"   {date_str}")

    body = "\n\n".join(events_list)

    # Footer
    footer = ""
    if len(history) > 10:
        footer = f"\n\n... and {len(history) - 10} more events"

    footer += (
        "\n\n<i>Your history is private — never shown to others.</i>\n"
        "Use /my_history [type] to filter by event type."
    )

    return header + body + footer


async def _get_participation_summary(
    session,
    user_id: int,
) -> Dict[str, Any]:
    """Get participation summary statistics."""
    # Total events
    total_result = await session.execute(
        select(func.count(func.distinct(EventParticipant.event_id))).where(EventParticipant.telegram_user_id == user_id)
    )
    total_events = total_result.scalar() or 0

    # By status
    status_counts = {}
    for status in ParticipantStatus:
        result = await session.execute(
            select(func.count(EventParticipant.event_id)).where(
                EventParticipant.telegram_user_id == user_id,
                EventParticipant.status == status,
            )
        )
        status_counts[status.value] = result.scalar() or 0

    # By event type
    type_result = await session.execute(
        select(Event.event_type, func.count(func.distinct(Event.event_id)))
        .join(EventParticipant, Event.event_id == EventParticipant.event_id)
        .where(EventParticipant.telegram_user_id == user_id)
        .group_by(Event.event_type)
    )
    by_type = {row[0]: row[1] for row in type_result.all()}

    # Memory contributions
    memory_result = await session.execute(
        select(func.count(EventMemory.event_id))
        .join(Event)
        .where(
            EventParticipant.telegram_user_id == user_id,
            EventParticipant.event_id == Event.event_id,
        )
    )
    memories = memory_result.scalar() or 0

    return {
        "total_events": total_events,
        "by_status": status_counts,
        "by_type": by_type,
        "memories": memories,
    }
