#!/usr/bin/env python3
"""Tests for bot/services/live_card_service.py.

This module tests the v3.5 Live Card service for posting and managing
event cards in group chats.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, ANY


class TestLiveCardService:
    """Tests for LiveCardService class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock Telegram bot."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot.edit_message_text = AsyncMock()
        return bot

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a LiveCardService instance."""
        from bot.services.live_card_service import LiveCardService
        return LiveCardService(mock_session, mock_bot)

    def test_service_init(self, service, mock_session, mock_bot):
        """Test service initialization."""
        assert service.session is mock_session
        assert service.bot is mock_bot


class TestCreateLiveCard:
    """Tests for create_live_card method."""

    @pytest.mark.asyncio
    async def test_create_new_card_success(self):
        """Test successfully creating a new live card."""
        from bot.services.live_card_service import LiveCardService
        from db.models import EventLiveCard
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=12345))
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock no existing card
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        
        card = await service.create_live_card(
            event_id=1,
            chat_id=-100123456789,
            text="📅 *Test Event*\n\nDetails here...",
            reply_markup=MagicMock(),
        )
        
        assert isinstance(card, EventLiveCard)
        assert card.event_id == 1
        assert card.chat_id == -100123456789
        assert card.message_id == 12345
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_existing_card(self):
        """Test updating an existing live card."""
        from bot.services.live_card_service import LiveCardService
        from db.models import EventLiveCard
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        mock_bot.edit_message_text = AsyncMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock existing card
        existing_card = EventLiveCard(
            id=1,
            event_id=1,
            chat_id=-100123456789,
            message_id=12345,
            participant_count=0,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_card
        mock_session.execute.return_value = mock_result
        
        card = await service.create_live_card(
            event_id=1,
            chat_id=-100123456789,
            text="Updated text",
            reply_markup=MagicMock(),
        )
        
        assert card is existing_card
        mock_bot.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_respects_group_setting_disabled(self):
        """Test that live cards are not created when group setting is disabled."""
        from bot.services.live_card_service import LiveCardService
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock group settings with live cards disabled
        from db.models import GroupSettings
        settings = GroupSettings(group_id=1, enable_live_cards=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = settings
        mock_session.execute.return_value = mock_result
        
        result = await service.create_live_card(
            event_id=1,
            chat_id=-100123456789,
            text="Test",
            reply_markup=MagicMock(),
        )
        
        assert result is None
        mock_bot.send_message.assert_not_called()


class TestUpdateLiveCard:
    """Tests for update_live_card method."""

    @pytest.mark.asyncio
    async def test_update_success(self):
        """Test successfully updating card content."""
        from bot.services.live_card_service import LiveCardService
        from db.models import EventLiveCard
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        mock_bot.edit_message_text = AsyncMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock existing card
        existing_card = EventLiveCard(
            id=1,
            event_id=1,
            chat_id=-100123456789,
            message_id=12345,
            participant_count=1,
            confirmed_count=0,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_card
        mock_session.execute.return_value = mock_result
        
        success = await service.update_live_card(
            event_id=1,
            text="Updated text",
            participant_count=2,
            confirmed_count=1,
        )
        
        assert success is True
        assert existing_card.participant_count == 2
        assert existing_card.confirmed_count == 1
        mock_bot.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_no_card_exists(self):
        """Test update returns False when no card exists."""
        from bot.services.live_card_service import LiveCardService
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock no existing card
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        
        success = await service.update_live_card(
            event_id=1,
            text="Updated text",
        )
        
        assert success is False
        mock_bot.edit_message_text.assert_not_called()


class TestRecordReaction:
    """Tests for record_reaction method."""

    @pytest.mark.asyncio
    async def test_record_new_reaction(self):
        """Test recording a new reaction."""
        from bot.services.live_card_service import LiveCardService
        from db.models import EventLiveCard
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock existing card with empty reactions
        existing_card = EventLiveCard(
            id=1,
            event_id=1,
            chat_id=-100123456789,
            message_id=12345,
            reaction_counts={},
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_card
        mock_session.execute.return_value = mock_result
        
        await service.record_reaction(event_id=1, emoji="👍")
        
        assert existing_card.reaction_counts["👍"] == 1

    @pytest.mark.asyncio
    async def test_increment_existing_reaction(self):
        """Test incrementing an existing reaction."""
        from bot.services.live_card_service import LiveCardService
        from db.models import EventLiveCard
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock existing card with reactions
        existing_card = EventLiveCard(
            id=1,
            event_id=1,
            chat_id=-100123456789,
            message_id=12345,
            reaction_counts={"👍": 5, "👎": 1},
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_card
        mock_session.execute.return_value = mock_result
        
        await service.record_reaction(event_id=1, emoji="👍")
        
        assert existing_card.reaction_counts["👍"] == 6


class TestBuildCardText:
    """Tests for _build_card_text helper method."""

    def test_build_card_includes_event_details(self):
        """Test that card text includes event details."""
        from bot.services.live_card_service import LiveCardService
        
        event = MagicMock()
        event.event_id = 1
        event.event_type = "social"
        event.description = "Test event"
        event.state = "proposed"
        
        text = LiveCardService._build_card_text(event, participant_count=3, confirmed_count=1)
        
        assert "Test event" in text or "social" in text

    def test_build_card_shows_gravity_signals(self):
        """Test that card shows gravity signals (counts, hashtags)."""
        from bot.services.live_card_service import LiveCardService
        
        event = MagicMock()
        event.event_id = 1
        event.event_type = "hiking"
        event.description = "Mountain hike"
        event.state = "proposed"
        
        hashtags = ["#hiking", "#weekend"]
        text = LiveCardService._build_card_text(
            event,
            participant_count=5,
            confirmed_count=3,
            hashtags=hashtags
        )
        
        assert "5" in text or "3" in text  # Counts shown


class TestGetCardStatus:
    """Tests for get_card_status method."""

    @pytest.mark.asyncio
    async def test_get_card_status_existing(self):
        """Test getting status of an existing card."""
        from bot.services.live_card_service import LiveCardService
        from db.models import EventLiveCard
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock existing card
        existing_card = EventLiveCard(
            id=1,
            event_id=1,
            chat_id=-100123456789,
            message_id=12345,
            participant_count=3,
            confirmed_count=2,
            reaction_counts={"👍": 5},
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_card
        mock_session.execute.return_value = mock_result
        
        status = await service.get_card_status(event_id=1)
        
        assert status is not None
        assert status["message_id"] == 12345
        assert status["participant_count"] == 3
        assert status["confirmed_count"] == 2
        assert status["reactions"]["👍"] == 5

    @pytest.mark.asyncio
    async def test_get_card_status_none(self):
        """Test getting status when no card exists."""
        from bot.services.live_card_service import LiveCardService
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_bot = MagicMock()
        
        service = LiveCardService(mock_session, mock_bot)
        
        # Mock no existing card
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        
        status = await service.get_card_status(event_id=1)
        
        assert status is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
