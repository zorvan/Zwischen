#!/usr/bin/env python3
"""
EventLiveCardService - Phase 1: Live event cards in group chat.

Manages:
- Creating live status cards when events are proposed
- Updating cards as participants join/confirm/cancel
- Deleting cards when events lock/completed/cancel
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from telegram import Bot
from telegram.ext import ContextTypes

from db.models import (
    Event,
    EventLiveCard,
    EventParticipant,
    ParticipantStatus,
    GroupSettings,
)

logger = logging.getLogger("coord_bot.services.live_card")


class EventLiveCardService:
    """
    Manages live event status cards in group chat.

    v3.3 Design:
    - Cards appear when event is proposed
    - Auto-update on participant changes
    - Show participant count, hashtags, reactions
    - Deleted when event locks/completes/cancels
    """

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def create_live_card(
        self, event: Event, hashtags: Optional[list[str]] = None
    ) -> Optional[EventLiveCard]:
        """
        Create live status card for a new event.

        Posts initial card to group chat, stores reference.
        """
        group_id = event.group_id
        if not group_id:
            logger.warning("Event has no group_id, cannot create live card")
            return None

        settings = await self._get_group_settings(group_id)
        if not settings.enable_live_cards:
            logger.info(f"Live cards disabled for group {group_id}")
            return None

        card_text = self._build_live_card_text(event, hashtags=hashtags or [])

        message = await self.bot.send_message(
            chat_id=event.group_id, text=card_text, parse_mode="Markdown"
        )

        card = EventLiveCard(
            event_id=event.event_id,
            message_id=message.message_id,
            chat_id=event.group_id,
            participant_count=0,
            confirmed_count=0,
            hashtags=hashtags or [],
        )
        self.session.add(card)
        await self.session.commit()
        await self.session.refresh(card)

        logger.info(f"Created live card for event {event.event_id}")
        return card

    async def update_live_card(self, event: Event) -> Optional[EventLiveCard]:
        """
        Update live card after participant changes.

        Updates: participant count, confirmed count, hashtags
        """
        card = await self._get_live_card(event.event_id)
        if not card:
            logger.warning(f"No live card for event {event.event_id}")
            return None

        result = await self.session.execute(
            select(EventParticipant).where(EventParticipant.event_id == event.event_id)
        )
        participants = result.scalars().all()

        participant_count = sum(
            1 for p in participants if p.status == ParticipantStatus.joined
        )
        confirmed_count = sum(
            1 for p in participants if p.status == ParticipantStatus.confirmed
        )

        hashtags = event.formation_hashtag or []

        card_text = self._build_live_card_text(
            event, participant_count, confirmed_count, hashtags
        )

        try:
            await self.bot.edit_message_text(
                chat_id=card.chat_id,
                message_id=card.message_id,
                text=card_text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to edit live card: {e}")
            return None

        card.participant_count = participant_count
        card.confirmed_count = confirmed_count
        card.hashtags = hashtags
        card.updated_at = datetime.utcnow()
        await self.session.commit()

        logger.info(f"Updated live card for event {event.event_id}")
        return card

    async def delete_live_card(self, event_id: int) -> bool:
        """
        Delete live card when event locks/completes/cancels.

        Also deletes from DB.
        """
        card = await self._get_live_card(event_id)
        if not card:
            return False

        try:
            await self.bot.delete_message(
                chat_id=card.chat_id, message_id=card.message_id
            )
        except Exception as e:
            logger.error(f"Failed to delete live card message: {e}")

        await self.session.delete(card)
        await self.session.commit()

        logger.info(f"Deleted live card for event {event_id}")
        return True

    async def add_reaction(self, event_id: int, emoji: str) -> dict:
        """
        Add bot reaction to live card.

        Returns updated reaction counts.
        """
        card = await self._get_live_card(event_id)
        if not card:
            return {}

        sentiment = self._categorize_sentiment(emoji)

        counts = card.reaction_counts or {}
        current = counts.get(sentiment, 0)
        counts[sentiment] = current + 1
        card.reaction_counts = counts
        await self.session.commit()

        logger.info(f"Added reaction {emoji} ({sentiment}) to event {event_id}")
        return counts

    def _build_live_card_text(
        self,
        event: Event,
        participant_count: Optional[int] = None,
        confirmed_count: Optional[int] = None,
        hashtags: Optional[list[str]] = None,
    ) -> str:
        """Build the live card text."""
        from bot.common.event_formatters import format_scheduled_time

        if participant_count is None or confirmed_count is None:
            participant_count = 0
            confirmed_count = 0

        deadline = event.collapse_at or event.lock_deadline
        time_str = "No deadline"
        if deadline:
            remaining = deadline - datetime.utcnow()
            if remaining.total_seconds() > 0:
                hours = int(remaining.total_seconds() / 3600)
                time_str = f"{hours}h until deadline"

        hashtag_str = ""
        if hashtags:
            hashtag_str = "\n" + " ".join(hashtags)

        scheduled = (
            format_scheduled_time(event.scheduled_time)
            if event.scheduled_time
            else "TBD"
        )

        text = (
            f"🚀 {event.event_type}: {event.description[:50]}\n"
            f"{hashtag_str}\n\n"
            f"📅 {scheduled}\n"
            f"⏳ {time_str}\n\n"
            f"👥 {participant_count or 0}/{event.min_participants} joined\n"
            f"✅ {confirmed_count or 0} confirmed"
        )

        return text

    def _categorize_sentiment(self, emoji: str) -> str:
        """Categorize emoji into sentiment type."""
        enthusiasm = {"🎉", "✨", "❤️", "😍", "🥰"}
        interest = {"🔥", "👀", "🤩", "😮"}
        acknowledgment = {"👍", "👋"}
        timing = {"⏳", "⏰", "🕒"}

        if emoji in enthusiasm:
            return "enthusiasm"
        elif emoji in interest:
            return "interest"
        elif emoji in acknowledgment:
            return "acknowledgment"
        elif emoji in timing:
            return "timing_concern"
        else:
            return "other"

    async def _get_live_card(self, event_id: int) -> Optional[EventLiveCard]:
        """Get live card for event."""
        result = await self.session.execute(
            select(EventLiveCard).where(EventLiveCard.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def _get_group_settings(self, group_id: int) -> GroupSettings:
        """Get group settings, create defaults if not exist."""
        result = await self.session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group_id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            settings = GroupSettings(group_id=group_id)
            self.session.add(settings)
            await self.session.commit()

        return settings
