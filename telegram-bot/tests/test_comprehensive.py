#!/usr/bin/env python3
"""
Comprehensive test suite for Telegram Coordination Bot.
Tests cover critical flows, edge cases, and error handling.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
from sqlalchemy import select


class TestParticipantService:
    """Test ParticipantService operations."""

    @pytest.mark.asyncio
    async def test_join_creates_participant(self):
        """Test joining event creates participant record."""
        from bot.services.participant_service import ParticipantService
        from db.models import ParticipantStatus

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        # Mock the query result for event existence check
        mock_event = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_event
        mock_session.execute = AsyncMock(return_value=mock_result)

        service = ParticipantService(mock_session)

        participant, is_new = await service.join(
            event_id=1, telegram_user_id=12345, source="callback"
        )

        assert participant is not None

    @pytest.mark.asyncio
    async def test_cancel_removes_participant(self):
        """Test cancelling removes participant record."""
        from bot.services.participant_service import ParticipantService

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.delete = AsyncMock()

        # Mock existing participant
        mock_participant = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_participant
        mock_session.execute = AsyncMock(return_value=mock_result)

        service = ParticipantService(mock_session)

        participant, is_new = await service.cancel(
            event_id=1, telegram_user_id=12345, source="callback"
        )

        assert participant is not None

    @pytest.mark.asyncio
    async def test_get_confirmed_count(self):
        """Test counting confirmed participants."""
        from bot.services.participant_service import ParticipantService
        from db.models import ParticipantStatus

        mock_session = AsyncMock()

        # Mock count result
        mock_scalar = MagicMock()
        mock_scalar.scalar.return_value = 5
        mock_session.execute = AsyncMock(return_value=mock_scalar)

        service = ParticipantService(mock_session)

        count = await service.get_confirmed_count(1)

        assert count == 5


class TestEventDetails:
    """Test event details display."""

    @pytest.mark.asyncio
    async def test_show_logs_with_users(self):
        """Test log display includes user information."""
        from bot.commands.event_details import show_logs

        query = MagicMock()
        query.edit_message_text = AsyncMock()

        mock_log = MagicMock()
        mock_log.action = "join"
        mock_log.timestamp = datetime.utcnow()

        mock_user = MagicMock()
        mock_user.telegram_user_id = 12345
        mock_user.username = "testuser"
        mock_user.display_name = "Test User"

        with patch("bot.commands.event_details.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.all.return_value = [(mock_log, mock_user)]
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await show_logs(query, 1)

            # Verify user info is included
            call_args = query.edit_message_text.call_args[0][0]
            assert "testuser" in call_args or "Test User" in call_args

    @pytest.mark.asyncio
    async def test_show_logs_without_users(self):
        """Test log display handles missing users gracefully."""
        from bot.commands.event_details import show_logs

        query = MagicMock()
        query.edit_message_text = AsyncMock()

        mock_log = MagicMock()
        mock_log.action = "system"
        mock_log.timestamp = datetime.utcnow()

        with patch("bot.commands.event_details.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.all.return_value = [(mock_log, None)]
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await show_logs(query, 1)

            # Should not crash, should show log without user info
            assert query.edit_message_text.called


class TestEventPresenters:
    """Test event presentation helpers."""

    @pytest.mark.asyncio
    async def test_get_user_mention_with_username(self):
        """Test user mention format with username."""
        from bot.common.event_presenters import get_user_mention

        mock_session = AsyncMock()
        mock_user = MagicMock()
        mock_user.username = "testuser"
        mock_user.display_name = "Test User"
        mock_session.execute.return_value = MagicMock(
            scalar_one_or_none=lambda: mock_user
        )

    @pytest.mark.asyncio
    async def test_get_user_mention_without_username(self):
        """Test user mention format with display name."""
        from bot.common.event_presenters import get_user_mention

        mock_session = AsyncMock()
        mock_user = MagicMock()
        mock_user.username = None
        mock_user.display_name = "Test User"
        mock_session.execute.return_value = MagicMock(
            scalar_one_or_none=lambda: mock_user
        )

        result = await get_user_mention(mock_session, 12345)

        assert "Test User" in result

    @pytest.mark.asyncio
    async def test_get_user_mention_no_user(self):
        """Test user mention format fallback to ID."""
        from bot.common.event_presenters import get_user_mention

        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

        result = await get_user_mention(mock_session, 12345)

        assert "User12345" in result


class TestConstraintsAvailability:
    """Test availability submission rules."""

    @pytest.mark.asyncio
    async def test_organizer_can_add_private_constraint(self):
        """Organizer should be able to add private constraints in DM when participating."""
        from bot.commands.constraints import _save_constraint_from_inputs

        update = MagicMock()
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        update.callback_query = None
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        update.effective_user.full_name = "Organizer"
        update.effective_user.username = "organizer"
        update.effective_chat = MagicMock()
        update.effective_chat.type = "private"

        context = MagicMock()
        context.bot = MagicMock()

        event = MagicMock()
        event.participants = [MagicMock(telegram_user_id=12345)]

        mock_event_result = MagicMock()
        mock_event_result.scalar_one_or_none.return_value = event

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_event_result)

        with (
            patch("bot.commands.constraints.get_session") as mock_get_session,
            patch(
                "bot.commands.constraints.get_or_create_user_id",
                AsyncMock(side_effect=[99, 88]),
            ),
            patch(
                "bot.commands.constraints.get_user_id_by_username",
                AsyncMock(return_value=88),
            ),
            patch("bot.commands.constraints.is_attendee", return_value=True),
        ):
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await _save_constraint_from_inputs(
                update=update,
                context=context,
                event_id=77,
                target_input="@reza",
                constraint_type="if_joins",
                confidence=0.8,
                summary="Need Reza in",
            )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()
        update.message.reply_text.assert_awaited()
        assert (
            "Constraint added to event 77"
            in update.message.reply_text.await_args.args[0]
        )


class TestPrivateNotePermissions:
    """Test private-note permission rules."""

    @pytest.mark.asyncio
    async def test_organizer_participant_can_submit_private_note(self):
        """Organizer should be allowed to submit private notes when participating."""
        from bot.common.rbac import check_can_submit_private_note

        event = MagicMock()
        participant = MagicMock()

        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event
        participant_result = MagicMock()
        participant_result.scalar_one_or_none.return_value = participant

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[event_result, participant_result])

        allowed, error = await check_can_submit_private_note(
            session=session,
            event_id=55,
            telegram_user_id=12345,
        )

        assert allowed is True
        assert error is None


class TestParticipantStateReconcile:
    """Test state reconciliation after participant changes."""

    @pytest.mark.asyncio
    async def test_confirmed_event_steps_back_to_interested_with_active_participants(
        self,
    ):
        from bot.common.participant_state_reconcile import (
            reconcile_event_state_after_participant_change,
        )

        event = MagicMock()
        event.event_id = 9
        event.state = "confirmed"
        event.version = 3

        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event
        active_count_result = MagicMock()
        active_count_result.scalar_one.return_value = 2
        confirmed_count_result = MagicMock()
        confirmed_count_result.scalar_one.return_value = 0

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[event_result, active_count_result, confirmed_count_result]
        )
        bot = MagicMock()

        transitioned_event = MagicMock()
        with patch(
            "bot.common.participant_state_reconcile.EventLifecycleService"
        ) as mock_lifecycle_cls:
            mock_lifecycle = mock_lifecycle_cls.return_value
            mock_lifecycle.transition_with_lifecycle = AsyncMock(
                return_value=(transitioned_event, True)
            )

            result = await reconcile_event_state_after_participant_change(
                session=session,
                bot=bot,
                event_id=9,
                actor_telegram_user_id=12345,
                source="test",
                reason="state drop",
            )

        assert result is transitioned_event
        mock_lifecycle.transition_with_lifecycle.assert_awaited_once()
        assert (
            mock_lifecycle.transition_with_lifecycle.await_args.kwargs["target_state"]
            == "interested"
        )

    @pytest.mark.asyncio
    async def test_interested_event_steps_back_to_proposed_when_empty(self):
        from bot.common.participant_state_reconcile import (
            reconcile_event_state_after_participant_change,
        )

        event = MagicMock()
        event.event_id = 11
        event.state = "interested"
        event.version = 4

        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event
        active_count_result = MagicMock()
        active_count_result.scalar_one.return_value = 0
        confirmed_count_result = MagicMock()
        confirmed_count_result.scalar_one.return_value = 0

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[event_result, active_count_result, confirmed_count_result]
        )

        transitioned_event = MagicMock()
        with patch(
            "bot.common.participant_state_reconcile.EventLifecycleService"
        ) as mock_lifecycle_cls:
            mock_lifecycle = mock_lifecycle_cls.return_value
            mock_lifecycle.transition_with_lifecycle = AsyncMock(
                return_value=(transitioned_event, True)
            )

            result = await reconcile_event_state_after_participant_change(
                session=session,
                bot=MagicMock(),
                event_id=11,
                actor_telegram_user_id=12345,
                source="test",
                reason="state drop",
            )

        assert result is transitioned_event
        assert (
            mock_lifecycle.transition_with_lifecycle.await_args.kwargs["target_state"]
            == "proposed"
        )


class TestEventMaterializationService:
    """Test event materialization service."""

    def test_import_service(self):
        """Test service imports correctly."""
        from bot.services import event_materialization_service

        assert hasattr(event_materialization_service, "EventMaterializationService")


class TestMentionHandler:
    """Test mention-based command handling."""

    def test_import_mention_handler(self):
        """Test mention handler imports correctly."""
        from bot.handlers import mentions

        assert hasattr(mentions, "handle_mention")
        assert hasattr(mentions, "handle_mention_callback")


class TestEventCreation:
    """Test event creation flow."""

    def test_import_event_creation_module(self):
        """Test event creation module imports correctly."""
        from bot.commands.event_creation import start_event_flow_from_prefill

        assert callable(start_event_flow_from_prefill)


class TestScheduling:
    """Test scheduling conflict detection."""

    def test_find_user_event_conflict_no_overlap(self):
        """Test no conflict when events don't overlap."""
        from bot.common.scheduling import events_overlap

        event1_start = datetime(2026, 4, 1, 10, 0)
        event1_duration = 120  # minutes

        event2_start = datetime(2026, 4, 1, 14, 0)  # 2 hours after event1 starts
        event2_duration = 120  # minutes

        # Event1: 10:00-12:00, Event2: 14:00-16:00 - no overlap
        assert not events_overlap(
            event1_start, event1_duration, event2_start, event2_duration
        )

    def test_find_user_event_conflict_with_overlap(self):
        """Test conflict detected when events overlap."""
        from bot.common.scheduling import events_overlap

        event1_start = datetime(2026, 4, 1, 10, 0)
        event1_duration = 120  # minutes (10:00-12:00)

        event2_start = datetime(2026, 4, 1, 11, 0)  # During event1
        event2_duration = 120  # minutes (11:00-13:00)

        assert events_overlap(
            event1_start, event1_duration, event2_start, event2_duration
        )

    def test_find_user_event_conflict_touching_edges(self):
        """Test edge case: events that touch but don't overlap."""
        from bot.common.scheduling import events_overlap

        event1_start = datetime(2026, 4, 1, 10, 0)
        event1_duration = 120  # minutes (10:00-12:00)

        event2_start = datetime(2026, 4, 1, 12, 0)  # Exactly when event1 ends
        event2_duration = 120  # minutes (12:00-14:00)

        # Touching edges should not be a conflict
        assert not events_overlap(
            event1_start, event1_duration, event2_start, event2_duration
        )


class TestParticipantAccess:
    """Test normalized participant helpers."""

    def test_is_attendee_uses_participant_rows(self):
        """Participant presence should come from normalized rows only."""
        from bot.common.event_access import is_attendee
        from tests.fixtures.factories import make_event, make_participant

        event = make_event()
        event.participants = [
            make_participant(event.event_id, 12345),
            make_participant(event.event_id, 67890),
        ]

        assert is_attendee(event, 12345)
        assert not is_attendee(event, 11111)


class TestUserPreferences:
    """Test user preference handling."""

    def test_import_user_preferences_module(self):
        """Test user preferences module imports correctly."""
        from bot.common import user_preferences

        # Verify module has expected attributes
        assert hasattr(user_preferences, "get_user_preferences")
        assert hasattr(user_preferences, "set_preference_private_mode")


class TestDeepLinks:
    """Test Telegram deep link generation."""

    def test_build_start_link(self):
        """Test start link generation."""
        from bot.common.deeplinks import build_start_link

        link = build_start_link("testbot", "avail_123")

        assert link.startswith("https://t.me/testbot?start=")
        assert "avail_123" in link


class TestEventStates:
    """Test event state machine."""

    def test_state_explanations_complete(self):
        """Test all states have explanations."""
        from bot.common.event_states import STATE_EXPLANATIONS, EVENT_STATE_TRANSITIONS

        for state in EVENT_STATE_TRANSITIONS:
            assert state in STATE_EXPLANATIONS, (
                f"Missing explanation for state: {state}"
            )

    def test_valid_states_defined(self):
        """Test expected states are defined."""
        from bot.common.event_states import EVENT_STATE_TRANSITIONS

        expected_states = {
            "proposed",
            "interested",
            "confirmed",
            "locked",
            "completed",
            "cancelled",
        }
        assert expected_states == set(EVENT_STATE_TRANSITIONS.keys())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
