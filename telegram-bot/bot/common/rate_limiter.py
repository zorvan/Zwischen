"""
Rate Limiting Middleware - Prevents abuse and spam.
PRD v2 Priority 4: Production Hardening.

Features:
- Per-user rate limits
- Per-group rate limits
- Sliding window algorithm
- Configurable limits per action type

Counters live in ``StateBackend`` so every application instance observes the
same sliding window.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from core.state import StateBackend

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

    def __init__(self, backend: StateBackend):
        self.backend = backend

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

    async def check_rate_limit(
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
        # Get limits for action type
        config = self.ACTION_LIMITS.get(
            action_type,
            {"limit": self.DEFAULT_LIMIT, "window": self.DEFAULT_WINDOW_SECONDS},
        )
        limit = config["limit"]
        window = config["window"]

        key = self._get_key(user_id, group_id, action_type)
        current_count = await self.backend.hit_window(key, window)
        return (current_count <= limit, None if current_count <= limit else window)


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def configure_rate_limiter(backend: StateBackend) -> RateLimiter:
    global _rate_limiter
    _rate_limiter = RateLimiter(backend)
    return _rate_limiter


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        raise RuntimeError("Rate limiter has not been configured")
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
    is_allowed, retry_after = await limiter.check_rate_limit(
        user_id, group_id, action_type
    )

    if not is_allowed:
        error_msg = (
            f"⚠️ Rate limit exceeded. Please wait {retry_after} seconds "
            f"before trying again."
        )
        if raise_on_exceed:
            raise RateLimitExceeded(error_msg, retry_after)
        return False, error_msg

    return True, None


async def rate_limit_update(update, context):
    """Stop update dispatch when the shared sliding-window limit is exceeded."""
    from telegram import Update

    if not isinstance(update, Update):
        return

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
        from telegram.ext import ApplicationHandlerStop

        raise ApplicationHandlerStop
