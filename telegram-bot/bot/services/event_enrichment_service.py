#!/usr/bin/env python3
"""Event Enrichment Service for v3.5.

This service manages member contributions during event formation:
- Ideas (max 300 chars, private until event locks)
- Hashtags (max 3 per user per event, public after 2+ contributors)
- Memories (max 200 words, private until mosaic assembles)

All content is stored in event_enrichments table. Zero LLM involvement.

PRD v3.5 Section 2.3: Application-layer validation replaces SQL CHECK constraints.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from db.models import EventEnrichment


# =============================================================================
# Validation Constants
# =============================================================================

MAX_IDEA_LENGTH = 300
MAX_MEMORY_WORDS = 200
MAX_HASHTAGS_PER_USER = 3

VALID_ENRICHMENT_TYPES = {"idea", "hashtag", "memory"}

HASHTAG_PUBLIC_THRESHOLD = 2  # Hashtags become public after 2+ members contribute


# =============================================================================
# Exceptions
# =============================================================================

class EnrichmentError(Exception):
    """Base exception for enrichment operations."""
    pass


class ContentValidationError(EnrichmentError):
    """Raised when content fails validation."""
    pass


class HashtagLimitError(EnrichmentError):
    """Raised when user exceeds hashtag limit."""
    pass


# =============================================================================
# Service Class
# =============================================================================

class EventEnrichmentService:
    """
    Single write path for event enrichments.
    
    All member-contributed content (ideas, hashtags, memories) goes here.
    Organizer-level draft storage stays in planning_prefs.
    This boundary prevents the JSON blob from growing.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    # -------------------------------------------------------------------------
    # Core CRUD Operations
    # -------------------------------------------------------------------------
    
    async def add_idea(
        self,
        event_id: int,
        telegram_user_id: int,
        content: str,
    ) -> EventEnrichment:
        """
        Add an idea to an event.
        
        Ideas are visible only to organizer until event locks.
        Maximum 300 characters.
        
        Args:
            event_id: Event being enriched
            telegram_user_id: User contributing the idea
            content: Idea text (max 300 chars)
            
        Returns:
            Created EventEnrichment record
            
        Raises:
            ContentValidationError: If content exceeds 300 chars
        """
        # Validate content
        self._validate_idea_content(content)
        
        # Create enrichment
        enrichment = EventEnrichment(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            enrichment_type="idea",
            content=content[:MAX_IDEA_LENGTH].strip(),
            is_public=False,  # Ideas stay private until event locks
        )
        
        self.session.add(enrichment)
        await self.session.flush()
        
        return enrichment
    
    async def add_hashtag(
        self,
        event_id: int,
        telegram_user_id: int,
        hashtag: str,
    ) -> EventEnrichment:
        """
        Add a hashtag to an event.
        
        Max 3 hashtags per user per event.
        Hashtags become public on live card after 2+ members contribute the same tag.
        
        Args:
            event_id: Event being enriched
            telegram_user_id: User contributing the hashtag
            hashtag: Hashtag text (will be normalized)
            
        Returns:
            Created EventEnrichment record
            
        Raises:
            HashtagLimitError: If user already has 3 hashtags for this event
        """
        # Check per-user limit
        current_count = await self._count_user_hashtags(event_id, telegram_user_id)
        if current_count >= MAX_HASHTAGS_PER_USER:
            raise HashtagLimitError(
                f"Maximum {MAX_HASHTAGS_PER_USER} hashtags per event. "
                "Remove an existing hashtag to add a new one."
            )
        
        # Normalize hashtag
        normalized = self._normalize_hashtag(hashtag)
        
        # Check if this exact hashtag already exists from another user
        # If so, we'll mark it as having multiple contributors
        existing_count = await self._count_hashtag_contributors(event_id, normalized)
        
        # Create enrichment
        # Public visibility is determined by _update_hashtag_visibility
        enrichment = EventEnrichment(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            enrichment_type="hashtag",
            content=normalized,
            is_public=existing_count >= HASHTAG_PUBLIC_THRESHOLD - 1,  # Will be public if this makes 2+
        )
        
        self.session.add(enrichment)
        await self.session.flush()
        
        # Update visibility for all matching hashtags if threshold is now met
        if existing_count + 1 >= HASHTAG_PUBLIC_THRESHOLD:
            await self._make_hashtag_public(event_id, normalized)
        
        return enrichment
    
    async def add_memory(
        self,
        event_id: int,
        telegram_user_id: int,
        content: str,
    ) -> EventEnrichment:
        """
        Add a memory to a completed event.
        
        Memories are private until mosaic assembles (at least 2 fragments).
        Maximum 200 words.
        
        Args:
            event_id: Completed event
            telegram_user_id: User contributing the memory
            content: Memory text (max 200 words)
            
        Returns:
            Created EventEnrichment record
            
        Raises:
            ContentValidationError: If content exceeds 200 words
        """
        # Validate content
        self._validate_memory_content(content)
        
        # Create enrichment
        enrichment = EventEnrichment(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            enrichment_type="memory",
            content=content.strip(),
            is_public=False,  # Memories stay private until mosaic
        )
        
        self.session.add(enrichment)
        await self.session.flush()
        
        return enrichment
    
    async def get_by_event(
        self,
        event_id: int,
        enrichment_type: Optional[str] = None,
        include_private: bool = False,
    ) -> List[EventEnrichment]:
        """
        Get all enrichments for an event.
        
        Args:
            event_id: Event to query
            enrichment_type: Filter by type (idea, hashtag, memory)
            include_private: If False, only return public enrichments
            
        Returns:
            List of EventEnrichment records
        """
        query = select(EventEnrichment).where(
            EventEnrichment.event_id == event_id
        )
        
        if enrichment_type:
            query = query.where(EventEnrichment.enrichment_type == enrichment_type)
        
        if not include_private:
            query = query.where(EventEnrichment.is_public == True)
        
        query = query.order_by(EventEnrichment.created_at)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())
    
    async def get_public_hashtags(self, event_id: int) -> List[str]:
        """
        Get public hashtags for display on live card.
        
        Args:
            event_id: Event to query
            
        Returns:
            List of hashtag strings (e.g., ["#hiking", "#weekend"])
        """
        result = await self.session.execute(
            select(EventEnrichment.content)
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.enrichment_type == "hashtag",
                EventEnrichment.is_public == True,
            )
            .distinct()
        )
        
        return [row[0] for row in result.all()]
    
    async def get_user_contributions(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> List[EventEnrichment]:
        """
        Get all contributions from a specific user for an event.
        
        Used for "My contributions" view in Enrich sub-menu.
        
        Args:
            event_id: Event to query
            telegram_user_id: User to look up
            
        Returns:
            List of user's EventEnrichment records
        """
        result = await self.session.execute(
            select(EventEnrichment)
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.telegram_user_id == telegram_user_id,
            )
            .order_by(EventEnrichment.created_at)
        )
        
        return list(result.scalars().all())
    
    async def get_memories_for_mosaic(
        self,
        event_id: int,
        min_fragments: int = 2,
    ) -> List[EventEnrichment]:
        """
        Get memory fragments ready for mosaic assembly.
        
        Mosaic assembles when at least 2 fragments exist.
        
        Args:
            event_id: Completed event
            min_fragments: Minimum fragments needed (default 2)
            
        Returns:
            List of memory enrichments, or empty if insufficient fragments
        """
        # First count available fragments
        count_result = await self.session.execute(
            select(func.count(EventEnrichment.enrichment_id))
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.enrichment_type == "memory",
            )
        )
        count = count_result.scalar() or 0
        
        if count < min_fragments:
            return []
        
        # Return all fragments for assembly
        result = await self.session.execute(
            select(EventEnrichment)
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.enrichment_type == "memory",
            )
            .order_by(EventEnrichment.created_at)
        )
        
        return list(result.scalars().all())
    
    async def make_memories_public(self, event_id: int) -> int:
        """
        Mark all memories for an event as public.
        
        Called after mosaic is assembled and posted to group.
        
        Args:
            event_id: Event whose memories should become public
            
        Returns:
            Number of memories made public
        """
        from sqlalchemy import update
        
        result = await self.session.execute(
            update(EventEnrichment)
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.enrichment_type == "memory",
                EventEnrichment.is_public == False,
            )
            .values(is_public=True)
        )
        
        return result.rowcount
    
    # -------------------------------------------------------------------------
    # Private Helper Methods
    # -------------------------------------------------------------------------
    
    @staticmethod
    def _validate_idea_content(content: str) -> None:
        """Validate idea content length."""
        if not content or not isinstance(content, str):
            raise ContentValidationError("Content must be a non-empty string")
        
        if len(content) > MAX_IDEA_LENGTH:
            raise ContentValidationError(
                f"Ideas must be {MAX_IDEA_LENGTH} characters or less"
            )
    
    @staticmethod
    def _validate_memory_content(content: str) -> None:
        """Validate memory content word count."""
        if not content or not isinstance(content, str):
            raise ContentValidationError("Content must be a non-empty string")
        
        word_count = len(content.split())
        if word_count > MAX_MEMORY_WORDS:
            raise ContentValidationError(
                f"Memories must be {MAX_MEMORY_WORDS} words or less (you have {word_count})"
            )
    
    @staticmethod
    def _normalize_hashtag(hashtag: str) -> str:
        """
        Normalize a hashtag for storage.
        
        - Strip whitespace
        - Lowercase
        - Ensure # prefix
        """
        if not hashtag:
            return ""
        
        normalized = hashtag.strip().lower()
        
        # Ensure # prefix
        if not normalized.startswith("#"):
            normalized = f"#{normalized}"
        
        return normalized
    
    async def _count_user_hashtags(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> int:
        """Count how many hashtags a user has contributed to an event."""
        result = await self.session.execute(
            select(func.count(EventEnrichment.enrichment_id))
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.telegram_user_id == telegram_user_id,
                EventEnrichment.enrichment_type == "hashtag",
            )
        )
        return result.scalar() or 0
    
    async def _count_hashtag_contributors(
        self,
        event_id: int,
        hashtag: str,
    ) -> int:
        """Count unique users who have contributed this exact hashtag."""
        result = await self.session.execute(
            select(func.count(func.distinct(EventEnrichment.telegram_user_id)))
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.enrichment_type == "hashtag",
                EventEnrichment.content == hashtag,
            )
        )
        return result.scalar() or 0
    
    async def _make_hashtag_public(
        self,
        event_id: int,
        hashtag: str,
    ) -> int:
        """Mark a hashtag as public for all contributors."""
        from sqlalchemy import update
        
        result = await self.session.execute(
            update(EventEnrichment)
            .where(
                EventEnrichment.event_id == event_id,
                EventEnrichment.enrichment_type == "hashtag",
                EventEnrichment.content == hashtag,
                EventEnrichment.is_public == False,
            )
            .values(is_public=True)
        )
        
        return result.rowcount


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "EventEnrichmentService",
    "EnrichmentError",
    "ContentValidationError",
    "HashtagLimitError",
    "MAX_IDEA_LENGTH",
    "MAX_MEMORY_WORDS",
    "MAX_HASHTAGS_PER_USER",
    "VALID_ENRICHMENT_TYPES",
    "HASHTAG_PUBLIC_THRESHOLD",
]
