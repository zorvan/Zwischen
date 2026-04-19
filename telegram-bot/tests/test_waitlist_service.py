#!/usr/bin/env python3
"""Comprehensive tests for bot/services/waitlist_service.py.

This module tests the WaitlistService which manages FIFO waitlists with
time-scaled response windows.

Critical areas tested:
- FIFO ordering (by added_at, not position integer)
- Time-scaled response windows (>24h=2h, <24h=30m, <2h=15m)
- Auto-fill flow: cancel -> offer -> accept/decline/expire -> next
- Offer expiration and sweeping
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from db.models import EventWaitlist, EventParticipant, Event


class TestComputeOfferDuration:
    """Tests for _compute_offer_duration helper - time-scaled windows."""

    def test_offer_duration_no_time_set(self):
        """Default 2 hours when no scheduled time."""
        from bot.services.waitlist_service import _compute_offer_duration
        
        duration = _compute_offer_duration(None)
        assert duration == 120  # 2 hours

    def test_offer_duration_far_future(self):
        """2 hours when event is >24h away."""
        from bot.services.waitlist_service import _compute_offer_duration
        
        future = datetime.utcnow() + timedelta(hours=25)
        duration = _compute_offer_duration(future)
        assert duration == 120  # 2 hours

    def test_offer_duration_within_24h(self):
        """30 minutes when event is <24h away."""
        from bot.services.waitlist_service import _compute_offer_duration
        
        future = datetime.utcnow() + timedelta(hours=12)
        duration = _compute_offer_duration(future)
        assert duration == 30  # 30 minutes

    def test_offer_duration_within_2h(self):
        """15 minutes when event is <2h away."""
        from bot.services.waitlist_service import _compute_offer_duration
        
        future = datetime.utcnow() + timedelta(minutes=90)
        duration = _compute_offer_duration(future)
        assert duration == 15  # 15 minutes

    def test_offer_duration_past_event(self):
        """15 minutes when event is in the past (edge case)."""
        from bot.services.waitlist_service import _compute_offer_duration
        
        past = datetime.utcnow() - timedelta(hours=1)
        duration = _compute_offer_duration(past)
        assert duration == 15  # Minimum window


class TestWaitlistServiceInit:
    """Tests for service initialization."""

    def test_service_init(self):
        """Test service stores session and bot."""
        from bot.services.waitlist_service import WaitlistService
        
        mock_session = MagicMock()
        mock_bot = MagicMock()
        
        service = WaitlistService(mock_session, mock_bot)
        
        assert service.session is mock_session
        assert service.bot is mock_bot


class TestAddToWaitlist:
    """Tests for add_to_waitlist - FIFO ordering critical."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_add_new_user(self, service, mock_session):
        """Test adding user to waitlist."""
        # Mock no existing participant
        mock_participant_result = MagicMock()
        mock_participant_result.scalar_one_or_none.return_value = None
        
        # Mock no existing waitlist entry
        mock_waitlist_result = MagicMock()
        mock_waitlist_result.scalar_one_or_none.return_value = None
        
        # Mock _get_waiting in get_waitlist_position (called first)
        mock_get_waiting_result = MagicMock()
        mock_get_waiting_result.scalar_one_or_none.return_value = None  # Not found = new entry
        
        # Mock count query in get_waitlist_position
        mock_position_result = MagicMock()
        mock_position_result.scalar_one.return_value = 1
        
        mock_session.execute.side_effect = [
            mock_participant_result,
            mock_waitlist_result,
            mock_get_waiting_result,  # _get_waiting call
            mock_position_result,      # count query
        ]

        position = await service.add_to_waitlist(event_id=1, telegram_user_id=12345)

        assert position == 1
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_already_participant_raises(self, service, mock_session):
        """Test adding user who is already a participant raises error."""
        existing_participant = EventParticipant(
            event_id=1,
            telegram_user_id=12345,
            status=EventParticipant.status.property.enum_class.joined,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_participant
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError) as exc_info:
            await service.add_to_waitlist(event_id=1, telegram_user_id=12345)
        
        assert "already a participant" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_add_already_on_waitlist_raises(self, service, mock_session):
        """Test adding user already on waitlist raises error."""
        existing_entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="waiting",
        )
        
        # First call checks participant (None), second checks waitlist (found)
        mock_participant_result = MagicMock()
        mock_participant_result.scalar_one_or_none.return_value = None
        
        mock_waitlist_result = MagicMock()
        mock_waitlist_result.scalar_one_or_none.return_value = existing_entry
        
        mock_session.execute.side_effect = [
            mock_participant_result,
            mock_waitlist_result,
        ]

        with pytest.raises(ValueError) as exc_info:
            await service.add_to_waitlist(event_id=1, telegram_user_id=12345)
        
        assert "already on the waitlist" in str(exc_info.value).lower()


class TestLeaveWaitlist:
    """Tests for leave_waitlist."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.delete = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_leave_success(self, service, mock_session):
        """Test leaving waitlist successfully."""
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="waiting",
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry
        mock_session.execute.return_value = mock_result

        result = await service.leave_waitlist(event_id=1, telegram_user_id=12345)

        assert result is True
        mock_session.delete.assert_called_once_with(entry)

    @pytest.mark.asyncio
    async def test_leave_not_on_waitlist(self, service, mock_session):
        """Test leaving when not on waitlist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.leave_waitlist(event_id=1, telegram_user_id=12345)

        assert result is False
        mock_session.delete.assert_not_called()


class TestGetNextWaitlisted:
    """Tests for get_next_waitlisted - FIFO ordering."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_get_next_returns_first_waiting(self, service, mock_session):
        """Test FIFO - returns earliest added_at entry."""
        earliest = EventWaitlist(
            event_id=1,
            telegram_user_id=111,
            status="waiting",
            added_at=datetime.utcnow() - timedelta(hours=2),
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = earliest
        mock_session.execute.return_value = mock_result

        result = await service.get_next_waitlisted(event_id=1)

        assert result is earliest
        assert result.telegram_user_id == 111

    @pytest.mark.asyncio
    async def test_get_next_none_waiting(self, service, mock_session):
        """Test no entries waiting."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.get_next_waitlisted(event_id=1)

        assert result is None


class TestOfferSpot:
    """Tests for offer_spot - time-scaled windows."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_offer_spot_with_explicit_duration(self, service, mock_session, mock_bot):
        """Test offering spot with explicit duration."""
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="waiting",
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry
        mock_session.execute.return_value = mock_result

        result = await service.offer_spot(
            event_id=1, 
            telegram_user_id=12345, 
            expires_in_minutes=60
        )

        assert result is entry
        assert result.status == "offered"
        assert result.expires_at is not None
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_offer_spot_with_time_scaled_duration(self, service, mock_session, mock_bot):
        """Test offering spot with time-scaled duration based on event time."""
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="waiting",
        )
        
        event = MagicMock()
        event.scheduled_time = datetime.utcnow() + timedelta(hours=12)  # <24h = 30min
        
        mock_waitlist_result = MagicMock()
        mock_waitlist_result.scalar_one_or_none.return_value = entry
        
        mock_event_result = MagicMock()
        mock_event_result.scalar_one_or_none.return_value = event
        
        mock_session.execute.side_effect = [
            mock_waitlist_result,  # _get_waiting
            mock_event_result,     # event query for duration
        ]

        result = await service.offer_spot(event_id=1, telegram_user_id=12345)

        assert result is entry
        assert result.status == "offered"
        # Duration should be 30 minutes (<24h to event)

    @pytest.mark.asyncio
    async def test_offer_spot_not_waiting(self, service, mock_session, mock_bot):
        """Test offering spot to user not in waiting status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.offer_spot(event_id=1, telegram_user_id=12345)

        assert result is None
        mock_bot.send_message.assert_not_called()


class TestAcceptOffer:
    """Tests for accept_offer - full auto-fill flow."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.delete = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_accept_valid_offer(self, service, mock_session, mock_bot):
        """Test accepting a valid offer."""
        from db.models import ParticipantStatus
        
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="offered",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry
        mock_session.execute.return_value = mock_result

        with patch('bot.services.waitlist_service.ParticipantService') as MockParticipantService:
            mock_participant_service = AsyncMock()
            mock_participant_service.join.return_value = (MagicMock(), True)
            mock_participant_service.confirm.return_value = (MagicMock(), True)
            MockParticipantService.return_value = mock_participant_service

            result = await service.accept_offer(event_id=1, telegram_user_id=12345)

            assert result is True
            mock_participant_service.join.assert_called_once_with(1, 12345, source="waitlist")
            mock_participant_service.confirm.assert_called_once_with(1, 12345, source="waitlist")
            mock_session.delete.assert_called_once_with(entry)

    @pytest.mark.asyncio
    async def test_accept_expired_offer(self, service, mock_session, mock_bot):
        """Test accepting expired offer fails and triggers expiration."""
        from db.models import ParticipantStatus
        
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="offered",
            expires_at=datetime.utcnow() - timedelta(minutes=1),  # Expired
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry
        mock_session.execute.return_value = mock_result

        # Mock expire_offer to verify it's called
        with patch.object(service, 'expire_offer', new_callable=AsyncMock) as mock_expire:
            result = await service.accept_offer(event_id=1, telegram_user_id=12345)

            assert result is False
            mock_expire.assert_called_once_with(1, 12345)

    @pytest.mark.asyncio
    async def test_accept_not_offered(self, service, mock_session):
        """Test accepting when not in offered status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.accept_offer(event_id=1, telegram_user_id=12345)

        assert result is False


class TestDeclineOffer:
    """Tests for decline_offer - triggers auto-fill."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_decline_valid_offer(self, service, mock_session):
        """Test declining an offer marks as cancelled and auto-fills."""
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="offered",
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry
        mock_session.execute.return_value = mock_result

        with patch.object(service, '_auto_fill_next', new_callable=AsyncMock) as mock_autofill:
            result = await service.decline_offer(event_id=1, telegram_user_id=12345)

            assert result is True
            assert entry.status == "cancelled"
            mock_autofill.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_decline_not_offered(self, service, mock_session):
        """Test declining when not in offered status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.decline_offer(event_id=1, telegram_user_id=12345)

        assert result is False


class TestExpireOffer:
    """Tests for expire_offer - triggers auto-fill."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_expire_valid_offer(self, service, mock_session):
        """Test expiring an offer marks as expired and auto-fills."""
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="offered",
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry
        mock_session.execute.return_value = mock_result

        with patch.object(service, '_auto_fill_next', new_callable=AsyncMock) as mock_autofill:
            result = await service.expire_offer(event_id=1, telegram_user_id=12345)

            assert result is True
            assert entry.status == "expired"
            mock_autofill.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_expire_not_offered(self, service, mock_session):
        """Test expiring when not in offered status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.expire_offer(event_id=1, telegram_user_id=12345)

        assert result is False


class TestQueryMethods:
    """Tests for query methods."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_get_waitlist_position(self, service, mock_session):
        """Test getting position in waitlist."""
        entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="waiting",
            added_at=datetime.utcnow(),
        )
        
        mock_entry_result = MagicMock()
        mock_entry_result.scalar_one_or_none.return_value = entry
        
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 3  # 3rd in line
        
        mock_session.execute.side_effect = [
            mock_entry_result,
            mock_count_result,
        ]

        position = await service.get_waitlist_position(event_id=1, telegram_user_id=12345)

        assert position == 3

    @pytest.mark.asyncio
    async def test_get_waitlist_position_not_on_list(self, service, mock_session):
        """Test getting position when not on waitlist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        position = await service.get_waitlist_position(event_id=1, telegram_user_id=12345)

        assert position is None

    @pytest.mark.asyncio
    async def test_get_waitlist_count(self, service, mock_session):
        """Test getting count of waiting users."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 5
        mock_session.execute.return_value = mock_result

        count = await service.get_waitlist_count(event_id=1)

        assert count == 5

    @pytest.mark.asyncio
    async def test_get_waitlist(self, service, mock_session):
        """Test getting full waitlist ordered by added_at."""
        entries = [
            EventWaitlist(event_id=1, telegram_user_id=1, status="waiting"),
            EventWaitlist(event_id=1, telegram_user_id=2, status="offered"),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = entries
        mock_session.execute.return_value = mock_result

        result = await service.get_waitlist(event_id=1)

        assert len(result) == 2
        # Both waiting and offered should be included


class TestAutoFill:
    """Tests for auto-fill orchestration."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_trigger_auto_fill_offers_next(self, service, mock_session, mock_bot):
        """Test trigger_auto_fill offers spot to next in line."""
        next_entry = EventWaitlist(
            event_id=1,
            telegram_user_id=99999,
            status="waiting",
        )
        
        event = MagicMock()
        event.scheduled_time = datetime.utcnow() + timedelta(days=2)
        
        mock_next_result = MagicMock()
        mock_next_result.scalar_one_or_none.return_value = next_entry
        
        mock_event_result = MagicMock()
        mock_event_result.scalar_one_or_none.return_value = event
        
        mock_waitlist_result = MagicMock()
        mock_waitlist_result.scalar_one_or_none.return_value = next_entry
        
        mock_session.execute.side_effect = [
            mock_next_result,      # get_next_waitlisted
            mock_event_result,     # event query for duration
            mock_waitlist_result,  # _get_waiting in offer_spot
        ]

        await service.trigger_auto_fill(event_id=1)

        assert next_entry.status == "offered"
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_auto_fill_no_one_waiting(self, service, mock_session):
        """Test trigger_auto_fill when no one is waiting."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        await service.trigger_auto_fill(event_id=1)

        # Should complete without error, no offers sent


class TestSweepExpiredOffers:
    """Tests for sweep_expired_offers - periodic job."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def service(self, mock_session, mock_bot):
        """Create a WaitlistService instance."""
        from bot.services.waitlist_service import WaitlistService
        return WaitlistService(mock_session, mock_bot)

    @pytest.mark.asyncio
    async def test_sweep_expired_offers(self, service, mock_session):
        """Test sweeping expired offers marks them and auto-fills."""
        expired_entry = EventWaitlist(
            event_id=1,
            telegram_user_id=12345,
            status="offered",
            expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [expired_entry]
        mock_session.execute.return_value = mock_result

        with patch.object(service, '_auto_fill_next', new_callable=AsyncMock) as mock_autofill:
            swept = await service.sweep_expired_offers()

            assert swept == 1
            assert expired_entry.status == "expired"
            mock_autofill.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_sweep_no_expired_offers(self, service, mock_session):
        """Test sweeping when no offers have expired."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        swept = await service.sweep_expired_offers()

        assert swept == 0

    @pytest.mark.asyncio
    async def test_sweep_for_specific_event(self, service, mock_session):
        """Test sweeping for a specific event only."""
        expired_entry = EventWaitlist(
            event_id=5,
            telegram_user_id=12345,
            status="offered",
            expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [expired_entry]
        mock_session.execute.return_value = mock_result

        with patch.object(service, '_auto_fill_next', new_callable=AsyncMock):
            swept = await service.sweep_expired_offers(event_id=5)

            assert swept == 1


class TestDisplayName:
    """Tests for _display_name helper."""

    def test_display_name_with_display_name(self):
        """Test using display_name when available."""
        from bot.services.waitlist_service import WaitlistService
        
        user = MagicMock()
        user.display_name = "John Doe"
        user.username = "johndoe"
        
        result = WaitlistService._display_name(user, 12345)
        assert result == "John Doe"

    def test_display_name_with_username(self):
        """Test using username when no display_name."""
        from bot.services.waitlist_service import WaitlistService
        
        user = MagicMock()
        user.display_name = None
        user.username = "johndoe"
        
        result = WaitlistService._display_name(user, 12345)
        assert result == "@johndoe"

    def test_display_name_fallback_to_id(self):
        """Test fallback to user ID when no name info."""
        from bot.services.waitlist_service import WaitlistService
        
        user = MagicMock()
        user.display_name = None
        user.username = None
        
        result = WaitlistService._display_name(user, 12345)
        assert result == "User #12345"

    def test_display_name_no_user(self):
        """Test fallback when no user record."""
        from bot.services.waitlist_service import WaitlistService
        
        result = WaitlistService._display_name(None, 12345)
        assert result == "User #12345"


class TestFormatExpiry:
    """Tests for _format_expiry helper."""

    def test_format_expiry_minutes(self):
        """Test formatting minutes only."""
        from bot.services.waitlist_service import WaitlistService
        
        result = WaitlistService._format_expiry(30)
        assert result == "30 minutes"

    def test_format_expiry_hours(self):
        """Test formatting whole hours."""
        from bot.services.waitlist_service import WaitlistService
        
        result = WaitlistService._format_expiry(120)
        assert result == "2 hours"

    def test_format_expiry_hours_and_minutes(self):
        """Test formatting hours and minutes."""
        from bot.services.waitlist_service import WaitlistService
        
        result = WaitlistService._format_expiry(90)
        assert result == "1h 30m"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
