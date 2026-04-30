"""
GroupEventTypeStatsService - Tracks group-level coordination patterns.
PRD v3.2: Used for repeated failure pattern surface in meaning-formation.

Invariant: No individual user data. Group-level only.
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import GroupEventTypeStats

logger = logging.getLogger("coord_bot.services.event_type_stats")


class GroupEventTypeStatsService:
    """
    Manages group_event_type_stats records.

    Updated on:
    - Event cancelled (below min participants) → increment attempt, record dropout
    - Event completed → increment attempt + completed
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_attempt(
        self,
        group_id: int,
        event_type: str,
        dropout_point: Optional[int] = None,
    ) -> None:
        """
        Record an event attempt (created and then cancelled/failed).

        Args:
            group_id: The group ID
            event_type: Type of event (social, sports, outdoor, work)
            dropout_point: Number of participants at time of cancellation
        """
        stats = await self._get_or_create(group_id, event_type)
        stats.attempt_count += 1
        if dropout_point is not None:
            stats.last_dropout_point = dropout_point

        logger.info(
            "Recorded event attempt: group=%s, type=%s, attempts=%s, dropout=%s",
            group_id,
            event_type,
            stats.attempt_count,
            dropout_point,
        )

    async def record_completion(self, group_id: int, event_type: str) -> None:
        """
        Record a completed event.

        Args:
            group_id: The group ID
            event_type: Type of event
        """
        stats = await self._get_or_create(group_id, event_type)
        stats.attempt_count += 1
        stats.completed_count += 1

        logger.info(
            "Recorded event completion: group=%s, type=%s, completed=%s",
            group_id,
            event_type,
            stats.completed_count,
        )

    async def get_failure_pattern(
        self,
        group_id: int,
        event_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get failure pattern if ≥3 failed attempts.

        Returns None if threshold not met.
        """
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

    async def _get_or_create(
        self,
        group_id: int,
        event_type: str,
    ) -> GroupEventTypeStats:
        """Get or create stats record."""
        result = await self.session.execute(
            select(GroupEventTypeStats).where(
                GroupEventTypeStats.group_id == group_id,
                GroupEventTypeStats.event_type == event_type,
            )
        )
        stats = result.scalar_one_or_none()
        if not stats:
            stats = GroupEventTypeStats(
                group_id=group_id,
                event_type=event_type,
                attempt_count=0,
                completed_count=0,
            )
            self.session.add(stats)
        return stats
