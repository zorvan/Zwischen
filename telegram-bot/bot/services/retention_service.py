# mypy: disable-error-code="attr-defined"
"""Executable data-retention policy (see docs/RETENTION_POLICY.md)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Event,
    EventEnrichment,
    EventMemory,
    EventParticipant,
    EventStateTransition,
    Log,
    User,
)


class RetentionService:
    LOG_DAYS = 90
    SOCIAL_GRAPH_DAYS = 180
    DETAIL_DAYS = 180
    MEMORY_DAYS = 365

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def decay(self, *, now: datetime | None = None) -> dict[str, int]:
        """Idempotently remove details in stages; returns affected row counts."""
        moment = now or datetime.now(timezone.utc)
        detail_cutoff = moment - timedelta(days=self.DETAIL_DAYS)
        memory_cutoff = moment - timedelta(days=self.MEMORY_DAYS)
        old_events = select(Event.event_id).where(Event.completed_at < detail_cutoff)
        ancient_events = select(Event.event_id).where(
            Event.completed_at < memory_cutoff
        )

        counts: dict[str, int] = {}
        result = await self.session.execute(
            delete(Log).where(Log.timestamp < moment - timedelta(days=self.LOG_DAYS))
        )
        counts["logs"] = result.rowcount or 0
        result = await self.session.execute(
            delete(EventParticipant).where(EventParticipant.event_id.in_(old_events))
        )
        counts["participants"] = result.rowcount or 0
        result = await self.session.execute(
            delete(EventEnrichment).where(EventEnrichment.event_id.in_(old_events))
        )
        counts["enrichments"] = result.rowcount or 0
        # Preserve that a transition happened while dropping actor/reason detail.
        result = await self.session.execute(
            update(EventStateTransition)
            .where(EventStateTransition.event_id.in_(old_events))
            .values(actor_user_id=None, reason=None)
        )
        counts["transitions_anonymized"] = result.rowcount or 0
        result = await self.session.execute(
            update(EventMemory)
            .where(
                EventMemory.event_id.in_(old_events),
                EventMemory.event_id.not_in(ancient_events),
            )
            .values(fragments=[], lineage_event_ids=[])
        )
        counts["memories_summarized"] = result.rowcount or 0
        result = await self.session.execute(
            delete(EventMemory).where(EventMemory.event_id.in_(ancient_events))
        )
        counts["memories_deleted"] = result.rowcount or 0
        return counts

    async def erase_user(self, user_id: int) -> bool:
        """Exercise FK policy: personal rows cascade; shared audit is anonymized."""
        user = await self.session.get(User, user_id)
        if user is None:
            return False
        await self.session.delete(user)
        await self.session.flush()
        return True
