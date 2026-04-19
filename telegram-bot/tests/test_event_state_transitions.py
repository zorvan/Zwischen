#!/usr/bin/env python3
"""Comprehensive tests for bot/services/event_state_transition_service.py.

This module tests the EventStateTransitionService which is the ONLY allowed
path for mutating event state. It enforces the state machine, preconditions,
and optimistic concurrency control.

Critical areas tested:
- Valid state machine transitions
- Invalid transition blocking
- Threshold checks for locking
- Optimistic concurrency control
- Transition audit logging
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from db.models import Event, EventStateTransition, EventParticipant


class TestStateMachineTransitions:
    """Tests for valid state transitions."""

    def test_can_transition_valid(self):
        """Test valid transitions are allowed."""
        from bot.common.event_states import can_transition
        
        # From proposed
        assert can_transition("proposed", "interested") is True
        assert can_transition("proposed", "cancelled") is True
        
        # From interested
        assert can_transition("interested", "confirmed") is True
        assert can_transition("interested", "cancelled") is True
        
        # From confirmed
        assert can_transition("confirmed", "interested") is True
        assert can_transition("confirmed", "proposed") is True
        assert can_transition("confirmed", "locked") is True
        assert can_transition("confirmed", "cancelled") is True
        
        # From locked
        assert can_transition("locked", "completed") is True
        assert can_transition("locked", "cancelled") is True

    def test_can_transition_invalid(self):
        """Test invalid transitions are blocked."""
        from bot.common.event_states import can_transition
        
        # Cannot go backwards from cancelled/completed
        assert can_transition("cancelled", "proposed") is False
        assert can_transition("completed", "locked") is False
        
        # Cannot skip states
        assert can_transition("proposed", "locked") is False
        assert can_transition("proposed", "confirmed") is False
        
        # Cannot go to same state
        assert can_transition("proposed", "proposed") is False

    def test_state_explanations_exist(self):
        """Test all states have explanations."""
        from bot.common.event_states import STATE_EXPLANATIONS, EVENT_STATE_TRANSITIONS
        
        for state in EVENT_STATE_TRANSITIONS.keys():
            assert state in STATE_EXPLANATIONS


class TestGetAvailableActions:
    """Tests for get_available_actions - context-aware buttons."""

    def test_available_actions_not_participating(self):
        """Test actions for non-participant."""
        from bot.common.event_states import get_available_actions
        
        actions = get_available_actions(None, "proposed")
        
        assert "view" in actions
        assert "join" in actions
        assert "relinquish" not in actions

    def test_available_actions_joined(self):
        """Test actions for joined participant."""
        from bot.common.event_states import get_available_actions
        
        actions = get_available_actions("joined", "interested")
        
        assert "view" in actions
        assert "enrich" in actions
        assert "constraint" in actions
        assert "relinquish" in actions
        assert "commit" in actions
        assert "join" not in actions

    def test_available_actions_confirmed(self):
        """Test actions for confirmed participant."""
        from bot.common.event_states import get_available_actions
        
        actions = get_available_actions("confirmed", "confirmed")
        
        assert "view" in actions
        assert "enrich" in actions
        assert "constraint" in actions
        assert "relinquish" in actions
        assert "commit" not in actions  # Already confirmed

    def test_available_actions_locked_event(self):
        """Test limited actions for locked event."""
        from bot.common.event_states import get_available_actions
        
        actions = get_available_actions("confirmed", "locked")
        
        assert actions == ["view"]  # Only view for locked events


class TestEventStateTransitionServiceInit:
    """Tests for service initialization."""

    def test_service_init(self):
        """Test service stores session."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        
        mock_session = MagicMock()
        service = EventStateTransitionService(mock_session)
        
        assert service.session is mock_session


class TestSuccessfulTransitions:
    """Tests for successful state transitions."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventStateTransitionService instance."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        return EventStateTransitionService(mock_session)

    @pytest.mark.asyncio
    async def test_transition_proposed_to_interested(self, service, mock_session):
        """Test valid transition proposed -> interested."""
        event = MagicMock()
        event.event_id = 1
        event.state = "proposed"
        event.version = 1
        event.min_participants = 2
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        updated_event, occurred = await service.transition(
            event_id=1,
            target_state="interested",
            actor_telegram_user_id=12345,
            source="callback",
        )

        assert occurred is True
        assert updated_event.state == "interested"
        assert updated_event.version == 2
        mock_session.add.assert_called_once()  # Transition log added

    @pytest.mark.asyncio
    async def test_transition_interested_to_confirmed(self, service, mock_session):
        """Test valid transition interested -> confirmed."""
        event = MagicMock()
        event.event_id = 1
        event.state = "interested"
        event.version = 1
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        updated_event, occurred = await service.transition(
            event_id=1,
            target_state="confirmed",
            actor_telegram_user_id=12345,
            source="callback",
        )

        assert occurred is True
        assert updated_event.state == "confirmed"

    @pytest.mark.asyncio
    async def test_transition_confirmed_to_locked(self, service, mock_session):
        """Test valid transition confirmed -> locked."""
        event = MagicMock()
        event.event_id = 1
        event.state = "confirmed"
        event.version = 1
        event.min_participants = 2
        event.locked_at = None
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result
        
        # Mock confirmed count >= min_participants
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 3
        
        mock_session.execute.side_effect = [
            mock_result,
            mock_count_result,
        ]

        updated_event, occurred = await service.transition(
            event_id=1,
            target_state="locked",
            actor_telegram_user_id=12345,
            source="callback",
        )

        assert occurred is True
        assert updated_event.state == "locked"
        assert updated_event.locked_at is not None

    @pytest.mark.asyncio
    async def test_transition_locked_to_completed(self, service, mock_session):
        """Test valid transition locked -> completed."""
        event = MagicMock()
        event.event_id = 1
        event.state = "locked"
        event.version = 1
        event.completed_at = None
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        updated_event, occurred = await service.transition(
            event_id=1,
            target_state="completed",
            actor_telegram_user_id=12345,
            source="callback",
        )

        assert occurred is True
        assert updated_event.state == "completed"
        assert updated_event.completed_at is not None


class TestInvalidTransitions:
    """Tests for invalid/blocked transitions."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventStateTransitionService instance."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        return EventStateTransitionService(mock_session)

    @pytest.mark.asyncio
    async def test_invalid_transition_raises_error(self, service, mock_session):
        """Test invalid transition raises EventStateTransitionError."""
        from bot.services.event_state_transition_service import EventStateTransitionError
        
        event = MagicMock()
        event.event_id = 1
        event.state = "proposed"
        event.version = 1
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        with pytest.raises(EventStateTransitionError) as exc_info:
            await service.transition(
                event_id=1,
                target_state="locked",  # Cannot go proposed -> locked
                actor_telegram_user_id=12345,
                source="callback",
            )
        
        assert "Invalid transition" in str(exc_info.value)
        assert exc_info.value.error_code == "INVALID_TRANSITION"

    @pytest.mark.asyncio
    async def test_transition_from_terminal_state_fails(self, service, mock_session):
        """Test cannot transition from cancelled/completed."""
        from bot.services.event_state_transition_service import EventStateTransitionError
        
        event = MagicMock()
        event.event_id = 1
        event.state = "cancelled"
        event.version = 1
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        with pytest.raises(EventStateTransitionError):
            await service.transition(
                event_id=1,
                target_state="proposed",
                actor_telegram_user_id=12345,
                source="callback",
            )


class TestThresholdPreconditions:
    """Tests for threshold checks on lock."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventStateTransitionService instance."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        return EventStateTransitionService(mock_session)

    @pytest.mark.asyncio
    async def test_lock_below_threshold_raises_error(self, service, mock_session):
        """Test locking below min_participants raises ThresholdNotMetError."""
        from bot.services.event_state_transition_service import ThresholdNotMetError
        
        event = MagicMock()
        event.event_id = 1
        event.state = "confirmed"
        event.version = 1
        event.min_participants = 5
        
        mock_event_result = MagicMock()
        mock_event_result.scalar_one_or_none.return_value = event
        
        # Mock confirmed count = 2 (below threshold of 5)
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 2
        
        mock_session.execute.side_effect = [
            mock_event_result,
            mock_count_result,
        ]

        with pytest.raises(ThresholdNotMetError) as exc_info:
            await service.transition(
                event_id=1,
                target_state="locked",
                actor_telegram_user_id=12345,
                source="callback",
            )
        
        assert "2 confirmed, need 5" in str(exc_info.value)
        assert exc_info.value.error_code == "THRESHOLD_NOT_MET"

    @pytest.mark.asyncio
    async def test_lock_at_threshold_succeeds(self, service, mock_session):
        """Test locking at exactly min_participants succeeds."""
        event = MagicMock()
        event.event_id = 1
        event.state = "confirmed"
        event.version = 1
        event.min_participants = 3
        event.locked_at = None
        
        mock_event_result = MagicMock()
        mock_event_result.scalar_one_or_none.return_value = event
        
        # Mock confirmed count = 3 (exactly at threshold)
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 3
        
        mock_session.execute.side_effect = [
            mock_event_result,
            mock_count_result,
        ]
        mock_session.flush = AsyncMock()
        mock_session.add = MagicMock()

        updated_event, occurred = await service.transition(
            event_id=1,
            target_state="locked",
            actor_telegram_user_id=12345,
            source="callback",
        )

        assert occurred is True


class TestConcurrencyControl:
    """Tests for optimistic concurrency control."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventStateTransitionService instance."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        return EventStateTransitionService(mock_session)

    @pytest.mark.asyncio
    async def test_concurrency_conflict_raises_error(self, service, mock_session):
        """Test version mismatch raises ConcurrencyConflictError."""
        from bot.services.event_state_transition_service import ConcurrencyConflictError
        
        event = MagicMock()
        event.event_id = 1
        event.state = "proposed"
        event.version = 5  # Current version is 5
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        with pytest.raises(ConcurrencyConflictError) as exc_info:
            await service.transition(
                event_id=1,
                target_state="interested",
                actor_telegram_user_id=12345,
                source="callback",
                expected_version=3,  # But we expect version 3
            )
        
        assert "version 5, expected 3" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_matching_version_succeeds(self, service, mock_session):
        """Test matching version allows transition."""
        event = MagicMock()
        event.event_id = 1
        event.state = "proposed"
        event.version = 3
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()
        mock_session.add = MagicMock()

        updated_event, occurred = await service.transition(
            event_id=1,
            target_state="interested",
            actor_telegram_user_id=12345,
            source="callback",
            expected_version=3,  # Matches current version
        )

        assert occurred is True


class TestEventNotFound:
    """Tests for missing event handling."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventStateTransitionService instance."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        return EventStateTransitionService(mock_session)

    @pytest.mark.asyncio
    async def test_event_not_found_raises_error(self, service, mock_session):
        """Test missing event raises EventNotFoundError."""
        from bot.services.event_state_transition_service import EventNotFoundError
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(EventNotFoundError) as exc_info:
            await service.transition(
                event_id=999,
                target_state="interested",
                actor_telegram_user_id=12345,
                source="callback",
            )
        
        assert "Event 999 not found" in str(exc_info.value)


class TestQueryMethods:
    """Tests for query methods."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventStateTransitionService instance."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        return EventStateTransitionService(mock_session)

    @pytest.mark.asyncio
    async def test_get_transition_history(self, service, mock_session):
        """Test retrieving transition history."""
        transitions = [
            EventStateTransition(event_id=1, from_state="proposed", to_state="interested"),
            EventStateTransition(event_id=1, from_state="interested", to_state="confirmed"),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = transitions
        mock_session.execute.return_value = mock_result

        history = await service.get_transition_history(event_id=1)

        assert len(history) == 2
        assert history[0].from_state == "proposed"

    @pytest.mark.asyncio
    async def test_get_current_state(self, service, mock_session):
        """Test getting current state."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "confirmed"
        mock_session.execute.return_value = mock_result

        state = await service.get_current_state(event_id=1)

        assert state == "confirmed"

    @pytest.mark.asyncio
    async def test_get_current_state_not_found(self, service, mock_session):
        """Test getting state for missing event."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        state = await service.get_current_state(event_id=999)

        assert state is None


class TestValidateTransition:
    """Tests for validate_transition (dry-run validation)."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventStateTransitionService instance."""
        from bot.services.event_state_transition_service import EventStateTransitionService
        return EventStateTransitionService(mock_session)

    @pytest.mark.asyncio
    async def test_validate_valid_transition(self, service, mock_session):
        """Test validating a valid transition."""
        event = MagicMock()
        event.event_id = 1
        event.state = "proposed"
        event.min_participants = 2
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        result = await service.validate_transition(event_id=1, target_state="interested")

        assert result["valid"] is True
        assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_validate_invalid_transition(self, service, mock_session):
        """Test validating an invalid transition."""
        event = MagicMock()
        event.event_id = 1
        event.state = "proposed"
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = event
        mock_session.execute.return_value = mock_result

        result = await service.validate_transition(event_id=1, target_state="locked")

        assert result["valid"] is False
        assert "Invalid transition" in result["reason"]

    @pytest.mark.asyncio
    async def test_validate_event_not_found(self, service, mock_session):
        """Test validating for missing event."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.validate_transition(event_id=999, target_state="interested")

        assert result["valid"] is False
        assert "Event not found" in result["reason"]

    @pytest.mark.asyncio
    async def test_validate_lock_preconditions(self, service, mock_session):
        """Test validating lock preconditions."""
        event = MagicMock()
        event.event_id = 1
        event.state = "confirmed"
        event.min_participants = 5
        
        mock_event_result = MagicMock()
        mock_event_result.scalar_one_or_none.return_value = event
        
        # Mock count below threshold
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 2
        
        mock_session.execute.side_effect = [
            mock_event_result,
            mock_count_result,
        ]

        result = await service.validate_transition(event_id=1, target_state="locked")

        assert result["valid"] is True  # Transition is valid, but...
        assert result["preconditions"]["threshold_met"] is False
        assert result["preconditions"]["confirmed_count"] == 2
        assert result["preconditions"]["min_required"] == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
