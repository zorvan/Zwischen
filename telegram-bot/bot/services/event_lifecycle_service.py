"""
EventLifecycleService - Orchestrates event state transitions with materialization and memory.
PRD v2: Integrates all three layers (Coordination, Materialization, Memory).
PRD v3.2: Adds event-level resilience (failure tracking, waitlist auto-fill hooks).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from db.models import Event, EventParticipant, ParticipantStatus
from bot.services import (
    EventStateTransitionService,
    EventMaterializationService,
    EventMemoryService,
)
from bot.services.group_event_type_stats_service import GroupEventTypeStatsService
from config.settings import settings

logger = logging.getLogger("coord_bot.services.lifecycle")


class EventLifecycleService:
    """
    Orchestrates complete event lifecycle transitions.

    This service coordinates:
    - State transitions (via EventStateTransitionService)
    - Materialization announcements (via EventMaterializationService)
    - Memory collection triggers (via EventMemoryService)
    """

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session
        self.transition_service = EventStateTransitionService(session)
        self.materialization_service = (
            EventMaterializationService(bot, session)
            if settings.enable_materialization
            else None
        )
        self.memory_service = (
            EventMemoryService(bot, session) if settings.enable_memory_layer else None
        )
        self.stats_service = GroupEventTypeStatsService(session)

    async def transition_with_lifecycle(
        self,
        event_id: int,
        target_state: str,
        actor_telegram_user_id: int,
        source: str,
        reason: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Tuple[Event, bool]:
        """
        Execute state transition with full lifecycle integration.

        Triggers materialization announcements and memory collection as appropriate.
        """
        logger.info(
            "[LIFECYCLE] State transition starting | event_id=%s target_state=%s actor=%s source=%s",
            event_id,
            target_state,
            actor_telegram_user_id,
            source,
        )

        # Execute the state transition
        event, transitioned = await self.transition_service.transition(
            event_id=event_id,
            target_state=target_state,
            actor_telegram_user_id=actor_telegram_user_id,
            source=source,
            reason=reason,
            expected_version=expected_version,
        )

        if not transitioned:
            logger.info(
                "[LIFECYCLE] State transition rejected | event_id=%s target_state=%s "
                "reason=transition_service_rejected",
                event_id,
                target_state,
            )
            return event, transitioned

        logger.info(
            "[LIFECYCLE] State transition successful | event_id=%s new_state=%s",
            event_id,
            target_state,
        )

        # Trigger lifecycle events based on target state
        await self._trigger_lifecycle_events(
            event, target_state, actor_telegram_user_id
        )

        logger.info(
            "[LIFECYCLE] Lifecycle events completed | event_id=%s state=%s",
            event_id,
            target_state,
        )

        return event, transitioned

    async def _trigger_lifecycle_events(
        self,
        event: Event,
        target_state: str,
        actor_telegram_user_id: int,
    ) -> None:
        """Trigger appropriate lifecycle events for the new state."""
        logger.info(
            "[LIFECYCLE] Triggering lifecycle events | event_id=%s state=%s",
            event.event_id,
            target_state,
        )

        # Get group chat ID for announcements
        group_chat_id = await self._get_group_chat_id(event)
        logger.info(
            "[LIFECYCLE] Group chat resolved | event_id=%s group_chat_id=%s",
            event.event_id,
            group_chat_id,
        )

        if target_state == "locked" and self.materialization_service:
            # Announce event locked
            if group_chat_id:
                participants = await self._get_confirmed_participants(event.event_id)
                await self.materialization_service.announce_event_locked(
                    event, participants, group_chat_id
                )

        elif target_state == "completed":
            # Track completion in stats
            if event.group_id and event.event_type:
                await self.stats_service.record_completion(
                    event.group_id, event.event_type
                )

            # Announce event completed
            if self.materialization_service and group_chat_id:
                participant_count = await self._get_participant_count(event.event_id)
                await self.materialization_service.announce_event_completed(
                    event, participant_count, group_chat_id
                )

            # Trigger memory collection
            if self.memory_service:
                await self.memory_service.start_memory_collection(event)

        elif target_state == "cancelled":
            # Track failed attempt in stats
            if event.group_id and event.event_type:
                confirmed = await self._get_participant_count(event.event_id)
                await self.stats_service.record_attempt(
                    event.group_id, event.event_type, dropout_point=confirmed
                )

    async def _get_group_chat_id(self, event: Event) -> Optional[int]:
        """Get the Telegram group chat ID for the event."""
        from sqlalchemy import select
        from db.models import Group

        result = await self.session.execute(
            select(Group.telegram_group_id).where(Group.group_id == event.group_id)
        )
        return result.scalar_one_or_none()

    async def _get_confirmed_participants(
        self, event_id: int
    ) -> list[EventParticipant]:
        """Get confirmed participants for the event."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        return list(result.scalars().all())

    async def _get_participant_count(self, event_id: int) -> int:
        """Get total participant count for the event."""
        from sqlalchemy import select
        from sqlalchemy.sql import func

        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        return result.scalar_one() or 0
