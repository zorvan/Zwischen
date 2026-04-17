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
from bot.services.event_live_card_service import EventLiveCardService
from bot.services.event_hashtag_service import EventHashtagService
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
            return event, transitioned

        # Trigger lifecycle events based on target state
        await self._trigger_lifecycle_events(
            event, target_state, actor_telegram_user_id
        )

        return event, transitioned

    async def _trigger_lifecycle_events(
        self,
        event: Event,
        target_state: str,
        actor_telegram_user_id: int,
    ) -> None:
        """Trigger appropriate lifecycle events for the new state."""

        # Get group chat ID for announcements
        group_chat_id = await self._get_group_chat_id(event)

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

        # Phase 3.3: Delete live card on state change
        if target_state in {"locked", "completed", "cancelled"}:
            await self._delete_live_card(event.event_id, self.session)

            # Phase 3.3: Freeze hashtags
            if target_state == "locked":
                await self._freeze_hashtags(event, self.session)

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

    async def _delete_live_card(
        self, event_id: int, session: Optional[AsyncSession] = None
    ) -> None:
        """Delete live card when event reaches terminal state."""
        from db.connection import get_session
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        use_session = session or self.session

        if use_session is None:
            async with get_session(settings.db_url) as sess:
                result = await sess.execute(
                    select(Event).where(Event.event_id == event_id)
                )
                event = result.scalar_one_or_none()

                if event and event.group_id:
                    service = EventLiveCardService(self.bot, sess)
                    await service.delete_live_card(event_id)
        else:
            result = await use_session.execute(
                select(Event).where(Event.event_id == event_id)
            )
            event = result.scalar_one_or_none()

            if event and event.group_id:
                service = EventLiveCardService(self.bot, use_session)
                await service.delete_live_card(event_id)

    async def _freeze_hashtags(
        self, event: Event, session: Optional[AsyncSession] = None
    ) -> None:
        """Freeze hashtags when event locks."""
        from db.connection import get_session
        from sqlalchemy.ext.asyncio import AsyncSession

        use_session = session or self.session

        if use_session is None:
            async with get_session(settings.db_url) as sess:
                service = EventHashtagService(sess)
                await service.freeze_hashtags(event)
        else:
            service = EventHashtagService(use_session)
            await service.freeze_hashtags(event)
