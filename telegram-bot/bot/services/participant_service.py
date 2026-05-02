"""
ParticipantService - Manages normalized participant records.

This service provides the single write path for participant management.
All join/confirm/cancel operations must route through this service.

PRD v3.5 Section 2.2: Application-layer validation replaces SQL CHECK constraints.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, List, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func

from db.models import EventParticipant, ParticipantStatus, ParticipantRole

logger = logging.getLogger("coord_bot.services.participant")


# =============================================================================
# Application-Layer Validation Constants (replaces SQL CHECK constraints)
# PRD v3.5 Section 2.2
# =============================================================================

VALID_CONSTRAINT_TYPES: Set[str] = {"if_joins", "if_attends", "unless_joins"}
"""Valid constraint types for conditional participation."""

VALID_LOG_ACTIONS: Set[str] = {
    # Legacy actions
    "organize_event",
    "join",
    "confirm",
    "cancel",
    "suggest_time",
    "nudge",
    "constraint_update",
    # v3.5 new actions
    "relinquish",
    "enrich_idea",
    "enrich_hashtag",
    "enrich_memory",
    "lock",
    "complete",
    "collapse",
}
"""Valid audit log actions."""


# =============================================================================
# Validation Functions
# =============================================================================


def validate_constraint_type(value: str) -> str:
    """
    Validate and normalize constraint type.

    Replaces SQL CHECK constraint on constraints.type.
    When the LLM outputs a slightly different string, this normalizes it
    or raises a ValueError with a clear error — not a silent crash.

    Args:
        value: The constraint type string to validate

    Returns:
        Normalized (lowercase, stripped) constraint type

    Raises:
        ValueError: If the constraint type is not recognized
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"Constraint type must be a non-empty string, got: {value!r}")

    normalized = value.strip().lower()
    if normalized not in VALID_CONSTRAINT_TYPES:
        raise ValueError(
            f"Unknown constraint type: {value!r}. "
            f"Valid types: {', '.join(sorted(VALID_CONSTRAINT_TYPES))}"
        )
    return normalized


def validate_log_action(value: str) -> str:
    """
    Validate and normalize log action.

    Replaces SQL CHECK constraint on logs.action.
    Raises ValueError with a clear error for invalid actions.

    Args:
        value: The log action string to validate

    Returns:
        Normalized (lowercase, stripped) action name

    Raises:
        ValueError: If the action is not recognized
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"Log action must be a non-empty string, got: {value!r}")

    normalized = value.strip().lower()
    if normalized not in VALID_LOG_ACTIONS:
        raise ValueError(
            f"Unknown log action: {value!r}. "
            f"Valid actions: {', '.join(sorted(VALID_LOG_ACTIONS))}"
        )
    return normalized


# =============================================================================
# Service Exceptions
# =============================================================================


class ParticipantError(Exception):
    """Base exception for participant operations."""

    pass


class ParticipantNotFoundError(ParticipantError):
    """Raised when expected participant record not found."""

    pass


class ParticipantService:
    """
    Single write path for participant management.

    Handles:
    - Join/leave operations
    - Confirm/cancel operations
    - Status queries and counts

    PRD v3.5: Application-layer validation constants replace SQL CHECK constraints.
    """

    # Expose module-level constants for convenient access
    # These are also available as:
    #   from bot.services.participant_service import VALID_CONSTRAINT_TYPES
    VALID_CONSTRAINT_TYPES = VALID_CONSTRAINT_TYPES
    VALID_LOG_ACTIONS = VALID_LOG_ACTIONS

    def __init__(self, session: AsyncSession):
        self.session = session

    async def join(
        self,
        event_id: int,
        telegram_user_id: int,
        source: str = "slash",
        role: ParticipantRole = ParticipantRole.participant,
    ) -> Tuple[EventParticipant, bool]:
        """
        Add user as participant (joined state).

        Returns:
            (participant_record, is_new_join)
        """
        # Check if already exists
        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant:
            # Already joined - update status if cancelled
            if participant.status == ParticipantStatus.cancelled:
                participant.status = ParticipantStatus.joined
                participant.joined_at = datetime.utcnow()
                participant.cancelled_at = None
                logger.info(
                    "Participant rejoined event",
                    extra={"event_id": event_id, "user": telegram_user_id},
                )
                return participant, True

            if participant.status == ParticipantStatus.joined:
                return participant, False

            # Upgrade from no_show
            if participant.status == ParticipantStatus.no_show:
                participant.status = ParticipantStatus.joined
                participant.joined_at = datetime.utcnow()
                return participant, True

            return participant, False

        # Create new participant
        participant = EventParticipant(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            status=ParticipantStatus.joined,
            role=role,
            source=source,
            joined_at=datetime.utcnow(),
        )
        self.session.add(participant)

        logger.info(
            "New participant joined",
            extra={
                "event_id": event_id,
                "user": telegram_user_id,
                "source": source,
            },
        )

        return participant, True

    async def confirm(
        self,
        event_id: int,
        telegram_user_id: int,
        source: str = "callback",
    ) -> Tuple[EventParticipant, bool]:
        """
        Confirm participant attendance.

        Returns:
            (participant_record, is_new_confirm)
        """
        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if not participant:
            # Auto-join on confirm
            return await self.join(event_id, telegram_user_id, source)

        if participant.status == ParticipantStatus.confirmed:
            return participant, False

        if participant.status == ParticipantStatus.cancelled:
            raise ParticipantError(
                f"User {telegram_user_id} cannot confirm after cancelling"
            )

        participant.status = ParticipantStatus.confirmed
        participant.confirmed_at = datetime.utcnow()

        logger.info(
            "Participant confirmed",
            extra={
                "event_id": event_id,
                "user": telegram_user_id,
                "source": source,
            },
        )

        return participant, True

    async def cancel(
        self,
        event_id: int,
        telegram_user_id: int,
        source: str = "callback",
    ) -> Tuple[EventParticipant, bool]:
        """
        Cancel participant attendance.

        Returns:
            (participant_record, is_new_cancel)
        """
        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if not participant:
            raise ParticipantNotFoundError(
                f"User {telegram_user_id} is not a participant of event {event_id}"
            )

        if participant.status == ParticipantStatus.cancelled:
            return participant, False

        participant.status = ParticipantStatus.cancelled
        participant.cancelled_at = datetime.utcnow()

        logger.info(
            "Participant cancelled",
            extra={
                "event_id": event_id,
                "user": telegram_user_id,
                "source": source,
            },
        )

        return participant, True

    async def mark_no_show(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> None:
        """Mark participant as no-show after event completion."""
        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant and participant.status == ParticipantStatus.confirmed:
            participant.status = ParticipantStatus.no_show
            logger.warning(
                "Participant marked as no-show",
                extra={"event_id": event_id, "user": telegram_user_id},
            )

    async def get_participant(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> Optional[EventParticipant]:
        """Get participant record."""
        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_participants(
        self,
        event_id: int,
        status_filter: Optional[ParticipantStatus] = None,
    ) -> List[EventParticipant]:
        """Get all participants for an event, optionally filtered by status."""
        query = select(EventParticipant).where(EventParticipant.event_id == event_id)

        if status_filter:
            query = query.where(EventParticipant.status == status_filter)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_counts(self, event_id: int) -> Dict[str, int]:
        """
        Get participant counts by status.

        Returns dict with: joined, confirmed, cancelled, total
        """
        result = await self.session.execute(
            select(
                EventParticipant.status, func.count(EventParticipant.telegram_user_id)
            )
            .where(EventParticipant.event_id == event_id)
            .group_by(EventParticipant.status)
        )

        counts = {
            "joined": 0,
            "confirmed": 0,
            "cancelled": 0,
            "no_show": 0,
            "total": 0,
        }

        for status, count in result.all():
            counts[status.value] = count
            counts["total"] += count

        return counts

    async def get_interested_count(self, event_id: int) -> int:
        """Get count of interested participants (joined but not confirmed)."""
        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == ParticipantStatus.joined,
            )
        )
        return result.scalar() or 0

    async def get_confirmed_count(self, event_id: int) -> int:
        """Get count of confirmed participants (for threshold checks)."""
        result = await self.session.execute(
            select(func.count(EventParticipant.telegram_user_id)).where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == ParticipantStatus.confirmed,
            )
        )
        return result.scalar() or 0

    async def finalize_commitments(self, event_id: int) -> int:
        """
        Finalize commitments by marking all joined participants as confirmed.

        Returns the number of participants that were finalized.
        """
        result = await self.session.execute(
            update(EventParticipant)
            .where(
                EventParticipant.event_id == event_id,
                EventParticipant.status == ParticipantStatus.joined,
            )
            .values(
                status=ParticipantStatus.confirmed,
                confirmed_at=datetime.utcnow(),
            )
        )

        finalized_count = result.rowcount
        if finalized_count > 0:
            logger.info(
                "Finalized commitments for event",
                extra={
                    "event_id": event_id,
                    "finalized_count": finalized_count,
                },
            )

        return finalized_count

    async def unconfirm(
        self,
        event_id: int,
        telegram_user_id: int,
        source: str = "callback",
    ) -> Tuple[EventParticipant, bool]:
        """
        Unconfirm participant attendance (revert from confirmed to joined).

        Returns:
            (participant_record, is_new_unconfirm)
        """
        result = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if not participant:
            raise ParticipantNotFoundError(
                f"User {telegram_user_id} is not a participant of event {event_id}"
            )

        if participant.status != ParticipantStatus.confirmed:
            return participant, False

        participant.status = ParticipantStatus.joined
        participant.confirmed_at = None

        logger.info(
            "Participant unconfirmed",
            extra={
                "event_id": event_id,
                "user": telegram_user_id,
                "source": source,
            },
        )

        return participant, True

    async def remove_participant(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> bool:
        """
        Completely remove participant record.

        Use with caution - prefer cancel() for audit trail.
        """
        result = await self.session.execute(
            delete(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        return result.rowcount > 0
