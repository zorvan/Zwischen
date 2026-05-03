"""
Materialization helpers - Layer 2: Makes events feel real.
PRD v2 Section 2.2: Event Materialization Layer.
PRD v3.2: Temporal gradient, memory hooks, cancellation-with-action DM.

This module provides the integration between service layer and group announcements.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from telegram import Bot

if TYPE_CHECKING:
    from db.models import Event, EventParticipant, User, ParticipantStatus
    from sqlalchemy.ext.asyncio import AsyncSession
    from bot.services import EventMaterializationService

logger = logging.getLogger("coord_bot.materialization")


def get_time_framing_tier(event: "Event") -> str:
    """
    v3.2: Returns tier based on time to event.
    Operates on event state only — no user data.

    Tiers:
    - light: >72h before event
    - warm: 24–72h before event
    - urgent: 2–24h before event
    - immediate: <2h before event
    """
    if not event.scheduled_time:
        return "light"
    now = datetime.now(timezone.utc)
    scheduled = event.scheduled_time
    if isinstance(scheduled, str):
        # Handle case where scheduled_time might be a string
        try:
            scheduled = datetime.fromisoformat(scheduled)
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return "light"
    if not isinstance(scheduled, datetime):
        return "light"
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    hours = (scheduled - now).total_seconds() / 3600
    if hours > 72:
        return "light"
    elif hours > 24:
        return "warm"
    elif hours > 2:
        return "urgent"
    else:
        return "immediate"


class MaterializationOrchestrator:
    """
    Orchestrates materialization announcements based on triggers.

    This is the bridge between EventLifecycleService and EventMaterializationService.
    It determines which announcements to make based on the trigger type and event context.
    """

    def __init__(self, bot: Bot, session: "AsyncSession"):
        self.bot = bot
        self.session = session

    async def trigger_announcement(
        self,
        event: "Event",
        trigger: str,
        actor_user_id: Optional[int] = None,
        group_chat_id: Optional[int] = None,
    ) -> None:
        """
        Trigger appropriate materialization announcement.

        Args:
            event: The event object
            trigger: Trigger type (e.g., 'first_join', 'threshold_reached', 'locked')
            actor_user_id: User who triggered the action (optional)
            group_chat_id: Telegram group chat ID (optional, will be fetched if not provided)
        """
        if not group_chat_id:
            group_chat_id = await self._get_group_chat_id(event)

        if not group_chat_id:
            logger.warning(
                "Cannot announce: no group chat ID for event %s", event.event_id
            )
            return

        from bot.services import EventMaterializationService

        materialization = EventMaterializationService(self.bot, self.session)

        if trigger == "first_join":
            await self._announce_first_join(
                event, actor_user_id, group_chat_id, materialization
            )

        elif trigger == "join":
            await self._announce_join(
                event, actor_user_id, group_chat_id, materialization
            )

        elif trigger == "threshold_reached":
            await self._announce_threshold(event, group_chat_id, materialization)

        elif trigger == "locked":
            await self._announce_locked(event, group_chat_id, materialization)

        elif trigger == "completed":
            await self._announce_completed(event, group_chat_id, materialization)

        elif trigger == "cancellation":
            await self._announce_cancellation(event, actor_user_id, materialization)

        else:
            logger.debug("Unknown materialization trigger: %s", trigger)

    async def _announce_first_join(
        self,
        event: Event,
        user_id: Optional[int],
        group_chat_id: int,
        materialization: EventMaterializationService,
    ) -> None:
        """Announce first person joining."""
        if not user_id:
            return

        user = await self._get_user(user_id)
        if not user:
            return

        await materialization.announce_first_join(event, user, group_chat_id)

    async def _announce_join(
        self,
        event: Event,
        user_id: Optional[int],
        group_chat_id: int,
        materialization: EventMaterializationService,
    ) -> None:
        """Announce someone joining."""
        if not user_id:
            return

        user = await self._get_user(user_id)
        if not user:
            return

        # Get confirmed count
        from sqlalchemy import select, func

        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event.event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        confirmed_count = result.scalar() or 0

        await materialization.announce_join(event, user, confirmed_count, group_chat_id)

    async def _announce_threshold(
        self,
        event: Event,
        group_chat_id: int,
        materialization: EventMaterializationService,
    ) -> None:
        """Announce threshold reached."""
        from sqlalchemy import select, func

        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event.event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        confirmed_count = result.scalar() or 0

        await materialization.announce_threshold_reached(
            event, confirmed_count, group_chat_id
        )

    async def _announce_locked(
        self,
        event: Event,
        group_chat_id: int,
        materialization: EventMaterializationService,
    ) -> None:
        """Announce event locked."""
        from sqlalchemy import select

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
        participants = list(result.scalars().all())

        await materialization.announce_event_locked(event, participants, group_chat_id)

    async def _announce_completed(
        self,
        event: Event,
        group_chat_id: int,
        materialization: EventMaterializationService,
    ) -> None:
        """Announce event completed."""
        from sqlalchemy import select, func

        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event.event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        participant_count = result.scalar() or 0

        await materialization.announce_event_completed(
            event, participant_count, group_chat_id
        )

    async def _announce_cancellation(
        self,
        event: Event,
        cancelled_user_id: Optional[int],
        materialization: EventMaterializationService,
    ) -> None:
        """Announce cancellation privately to organizer."""
        if not cancelled_user_id:
            return

        user = await self._get_user(cancelled_user_id)
        if not user:
            return

        # Get organizer chat ID
        organizer_chat_id = await self._get_organizer_chat_id(event)
        if not organizer_chat_id:
            return

        # Get remaining count
        from sqlalchemy import select, func

        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event.event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        remaining_count = result.scalar() or 0

        await materialization.announce_cancellation_private(
            event, user, organizer_chat_id, remaining_count
        )

    async def _get_user(self, telegram_user_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()

    async def _get_group_chat_id(self, event: "Event") -> Optional[int]:
        """Get Telegram group chat ID for event."""
        from sqlalchemy import select
        from db.models import Group

        result = await self.session.execute(
            select(Group.telegram_group_id).where(Group.group_id == event.group_id)
        )
        return result.scalar_one_or_none()

    async def _get_organizer_chat_id(self, event: "Event") -> Optional[int]:
        """Get organizer's Telegram chat ID (for DMs)."""
        from sqlalchemy import select
        from db.models import User

        if not event.organizer_telegram_user_id:
            return None

        result = await self.session.execute(
            select(User.telegram_user_id).where(
                User.telegram_user_id == event.organizer_telegram_user_id
            )
        )
        return result.scalar_one_or_none()


async def announce_participation_change(
    bot: Bot,
    session: "AsyncSession",
    event: "Event",
    trigger: str,
    actor_user_id: Optional[int] = None,
) -> None:
    """
    Convenience function to trigger materialization announcement.

    Usage:
        await announce_participation_change(
            bot=context.bot,
            session=session,
            event=event,
            trigger='first_join',
            actor_user_id=user_id,
        )
    """
    orchestrator = MaterializationOrchestrator(bot, session)
    await orchestrator.trigger_announcement(event, trigger, actor_user_id)
