"""
EventStateTransitionService - Single write path for event state changes.
PRD v2 Section 2.1: Centralized state machine governance.

This service is the ONLY allowed path for mutating event state.
All command handlers must route through this service.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from db.models import Event, EventParticipant, EventStateTransition, ParticipantStatus
from bot.common.event_states import can_transition

logger = logging.getLogger("coord_bot.services.event_state")


class EventStateTransitionError(Exception):
    """Raised when state transition fails validation."""

    def __init__(self, message: str, error_code: str = "INVALID_TRANSITION"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class EventNotFoundError(Exception):
    """Raised when event is not found."""

    pass


class ConcurrencyConflictError(Exception):
    """Raised when optimistic concurrency check fails."""

    pass


class ThresholdNotMetError(EventStateTransitionError):
    """Raised when trying to lock event below minimum participants."""

    pass


class EventStateTransitionService:
    """
    Single write path for all event state transitions.

    Enforces:
    - Valid state machine transitions
    - Precondition checks (e.g., lock requires min_participants)
    - Optimistic concurrency control
    - Transition audit logging
    - Materialization announcements (Layer 2)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def transition(
        self,
        event_id: int,
        target_state: str,
        actor_telegram_user_id: int,
        source: str,  # slash, callback, AI mention
        reason: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Tuple[Event, bool]:
        """
        Execute a state transition with full validation and logging.

        Args:
            event_id: Target event ID
            target_state: Desired state
            actor_telegram_user_id: User initiating transition
            source: Origin of action (slash/callback/AI mention)
            reason: Optional human-readable reason
            expected_version: For optimistic concurrency (optional)

        Returns:
            Tuple of (updated_event, transition_occurred)

        Raises:
            EventNotFoundError: If event doesn't exist
            EventStateTransitionError: If transition is invalid
            ConcurrencyConflictError: If version mismatch
            ThresholdNotMetError: If locking below min_participants
        """
        # Fetch event
        result = await self.session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        if not event:
            raise EventNotFoundError(f"Event {event_id} not found")

        # Check optimistic concurrency
        if expected_version is not None and event.version != expected_version:
            raise ConcurrencyConflictError(
                f"Event {event_id} was modified (version {event.version}, expected {expected_version})",
                error_code="CONCURRENCY_CONFLICT",
            )

        current_state = event.state

        # Validate transition
        if not can_transition(current_state, target_state):
            raise EventStateTransitionError(
                f"Invalid transition from {current_state} to {target_state}", error_code="INVALID_TRANSITION"
            )

        # Check preconditions
        await self._check_preconditions(event, target_state)

        # Execute transition
        event.state = target_state
        event.version += 1

        # Set state-specific timestamps
        now = datetime.utcnow()
        if target_state == "locked":
            event.locked_at = now
        elif target_state == "completed":
            event.completed_at = now

        # Log transition
        transition_log = EventStateTransition(
            event_id=event_id,
            from_state=current_state,
            to_state=target_state,
            actor_telegram_user_id=actor_telegram_user_id,
            reason=reason,
            source=source,
        )
        self.session.add(transition_log)

        # Increment version for return
        await self.session.flush()

        logger.info(
            "Event state transition",
            extra={
                "event_id": event_id,
                "from_state": current_state,
                "to_state": target_state,
                "actor": actor_telegram_user_id,
                "source": source,
                "transition_id": transition_log.transition_id,
            },
        )

        return event, True

    async def _check_preconditions(self, event: Event, target_state: str) -> None:
        """Check transition preconditions."""

        if target_state == "locked":
            # Check minimum participants
            confirmed_count = await self._get_confirmed_count(event)
            min_required = event.min_participants or 2

            if confirmed_count < min_required:
                raise ThresholdNotMetError(
                    f"Cannot lock: {confirmed_count} confirmed, need {min_required}", error_code="THRESHOLD_NOT_MET"
                )

    async def _get_confirmed_count(self, event: Event) -> int:
        """Get count of confirmed participants."""
        result = await self.session.execute(
            select(func.count())
            .select_from(EventParticipant)
            .where(
                EventParticipant.event_id == event.event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        return int(result.scalar_one() or 0)

    async def get_transition_history(self, event_id: int) -> list[EventStateTransition]:
        """Get full transition history for an event."""
        result = await self.session.execute(
            select(EventStateTransition)
            .where(EventStateTransition.event_id == event_id)
            .order_by(EventStateTransition.timestamp)
        )
        return list(result.scalars().all())

    async def get_current_state(self, event_id: int) -> Optional[str]:
        """Get current state without locking."""
        result = await self.session.execute(select(Event.state).where(Event.event_id == event_id))
        return result.scalar_one_or_none()

    async def validate_transition(self, event_id: int, target_state: str) -> Dict[str, Any]:
        """
        Validate a potential transition without executing it.

        Returns dict with:
        - valid: bool
        - reason: str (if invalid)
        - preconditions: dict of precondition status
        """
        result = await self.session.execute(select(Event).where(Event.event_id == event_id))
        event = result.scalar_one_or_none()

        if not event:
            return {"valid": False, "reason": "Event not found", "preconditions": {}}

        if not can_transition(event.state, target_state):
            return {
                "valid": False,
                "reason": f"Invalid transition from {event.state} to {target_state}",
                "preconditions": {},
            }

        preconditions = {}

        if target_state == "locked":
            confirmed_count = await self._get_confirmed_count(event)
            min_required = event.min_participants or 2
            preconditions["threshold_met"] = confirmed_count >= min_required
            preconditions["confirmed_count"] = confirmed_count
            preconditions["min_required"] = min_required

        return {"valid": True, "reason": None, "preconditions": preconditions}
