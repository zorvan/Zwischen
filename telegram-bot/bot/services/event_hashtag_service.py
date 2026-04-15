#!/usr/bin/env python3
"""
EventHashtagService - Phase 1: Hashtag management.

Manages:
- Validating hashtags (format, count)
- Assigning hashtags to events
- Freezing hashtags after lock
- Querying by hashtag
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Event

logger = logging.getLogger("coord_bot.services.hashtags")


class EventHashtagService:
    """
    Manages event hashtags.
    
    v3.3 Design:
    - Hashtags = event identity (permanent)
    - Format: #[a-z0-9_]+
    - Max configurable per group (default: 5)
    - Frozen on event lock
    """

    HASH_PATTERN = re.compile(r"^#[a-z0-9_]+$")
    MAX_HASHTAGS_DEFAULT = 5

    def __init__(self, session: AsyncSession):
        self.session = session

    async def validate_hashtags(
        self,
        hashtags: list[str],
        group_id: Optional[int] = None
    ) -> tuple[bool, list[str]]:
        """
        Validate hashtags format and count.
        
        Returns: (is_valid, list_of_errors)
        """
        errors = []

        if not hashtags:
            return True, errors

        if len(hashtags) > self.MAX_HASHTAGS_DEFAULT:
            errors.append(f"Maximum {self.MAX_HASHTAGS_DEFAULT} hashtags allowed")

        for tag in hashtags:
            tag_lower = tag.lower()
            if not self.HASH_PATTERN.match(tag_lower):
                errors.append(f"Invalid format: {tag}.Must be #\\[a-z0-9_\\]+")
            
            if len(tag) > 30:
                errors.append(f"Too long: {tag}. Max 30 characters")

        return len(errors) == 0, errors

    async def assign_hashtags(
        self,
        event: Event,
        hashtags: list[str]
    ) -> Event:
        """
        Assign hashtags to event (during formation).
        
        Hashtags are stored in `formation_hashtag` column.
        """
        valid, errors = await self.validate_hashtags(hashtags)
        if not valid:
            raise ValueError(f"Invalid hashtags: {'; '.join(errors)}")

        normalized = [tag.lower().lstrip("#") for tag in hashtags]

        event.formation_hashtag = normalized
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)

        logger.info(f"Assigned {normalized} to event {event.event_id}")
        return event

    async def freeze_hashtags(self, event: Event) -> Event:
        """
        Freeze hashtags when event locks.
        
        Moves hashtags from `formation_hashtag` to `locked_hashtag`.
        """
        if event.formation_hashtag:
            event.locked_hashtag = event.formation_hashtag
            event.formation_hashtag = None
            self.session.add(event)
            await self.session.commit()
            await self.session.refresh(event)

            logger.info(f"Frozen hashtags for event {event.event_id}")
        
        return event

    async def query_by_hashtag(
        self,
        group_id: int,
        hashtag: str
    ) -> list[Event]:
        """
        Query events by hashtag.
        
        Searches both formation and locked hashtags.
        """
        hashtag_lower = hashtag.lower().lstrip("#")
        
        result = await self.session.execute(
            select(Event)
            .where(
                Event.group_id == group_id,
                (Event.formation_hashtag.contains([hashtag_lower]) |
                 Event.locked_hashtag.contains([hashtag_lower]))
            )
        )
        
        return result.scalars().all()

    async def get_hashtags_for_event(
        self,
        event_id: int
    ) -> list[str]:
        """Get all hashtags for event (formation + locked)."""
        result = await self.session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = result.scalar_one_or_none()
        
        if not event:
            return []

        hashtags = []
        if event.formation_hashtag:
            hashtags.extend(event.formation_hashtag)
        if event.locked_hashtag:
            hashtags.extend(event.locked_hashtag)
        
        return hashtags
