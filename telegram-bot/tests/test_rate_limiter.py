#!/usr/bin/env python3
"""Comprehensive tests for bot/common/rate_limiter.py.

This module tests the RateLimiter which prevents abuse and spam through
sliding window rate limiting.

Critical areas tested:
- Per-user rate limits
- Per-group rate limits  
- Sliding window algorithm
- Different limits per action type
- Rate limit exception handling
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


class TestRateLimiterInit:
    """Tests for rate limiter initialization."""

    def test_rate_limiter_init(self):
        """Test rate limiter initializes with empty state."""
        from bot.common.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        
        assert limiter._requests == {}
        assert limiter.DEFAULT_LIMIT == 10
        assert limiter.DEFAULT_WINDOW_SECONDS == 60

    def test_action_limits_configured(self):
        """Test specific action limits are configured."""
        from bot.common.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        
        assert "message" in limiter.ACTION_LIMITS
        assert "command" in limiter.ACTION_LIMITS
        assert "callback" in limiter.ACTION_LIMITS
        assert "event_creation" in limiter.ACTION_LIMITS
        assert "mention" in limiter.ACTION_LIMITS
        assert "dm" in limiter.ACTION_LIMITS


class TestKeyGeneration:
    """Tests for rate limit key generation."""

    def test_key_user_only(self):
        """Test key for user-only request."""
        from bot.common.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        key = limiter._get_key(user_id=12345, group_id=None, action_type="message")
        
        assert key == "user:12345:message"

    def test_key_group_only(self):
        """Test key for group-only request."""
        from bot.common.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        key = limiter._get_key(user_id=None, group_id=-100123456, action_type="command")
        
        assert key == "group:-100123456:command"

    def test_key_global(self):
        """Test key for global request (no user/group)."""
        from bot.common.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        key = limiter._get_key(user_id=None, group_id=None, action_type="message")
        
        assert key == "global:message"

    def test_key_group_takes_precedence(self):
        """Test that group_id takes precedence over user_id."""
        from bot.common.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        key = limiter._get_key(user_id=12345, group_id=-100123456, action_type="message")
        
        # Should use group key, not user key
        assert key.startswith("group:")


class TestCheckRateLimit:
    """Tests for check_rate_limit - core rate limiting logic."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh RateLimiter instance."""
        from bot.common.rate_limiter import RateLimiter
        return RateLimiter()

    def test_first_request_allowed(self, limiter):
        """Test first request is always allowed."""
        is_allowed, retry_after = limiter.check_rate_limit(
            user_id=12345, action_type="message"
        )
        
        assert is_allowed is True
        assert retry_after is None

    def test_requests_within_limit_allowed(self, limiter):
        """Test requests within limit are allowed."""
        # Make 5 requests (under the 20 message limit)
        for _ in range(5):
            limiter.record_request(user_id=12345, action_type="message")
        
        is_allowed, retry_after = limiter.check_rate_limit(
            user_id=12345, action_type="message"
        )
        
        assert is_allowed is True
        assert retry_after is None

    def test_limit_exceeded_blocked(self, limiter):
        """Test requests over limit are blocked."""
        # Make 20 requests (at the message limit)
        for _ in range(20):
            limiter.record_request(user_id=12345, action_type="message")
        
        is_allowed, retry_after = limiter.check_rate_limit(
            user_id=12345, action_type="message"
        )
        
        assert is_allowed is False
        assert retry_after is not None
        assert retry_after > 0

    def test_different_users_separate_limits(self, limiter):
        """Test different users have separate rate limits."""
        # User 1 hits their limit
        for _ in range(20):
            limiter.record_request(user_id=1, action_type="message")
        
        # User 1 is blocked
        is_allowed, _ = limiter.check_rate_limit(user_id=1, action_type="message")
        assert is_allowed is False
        
        # User 2 is not affected
        is_allowed, _ = limiter.check_rate_limit(user_id=2, action_type="message")
        assert is_allowed is True

    def test_different_actions_separate_limits(self, limiter):
        """Test different action types have separate limits."""
        # Hit message limit
        for _ in range(20):
            limiter.record_request(user_id=12345, action_type="message")
        
        # Messages blocked
        is_allowed, _ = limiter.check_rate_limit(
            user_id=12345, action_type="message"
        )
        assert is_allowed is False
        
        # Commands still allowed (separate limit)
        is_allowed, _ = limiter.check_rate_limit(
            user_id=12345, action_type="command"
        )
        assert is_allowed is True

    def test_event_creation_stricter_limit(self, limiter):
        """Test event creation has stricter limits (5 per 5 min)."""
        # Make 5 event creation requests
        for _ in range(5):
            limiter.record_request(user_id=12345, action_type="event_creation")
        
        # 6th request blocked
        is_allowed, retry_after = limiter.check_rate_limit(
            user_id=12345, action_type="event_creation"
        )
        
        assert is_allowed is False
        assert retry_after is not None
        # Retry after should be around 300 seconds (5 minutes)
        assert retry_after > 250

    def test_dm_stricter_limit(self, limiter):
        """Test DMs have stricter limits (3 per minute)."""
        # Make 3 DM requests
        for _ in range(3):
            limiter.record_request(user_id=12345, action_type="dm")
        
        # 4th request blocked
        is_allowed, retry_after = limiter.check_rate_limit(
            user_id=12345, action_type="dm"
        )
        
        assert is_allowed is False

    def test_sliding_window_expires_old_requests(self, limiter):
        """Test old requests are expired from sliding window."""
        # Add old requests (outside window)
        old_time = datetime.utcnow() - timedelta(minutes=2)
        key = limiter._get_key(user_id=12345, group_id=None, action_type="message")
        limiter._requests[key] = [old_time] * 25  # Would exceed limit if counted
        
        # Should be allowed because old requests are outside window
        is_allowed, _ = limiter.check_rate_limit(
            user_id=12345, action_type="message"
        )
        
        assert is_allowed is True


class TestRecordRequest:
    """Tests for record_request."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh RateLimiter instance."""
        from bot.common.rate_limiter import RateLimiter
        return RateLimiter()

    def test_record_adds_timestamp(self, limiter):
        """Test recording adds timestamp to requests."""
        limiter.record_request(user_id=12345, action_type="message")
        
        key = limiter._get_key(user_id=12345, group_id=None, action_type="message")
        assert key in limiter._requests
        assert len(limiter._requests[key]) == 1
        assert isinstance(limiter._requests[key][0], datetime)

    def test_record_multiple_requests(self, limiter):
        """Test recording multiple requests accumulates."""
        for i in range(5):
            limiter.record_request(user_id=12345, action_type="message")
        
        key = limiter._get_key(user_id=12345, group_id=None, action_type="message")
        assert len(limiter._requests[key]) == 5


class TestGetUsage:
    """Tests for get_usage stats."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh RateLimiter instance."""
        from bot.common.rate_limiter import RateLimiter
        return RateLimiter()

    def test_usage_empty(self, limiter):
        """Test usage stats when no requests made."""
        usage = limiter.get_usage(user_id=12345, action_type="message")
        
        assert usage["current_count"] == 0
        assert usage["limit"] == 20  # Message limit
        assert usage["remaining"] == 20

    def test_usage_with_requests(self, limiter):
        """Test usage stats with some requests."""
        for _ in range(10):
            limiter.record_request(user_id=12345, action_type="message")
        
        usage = limiter.get_usage(user_id=12345, action_type="message")
        
        assert usage["current_count"] == 10
        assert usage["remaining"] == 10
        assert usage["window_seconds"] == 60
        assert "reset_at" in usage

    def test_usage_at_limit(self, limiter):
        """Test usage stats at limit."""
        for _ in range(20):
            limiter.record_request(user_id=12345, action_type="message")
        
        usage = limiter.get_usage(user_id=12345, action_type="message")
        
        assert usage["current_count"] == 20
        assert usage["remaining"] == 0


class TestCleanup:
    """Tests for cleanup of old entries."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh RateLimiter instance."""
        from bot.common.rate_limiter import RateLimiter
        return RateLimiter()

    def test_cleanup_removes_expired_keys(self, limiter):
        """Test cleanup removes keys with only old requests."""
        # Add old entries
        old_time = datetime.utcnow() - timedelta(hours=2)
        limiter._requests["user:12345:message"] = [old_time]
        limiter._requests["user:12346:message"] = [old_time]
        limiter._last_cleanup = datetime.utcnow() - timedelta(minutes=10)  # Force cleanup
        
        limiter._cleanup()
        
        assert "user:12345:message" not in limiter._requests
        assert "user:12346:message" not in limiter._requests

    def test_cleanup_preserves_recent_keys(self, limiter):
        """Test cleanup preserves keys with recent requests."""
        # Add recent entry
        recent_time = datetime.utcnow()
        limiter._requests["user:12345:message"] = [recent_time]
        limiter._last_cleanup = datetime.utcnow() - timedelta(minutes=10)  # Force cleanup
        
        limiter._cleanup()
        
        assert "user:12345:message" in limiter._requests

    def test_cleanup_skips_if_recent(self, limiter):
        """Test cleanup skipped if recently run."""
        # Add old entry but recent cleanup
        old_time = datetime.utcnow() - timedelta(hours=2)
        limiter._requests["user:12345:message"] = [old_time]
        limiter._last_cleanup = datetime.utcnow()  # Just ran
        
        limiter._cleanup()
        
        # Should still be there (cleanup skipped)
        assert "user:12345:message" in limiter._requests


class TestGlobalRateLimiter:
    """Tests for global rate limiter singleton."""

    def test_get_rate_limiter_singleton(self):
        """Test get_rate_limiter returns same instance."""
        from bot.common.rate_limiter import get_rate_limiter
        
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()
        
        assert limiter1 is limiter2

    def test_get_rate_limiter_creates_instance(self):
        """Test get_rate_limiter creates instance on first call."""
        from bot.common.rate_limiter import get_rate_limiter, _rate_limiter
        
        # Reset global
        import bot.common.rate_limiter as rl_module
        original = rl_module._rate_limiter
        rl_module._rate_limiter = None
        
        try:
            limiter = get_rate_limiter()
            assert limiter is not None
            assert isinstance(limiter, rl_module.RateLimiter)
        finally:
            rl_module._rate_limiter = original


class TestAsyncCheckRateLimit:
    """Tests for async check_rate_limit function."""

    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self):
        """Test async check returns allowed."""
        from bot.common.rate_limiter import check_rate_limit
        
        is_allowed, error = await check_rate_limit(
            user_id=12345, action_type="message"
        )
        
        assert is_allowed is True
        assert error is None

    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded(self):
        """Test async check returns error when exceeded."""
        from bot.common.rate_limiter import check_rate_limit, get_rate_limiter
        
        # Pre-fill to limit
        limiter = get_rate_limiter()
        for _ in range(20):
            limiter.record_request(user_id=99999, action_type="message")
        
        is_allowed, error = await check_rate_limit(
            user_id=99999, action_type="message"
        )
        
        assert is_allowed is False
        assert error is not None
        assert "Rate limit exceeded" in error
        assert "seconds" in error

    @pytest.mark.asyncio
    async def test_check_rate_limit_raises_exception(self):
        """Test async check raises when raise_on_exceed=True."""
        from bot.common.rate_limiter import check_rate_limit, RateLimitExceeded
        
        # Pre-fill to limit
        limiter = get_rate_limiter()
        for _ in range(20):
            limiter.record_request(user_id=88888, action_type="message")
        
        with pytest.raises(RateLimitExceeded) as exc_info:
            await check_rate_limit(
                user_id=88888, 
                action_type="message",
                raise_on_exceed=True
            )
        
        assert "Rate limit exceeded" in str(exc_info.value)
        assert exc_info.value.retry_after > 0


class TestRecordRequestFunction:
    """Tests for record_request function."""

    def test_record_request_updates_global_limiter(self):
        """Test record_request updates global limiter."""
        from bot.common.rate_limiter import record_request, get_rate_limiter
        
        limiter = get_rate_limiter()
        key = limiter._get_key(user_id=77777, group_id=None, action_type="message")
        
        # Clear any existing requests
        limiter._requests[key] = []
        
        record_request(user_id=77777, action_type="message")
        
        assert len(limiter._requests[key]) == 1


class TestRateLimitMiddleware:
    """Tests for rate_limit_middleware."""

    @pytest.mark.asyncio
    async def test_middleware_allows_normal_request(self):
        """Test middleware allows normal request."""
        from bot.common.rate_limiter import rate_limit_middleware
        
        # Create mock update
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_chat.id = -100123456
        update.message.text = "/start"
        update.callback_query = None
        
        context = MagicMock()
        next_handler = AsyncMock()
        
        await rate_limit_middleware(update, context, next_handler)
        
        next_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_blocks_rate_limited(self):
        """Test middleware blocks rate limited requests."""
        from bot.common.rate_limiter import rate_limit_middleware, get_rate_limiter
        
        # Pre-fill to limit
        limiter = get_rate_limiter()
        for _ in range(20):
            limiter.record_request(user_id=66666, action_type="command")
        
        # Create mock update for command
        update = MagicMock()
        update.effective_user.id = 66666
        update.effective_chat.id = None
        update.message.text = "/start"
        update.callback_query = None
        
        context = MagicMock()
        next_handler = AsyncMock()
        
        await rate_limit_middleware(update, context, next_handler)
        
        # Handler should NOT be called
        next_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_middleware_detects_callback(self):
        """Test middleware detects callback queries."""
        from bot.common.rate_limiter import rate_limit_middleware, get_rate_limiter
        
        # Clear any existing requests for this user
        limiter = get_rate_limiter()
        key = limiter._get_key(user_id=55555, group_id=None, action_type="callback")
        limiter._requests[key] = []
        
        # Create mock update for callback
        update = MagicMock()
        update.effective_user.id = 55555
        update.effective_chat.id = None
        update.message = None
        update.callback_query = MagicMock()
        
        context = MagicMock()
        next_handler = AsyncMock()
        
        await rate_limit_middleware(update, context, next_handler)
        
        # Should record as callback type
        assert len(limiter._requests[key]) == 1
        next_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_handles_non_update(self):
        """Test middleware passes through non-Update objects."""
        from bot.common.rate_limiter import rate_limit_middleware
        
        update = {"not": "an update"}
        context = MagicMock()
        next_handler = AsyncMock()
        
        await rate_limit_middleware(update, context, next_handler)
        
        next_handler.assert_called_once_with(update, context)


class TestRateLimitException:
    """Tests for RateLimitExceeded exception."""

    def test_exception_message(self):
        """Test exception stores message."""
        from bot.common.rate_limiter import RateLimitExceeded
        
        exc = RateLimitExceeded("Test message", retry_after=30)
        
        assert "Test message" in str(exc)
        assert exc.retry_after == 30


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
