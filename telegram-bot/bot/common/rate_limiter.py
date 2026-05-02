"""
Rate Limiting Middleware - Prevents abuse and spam.
PRD v2 Priority 4: Production Hardening.

Features:
- Per-user rate limits
- Per-group rate limits
- Sliding window algorithm
- Configurable limits per action type

WARNING: Rate limit state is in-memory and NOT restart-safe.
For multi-instance deployment, move state to Redis or a dedicated DB table.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, Any
from collections import defaultdict

logger = logging.getLogger("coord_bot.rate_limiter")


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int):
        self.message = message
        self.retry_after = retry_after
        super().__init__(self.message)


class RateLimiter:
    """
    Sliding window rate limiter.

    Tracks request timestamps and enforces limits.
    """

    # Default limits (requests per window)
    DEFAULT_LIMIT = 10
    DEFAULT_WINDOW_SECONDS = 60

    # Specific limits by action type
    ACTION_LIMITS = {
        "message": {"limit": 20, "window": 60},  # Messages per minute
        "command": {"limit": 10, "window": 60},  # Commands per minute
        "callback": {"limit": 30, "window": 60},  # Callbacks per minute
        "event_creation": {"limit": 5, "window": 300},  # Event creation per 5 min
        "mention": {"limit": 5, "window": 60},  # Bot mentions per minute
        "dm": {"limit": 3, "window": 60},  # DMs from bot per minute
    }

    def __init__(self):
        # Storage: {key: [timestamps]}
        self._requests: Dict[str, list[datetime]] = defaultdict(list)
        self._cleanup_interval = 300  # Cleanup every 5 minutes
        self._last_cleanup = datetime.utcnow()

    def _get_key(
        self, user_id: Optional[int], group_id: Optional[int], action_type: str
    ) -> str:
        """Generate rate limit key."""
        if group_id:
            return f"group:{group_id}:{action_type}"
        elif user_id:
            return f"user:{user_id}:{action_type}"
        else:
            return f"global:{action_type}"

    def _cleanup(self) -> None:
        """Remove expired entries."""
        now = datetime.utcnow()
        if now - self._last_cleanup < timedelta(seconds=self._cleanup_interval):
            return

        max_window = max(config["window"] for config in self.ACTION_LIMITS.values())
        cutoff = now - timedelta(seconds=max_window * 2)

        expired_keys = []
        for key, timestamps in self._requests.items():
            self._requests[key] = [ts for ts in timestamps if ts > cutoff]
            if not self._requests[key]:
                expired_keys.append(key)

        for key in expired_keys:
            del self._requests[key]

        self._last_cleanup = now
        logger.debug("Rate limiter cleanup completed")

    def check_rate_limit(
        self,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        action_type: str = "message",
    ) -> Tuple[bool, Optional[int]]:
        """
        Check if action is within rate limit.

        Returns:
            (is_allowed, retry_after_seconds)
        """
        self._cleanup()

        # Get limits for action type
        config = self.ACTION_LIMITS.get(
            action_type,
            {"limit": self.DEFAULT_LIMIT, "window": self.DEFAULT_WINDOW_SECONDS},
        )
        limit = config["limit"]
        window = config["window"]

        key = self._get_key(user_id, group_id, action_type)
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=window)

        # Count requests in current window
        self._requests[key] = [ts for ts in self._requests[key] if ts > window_start]
        current_count = len(self._requests[key])

        if current_count >= limit:
            # Calculate retry after
            oldest_in_window = min(self._requests[key])
            retry_after = int(
                (oldest_in_window + timedelta(seconds=window) - now).total_seconds()
            )
            retry_after = max(1, retry_after)  # At least 1 second
            return False, retry_after

        return True, None

    def record_request(
        self,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        action_type: str = "message",
    ) -> None:
        """Record a request for rate limiting."""
        key = self._get_key(user_id, group_id, action_type)
        self._requests[key].append(datetime.utcnow())

    def get_usage(
        self,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        action_type: str = "message",
    ) -> Dict[str, Any]:
        """
        Get current usage stats.

        Returns dict with: current_count, limit, window, remaining, reset_at
        """
        config = self.ACTION_LIMITS.get(
            action_type,
            {"limit": self.DEFAULT_LIMIT, "window": self.DEFAULT_WINDOW_SECONDS},
        )
        limit = config["limit"]
        window = config["window"]

        key = self._get_key(user_id, group_id, action_type)
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=window)

        self._requests[key] = [ts for ts in self._requests[key] if ts > window_start]
        current_count = len(self._requests[key])

        reset_at = now + timedelta(seconds=window)
        if self._requests[key]:
            oldest_in_window = min(self._requests[key])
            reset_at = oldest_in_window + timedelta(seconds=window)

        return {
            "current_count": current_count,
            "limit": limit,
            "window_seconds": window,
            "remaining": max(0, limit - current_count),
            "reset_at": reset_at,
        }


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def check_rate_limit(
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    action_type: str = "message",
    raise_on_exceed: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Check rate limit and optionally raise exception.

    Usage:
        is_allowed, error = await check_rate_limit(user_id, group_id, "command")
        if not is_allowed:
            await update.message.reply_text(error)
            return
    """
    limiter = get_rate_limiter()
    is_allowed, retry_after = limiter.check_rate_limit(user_id, group_id, action_type)

    if not is_allowed:
        error_msg = (
            f"⚠️ Rate limit exceeded. Please wait {retry_after} seconds "
            f"before trying again."
        )
        if raise_on_exceed:
            raise RateLimitExceeded(error_msg, retry_after)
        return False, error_msg

    return True, None


def record_request(
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    action_type: str = "message",
) -> None:
    """Record request for rate limiting."""
    limiter = get_rate_limiter()
    limiter.record_request(user_id, group_id, action_type)


async def rate_limit_middleware(update, context, next_handler):
    """
    Rate limiting middleware for telegram.ext.

    Usage in main.py:
        application.middleware().add(rate_limit_middleware)
    """
    from telegram import Update

    if not isinstance(update, Update):
        return await next_handler(update, context)

    user_id = update.effective_user.id if update.effective_user else None
    group_id = update.effective_chat.id if update.effective_chat else None

    # Determine action type
    if update.message and update.message.text:
        if update.message.text.startswith("/"):
            action_type = "command"
        else:
            action_type = "message"
    elif update.callback_query:
        action_type = "callback"
    else:
        action_type = "message"

    # Check rate limit
    is_allowed, error = await check_rate_limit(user_id, group_id, action_type)

    if not is_allowed:
        logger.warning(
            "Rate limit exceeded",
            extra={
                "user_id": user_id,
                "group_id": group_id,
                "action_type": action_type,
                "error": error,
            },
        )
        # Silently drop the update or send rate limit message
        # For now, silently drop to avoid spam
        return

    # Record the request
    record_request(user_id, group_id, action_type)

    return await next_handler(update, context)
