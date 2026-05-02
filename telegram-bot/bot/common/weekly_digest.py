"""
Weekly Group Digest - Recent memories + upcoming events.
PRD v2 Priority 3: Layer 3 Features.

Sends weekly digest to group chat with:
- Recent event memories
- Upcoming events
- Activity statistics
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from bot.common.i18n import t
from db.models import Event, EventMemory, EventParticipant, Group, ParticipantStatus

logger = logging.getLogger("coord_bot.digest")


class WeeklyDigestService:
    """
    Generates and sends weekly digest to groups.

    Content:
    - Recent event memories (completed events)
    - Upcoming events (next 7 days)
    - Activity statistics
    """

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def generate_digest(
        self,
        group_id: int,
        days_back: int = 7,
        days_forward: int = 7,
    ) -> Dict[str, Any]:
        """
        Generate weekly digest for a group.

        Returns dict with: memories, upcoming_events, stats
        """
        now = datetime.utcnow()
        past_cutoff = now - timedelta(days=days_back)
        future_cutoff = now + timedelta(days=days_forward)

        # Get recent memories
        memories = await self._get_recent_memories(group_id, past_cutoff)

        # Get upcoming events
        upcoming = await self._get_upcoming_events(group_id, now, future_cutoff)

        # Get activity stats
        stats = await self._get_activity_stats(group_id, past_cutoff, now)

        return {
            "group_id": group_id,
            "period_start": past_cutoff,
            "period_end": future_cutoff,
            "memories": memories,
            "upcoming_events": upcoming,
            "stats": stats,
            "generated_at": now,
        }

    async def _get_recent_memories(
        self,
        group_id: int,
        since: datetime,
    ) -> List[Dict[str, Any]]:
        """Get recent event memories for group."""
        result = await self.session.execute(
            select(EventMemory, Event)
            .join(Event, EventMemory.event_id == Event.event_id)
            .where(
                Event.group_id == group_id,
                Event.completed_at >= since,
            )
            .order_by(Event.completed_at.desc())
            .limit(5)
        )

        memories = []
        for memory, event in result.all():
            memories.append(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "description": (
                        event.description[:100] if event.description else "N/A"
                    ),
                    "completed_at": event.completed_at,
                    "weave_text": memory.weave_text,
                    "hashtags": memory.hashtags or [],
                    "participant_count": await self._get_participant_count(
                        event.event_id
                    ),
                }
            )

        return memories

    async def _get_upcoming_events(
        self,
        group_id: int,
        from_date: datetime,
        to_date: datetime,
    ) -> List[Dict[str, Any]]:
        """Get upcoming events for group."""
        result = await self.session.execute(
            select(Event)
            .where(
                Event.group_id == group_id,
                Event.state.in_(["proposed", "interested", "confirmed", "locked"]),
                Event.scheduled_time >= from_date,
                Event.scheduled_time <= to_date,
            )
            .order_by(Event.scheduled_time)
            .limit(10)
        )

        events = []
        for event in result.scalars().all():
            events.append(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "description": (
                        event.description[:100] if event.description else "N/A"
                    ),
                    "scheduled_time": event.scheduled_time,
                    "state": event.state,
                    "confirmed_count": await self._get_confirmed_count(event.event_id),
                    "minimum": event.min_participants,
                }
            )

        return events

    async def _get_activity_stats(
        self,
        group_id: int,
        from_date: datetime,
        to_date: datetime,
    ) -> Dict[str, Any]:
        """Get activity statistics for group."""
        # Events completed
        completed_result = await self.session.execute(
            select(func.count(Event.event_id)).where(
                Event.group_id == group_id,
                Event.completed_at >= from_date,
                Event.completed_at <= to_date,
            )
        )
        events_completed = completed_result.scalar() or 0

        # Events created
        created_result = await self.session.execute(
            select(func.count(Event.event_id)).where(
                Event.group_id == group_id,
                Event.created_at >= from_date,
                Event.created_at <= to_date,
            )
        )
        events_created = created_result.scalar() or 0

        # Total participants (unique users)
        participant_result = await self.session.execute(
            select(func.count(func.distinct(EventParticipant.telegram_user_id)))
            .join(Event, EventParticipant.event_id == Event.event_id)
            .where(
                Event.group_id == group_id,
                Event.created_at >= from_date,
            )
        )
        unique_participants = participant_result.scalar() or 0

        # Total confirmations
        confirm_result = await self.session.execute(
            select(func.count(EventParticipant.event_id))
            .join(Event, EventParticipant.event_id == Event.event_id)
            .where(
                Event.group_id == group_id,
                EventParticipant.status == ParticipantStatus.confirmed,
                EventParticipant.confirmed_at >= from_date,
            )
        )
        total_confirmations = confirm_result.scalar() or 0

        return {
            "events_completed": events_completed,
            "events_created": events_created,
            "unique_participants": unique_participants,
            "total_confirmations": total_confirmations,
            "period_days": (to_date - from_date).days,
        }

    async def _get_participant_count(self, event_id: int) -> int:
        """Get total participant count for event."""
        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id
            )
        )
        return result.scalar() or 0

    async def _get_confirmed_count(self, event_id: int) -> int:
        """Get confirmed participant count for event."""
        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == ParticipantStatus.confirmed,
            )
        )
        return result.scalar() or 0

    def format_digest_message(self, digest: Dict[str, Any]) -> str:
        """Format digest as Telegram message."""
        lines = [
            "📅 *Weekly Group Digest*\n",
            f"_Period: {digest['period_start'].strftime('%b %d')} - {digest['period_end'].strftime('%b %d')}_\n",
        ]

        # Activity Stats
        stats = digest["stats"]
        lines.extend(
            [
                "*📊 Activity Summary*\n",
                f"• Events completed: {stats['events_completed']}",
                f"• Events created: {stats['events_created']}",
                f"• Active participants: {stats['unique_participants']}",
                f"• Total confirmations: {stats['total_confirmations']}\n",
            ]
        )

        # Recent Memories
        memories = digest["memories"]
        if memories:
            lines.append("*📿 Recent Memories*\n")
            for mem in memories[:3]:
                hashtags = " ".join(f"#{tag}" for tag in mem.get("hashtags", []))
                lines.append(
                    f"• {mem['event_type']}: {mem['description']}\n"
                    f"  _{mem['participant_count']} participants_ {hashtags}"
                )
            lines.append("")

        # Upcoming Events
        upcoming = digest["upcoming_events"]
        if upcoming:
            lines.append("*🗓️ Upcoming Events*\n")
            for evt in upcoming[:5]:
                time_str = evt["scheduled_time"].strftime("%a %b %d, %H:%M")
                lines.append(
                    f"• {evt['event_type']}: {evt['description']}\n"
                    f"  _{time_str}_ • {evt['confirmed_count']}/{evt['minimum']} confirmed"
                )
            lines.append("")

        # Footer
        lines.append(
            f"_Generated on {digest['generated_at'].strftime('%Y-%m-%d %H:%M')}_"
        )

        return "\n".join(lines)

    async def send_digest(
        self,
        group_chat_id: int,
        digest: Dict[str, Any],
    ) -> bool:
        """Send digest to group chat."""
        message = self.format_digest_message(digest)

        # Add keyboard for quick actions
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t("digest_view_all_events", lang="en"),
                        callback_data="digest_events",
                    ),
                    InlineKeyboardButton(
                        t("digest_view_all_memories", lang="en"),
                        callback_data="digest_memories",
                    ),
                ],
            ]
        )

        try:
            await self.bot.send_message(
                chat_id=group_chat_id,
                text=message,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
            logger.info("Weekly digest sent to group %s", group_chat_id)
            return True
        except Exception as e:
            logger.error("Failed to send digest to group %s: %s", group_chat_id, e)
            return False


async def send_weekly_digest(
    bot: Bot,
    session: AsyncSession,
    group_id: int,
    group_chat_id: int,
) -> bool:
    """
    Convenience function to generate and send weekly digest.

    Usage:
        await send_weekly_digest(bot, session, group_id, chat_id)
    """
    service = WeeklyDigestService(bot, session)
    digest = await service.generate_digest(group_id)
    return await service.send_digest(group_chat_id, digest)


async def send_digest_to_all_groups(
    bot: Bot,
    session: AsyncSession,
) -> Dict[str, int]:
    """
    Send weekly digest to all active groups.

    Returns dict with: sent, failed, skipped
    """
    result = await session.execute(select(Group))
    groups = result.scalars().all()

    stats = {"sent": 0, "failed": 0, "skipped": 0}

    for group in groups:
        # Skip groups with no recent activity
        event_result = await session.execute(
            select(func.count(Event.event_id)).where(
                Event.group_id == group.group_id,
                Event.created_at >= datetime.utcnow() - timedelta(days=30),
            )
        )
        recent_events = event_result.scalar() or 0

        if recent_events == 0:
            stats["skipped"] += 1
            continue

        success = await send_weekly_digest(
            bot,
            session,
            group.group_id,
            group.telegram_group_id,
        )

        if success:
            stats["sent"] += 1
        else:
            stats["failed"] += 1

    return stats
