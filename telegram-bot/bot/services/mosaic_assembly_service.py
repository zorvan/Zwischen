#!/usr/bin/env python3
"""Mosaic Assembly Service for v3.5.

Assembles private memories from event_enrichments into a public mosaic
when events complete. Transforms fragmented private contributions into
a cohesive public memory artifact.

PRD v3.5 Section 4.4: Memory Loop Completion
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from db.models import EventEnrichment, EventMemory, EventLineage
from bot.services.event_enrichment_service import EventEnrichmentService


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class MosaicFragment:
    """A single fragment in the mosaic."""

    id: int
    content: str
    author_id: int
    created_at: datetime
    type: str = "memory"


@dataclass
class MosaicResult:
    """Result of mosaic assembly."""

    event_id: int
    fragments: List[MosaicFragment]
    summary: Optional[str]
    participant_count: int
    assembled_at: datetime
    lineage: Optional[Dict[str, Any]] = None


# =============================================================================
# Service Class
# =============================================================================


class MosaicAssembler:
    """
    Assembles private memories into public mosaics.

    When an event completes, this service:
    1. Fetches all private memory enrichments for the event
    2. Marks them as public
    3. Generates a summary using LLM
    4. Stores the mosaic in EventMemory
    5. Records lineage for future reference
    """

    # Maximum content length for a fragment
    MAX_FRAGMENT_LENGTH = 2000

    def __init__(self, session: AsyncSession, llm_client: Optional[Any] = None):
        self.session = session
        self.llm_client = llm_client
        self._enrichment_service: Optional[EventEnrichmentService] = None

    @property
    def enrichment_service(self) -> EventEnrichmentService:
        """Lazy initialization of enrichment service."""
        if self._enrichment_service is None:
            self._enrichment_service = EventEnrichmentService(self.session)
        return self._enrichment_service

    # -------------------------------------------------------------------------
    # Core Assembly Operations
    # -------------------------------------------------------------------------

    async def assemble_mosaic(
        self,
        event_id: int,
        parent_event_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Assemble a mosaic from event memories.

        Args:
            event_id: Event to assemble mosaic for
            parent_event_id: Optional parent event for lineage tracking

        Returns:
            Mosaic result dictionary
        """
        # Fetch all private memories for this event
        memories = await self._fetch_memories(event_id)

        if not memories:
            return {
                "event_id": event_id,
                "fragments": [],
                "summary": None,
                "participant_count": 0,
                "assembled_at": datetime.now(timezone.utc).isoformat(),
            }

        # Create fragments from memories
        fragments = [self._create_fragment(m) for m in memories]

        # Mark memories as public
        for memory in memories:
            await self._update_memory_visibility(memory.id, is_public=True)

        # Generate summary
        summary = await self._generate_summary(memories)

        # Record lineage if parent specified
        lineage = None
        if parent_event_id:
            lineage = await self._record_lineage(event_id, parent_event_id)

        # Build result
        result = {
            "event_id": event_id,
            "fragments": [
                {
                    "id": f.id,
                    "content": f.content,
                    "author_id": f.author_id,
                    "created_at": f.created_at.isoformat(),
                    "type": f.type,
                }
                for f in fragments
            ],
            "summary": summary,
            "participant_count": len(set(f.author_id for f in fragments)),
            "assembled_at": datetime.now(timezone.utc).isoformat(),
        }

        if lineage:
            result["lineage"] = lineage

        return result

    async def assemble_and_store(
        self,
        event_id: int,
        parent_event_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Assemble mosaic and store it in EventMemory.

        This is the main entry point for completing the memory loop.

        Args:
            event_id: Event to assemble mosaic for
            parent_event_id: Optional parent event for lineage tracking

        Returns:
            Mosaic result dictionary
        """
        # Assemble the mosaic
        mosaic = await self.assemble_mosaic(event_id, parent_event_id)

        # Store in EventMemory
        await self._store_mosaic(event_id, mosaic)

        # Append fragments to EventMemory
        await self._append_to_event_memory(event_id, mosaic["fragments"])

        return mosaic

    # -------------------------------------------------------------------------
    # Fetch Operations
    # -------------------------------------------------------------------------

    async def _fetch_memories(self, event_id: int) -> List[EventEnrichment]:
        """
        Fetch all private memory enrichments for an event.

        Args:
            event_id: Event to fetch memories for

        Returns:
            List of memory enrichments
        """
        stmt = select(EventEnrichment).where(
            EventEnrichment.event_id == event_id,
            EventEnrichment.enrichment_type == "memory",
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # -------------------------------------------------------------------------
    # Lineage Fragment Display (v3.5 Feature 4)
    # -------------------------------------------------------------------------

    async def get_lineage_fragments(self, event_id: int) -> List[Dict[str, Any]]:
        """
        Get memory fragments from parent events via lineage.

        v3.5: Displays memories from previous events that are related
        to this event through the lineage chain. Creates a memory
        trail that shows context and history.

        Args:
            event_id: Event to get lineage for

        Returns:
            List of fragment dictionaries with content and metadata
        """
        # Find parent event through lineage
        lineage_stmt = select(EventLineage).where(
            EventLineage.child_event_id == event_id
        )
        lineage_result = await self.session.execute(lineage_stmt)
        lineage = lineage_result.scalar_one_or_none()

        if not lineage:
            return []  # No parent event

        parent_event_id = lineage.parent_event_id

        # Fetch public memories from parent event
        memories_stmt = (
            select(EventEnrichment)
            .where(
                EventEnrichment.event_id == parent_event_id,
                EventEnrichment.enrichment_type == "memory",
                EventEnrichment.is_public.is_(True),  # Only public memories
            )
            .order_by(EventEnrichment.created_at.desc())
            .limit(5)
        )  # Show last 5

        memories_result = await self.session.execute(memories_stmt)
        memories = memories_result.scalars().all()

        # Convert to display format
        fragments = []
        for memory in memories:
            fragments.append(
                {
                    "id": memory.id,
                    "content": (
                        memory.content[:200] + "..."
                        if len(memory.content) > 200
                        else memory.content
                    ),
                    "author_id": memory.telegram_user_id,
                    "created_at": (
                        memory.created_at.isoformat() if memory.created_at else None
                    ),
                    "parent_event_id": parent_event_id,
                }
            )

        return fragments

    # -------------------------------------------------------------------------
    # Fragment Operations
    # -------------------------------------------------------------------------

    def _create_fragment(self, memory: EventEnrichment) -> MosaicFragment:
        """
        Create a mosaic fragment from a memory enrichment.

        Args:
            memory: Memory enrichment to convert

        Returns:
            Mosaic fragment
        """
        content = memory.content

        # Truncate if too long
        if len(content) > self.MAX_FRAGMENT_LENGTH:
            content = content[: self.MAX_FRAGMENT_LENGTH - 3] + "..."

        return MosaicFragment(
            id=memory.id,
            content=content,
            author_id=memory.telegram_user_id,
            created_at=memory.created_at or datetime.now(timezone.utc),
            type="memory",
        )

    # -------------------------------------------------------------------------
    # Visibility Operations
    # -------------------------------------------------------------------------

    async def _update_memory_visibility(
        self,
        memory_id: int,
        is_public: bool = True,
    ) -> None:
        """
        Update the visibility of a memory.

        Args:
            memory_id: Memory to update
            is_public: New visibility status
        """
        stmt = (
            update(EventEnrichment)
            .where(EventEnrichment.id == memory_id)
            .values(is_public=is_public)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    # -------------------------------------------------------------------------
    # Summary Generation
    # -------------------------------------------------------------------------

    async def _generate_summary(
        self,
        memories: List[EventEnrichment],
    ) -> Optional[str]:
        """
        Generate a summary of memories using LLM.

        Falls back to simple concatenation if LLM unavailable.

        Args:
            memories: List of memories to summarize

        Returns:
            Summary string or None
        """
        if not memories:
            return None

        # If LLM available, use it
        if self.llm_client:
            try:
                return await self._generate_llm_summary(memories)
            except Exception:
                # Fall back to basic summary
                pass

        # Basic fallback: return first memory as summary
        return f"Event memories from {len(memories)} participants"

    async def _generate_llm_summary(
        self,
        memories: List[EventEnrichment],
    ) -> str:
        """
        Use LLM to generate a poetic summary of memories.

        Args:
            memories: List of memories to summarize

        Returns:
            Generated summary
        """
        if not self.llm_client:
            raise ValueError("LLM client not available")

        # Build prompt from memories
        memory_texts = [m.content for m in memories]
        prompt = self._build_summary_prompt(memory_texts)

        try:
            # Call LLM
            response = await self.llm_client.summarize_memories(prompt)
            return response.get("summary", "Beautiful memories shared by all")
        except Exception as e:
            raise ValueError(f"LLM summary generation failed: {e}")

    def _build_summary_prompt(self, memory_texts: List[str]) -> str:
        """Build prompt for LLM summarization."""
        memories_str = "\n".join(f"- {text}" for text in memory_texts)

        return f"""Summarize these event memories into a brief, poetic paragraph:

Memories:
{memories_str}

Create a warm, cohesive summary that captures the essence of the event.
Keep it under 200 words."""

    # -------------------------------------------------------------------------
    # Lineage Operations
    # -------------------------------------------------------------------------

    async def _record_lineage(
        self,
        event_id: int,
        parent_event_id: int,
    ) -> Dict[str, Any]:
        """
        Record lineage between events.

        Args:
            event_id: Child event
            parent_event_id: Parent event

        Returns:
            Lineage record
        """
        lineage = EventLineage(
            parent_event_id=parent_event_id,
            child_event_id=event_id,
            relationship_type="memory_continuation",
            created_at=datetime.now(timezone.utc),
        )

        self.session.add(lineage)
        await self.session.commit()

        return {
            "parent_event_id": parent_event_id,
            "child_event_id": event_id,
            "relationship_type": "memory_continuation",
        }

    # -------------------------------------------------------------------------
    # Storage Operations
    # -------------------------------------------------------------------------

    async def _store_mosaic(
        self,
        event_id: int,
        mosaic: Dict[str, Any],
    ) -> None:
        """
        Store mosaic in EventMemory.

        Args:
            event_id: Event to store mosaic for
            mosaic: Mosaic data to store
        """
        # Check if EventMemory exists
        stmt = select(EventMemory).where(EventMemory.event_id == event_id)
        result = await self.session.execute(stmt)
        event_memory = result.scalar_one_or_none()

        if event_memory:
            # Update existing
            event_memory.mosaic = mosaic
            event_memory.mosaic_assembled_at = datetime.now(timezone.utc)
        else:
            # Create new
            event_memory = EventMemory(
                event_id=event_id,
                mosaic=mosaic,
                mosaic_assembled_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(event_memory)

        await self.session.commit()

    async def _append_to_event_memory(
        self,
        event_id: int,
        fragments: List[Dict[str, Any]],
    ) -> None:
        """
        Append mosaic fragments to EventMemory.fragments.

        Args:
            event_id: Event to append to
            fragments: Fragments to append
        """
        stmt = select(EventMemory).where(EventMemory.event_id == event_id)
        result = await self.session.execute(stmt)
        event_memory = result.scalar_one_or_none()

        if not event_memory:
            # Create new EventMemory
            event_memory = EventMemory(
                event_id=event_id,
                fragments=fragments,
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(event_memory)
        else:
            # Append to existing fragments
            existing = event_memory.fragments or []
            existing.extend(fragments)
            event_memory.fragments = existing

        await self.session.commit()

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_fragment_count(self, mosaic: Dict[str, Any]) -> int:
        """Get the number of fragments in a mosaic."""
        return len(mosaic.get("fragments", []))

    def get_participant_count(self, mosaic: Dict[str, Any]) -> int:
        """Get the number of unique participants in a mosaic."""
        fragments = mosaic.get("fragments", [])
        return len(set(f.get("author_id") for f in fragments))


# =============================================================================
# Convenience Functions
# =============================================================================


async def assemble_mosaic_for_event(
    session: AsyncSession,
    event_id: int,
    llm_client: Optional[Any] = None,
    parent_event_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Convenience function to assemble and store a mosaic.

    Args:
        session: Database session
        event_id: Event to assemble mosaic for
        llm_client: Optional LLM client for summary generation
        parent_event_id: Optional parent event for lineage

    Returns:
        Mosaic result
    """
    assembler = MosaicAssembler(session, llm_client)
    return await assembler.assemble_and_store(event_id, parent_event_id)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "MosaicAssembler",
    "MosaicFragment",
    "MosaicResult",
    "assemble_mosaic_for_event",
]
