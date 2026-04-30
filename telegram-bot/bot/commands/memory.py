"""
Memory commands - Layer 3: Memory Layer access.
PRD v2 Section 3.2: New features for v1 completion.

Commands:
- /memory [event_id] - View the memory weave for a past event
- /recall - List recent memory weaves for the group
- /remember [event_id] - Add a memory fragment outside the DM window
- /digest - Get weekly digest for the group (manual trigger)
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from db.connection import get_session
from db.models import Event, EventMemory
from bot.services.event_memory_service import EventMemoryService
from bot.common.weekly_digest import WeeklyDigestService
from config.logging import set_correlation_context, clear_correlation_context

logger = logging.getLogger("coord_bot.commands.memory")


async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    View the memory weave for a past event.

    Usage: /memory [event_id]
    """
    set_correlation_context(
        correlation_id=f"memory_{update.effective_user.id}",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
    )

    try:
        if not context.args:
            await update.message.reply_text("Usage: /memory [event_id]\n\n" "Example: /memory 123")
            return

        try:
            event_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Event ID must be a number.")
            return

        async with get_session(context.bot_data.get("db_url")) as session:
            # Get event
            from sqlalchemy import select

            result = await session.execute(select(Event).where(Event.event_id == event_id))
            event = result.scalar_one_or_none()

            if not event:
                await update.message.reply_text(f"Event {event_id} not found.")
                return

            # Get memory weave
            memory_service = EventMemoryService(context.bot, session)
            memory_weave = await memory_service.get_memory_weave(event_id)

            if not memory_weave:
                await update.message.reply_text(
                    f"No memory weave yet for this {event.event_type}.\n\n"
                    f"(Memories are collected within 24 hours after the event.)"
                )
                return

            # Format response
            response = memory_weave.weave_text or "No weave text available."

            # Add lineage if present
            if memory_weave.lineage_event_ids:
                lineage_str = ", ".join(str(eid) for eid in memory_weave.lineage_event_ids)
                response += f"\n\n_Part of a series: {lineage_str}_"

            await update.message.reply_text(response, parse_mode="HTML")

            logger.info(
                "User viewed memory weave",
                extra={
                    "event_id": event_id,
                    "user": update.effective_user.id,
                },
            )

    finally:
        clear_correlation_context()


async def recall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    List recent memory weaves for the group.

    Usage: /recall
    """
    set_correlation_context(
        correlation_id=f"recall_{update.effective_user.id}",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
    )

    try:
        if not update.effective_chat:
            return

        async with get_session(context.bot_data.get("db_url")) as session:
            # Get group
            from sqlalchemy import select
            from db.models import Group

            result = await session.execute(select(Group).where(Group.telegram_group_id == update.effective_chat.id))
            group = result.scalar_one_or_none()

            if not group:
                await update.message.reply_text("This group is not registered yet.\n" "Use /start to register.")
                return

            # Get recent memories
            memory_service = EventMemoryService(context.bot, session)
            memories = await memory_service.get_recent_memories(group.group_id, limit=10)

            if not memories:
                await update.message.reply_text(
                    "No memory weaves yet.\n\n" "Memories will appear here after events complete."
                )
                return

            # Build response
            response_parts = [f"📿 <b>Recent memories for {group.group_name or 'this group'}</b>"]

            for memory in memories:
                event = memory.event
                event_title = (
                    f"{event.event_type} • {event.scheduled_time.strftime('%d %b') if event.scheduled_time else 'TBD'}"
                )

                # Show first fragment preview
                preview = ""
                if memory.fragments and len(memory.fragments) > 0:
                    first_fragment = memory.fragments[0].get("text", "")[:50]
                    if first_fragment:
                        preview = (
                            f'\n  "{first_fragment}..."' if len(first_fragment) >= 50 else f'\n  "{first_fragment}"'
                        )

                # Show hashtags
                hashtags = ""
                if memory.hashtags:
                    hashtags = " " + " ".join(f"#{tag}" for tag in memory.hashtags)

                response_parts.append(f"• {event_title}{preview}{hashtags}")

            response = "\n\n".join(response_parts)
            response += "\n\n_Use /memory [event_id] to view full weave_"

            await update.message.reply_text(response, parse_mode="HTML")

            logger.info(
                "User recalled recent memories",
                extra={
                    "group_id": group.group_id,
                    "user": update.effective_user.id,
                    "count": len(memories),
                },
            )

    finally:
        clear_correlation_context()


async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Add a memory fragment outside the DM window.

    Usage: /remember [event_id] [your memory]
    Example: /remember 123 The moment when everyone laughed at the rain
    """
    set_correlation_context(
        correlation_id=f"remember_{update.effective_user.id}",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
    )

    try:
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /remember [event_id] [your memory]\n\n"
                "Example: /remember 123 The moment when everyone laughed at the rain"
            )
            return

        try:
            event_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Event ID must be a number.")
            return

        # Rest of args is the memory text
        memory_text = " ".join(context.args[1:])

        if len(memory_text) < 3:
            await update.message.reply_text("Please share a bit more detail (at least 3 characters).")
            return

        async with get_session(context.bot_data.get("db_url")) as session:
            # Get event
            from sqlalchemy import select

            result = await session.execute(select(Event).where(Event.event_id == event_id))
            event = result.scalar_one_or_none()

            if not event:
                await update.message.reply_text(f"Event {event_id} not found.")
                return

            # Check if user was a participant
            from db.models import EventParticipant

            participant_result = await session.execute(
                select(EventParticipant).where(
                    EventParticipant.event_id == event_id,
                    EventParticipant.telegram_user_id == update.effective_user.id,
                )
            )
            participant = participant_result.scalar_one_or_none()

            if not participant:
                await update.message.reply_text(
                    "You can only add memories for events you attended.\n\n"
                    "(If you think this is wrong, contact an organizer.)"
                )
                return

            # Collect memory fragment
            memory_service = EventMemoryService(context.bot, session)
            fragment = await memory_service.collect_memory_fragment(
                event_id=event_id,
                user_id=update.effective_user.id,
                fragment_text=memory_text,
            )

            # Add to memory
            await memory_service.add_fragment_to_memory(event_id, fragment)
            await session.commit()

            await update.message.reply_text(
                "✓ Memory added!\n\n" "Thank you for sharing. This will be woven into the group's memory of the event."
            )

            logger.info(
                "User added memory fragment",
                extra={
                    "event_id": event_id,
                    "user": update.effective_user.id,
                    "fragment_length": len(memory_text),
                },
            )

    finally:
        clear_correlation_context()


async def weekly_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Get weekly digest for the group (manual trigger).

    Usage: /digest
    """
    set_correlation_context(
        correlation_id=f"digest_{update.effective_user.id}",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
    )

    try:
        if not update.effective_chat:
            return

        async with get_session(context.bot_data.get("db_url")) as session:
            # Get group
            from sqlalchemy import select
            from db.models import Group

            result = await session.execute(select(Group).where(Group.telegram_group_id == update.effective_chat.id))
            group = result.scalar_one_or_none()

            if not group:
                await update.message.reply_text("This group is not registered yet.\n" "Use /start to register.")
                return

            # Generate digest
            digest_service = WeeklyDigestService(context.bot, session)
            digest_data = await digest_service.generate_digest(group.group_id)

            # Build response
            response_parts = []

            # Recent memories
            if digest_data.get("memories"):
                response_parts.append("📿 <b>Recent Memories</b>")
                for memory in digest_data["memories"]:
                    event = memory.event
                    event_title = (
                        f"{event.event_type} • "
                        f"{event.scheduled_time.strftime('%d %b') if event.scheduled_time else 'TBD'}"
                    )
                    response_parts.append(f"• {event_title}")

            # Upcoming events
            if digest_data.get("upcoming_events"):
                response_parts.append("\n📅 <b>Upcoming Events</b>")
                for event in digest_data["upcoming_events"]:
                    event_title = (
                        f"{event.event_type} • "
                        f"{event.scheduled_time.strftime('%d %b %H:%M') if event.scheduled_time else 'TBD'}"
                    )
                    response_parts.append(f"• {event_title}")

            # Stats
            if digest_data.get("stats"):
                stats = digest_data["stats"]
                response_parts.append("\n📊 <b>This Week</b>")
                if stats.get("events_completed"):
                    response_parts.append(f"• {stats['events_completed']} events completed")
                if stats.get("participants"):
                    response_parts.append(f"• {stats['participants']} participants")
                if stats.get("memory_fragments"):
                    response_parts.append(f"• {stats['memory_fragments']} memories shared")

            if not response_parts:
                await update.message.reply_text(
                    "No activity this week.\n\n"
                    "Memories and events will appear here as your group becomes more active!"
                )
                return

            response = "\n".join(response_parts)
            await update.message.reply_text(response, parse_mode="HTML")

            logger.info(
                "User requested weekly digest",
                extra={
                    "group_id": group.group_id,
                    "user": update.effective_user.id,
                },
            )

    finally:
        clear_correlation_context()


async def handle_digest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback queries from weekly digest inline keyboard.

    Callbacks:
    - digest_events - View all events
    - digest_memories - View all memories
    """
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    action = query.data.split("_", 1)[1] if "_" in query.data else ""

    async with get_session(context.bot_data.get("db_url")) as session:
        from sqlalchemy import select
        from db.models import Group

        # Get group
        result = await session.execute(select(Group).where(Group.telegram_group_id == query.message.chat_id))
        group = result.scalar_one_or_none()

        if not group:
            await query.edit_message_text("This group is not registered yet.")
            return

        if action == "events":
            # Show all events
            from db.models import Event

            result = await session.execute(
                select(Event).where(Event.group_id == group.group_id).order_by(Event.scheduled_time.desc()).limit(10)
            )
            events = result.scalars().all()

            if not events:
                await query.edit_message_text("No events found for this group.")
                return

            response = "📅 <b>Recent Events</b>\n\n"
            for event in events:
                status = event.status.value if event.status else "unknown"
                time_str = event.scheduled_time.strftime("%d %b %H:%M") if event.scheduled_time else "TBD"
                response += f"• {event.event_type} • {time_str} [{status}]\n"

            await query.edit_message_text(response, parse_mode="HTML")

        elif action == "memories":
            # Show all memories
            result = await session.execute(
                select(EventMemory)
                .join(Event)
                .where(Event.group_id == group.group_id)
                .order_by(EventMemory.created_at.desc())
                .limit(10)
            )
            memories = result.scalars().all()

            if not memories:
                await query.edit_message_text("No memories found for this group.")
                return

            response = "📿 <b>Recent Memories</b>\n\n"
            for memory in memories:
                event = memory.event
                event_title = (
                    f"{event.event_type} • {event.scheduled_time.strftime('%d %b') if event.scheduled_time else 'TBD'}"
                )
                fragment_count = len(memory.fragments) if memory.fragments else 0
                response += f"• {event_title} ({fragment_count} fragments)\n"

            await query.edit_message_text(response, parse_mode="HTML")

        else:
            await query.edit_message_text("Unknown action.")
