"""
EventEnrichmentService - Phase 1: Event Enrichments Infrastructure
v3.4 Rebuild Specification Section 2.2

This service manages member contributions during event formation:
- Ideas: Planning suggestions (location, activity, timing)
- Hashtags: Natural language tags that surface on live card
- Memories: Member reflections after event completion

v3.4 Design:
- Replaces JSONB planning_prefs for member input
- Queryable by type and event
- Privacy-aware contributor_hash instead of raw user_id
- Public flag controls visibility (hashtags vs ideas)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from telegram import Bot

from db.models import Event, User, EventEnrichment

logger = logging.getLogger("coord_bot.services.enrichment")


class EventEnrichmentService:
    """
    Manages event enrichments: ideas, hashtags, and memories.

    v3.4 Design:
    - Member contributions stored as separate records (not JSONB)
    - Ideas: Private until event locks, visible to organizer
    - Hashtags: Public after 2+ exist, shown on live card
    - Memories: Private until mosaic assembles
    """

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def add_idea(self, event: Event, user: User, content: str) -> EventEnrichment:
        """
        Add an idea during event formation.

        Ideas are planning suggestions (location, activity, timing) visible
        only to organizer until event locks.

        Args:
            event: The event to add idea to
            user: The user contributing the idea
            content: The idea text

        Returns:
            The created EventEnrichment record
        """
        enrichment = EventEnrichment(
            event_id=event.event_id,
            user_id=user.user_id,
            enrichment_type="idea",
            content=content,
            is_public=False,
            contributor_hash=self._hash_user_id(user.user_id),
        )
        self.session.add(enrichment)
        await self.session.flush()
        logger.info(
            "Idea added to event",
            extra={"event_id": event.event_id, "user_id": user.user_id},
        )
        return enrichment

    async def add_hashtag(
        self, event: Event, user: User, content: str
    ) -> EventEnrichment:
        """
        Add a hashtag during event formation.

        Hashtags attach to the live card after 2+ exist. Up to 3 per member.

        Args:
            event: The event to add hashtag to
            user: The user contributing the hashtag
            content: The hashtag text (without # prefix)

        Returns:
            The created EventEnrichment record
        """
        enrichment = EventEnrichment(
            event_id=event.event_id,
            user_id=user.user_id,
            enrichment_type="hashtag",
            content=content.lower().strip().lstrip("#"),
            is_public=False,  # Public flag set to True when threshold reached
            contributor_hash=self._hash_user_id(user.user_id),
        )
        self.session.add(enrichment)
        await self.session.flush()
        logger.info(
            "Hashtag added to event",
            extra={
                "event_id": event.event_id,
                "user_id": user.user_id,
                "hashtag": content,
            },
        )
        return enrichment

    async def add_memory(
        self, event: Event, user: User, content: str
    ) -> EventEnrichment:
        """
        Add a memory after event completion.

        Memories are stored privately until mosaic assembles.

        Args:
            event: The completed event
            user: The user contributing the memory
            content: The memory text (max 200 words)

        Returns:
            The created EventEnrichment record
        """
        if not event.completed_at:
            logger.warning(
                "Attempted to add memory to incomplete event",
                extra={"event_id": event.event_id},
            )
            raise ValueError("Cannot add memory to incomplete event")

        enrichment = EventEnrichment(
            event_id=event.event_id,
            user_id=user.user_id,
            enrichment_type="memory",
            content=content[:2000],  # Safety limit
            is_public=False,  # Public flag set during mosaic assembly
            contributor_hash=self._hash_user_id(user.user_id),
        )
        self.session.add(enrichment)
        await self.session.flush()
        logger.info(
            "Memory added to event",
            extra={"event_id": event.event_id, "user_id": user.user_id},
        )
        return enrichment

    async def get_by_event(
        self, event: Event, enrichment_type: Optional[str] = None
    ) -> List[EventEnrichment]:
        """
        Get all enrichments for an event, optionally filtered by type.

        Args:
            event: The event to get enrichments for
            enrichment_type: Optional filter: 'idea', 'hashtag', or 'memory'

        Returns:
            List of EventEnrichment records
        """
        stmt = select(EventEnrichment).where(EventEnrichment.event_id == event.event_id)
        if enrichment_type:
            stmt = stmt.where(EventEnrichment.enrichment_type == enrichment_type)
        stmt = stmt.order_by(EventEnrichment.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_public_hashtags(self, event: Event, min_count: int = 2) -> List[str]:
        """
        Get hashtags that should be visible on the live card.

        A hashtag is public if:
        - is_public=True (threshold reached)
        - AND at least min_count hashtags exist for this event

        Args:
            event: The event
            min_count: Minimum total hashtags required before any surface

        Returns:
            List of distinct hashtag texts
        """
        enrichment_stmt = select(EventEnrichment).where(
            EventEnrichment.event_id == event.event_id,
            EventEnrichment.enrichment_type == "hashtag",
        )
        enrichment_result = await self.session.execute(enrichment_stmt)
        all_hashtags = enrichment_result.scalars().all()

        if len(all_hashtags) < min_count:
            return []

        public_tags = [h.content for h in all_hashtags if h.is_public]
        return list(dict.fromkeys(public_tags))  # Deduplicate, preserve order

    async def get_user_contributions(
        self, event: Event, user: User
    ) -> List[EventEnrichment]:
        """
        Get all contributions from a specific user for an event.

        Args:
            event: The event
            user: The user

        Returns:
            List of EventEnrichment records
        """
        stmt = select(EventEnrichment).where(
            EventEnrichment.event_id == event.event_id,
            EventEnrichment.user_id == user.user_id,
        )
        stmt = stmt.order_by(EventEnrichment.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_user_hashtag_count(self, event: Event, user: User) -> int:
        """
        Count how many hashtags a user has contributed to an event.

        Args:
            event: The event
            user: The user

        Returns:
            Number of hashtag enrichments
        """
        stmt = select(func.count(EventEnrichment.enrichment_id)).where(
            EventEnrichment.event_id == event.event_id,
            EventEnrichment.user_id == user.user_id,
            EventEnrichment.enrichment_type == "hashtag",
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def check_hashtag_limit(
        self, event: Event, user: User, limit: int = 3
    ) -> bool:
        """
        Check if user has reached their hashtag limit.

        Args:
            event: The event
            user: The user
            limit: Maximum hashtags allowed per user (default 3)

        Returns:
            True if user can add more hashtags, False if at limit
        """
        count = await self.get_user_hashtag_count(event, user)
        return count < limit

    async def check_hashtag_threshold(
        self, event: Event, min_public: int = 2
    ) -> List[EventEnrichment]:
        """
        Check if hashtag threshold is reached and promote hashtags.

        When min_public hashtags exist, promote all to is_public=True.

        Args:
            event: The event
            min_public: Minimum public hashtags required

        Returns:
            List of enriched hashtag records that were promoted
        """
        enrichment_stmt = select(EventEnrichment).where(
            EventEnrichment.event_id == event.event_id,
            EventEnrichment.enrichment_type == "hashtag",
            EventEnrichment.is_public == False,  # noqa: E712
        )
        enrichment_result = await self.session.execute(enrichment_stmt)
        private_hashtags = enrichment_result.scalars().all()

        if len(private_hashtags) >= min_public:
            promoted = []
            for enrichment in private_hashtags:
                enrichment.is_public = True
                self.session.add(enrichment)
                promoted.append(enrichment)
            await self.session.flush()
            logger.info(
                "Hashtag threshold reached, promoted hashtags",
                extra={"event_id": event.event_id, "count": len(promoted)},
            )
            return promoted

        return []

    async def get_ideas_for_organizer(self, event: Event) -> List[EventEnrichment]:
        """
        Get all ideas for an event (for organizer review).

        Args:
            event: The event

        Returns:
            List of idea enrichments
        """
        return await self.get_by_event(event, enrichment_type="idea")

    async def get_memories_for_mosaic(self, event: Event) -> List[EventEnrichment]:
        """
        Get all memories for mosaic assembly.

        Args:
            event: The completed event

        Returns:
            List of memory enrichments
        """
        return await self.get_by_event(event, enrichment_type="memory")

    def _hash_user_id(self, user_id: int) -> str:
        """
        Hash a user_id for privacy (not stored in plaintext).

        Args:
            user_id: The raw user_id

        Returns:
            SHA-256 hex digest
        """
        return hashlib.sha256(str(user_id).encode()).hexdigest()
