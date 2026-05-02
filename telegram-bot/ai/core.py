"""
Core AI coordination engine with hybrid approach:
- Rules-based core
- LLM fallback for conflicts/low confidence
"""

from typing import Any, Callable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Event, Constraint


class AICoordinationEngine:
    """Hybrid AI engine - rules first, LLM fallback."""

    def __init__(self, session_factory: Callable, fallback_enabled: bool = True):
        self.session_factory = session_factory
        self.fallback_enabled = fallback_enabled
        from ai.rules import RuleBasedEngine
        from ai.llm import LLMClient

        self.rules_engine = RuleBasedEngine()
        self.llm = LLMClient()

    async def suggest_event_time(
        self, session: AsyncSession, event_id: int
    ) -> dict[str, Any]:
        """3-layer decision logic for time suggestions."""
        event = await session.get(Event, event_id)
        if not event:
            return {"error": "Event not found"}
        result = await session.execute(
            select(Constraint).where(Constraint.event_id == event_id)
        )
        constraints = result.scalars().all()

        try:
            return await self._compute_suggestion(event, constraints)
        except Exception as e:
            if self.fallback_enabled:
                return self.rules_engine.suggest_time_fallback(event)
            return {"error": str(e)}

    async def _compute_suggestion(
        self, event: Event, constraints: list[Constraint]
    ) -> dict[str, Any]:
        """Compute AI suggestion using availability only. No user history."""
        availability = self.rules_engine.check_availability(event, constraints)
        confidence = self._calculate_confidence(availability)

        if confidence >= 0.7:
            return self.rules_engine.resolve_conflicts(
                event,
                availability,
                constraints,
            )

        return await self.llm.resolve_conflicts(event, availability)

    def _calculate_confidence(self, availability: dict) -> float:
        """Calculate confidence from declared availability only."""
        if not availability:
            return 0.0

        return sum(availability.values()) / len(availability)

    async def check_constraint_compatibility(
        self, session: AsyncSession, event_id: int
    ) -> dict[str, Any]:
        """Check and resolve constraint conflicts."""
        event = await session.get(Event, event_id)
        if not event:
            return {"error": "Event not found"}

        result = await session.execute(
            select(Constraint).where(Constraint.event_id == event_id)
        )
        constraints = result.scalars().all()

        if len(constraints) < 5:
            conflicts = self.rules_engine.check_constraints(constraints)
        else:
            conflicts = await self.llm.analyze_constraints(constraints)

        return {
            "conflicts": conflicts,
            "suggestions": self.rules_engine.generate_compromises(conflicts),
        }
