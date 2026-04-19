#!/usr/bin/env python3
"""Comprehensive tests for bot/services/participant_service.py.

This module tests the ParticipantService which is the single write path
for all participant management operations.

Critical areas tested:
- Join/leave operations (common path)
- Confirm/cancel state transitions (frequently buggy)
- Edge cases: rejoin after cancel, confirm without join, etc.
- Count aggregation (for threshold calculations)
- Validation functions (replaces SQL CHECK constraints)
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from db.models import EventParticipant, ParticipantStatus, ParticipantRole


class TestValidationFunctions:
    """Tests for application-layer validation replacing SQL CHECK constraints."""

    def test_validate_constraint_type_valid(self):
        """Test valid constraint types are normalized."""
        from bot.services.participant_service import validate_constraint_type
        
        assert validate_constraint_type("if_joins") == "if_joins"
        assert validate_constraint_type("IF_JOINS") == "if_joins"  # uppercase
        assert validate_constraint_type("  if_attends  ") == "if_attends"  # whitespace
        assert validate_constraint_type("Unless_Joins") == "unless_joins"  # mixed case

    def test_validate_constraint_type_invalid(self):
        """Test invalid constraint types raise ValueError."""
        from bot.services.participant_service import validate_constraint_type
        
        with pytest.raises(ValueError) as exc_info:
            validate_constraint_type("invalid_type")
        assert "if_joins" in str(exc_info.value)  # Should list valid types
        
        with pytest.raises(ValueError):
            validate_constraint_type("")
        
        with pytest.raises(ValueError):
            validate_constraint_type(None)

    def test_validate_log_action_valid(self):
        """Test valid log actions are normalized."""
        from bot.services.participant_service import validate_log_action
        
        # Legacy actions
        assert validate_log_action("join") == "join"
        assert validate_log_action("CONFIRM") == "confirm"
        
        # v3.5 new actions
        assert validate_log_action("relinquish") == "relinquish"
        assert validate_log_action("Enrich_Hashtag") == "enrich_hashtag"

    def test_validate_log_action_invalid(self):
        """Test invalid log actions raise ValueError."""
        from bot.services.participant_service import validate_log_action
        
        with pytest.raises(ValueError) as exc_info:
            validate_log_action("unknown_action")
        assert "join" in str(exc_info.value)  # Should list valid actions


class TestParticipantServiceInitialization:
    """Tests for service setup."""

    def test_service_exposes_constants(self):
        """Test that service exposes validation constants."""
        from bot.services.participant_service import ParticipantService
        
        # These should be accessible on the class
        assert hasattr(ParticipantService, 'VALID_CONSTRAINT_TYPES')
        assert hasattr(ParticipantService, 'VALID_LOG_ACTIONS')
        assert "if_joins" in ParticipantService.VALID_CONSTRAINT_TYPES
        assert "join" in ParticipantService.VALID_LOG_ACTIONS


class TestJoinOperations:
    """Tests for join() method - most common operation."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_join_new_participant(self, service, mock_session):
        """Test joining a new participant creates record."""
        # Mock no existing participant
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.join(
            event_id=1,
            telegram_user_id=12345,
            source="callback"
        )

        assert is_new is True
        assert participant.event_id == 1
        assert participant.telegram_user_id == 12345
        assert participant.status == ParticipantStatus.joined
        assert participant.source == "callback"
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_join_already_joined(self, service, mock_session):
        """Test joining when already joined returns existing record."""
        existing = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.joined,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.join(event_id=1, telegram_user_id=12345)

        assert is_new is False
        assert participant is existing
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejoin_after_cancel(self, service, mock_session):
        """Test rejoining after cancel restores participant - BUG PRONE AREA."""
        cancelled = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.cancelled,
            cancelled_at=datetime.utcnow(),
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cancelled
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.join(event_id=1, telegram_user_id=12345)

        assert is_new is True  # This is a "new" rejoin
        assert participant.status == ParticipantStatus.joined
        assert participant.cancelled_at is None
        assert participant.joined_at is not None

    @pytest.mark.asyncio
    async def test_join_after_no_show(self, service, mock_session):
        """Test joining after no_show status upgrades to joined."""
        no_show = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.no_show,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = no_show
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.join(event_id=1, telegram_user_id=12345)

        assert is_new is True
        assert participant.status == ParticipantStatus.joined


class TestConfirmOperations:
    """Tests for confirm() method - state transition critical."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_confirm_existing_joined(self, service, mock_session):
        """Test confirming a joined participant."""
        joined = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.joined,
            joined_at=datetime.utcnow(),
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = joined
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.confirm(event_id=1, telegram_user_id=12345)

        assert is_new is True
        assert participant.status == ParticipantStatus.confirmed
        assert participant.confirmed_at is not None

    @pytest.mark.asyncio
    async def test_confirm_already_confirmed(self, service, mock_session):
        """Test confirming when already confirmed is idempotent."""
        confirmed = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.confirmed,
            confirmed_at=datetime.utcnow(),
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = confirmed
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.confirm(event_id=1, telegram_user_id=12345)

        assert is_new is False  # Not a new confirmation
        assert participant.status == ParticipantStatus.confirmed

    @pytest.mark.asyncio
    async def test_confirm_auto_joins_if_not_participant(self, service, mock_session):
        """Test confirm auto-joins if user not yet participant - COMMON FLOW."""
        from bot.services.participant_service import ParticipantService
        
        # First call returns None (not a participant)
        # Second call (from join) should create new participant
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Mock the join method to verify it's called
        with patch.object(service, 'join', new_callable=AsyncMock) as mock_join:
            mock_join.return_value = (MagicMock(status=ParticipantStatus.confirmed), True)
            await service.confirm(event_id=1, telegram_user_id=12345)
            
            mock_join.assert_called_once_with(1, 12345, "callback")

    @pytest.mark.asyncio
    async def test_confirm_after_cancel_raises_error(self, service, mock_session):
        """Test confirming after cancel raises error - BUSINESS RULE."""
        from bot.services.participant_service import ParticipantError
        
        cancelled = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.cancelled,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cancelled
        mock_session.execute.return_value = mock_result

        with pytest.raises(ParticipantError) as exc_info:
            await service.confirm(event_id=1, telegram_user_id=12345)
        
        assert "cannot confirm after cancelling" in str(exc_info.value).lower()


class TestCancelOperations:
    """Tests for cancel() method."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_cancel_joined_participant(self, service, mock_session):
        """Test cancelling a joined participant."""
        joined = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.joined,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = joined
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.cancel(event_id=1, telegram_user_id=12345)

        assert is_new is True
        assert participant.status == ParticipantStatus.cancelled
        assert participant.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_cancel_not_participant_raises_error(self, service, mock_session):
        """Test cancelling when not a participant raises error."""
        from bot.services.participant_service import ParticipantNotFoundError
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(ParticipantNotFoundError):
            await service.cancel(event_id=1, telegram_user_id=12345)

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_is_idempotent(self, service, mock_session):
        """Test cancelling when already cancelled returns False."""
        cancelled = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.cancelled,
            cancelled_at=datetime.utcnow(),
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cancelled
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.cancel(event_id=1, telegram_user_id=12345)

        assert is_new is False


class TestUnconfirmOperations:
    """Tests for unconfirm() method - revert confirmed to joined."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_unconfirm_confirmed_participant(self, service, mock_session):
        """Test unconfirming a confirmed participant."""
        confirmed = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.confirmed,
            confirmed_at=datetime.utcnow(),
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = confirmed
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.unconfirm(event_id=1, telegram_user_id=12345)

        assert is_new is True
        assert participant.status == ParticipantStatus.joined
        assert participant.confirmed_at is None

    @pytest.mark.asyncio
    async def test_unconfirm_not_confirmed_returns_false(self, service, mock_session):
        """Test unconfirming when not confirmed is no-op."""
        joined = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.joined,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = joined
        mock_session.execute.return_value = mock_result

        participant, is_new = await service.unconfirm(event_id=1, telegram_user_id=12345)

        assert is_new is False
        assert participant.status == ParticipantStatus.joined  # Unchanged


class TestCountOperations:
    """Tests for count aggregation methods - critical for thresholds."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_get_counts_returns_all_statuses(self, service, mock_session):
        """Test get_counts returns counts for all statuses."""
        # Mock query result: 2 joined, 3 confirmed, 1 cancelled
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (ParticipantStatus.joined, 2),
            (ParticipantStatus.confirmed, 3),
            (ParticipantStatus.cancelled, 1),
        ]
        mock_session.execute.return_value = mock_result

        counts = await service.get_counts(event_id=1)

        assert counts["joined"] == 2
        assert counts["confirmed"] == 3
        assert counts["cancelled"] == 1
        assert counts["total"] == 6  # Sum of all

    @pytest.mark.asyncio
    async def test_get_counts_no_participants(self, service, mock_session):
        """Test get_counts with no participants returns zeros."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        counts = await service.get_counts(event_id=1)

        assert counts["joined"] == 0
        assert counts["confirmed"] == 0
        assert counts["cancelled"] == 0
        assert counts["total"] == 0

    @pytest.mark.asyncio
    async def test_get_confirmed_count(self, service, mock_session):
        """Test get_confirmed_count returns scalar."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        count = await service.get_confirmed_count(event_id=1)

        assert count == 5

    @pytest.mark.asyncio
    async def test_get_interested_count(self, service, mock_session):
        """Test get_interested_count returns joined but not confirmed."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_session.execute.return_value = mock_result

        count = await service.get_interested_count(event_id=1)

        assert count == 3


class TestFinalizeCommitments:
    """Tests for finalize_commitments - critical for event locking."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_finalize_commitments_updates_joined(self, service, mock_session):
        """Test finalize converts joined participants to confirmed."""
        mock_result = MagicMock()
        mock_result.rowcount = 3  # 3 participants updated
        mock_session.execute.return_value = mock_result

        count = await service.finalize_commitments(event_id=1)

        assert count == 3
        # Verify the update query was called
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_commitments_none_to_finalize(self, service, mock_session):
        """Test finalize when no joined participants."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        count = await service.finalize_commitments(event_id=1)

        assert count == 0


class TestQueryOperations:
    """Tests for query methods."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_get_participant_found(self, service, mock_session):
        """Test getting existing participant."""
        existing = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.joined,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        participant = await service.get_participant(event_id=1, telegram_user_id=12345)

        assert participant is existing

    @pytest.mark.asyncio
    async def test_get_participant_not_found(self, service, mock_session):
        """Test getting non-existent participant returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        participant = await service.get_participant(event_id=1, telegram_user_id=12345)

        assert participant is None

    @pytest.mark.asyncio
    async def test_get_all_participants(self, service, mock_session):
        """Test getting all participants."""
        participants = [
            EventParticipant(event_id=1, telegram_user_id=1, status=ParticipantStatus.joined),
            EventParticipant(event_id=1, telegram_user_id=2, status=ParticipantStatus.confirmed),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = participants
        mock_session.execute.return_value = mock_result

        result = await service.get_all_participants(event_id=1)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_all_participants_with_status_filter(self, service, mock_session):
        """Test getting participants filtered by status."""
        confirmed = EventParticipant(
            event_id=1, 
            telegram_user_id=2, 
            status=ParticipantStatus.confirmed
        )
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [confirmed]
        mock_session.execute.return_value = mock_result

        result = await service.get_all_participants(
            event_id=1, 
            status_filter=ParticipantStatus.confirmed
        )

        assert len(result) == 1
        assert result[0].status == ParticipantStatus.confirmed


class TestMarkNoShow:
    """Tests for mark_no_show - post-event operations."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_mark_no_show_confirmed_participant(self, service, mock_session):
        """Test marking confirmed participant as no-show."""
        confirmed = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.confirmed,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = confirmed
        mock_session.execute.return_value = mock_result

        await service.mark_no_show(event_id=1, telegram_user_id=12345)

        assert confirmed.status == ParticipantStatus.no_show

    @pytest.mark.asyncio
    async def test_mark_no_show_not_confirmed_no_change(self, service, mock_session):
        """Test marking joined (not confirmed) participant doesn't change status."""
        joined = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=ParticipantStatus.joined,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = joined
        mock_session.execute.return_value = mock_result

        await service.mark_no_show(event_id=1, telegram_user_id=12345)

        # Status should remain joined (not no_show)
        assert joined.status == ParticipantStatus.joined


class TestRemoveParticipant:
    """Tests for remove_participant - destructive operation."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a ParticipantService instance."""
        from bot.services.participant_service import ParticipantService
        return ParticipantService(mock_session)

    @pytest.mark.asyncio
    async def test_remove_participant_success(self, service, mock_session):
        """Test removing participant record."""
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        result = await service.remove_participant(event_id=1, telegram_user_id=12345)

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_participant_not_found(self, service, mock_session):
        """Test removing non-existent participant."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        result = await service.remove_participant(event_id=1, telegram_user_id=12345)

        assert result is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
