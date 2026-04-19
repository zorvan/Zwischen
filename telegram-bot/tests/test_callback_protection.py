#!/usr/bin/env python3
"""Comprehensive tests for bot/common/callback_protection.py.

This module tests the CallbackProtectionService which prevents:
1. Replay attacks (callbacks processed multiple times)
2. Expired callback execution
3. Cross-user callback abuse (user A clicking user B's callback)

Security-critical: These tests verify protection against common Telegram bot attacks.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


class TestCallbackIdGeneration:
    """Tests for generate_callback_id - signature-based security."""

    def test_generate_callback_id_format(self):
        """Test callback ID has correct format."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        callback_id = service.generate_callback_id("join", 123, 456)
        
        parts = callback_id.split(":")
        assert len(parts) == 5
        assert parts[0] == "join"
        assert parts[1] == "123"
        assert parts[2] == "456"
        # parts[3] is timestamp, parts[4] is signature

    def test_generate_callback_id_signature_unique(self):
        """Test different inputs produce different signatures."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        id1 = service.generate_callback_id("join", 123, 456)
        id2 = service.generate_callback_id("confirm", 123, 456)
        id3 = service.generate_callback_id("join", 124, 456)
        id4 = service.generate_callback_id("join", 123, 457)
        
        all_ids = [id1, id2, id3, id4]
        assert len(set(all_ids)) == 4  # All unique

    def test_generate_callback_id_with_timestamp(self):
        """Test explicit timestamp in callback ID."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        timestamp = datetime(2024, 1, 15, 10, 30, 0)
        
        callback_id = service.generate_callback_id("join", 123, 456, timestamp)
        
        assert "20240115103000" in callback_id


class TestParseCallbackId:
    """Tests for parse_callback_id - signature verification."""

    def test_parse_valid_callback_id(self):
        """Test parsing valid callback ID returns metadata."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        callback_id = service.generate_callback_id("join", 123, 456)
        
        parsed = service.parse_callback_id(callback_id)
        
        assert parsed is not None
        assert parsed["type"] == "join"
        assert parsed["event_id"] == 123
        assert parsed["user_id"] == 456
        assert parsed["is_valid"] is True
        assert "timestamp" in parsed

    def test_parse_invalid_format(self):
        """Test parsing malformed callback ID returns None."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        parsed = service.parse_callback_id("invalid_format")
        assert parsed is None

    def test_parse_wrong_number_of_parts(self):
        """Test parsing callback ID with wrong number of colons."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        parsed = service.parse_callback_id("join:123:456:timestamp")
        assert parsed is None

    def test_parse_tampered_callback_id(self):
        """Test tampered callback ID fails signature verification."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        callback_id = service.generate_callback_id("join", 123, 456)
        
        # Tamper with the callback ID
        parts = callback_id.split(":")
        parts[1] = "999"  # Change event_id
        tampered_id = ":".join(parts)
        
        parsed = service.parse_callback_id(tampered_id)
        assert parsed is None  # Signature mismatch

    def test_parse_invalid_timestamp(self):
        """Test callback ID with invalid timestamp returns None."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        callback_id = "join:123:456:invalid_time:signature"
        
        parsed = service.parse_callback_id(callback_id)
        assert parsed is None

    def test_parse_non_numeric_ids(self):
        """Test callback ID with non-numeric IDs returns None."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        callback_id = "join:abc:def:20240115103000:signature"
        
        parsed = service.parse_callback_id(callback_id)
        assert parsed is None


class TestExpiryTimeCalculation:
    """Tests for get_expiry_time - different expiry for different actions."""

    def test_expiry_event_actions(self):
        """Test join/confirm/back actions have 60 min expiry."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        assert service.get_expiry_time("join") == 60
        assert service.get_expiry_time("confirm") == 60
        assert service.get_expiry_time("back") == 60
        assert service.get_expiry_time("unconfirm") == 60
        assert service.get_expiry_time("cancel") == 60

    def test_expiry_navigation(self):
        """Test navigation actions have 30 min expiry."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        assert service.get_expiry_time("details") == 30
        assert service.get_expiry_time("logs") == 30
        assert service.get_expiry_time("status") == 30
        assert service.get_expiry_time("constraints") == 30

    def test_expiry_creation(self):
        """Test creation actions have 300 min expiry."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        assert service.get_expiry_time("event_create") == 300
        assert service.get_expiry_time("event_type_select") == 300
        assert service.get_expiry_time("private_event_create") == 300

    def test_expiry_modification(self):
        """Test modification actions have 120 min expiry."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        assert service.get_expiry_time("modreq") == 120
        assert service.get_expiry_time("mentionact") == 120

    def test_expiry_default(self):
        """Test unknown actions default to 60 min."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        assert service.get_expiry_time("unknown_action") == 60


class TestIsExpired:
    """Tests for is_expired - time-based protection."""

    def test_not_expired_recent_callback(self):
        """Test recent callback is not expired."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        timestamp = datetime.utcnow() - timedelta(minutes=30)
        callback_id = service.generate_callback_id("join", 123, 456, timestamp)
        
        assert service.is_expired(callback_id) is False

    def test_expired_old_callback(self):
        """Test old callback is expired."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        timestamp = datetime.utcnow() - timedelta(minutes=61)  # > 60 min
        callback_id = service.generate_callback_id("join", 123, 456, timestamp)
        
        assert service.is_expired(callback_id) is True

    def test_expired_navigation_callback(self):
        """Test navigation callback expires after 30 min."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        timestamp = datetime.utcnow() - timedelta(minutes=31)
        callback_id = service.generate_callback_id("details", 123, 456, timestamp)
        
        assert service.is_expired(callback_id) is True

    def test_expired_invalid_callback(self):
        """Test invalid callback is considered expired."""
        from bot.common.callback_protection import CallbackProtectionService
        
        service = CallbackProtectionService(None)
        
        assert service.is_expired("invalid_format") is True


class TestCheckOwnership:
    """Tests for check_ownership - prevents cross-user callback abuse."""

    @pytest.fixture
    def service(self):
        """Create a CallbackProtectionService instance."""
        from bot.common.callback_protection import CallbackProtectionService
        return CallbackProtectionService(None)

    @pytest.mark.asyncio
    async def test_ownership_match(self, service):
        """Test correct user passes ownership check."""
        callback_id = service.generate_callback_id("join", 123, 456)
        
        is_owner, error = await service.check_ownership(callback_id, 456)
        
        assert is_owner is True
        assert error is None

    @pytest.mark.asyncio
    async def test_ownership_mismatch(self, service):
        """Test wrong user fails ownership check."""
        callback_id = service.generate_callback_id("join", 123, 456)
        
        is_owner, error = await service.check_ownership(callback_id, 999)
        
        assert is_owner is False
        assert error is not None
        assert "User 456" in error
        assert "invitation" in error.lower()

    @pytest.mark.asyncio
    async def test_ownership_invalid_callback(self, service):
        """Test invalid callback fails ownership check."""
        is_owner, error = await service.check_ownership("invalid", 456)
        
        assert is_owner is False
        assert "Invalid callback format" in error


class TestValidateCallback:
    """Tests for validate_callback - full validation."""

    @pytest.fixture
    def service(self):
        """Create a CallbackProtectionService instance."""
        from bot.common.callback_protection import CallbackProtectionService
        return CallbackProtectionService(None)

    @pytest.mark.asyncio
    async def test_valid_callback(self, service):
        """Test fully valid callback passes all checks."""
        callback_id = service.generate_callback_id("join", 123, 456)
        
        is_valid, error, parsed = await service.validate_callback(callback_id, 456)
        
        assert is_valid is True
        assert error is None
        assert parsed is not None
        assert parsed["event_id"] == 123

    @pytest.mark.asyncio
    async def test_invalid_format(self, service):
        """Test invalid format fails validation."""
        is_valid, error, parsed = await service.validate_callback("bad", 456)
        
        assert is_valid is False
        assert "Invalid callback format" in error
        assert parsed is None

    @pytest.mark.asyncio
    async def test_expired_callback(self, service):
        """Test expired callback fails validation."""
        timestamp = datetime.utcnow() - timedelta(hours=2)
        callback_id = service.generate_callback_id("join", 123, 456, timestamp)
        
        is_valid, error, parsed = await service.validate_callback(callback_id, 456)
        
        assert is_valid is False
        assert "expired" in error.lower()
        assert parsed is not None  # Still returns parsed data

    @pytest.mark.asyncio
    async def test_wrong_user(self, service):
        """Test callback clicked by wrong user fails validation."""
        callback_id = service.generate_callback_id("join", 123, 456)
        
        is_valid, error, parsed = await service.validate_callback(callback_id, 999)
        
        assert is_valid is False
        assert "intended for User 456" in error
        assert parsed is not None


class TestIdempotency:
    """Tests for idempotency tracking - prevents duplicate processing."""

    @pytest.fixture
    def service(self):
        """Create a CallbackProtectionService instance."""
        from bot.common.callback_protection import CallbackProtectionService
        return CallbackProtectionService(None)

    def test_register_callback(self, service):
        """Test registering callback marks it as processed."""
        callback_id = service.generate_callback_id("join", 123, 456)
        
        service.register_callback(callback_id, {"event_id": 123})
        
        assert callback_id in service._callback_cache

    def test_is_processed_true(self, service):
        """Test is_processed returns True for recent callback."""
        callback_id = service.generate_callback_id("join", 123, 456)
        service.register_callback(callback_id, {})
        
        assert service.is_processed(callback_id) is True

    def test_is_processed_false(self, service):
        """Test is_processed returns False for unprocessed callback."""
        callback_id = service.generate_callback_id("join", 123, 456)
        
        assert service.is_processed(callback_id) is False

    def test_is_processed_expired_cache_entry(self, service):
        """Test old cache entries are cleaned up."""
        callback_id = "join:123:456:20240101000000:abc123"
        
        # Manually add old entry
        service._callback_cache[callback_id] = {
            "processed_at": datetime.utcnow() - timedelta(hours=2),
            "metadata": {},
        }
        
        # Should be treated as not processed (expired from cache)
        assert service.is_processed(callback_id) is False
        assert callback_id not in service._callback_cache

    def test_cleanup_cache(self, service):
        """Test cleanup_cache removes old entries."""
        # Add some entries
        for i in range(5):
            callback_id = f"join:123:{i}:20240101000000:abc{i}"
            service._callback_cache[callback_id] = {
                "processed_at": datetime.utcnow() - timedelta(hours=2),
                "metadata": {},
            }
        
        # Add one recent entry
        recent_id = "join:123:999:20240101000000:abc999"
        service._callback_cache[recent_id] = {
            "processed_at": datetime.utcnow(),
            "metadata": {},
        }
        
        removed = service.cleanup_cache()
        
        assert removed == 5
        assert len(service._callback_cache) == 1
        assert recent_id in service._callback_cache


class TestBuildProtectedCallback:
    """Tests for build_protected_callback convenience function."""

    def test_build_protected_callback(self):
        """Test convenience function creates protected callback."""
        from bot.common.callback_protection import build_protected_callback
        
        callback = build_protected_callback("confirm", 123, 456)
        
        assert callback.startswith("confirm:123:456:")
        # Should have timestamp and signature
        parts = callback.split(":")
        assert len(parts) == 5


class TestValidateEventCallback:
    """Tests for validate_event_callback convenience function."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_validate_event_callback_valid(self, mock_session):
        """Test valid event callback passes."""
        from bot.common.callback_protection import (
            validate_event_callback, 
            CallbackProtectionService
        )
        from db.models import EventParticipant
        
        # Create a valid callback
        protection = CallbackProtectionService(None)
        callback_id = protection.generate_callback_id("confirm", 123, 456)
        
        # Mock participant exists
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = EventParticipant(
            event_id=123,
            telegram_user_id=456,
        )
        mock_session.execute.return_value = mock_result

        is_valid, error = await validate_event_callback(
            mock_session, callback_id, 456, 123
        )
        
        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_event_callback_invalid_format(self, mock_session):
        """Test invalid format fails."""
        from bot.common.callback_protection import validate_event_callback
        
        is_valid, error = await validate_event_callback(
            mock_session, "invalid", 456, 123
        )
        
        assert is_valid is False
        assert "Invalid callback format" in error

    @pytest.mark.asyncio
    async def test_validate_event_callback_not_participant(self, mock_session):
        """Test action callbacks require participant status."""
        from bot.common.callback_protection import (
            validate_event_callback,
            CallbackProtectionService
        )
        
        # Create a valid callback for an action that requires participant status
        protection = CallbackProtectionService(None)
        callback_id = protection.generate_callback_id("confirm", 123, 456)
        
        # Mock participant NOT found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        is_valid, error = await validate_event_callback(
            mock_session, callback_id, 456, 123
        )
        
        assert is_valid is False
        assert "must join" in error.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
