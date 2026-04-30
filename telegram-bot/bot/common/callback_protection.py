"""
Callback Replay Protection - Prevents duplicate callback execution.
PRD v2 Priority 4: Production Hardening.

Ensures callbacks:
1. Haven't expired (time-based expiry)
2. Belong to the clicking user (ownership check)
3. Haven't been processed before (idempotency)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import EventParticipant

logger = logging.getLogger("coord_bot.callback_protection")


class CallbackProtectionService:
    """
    Manages callback replay protection.

    Features:
    - Time-based expiry (callbacks expire after N minutes)
    - Ownership verification (only intended user can click)
    - Idempotency tracking (prevent duplicate processing)
    """

    # Default expiry times (minutes)
    EXPIRY_EVENT_ACTIONS = 60  # join, confirm, cancel, back
    EXPIRY_NAVIGATION = 30  # details, logs, status
    EXPIRY_CREATION = 300  # event creation flow (5 minutes)
    EXPIRY_MODIFICATION = 120  # modification approvals

    def __init__(self, session: AsyncSession):
        self.session = session
        self._callback_cache: Dict[str, Dict[str, Any]] = {}

    def generate_callback_id(
        self,
        callback_type: str,
        event_id: int,
        user_id: int,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """
        Generate a unique callback ID with embedded metadata.

        Format: {type}:{event_id}:{user_id}:{timestamp}:{signature}
        """
        ts = timestamp or datetime.utcnow()
        ts_str = ts.strftime("%Y%m%d%H%M%S")

        # Create signature for verification
        signature_raw = f"{callback_type}:{event_id}:{user_id}:{ts_str}"
        signature = hashlib.sha256(signature_raw.encode()).hexdigest()[:8]

        return f"{callback_type}:{event_id}:{user_id}:{ts_str}:{signature}"

    def parse_callback_id(self, callback_id: str) -> Optional[Dict[str, Any]]:
        """
        Parse callback ID and verify signature.

        Returns dict with: type, event_id, user_id, timestamp, is_valid
        """
        parts = callback_id.split(":")
        if len(parts) != 5:
            return None

        callback_type, event_id_str, user_id_str, ts_str, signature = parts

        try:
            event_id = int(event_id_str)
            user_id = int(user_id_str)
            timestamp = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
        except (ValueError, TypeError):
            return None

        # Verify signature
        signature_raw = f"{callback_type}:{event_id}:{user_id}:{ts_str}"
        expected_signature = hashlib.sha256(signature_raw.encode()).hexdigest()[:8]

        if signature != expected_signature:
            logger.warning("Callback signature mismatch: %s", callback_id)
            return None

        return {
            "type": callback_type,
            "event_id": event_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "is_valid": True,
        }

    def get_expiry_time(self, callback_type: str) -> int:
        """Get expiry time in minutes for callback type."""
        if callback_type in {"join", "confirm", "back", "unconfirm", "cancel"}:
            return self.EXPIRY_EVENT_ACTIONS
        elif callback_type in {"details", "logs", "status", "constraints"}:
            return self.EXPIRY_NAVIGATION
        elif callback_type.startswith("event_") or callback_type.startswith("private_event_"):
            return self.EXPIRY_CREATION
        elif callback_type in {"modreq", "mentionact"}:
            return self.EXPIRY_MODIFICATION
        else:
            return self.EXPIRY_EVENT_ACTIONS  # Default

    def is_expired(self, callback_id: str) -> bool:
        """Check if callback has expired."""
        parsed = self.parse_callback_id(callback_id)
        if not parsed:
            return True

        expiry_minutes = self.get_expiry_time(parsed["type"])
        expiry_time = parsed["timestamp"] + timedelta(minutes=expiry_minutes)

        return datetime.utcnow() > expiry_time

    async def check_ownership(
        self,
        callback_id: str,
        clicking_user_id: int,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify callback belongs to clicking user.

        Returns:
            (is_owner, error_message)
        """
        parsed = self.parse_callback_id(callback_id)
        if not parsed:
            return False, "Invalid callback format"

        if parsed["user_id"] != clicking_user_id:
            return False, (
                f"This action was intended for User {parsed['user_id']}. " f"Please use your own invitation link."
            )

        return True, None

    async def validate_callback(
        self,
        callback_id: str,
        clicking_user_id: int,
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Full callback validation (expiry + ownership + format).

        Returns:
            (is_valid, error_message, parsed_data)
        """
        # Parse and verify format
        parsed = self.parse_callback_id(callback_id)
        if not parsed:
            return False, "Invalid callback format", None

        # Check expiry
        if self.is_expired(callback_id):
            return False, "This invitation has expired. Please request a new one.", parsed

        # Check ownership
        is_owner, error = await self.check_ownership(callback_id, clicking_user_id)
        if not is_owner:
            return False, error, parsed

        return True, None, parsed

    def register_callback(self, callback_id: str, metadata: Dict[str, Any]) -> None:
        """
        Register callback in cache for idempotency tracking.

        Should be called when callback is first processed.
        """
        self._callback_cache[callback_id] = {
            "processed_at": datetime.utcnow(),
            "metadata": metadata,
        }

    def is_processed(self, callback_id: str) -> bool:
        """Check if callback was already processed."""
        if callback_id not in self._callback_cache:
            return False

        # Check if processing was recent (within expiry window)
        processed_at = self._callback_cache[callback_id]["processed_at"]
        expiry_minutes = 60  # Keep in cache for 1 hour
        if datetime.utcnow() - processed_at > timedelta(minutes=expiry_minutes):
            del self._callback_cache[callback_id]
            return False

        return True

    def cleanup_cache(self) -> int:
        """
        Remove expired entries from cache.

        Returns count of removed entries.
        """
        now = datetime.utcnow()
        expired_keys = []

        for key, value in self._callback_cache.items():
            if now - value["processed_at"] > timedelta(hours=1):
                expired_keys.append(key)

        for key in expired_keys:
            del self._callback_cache[key]

        return len(expired_keys)


async def validate_event_callback(
    session: AsyncSession,
    callback_data: str,
    clicking_user_id: int,
    event_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function for validating event action callbacks.

    Usage:
        is_valid, error = await validate_event_callback(
            session, callback_data, user_id, event_id
        )
        if not is_valid:
            await query.answer(error)
            return
    """
    protection = CallbackProtectionService(session)

    # Validate callback format and expiry
    is_valid, error, parsed = await protection.validate_callback(callback_data, clicking_user_id)

    if not is_valid:
        return False, error

    # Additional check: verify user is participant for action callbacks
    if parsed["type"] in {"confirm", "back", "unconfirm", "cancel"}:
        result = await session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == clicking_user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if not participant:
            return False, "You must join the event first"

    return True, None


def build_protected_callback(
    callback_type: str,
    event_id: int,
    user_id: int,
) -> str:
    """
    Build a protected callback string.

    Usage:
        callback = build_protected_callback("confirm", 123, user_id)
        keyboard = [[InlineKeyboardButton("Confirm", callback_data=callback)]]
    """
    protection = CallbackProtectionService(None)  # Session not needed for generation
    return protection.generate_callback_id(callback_type, event_id, user_id)
