#!/usr/bin/env python3
"""Tests for v2 service integrations."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services import (
    ParticipantService,
    EventStateTransitionService,
    EventLifecycleService,
)
from db.models import Event, EventParticipant, ParticipantStatus, ParticipantRole


@pytest.fixture
def session():
    """Mock async session for testing."""
    mock = MagicMock(spec=AsyncSession)
    mock.execute = AsyncMock()
    mock.add = MagicMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    mock.flush = AsyncMock()
    return mock


@pytest.fixture
def participant_service(session):
    """ParticipantService instance for testing."""
    return ParticipantService(session)


@pytest.fixture
def transition_service(session):
    """EventStateTransitionService instance for testing."""
    return EventStateTransitionService(session)


@pytest.fixture
def lifecycle_service(session):
    """EventLifecycleService instance for testing."""
    bot = MagicMock()
    return EventLifecycleService(bot, session)


class TestParticipantService:
    """Test ParticipantService functionality."""

    @pytest.mark.asyncio
    async def test_join_new_participant(self, participant_service, session):
        """Test joining a new participant."""
        # Mock the database calls
        session.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        session.add = MagicMock()

        participant, is_new = await participant_service.join(
            event_id=1, telegram_user_id=123, source="test"
        )

        assert is_new is True
        assert participant.event_id == 1
        assert participant.telegram_user_id == 123
        assert participant.status == ParticipantStatus.joined
        assert participant.role == ParticipantRole.participant

    @pytest.mark.asyncio
    async def test_join_existing_participant(self, participant_service, session):
        """Test rejoining an existing cancelled participant."""
        # Mock existing cancelled participant
        existing_participant = EventParticipant(
            event_id=1, telegram_user_id=123, status=ParticipantStatus.cancelled
        )

        session.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_participant
        session.execute.return_value = result

        participant, is_new = await participant_service.join(
            event_id=1, telegram_user_id=123, source="test"
        )

        assert is_new is True
        assert participant.status == ParticipantStatus.joined

    @pytest.mark.asyncio
    async def test_confirm_participant(self, participant_service, session):
        """Test confirming a participant."""
        # Mock existing joined participant
        existing_participant = EventParticipant(
            event_id=1, telegram_user_id=123, status=ParticipantStatus.joined
        )

        session.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_participant
        session.execute.return_value = result

        participant, is_new = await participant_service.confirm(
            event_id=1, telegram_user_id=123, source="test"
        )

        assert is_new is True
        assert participant.status == ParticipantStatus.confirmed
        assert participant.confirmed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_participant(self, participant_service, session):
        """Test cancelling a participant."""
        # Mock existing confirmed participant
        existing_participant = EventParticipant(
            event_id=1, telegram_user_id=123, status=ParticipantStatus.confirmed
        )

        session.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_participant
        session.execute.return_value = result

        participant, is_new = await participant_service.cancel(
            event_id=1, telegram_user_id=123, source="test"
        )

        assert is_new is True
        assert participant.status == ParticipantStatus.cancelled
        assert participant.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_unconfirm_participant(self, participant_service, session):
        """Test unconfirming a participant."""
        # Mock existing confirmed participant
        existing_participant = EventParticipant(
            event_id=1, telegram_user_id=123, status=ParticipantStatus.confirmed
        )

        session.execute = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_participant
        session.execute.return_value = result

        participant, is_new = await participant_service.unconfirm(
            event_id=1, telegram_user_id=123, source="test"
        )

        assert is_new is True
        assert participant.status == ParticipantStatus.joined
        assert participant.confirmed_at is None

    @pytest.mark.asyncio
    async def test_get_counts(self, participant_service, session):
        """Test getting participant counts."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (ParticipantStatus.joined, 3),
            (ParticipantStatus.confirmed, 2),
            (ParticipantStatus.cancelled, 1),
        ]
        session.execute = AsyncMock(return_value=mock_result)

        counts = await participant_service.get_counts(event_id=1)

        assert counts["joined"] == 3
        assert counts["confirmed"] == 2
        assert counts["cancelled"] == 1
        assert counts["total"] == 6

    @pytest.mark.asyncio
    async def test_finalize_commitments(self, participant_service, session):
        """Test finalizing commitments."""
        # Mock database update result
        mock_result = MagicMock()
        mock_result.rowcount = 3
        session.execute = AsyncMock(return_value=mock_result)

        count = await participant_service.finalize_commitments(event_id=1)

        assert count == 3


class TestEventStateTransitionService:
    """Test EventStateTransitionService functionality."""

    @pytest.mark.asyncio
    async def test_valid_transition(self, transition_service, session):
        """Test a valid state transition."""
        event = Event(
            event_id=1, state="proposed", organizer_telegram_user_id=123, version=1
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = event
        session.execute = AsyncMock(return_value=result)

        updated_event, transitioned = await transition_service.transition(
            event_id=1,
            target_state="interested",
            actor_telegram_user_id=123,
            source="test",
            reason="Test transition",
        )

        assert transitioned is True
        assert updated_event.state == "interested"

    @pytest.mark.asyncio
    async def test_invalid_transition(self, transition_service, session):
        """Test an invalid state transition."""
        event = Event(event_id=1, state="proposed", organizer_telegram_user_id=123)

        result = MagicMock()
        result.scalar_one_or_none.return_value = event
        session.execute = AsyncMock(return_value=result)

        with pytest.raises(Exception):  # Should raise EventStateTransitionError
            await transition_service.transition(
                event_id=1,
                target_state="completed",  # Invalid transition
                actor_telegram_user_id=123,
                source="test",
            )


class TestEventLifecycleService:
    """Test EventLifecycleService functionality."""

    @pytest.mark.asyncio
    async def test_transition_with_lifecycle_locked(self, lifecycle_service, session):
        """Test lifecycle transition to locked state."""
        event = Event(event_id=1, state="confirmed", organizer_telegram_user_id=123)

        # Mock transition service
        lifecycle_service.transition_service = MagicMock()
        lifecycle_service.transition_service.transition = AsyncMock(
            return_value=(event, True)
        )

        # Mock materialization service
        lifecycle_service.materialization_service = MagicMock()
        lifecycle_service.materialization_service.announce_event_locked = AsyncMock()

        # Mock lifecycle methods that access database
        lifecycle_service._delete_live_card = AsyncMock()
        lifecycle_service._freeze_hashtags = AsyncMock()

        # Mock group chat ID
        lifecycle_service._get_group_chat_id = AsyncMock(return_value=456)
        lifecycle_service._get_confirmed_participants = AsyncMock(return_value=[])

        updated_event, transitioned = await lifecycle_service.transition_with_lifecycle(
            event_id=1, target_state="locked", actor_telegram_user_id=123, source="test"
        )

        assert transitioned is True
        lifecycle_service.materialization_service.announce_event_locked.assert_called_once()

    @pytest.mark.asyncio
    async def test_transition_with_lifecycle_completed(
        self, lifecycle_service, session
    ):
        """Test lifecycle transition to completed state."""
        event = Event(event_id=1, state="locked", organizer_telegram_user_id=123)

        # Mock transition service
        lifecycle_service.transition_service = MagicMock()
        lifecycle_service.transition_service.transition = AsyncMock(
            return_value=(event, True)
        )

        # Mock services
        lifecycle_service.materialization_service = MagicMock()
        lifecycle_service.materialization_service.announce_event_completed = AsyncMock()
        lifecycle_service.memory_service = MagicMock()
        lifecycle_service.memory_service.start_memory_collection = AsyncMock()

        # Mock lifecycle methods that access database
        lifecycle_service._delete_live_card = AsyncMock()
        lifecycle_service._freeze_hashtags = AsyncMock()

        # Mock helper methods
        lifecycle_service._get_group_chat_id = AsyncMock(return_value=456)
        lifecycle_service._get_participant_count = AsyncMock(return_value=5)

        updated_event, transitioned = await lifecycle_service.transition_with_lifecycle(
            event_id=1,
            target_state="completed",
            actor_telegram_user_id=123,
            source="test",
        )

        assert transitioned is True
        lifecycle_service.materialization_service.announce_event_completed.assert_called_once()
        lifecycle_service.memory_service.start_memory_collection.assert_called_once()


class TestServiceIntegration:
    """Test integration between services."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="Complex async DB call sequence - use scenario simulator instead"
    )
    async def test_full_event_lifecycle(self, session):
        """Test a complete event lifecycle with all services."""
        # Create event
        event = Event(
            event_id=1, state="proposed", organizer_telegram_user_id=123, version=1
        )

        # Mock services
        participant_service = ParticipantService(session)
        transition_service = EventStateTransitionService(session)
        bot = MagicMock()
        lifecycle_service = EventLifecycleService(bot, session)

        # Mock all database calls - using side_effect for sequential calls
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        finalize_result = MagicMock()
        finalize_result.rowcount = 3
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        # Use a generator that always returns finalize_result after exhaustion
        call_results = [
            result,  # 1: participant lookup (join)
            result,  # 2: participant lookup (join 2)
            result,  # 3: participant lookup (confirm)
            result,  # 4: event lookup (lock)
            result,  # 5: confirmed participants lookup
            result,  # 6: group_chat_id lookup
            finalize_result,  # 7: finalize commitments
            result,  # 8: event lookup (complete)
            count_result,  # 9: participant count
        ]
        session.execute = AsyncMock(side_effect=call_results)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        # 1. Organizer joins (auto-join on creation)
        participant, _ = await participant_service.join(1, 123, "creation", "organizer")
        assert participant.status == ParticipantStatus.joined

        # 2. Another participant joins
        result.scalar_one_or_none.return_value = None
        participant2, _ = await participant_service.join(1, 456, "slash")
        assert participant2.status == ParticipantStatus.joined

        # 3. Participants confirm
        existing_participant = EventParticipant(
            event_id=1, telegram_user_id=456, status=ParticipantStatus.joined
        )
        result.scalar_one_or_none.return_value = existing_participant

        participant2, _ = await participant_service.confirm(1, 456, "callback")
        assert participant2.status == ParticipantStatus.confirmed

        # 4. Event should transition to confirmed (this would be handled by handlers)
        # 5. Event gets locked
        event.state = "confirmed"
        result.scalar_one_or_none.return_value = event

        # Mock transition
        transition_service.transition = AsyncMock(return_value=(event, True))
        lifecycle_service.transition_service = transition_service
        lifecycle_service.materialization_service = MagicMock()
        lifecycle_service.materialization_service.announce_event_locked = AsyncMock()
        lifecycle_service.materialization_service.announce_event_completed = AsyncMock()
        lifecycle_service._get_group_chat_id = AsyncMock(return_value=789)
        lifecycle_service._get_participant_count = AsyncMock(return_value=2)

        updated_event, _ = await lifecycle_service.transition_with_lifecycle(
            1, "locked", 123, "slash"
        )

        # 6. Commitments finalized
        finalized = await participant_service.finalize_commitments(1)
        assert finalized >= 0

        # 7. Event completed
        updated_event.state = "locked"
        lifecycle_service.memory_service = MagicMock()
        lifecycle_service.memory_service.start_memory_collection = AsyncMock()

        await lifecycle_service.transition_with_lifecycle(1, "completed", 123, "auto")
