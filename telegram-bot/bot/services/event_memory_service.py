"""
EventMemoryService - Layer 3: Memory Layer (v3).
PRD v3: Memory as pre-event input, not post-event output.

This service manages:
- Memory fragment collection (no deadline, receive indefinitely)
- Fragment Mosaic (LLM rearranges only — no words added, no interpretation)
- Event lineage (connecting related events)
- Memory-first event creation support
"""

from __future__ import annotations

import logging
import hashlib
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from telegram import Bot

from bot.common.i18n import t
from db.models import Event, EventMemory, EventParticipant, ParticipantStatus, User

logger = logging.getLogger("coord_bot.services.memory")


class EventMemoryService:
    """
    Manages the Memory Layer — transforming coordination into shared meaning.

    v3 Design principles:
    - Memory is infrastructure, not artifact
    - Receive fragments indefinitely — no collection deadline
    - Fragment Mosaic: LLM rearranges only, zero interpretation
    - Bot as facilitator of meaning-formation, not author
    """

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def start_memory_collection(self, event: Event) -> None:
        """
        Begin receiving memory fragments after event completion.

        v3: No deadline. Fragments accepted indefinitely.
        v3.2: Reflexive prompt — invites difficulty alongside celebration.
        DMs each confirmed participant with open-ended prompt that includes
        "something that didn't quite go as planned" as a valid frame.
        """
        if not event.completed_at:
            logger.warning(
                "Attempted memory collection for incomplete event %s", event.event_id
            )
            return

        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event.event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        participants = result.scalars().all()

        if not participants:
            logger.info(
                "No participants to collect memories from",
                extra={"event_id": event.event_id},
            )
            return

        logger.info(
            "Starting memory collection for %d participants",
            len(participants),
            extra={"event_id": event.event_id},
        )

        # v3.2: Check for reflexive lineage fragment
        lineage_fragment = await self.get_lineage_door_fragment(
            event.group_id or 0, event.event_type
        )

        for participant in participants:
            await self._send_memory_request(participant, event, lineage_fragment)

    async def _send_memory_request(
        self,
        participant: EventParticipant,
        event: Event,
        lineage_fragment: Optional[str] = None,
    ) -> None:
        """
        Send DM requesting memory fragment.

        v3: Open-ended prompt with no deadline or structured form.
        v3.2: Reflexive lineage door — includes prior fragment if available.
              Explicitly holds space for difficulty: "something that didn't
              quite go as planned".
        """
        user_result = await self.session.execute(
            select(User).where(User.telegram_user_id == participant.telegram_user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user or not user.telegram_user_id:
            logger.warning(
                "Cannot find user for participant %s", participant.telegram_user_id
            )
            return

        # v3.2: Build reflexive lineage door message
        event_name = f"{event.event_type}"
        if event.scheduled_time:
            event_name = (
                f"{event.event_type} on {event.scheduled_time.strftime('%d %b')}"
            )

        if lineage_fragment:
            # Reflexive lineage door with prior fragment
            message = t(
                "memory_request_with_lineage",
                lang="en",
                event_name=event_name,
                lineage_fragment=lineage_fragment,
            )
        else:
            # No prior fragment — reflexive prompt without lineage door
            message = t("memory_request", lang="en", event_name=event_name)

        try:
            await self.bot.send_message(
                chat_id=user.telegram_user_id,
                text=message,
                # No parse_mode — plain text to avoid issues with user-contributed
                # fragments containing HTML special characters
            )
            logger.info(
                "Sent memory request",
                extra={"event_id": event.event_id, "user": user.user_id},
            )
        except Exception as e:
            logger.error(
                "Failed to send memory request to user %s: %s", user.user_id, e
            )

    async def collect_memory_fragment(
        self,
        event_id: int,
        user_id: int,
        fragment_text: str,
        tone_tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Collect a memory fragment from a participant.

        v3: No deadline — fragments accepted weeks after event.
        v3.2: word_count computed at write time for hook/lineage qualification.
        """
        contributor_hash = hashlib.sha256(
            f"{event_id}:{user_id}:{datetime.utcnow().date()}".encode()
        ).hexdigest()[:8]

        # v3.2: count words at write time
        word_count = len(fragment_text.split())

        fragment = {
            "text": fragment_text,
            "contributor_hash": contributor_hash,
            "tone_tag": tone_tag or "neutral",
            "submitted_at": datetime.utcnow().isoformat(),
            "word_count": word_count,
        }

        logger.info(
            "Collected memory fragment",
            extra={
                "event_id": event_id,
                "contributor_hash": contributor_hash,
                "tone": fragment["tone_tag"],
                "word_count": word_count,
            },
        )

        return fragment

    async def add_fragment_to_memory(
        self,
        event_id: int,
        fragment: Dict[str, Any],
    ) -> EventMemory:
        """Add fragment to event memory (create or update EventMemory)."""
        result = await self.session.execute(
            select(EventMemory).where(EventMemory.event_id == event_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
            memory = EventMemory(
                event_id=event_id,
                fragments=[],
                hashtags=[],
                outcome_markers=[],
            )
            self.session.add(memory)

        if memory.fragments is None:
            memory.fragments = []
        memory.fragments.append(fragment)

        return memory

    async def generate_memory_weave(self, event: Event) -> Optional[str]:
        """
        Generate Fragment Mosaic from collected fragments.

        v3 Constraint: LLM rearranges fragments only. No words added. No interpretation.
        If LLM can't be constrained, fall back to chronological ordering.
        """
        result = await self.session.execute(
            select(EventMemory).where(EventMemory.event_id == event.event_id)
        )
        memory = result.scalar_one_or_none()

        if not memory or not memory.fragments:
            logger.info("No fragments to weave", extra={"event_id": event.event_id})
            return None

        try:
            from ai.llm import LLMClient

            llm = LLMClient()

            fragments_json = json.dumps(
                [{"text": f.get("text", "")} for f in memory.fragments],
                ensure_ascii=False,
            )

            prompt = (
                "You are arranging memory fragments. Your task is STRICTLY to reorder "
                "the fragments below into a coherent sequence.\n\n"
                "CONSTRAINTS (violation = failure):\n"
                "- You MUST NOT add any words that are not already in the fragments.\n"
                "- You MUST NOT interpret, summarize, or paraphrase any fragment.\n"
                "- You MUST NOT change the text of any fragment.\n"
                "- You MAY only add line breaks, bullet markers (•), and blank lines between fragments.\n"
                "- Output the fragments exactly as given, just rearranged. Nothing else.\n\n"
                f"Fragments (JSON):\n{fragments_json}\n\n"
                "Output only the rearranged fragments with • bullets and line breaks. Nothing else."
            )
            weave_text = await llm._call_llm(prompt)

            if not weave_text or len(weave_text.strip()) < 10:
                raise ValueError("LLM returned empty response")

            # Sanity check: LLM must not have added substantive content
            input_words = " ".join(f.get("text", "") for f in memory.fragments)
            output_clean = weave_text.replace("•", "").replace("\n", " ").strip()
            if len(output_clean) > len(input_words) * 1.5:
                raise ValueError("LLM appears to have added content; falling back")

        except Exception as e:
            logger.warning(
                "LLM mosaic failed (%s), using chronological fallback",
                e,
                extra={"event_id": event.event_id},
            )
            weave_text = self._chronological_weave(memory.fragments)

        event_anchor = f"{event.event_type} • {event.scheduled_time.strftime('%d %b %Y') if event.scheduled_time else 'TBD'}"
        header = f"📿 <b>How people remember: {event_anchor}</b>\n\n"
        full_weave = header + weave_text

        memory.weave_text = full_weave

        logger.info(
            "Generated fragment mosaic with %d fragments",
            len(memory.fragments),
            extra={"event_id": event.event_id},
        )

        return full_weave

    def _chronological_weave(self, fragments: List[Dict[str, Any]]) -> str:
        """Fallback: arrange fragments chronologically by submission time."""
        parts = []
        for fragment in fragments:
            text = fragment.get("text", "")
            parts.append(f'• "{text}"')

        return "\n".join(parts)

    async def post_memory_weave(self, event: Event, group_chat_id: int) -> bool:
        """Generate and post memory weave to group chat."""
        weave_text = await self.generate_memory_weave(event)

        if not weave_text:
            return False

        try:
            await self.bot.send_message(
                chat_id=group_chat_id,
                text=weave_text,
                parse_mode="HTML",
            )
            logger.info(
                "Posted memory weave to group", extra={"event_id": event.event_id}
            )
            return True
        except Exception as e:
            logger.error(
                "Failed to post memory weave to group %s: %s", group_chat_id, e
            )
            return False

    async def add_hashtags(self, event_id: int, hashtags: List[str]) -> EventMemory:
        """Add group hashtags to event memory."""
        result = await self.session.execute(
            select(EventMemory).where(EventMemory.event_id == event_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
            memory = EventMemory(event_id=event_id)
            self.session.add(memory)

        memory.hashtags = hashtags[:3]  # Max 3 per PRD
        return memory

    async def add_outcome_marker(
        self,
        event_id: int,
        marker: Dict[str, Any],
    ) -> EventMemory:
        """Add outcome marker (e.g., 'led to collaboration X')."""
        result = await self.session.execute(
            select(EventMemory).where(EventMemory.event_id == event_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
            memory = EventMemory(event_id=event_id)
            self.session.add(memory)

        if memory.outcome_markers is None:
            memory.outcome_markers = []

        memory.outcome_markers.append(marker)
        return memory

    async def link_lineage(
        self,
        current_event_id: int,
        prior_event_ids: List[int],
    ) -> EventMemory:
        """Link current event to prior similar events (lineage)."""
        result = await self.session.execute(
            select(EventMemory).where(EventMemory.event_id == current_event_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
            memory = EventMemory(event_id=current_event_id)
            self.session.add(memory)

        memory.lineage_event_ids = prior_event_ids
        logger.info("Linked lineage: %s -> %s", current_event_id, prior_event_ids)
        return memory

    async def get_memory_weave(self, event_id: int) -> Optional[EventMemory]:
        """Get memory weave for an event."""
        result = await self.session.execute(
            select(EventMemory).where(EventMemory.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def get_recent_memories(
        self, group_id: int, limit: int = 10
    ) -> List[EventMemory]:
        """Get recent memory weaves for a group (for /recall)."""
        result = await self.session.execute(
            select(EventMemory)
            .join(Event)
            .where(Event.group_id == group_id)
            .order_by(EventMemory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def suggest_hashtags_from_lineage(
        self,
        event_type: str,
        group_id: int,
    ) -> List[str]:
        """Suggest hashtags based on prior similar events."""
        result = await self.session.execute(
            select(EventMemory.hashtags)
            .join(Event)
            .where(
                Event.group_id == group_id,
                Event.event_type == event_type,
            )
            .order_by(Event.created_at.desc())
            .limit(5)
        )

        all_hashtags = []
        for hashtags in result.scalars().all():
            if hashtags:
                all_hashtags.extend(hashtags)

        from collections import Counter

        counts = Counter(all_hashtags)
        return [tag for tag, _ in counts.most_common(3)]

    async def get_prior_event_memories(
        self,
        event_type: str,
        group_id: int,
        limit: int = 5,
    ) -> List[EventMemory]:
        """
        v3: Get memories from prior events of the same type.

        Used in memory-first event creation: when creating a new event,
        surface memories from prior similar events first.
        """
        result = await self.session.execute(
            select(EventMemory)
            .join(Event)
            .where(
                Event.group_id == group_id,
                Event.event_type == event_type,
                Event.state == "completed",
                EventMemory.weave_text.isnot(None),
            )
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ========================================================================
    # v3.2: Memory hooks, reflexive fragments, failure patterns
    # ========================================================================

    async def get_memory_hook(
        self,
        group_id: int,
        event_type: str,
        max_words: int = 12,
    ) -> Optional[str]:
        """
        v3.2: Get a short verbatim fragment for memory hook in announcements.

        Returns the shortest qualifying fragment (≤max_words) from the most
        recent completed event of the same type. No LLM. Verbatim only.
        """
        result = await self.session.execute(
            select(EventMemory)
            .join(Event)
            .where(
                Event.group_id == group_id,
                Event.event_type == event_type,
                Event.state == "completed",
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        memory = result.scalar_one_or_none()
        if not memory or not memory.fragments:
            return None

        qualifying = [
            f for f in memory.fragments if f.get("word_count", 999) <= max_words
        ]
        if not qualifying:
            return None

        shortest = min(qualifying, key=lambda f: f.get("word_count", 999))
        return shortest.get("text")

    async def get_latest_with_mosaic(
        self,
        group_id: int,
        event_type: str,
    ) -> Optional[EventMemory]:
        """
        v3.2: Get the most recent memory with fragments for a given event type.
        """
        result = await self.session.execute(
            select(EventMemory)
            .join(Event)
            .where(
                Event.group_id == group_id,
                Event.event_type == event_type,
                Event.state == "completed",
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_lineage_door_fragment(
        self,
        group_id: int,
        event_type: str,
        max_words: int = 15,
    ) -> Optional[str]:
        """
        v3.2: Get fragment for lineage door with reflexive preference.

        Prefers fragments referencing difficulty or adaptation (keyword heuristic).
        Falls back to shortest available fragment. No LLM. No fabrication.
        """
        result = await self.session.execute(
            select(EventMemory)
            .join(Event)
            .where(
                Event.group_id == group_id,
                Event.event_type == event_type,
                Event.state == "completed",
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        memory = result.scalar_one_or_none()
        if not memory or not memory.fragments:
            return None

        qualifying = [
            f for f in memory.fragments if f.get("word_count", 999) <= max_words
        ]
        if not qualifying:
            return None

        # Reflexive keyword heuristic
        reflexive_keywords = {
            "almost",
            "hard",
            "wrong",
            "late",
            "cold",
            "rain",
            "tired",
            "difficult",
            "unexpected",
            "surprised",
            "didn't",
            "couldn't",
            "changed",
            "figured",
            "adapted",
            "anyway",
            "despite",
            "still",
        }
        reflexive = [
            f
            for f in qualifying
            if any(kw in f.get("text", "").lower() for kw in reflexive_keywords)
        ]
        if reflexive:
            return min(reflexive, key=lambda f: f.get("word_count", 999)).get("text")

        return min(qualifying, key=lambda f: f.get("word_count", 999)).get("text")

    async def get_failure_pattern(
        self,
        group_id: int,
        event_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        v3.2: Get group-level failure pattern for an event type.

        Returns {attempt_count, completed_count, last_dropout_point} if
        there are ≥3 failed attempts. No individual attribution.
        """
        from db.models import GroupEventTypeStats

        result = await self.session.execute(
            select(GroupEventTypeStats).where(
                GroupEventTypeStats.group_id == group_id,
                GroupEventTypeStats.event_type == event_type,
            )
        )
        stats = result.scalar_one_or_none()
        if not stats:
            return None

        failed_count = stats.attempt_count - stats.completed_count
        if failed_count < 3:
            return None

        return {
            "attempt_count": stats.attempt_count,
            "completed_count": stats.completed_count,
            "failed_count": failed_count,
            "last_dropout_point": stats.last_dropout_point,
        }
