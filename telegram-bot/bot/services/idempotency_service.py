"""
IdempotencyService - Prevents duplicate command execution.
PRD v2 Priority 1: Idempotent Command Execution.

Ensures that duplicate Telegram updates (common with polling) don't cause
duplicate state changes or side effects.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import IdempotencyKey

logger = logging.getLogger("coord_bot.services.idempotency")


class IdempotencyService:
    """
    Manages idempotency keys to prevent duplicate command execution.

    Usage:
        1. Before executing a command, check if idempotency key exists
        2. If exists and completed, return cached response
        3. If exists and pending, wait or reject (concurrent request)
        4. If not exists, create with status=pending, execute, then mark completed
    """

    # Default expiry: 24 hours
    DEFAULT_EXPIRY_HOURS = 24

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def generate_key(
        command_type: str,
        user_id: int,
        event_id: Optional[int] = None,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """
        Generate a deterministic idempotency key.

        For commands: "{command}:{user_id}:{event_id}"
        For callbacks: "callback:{update_id}"
        """
        if event_id is not None:
            key_raw = f"{command_type}:{user_id}:{event_id}"
        else:
            key_raw = f"{command_type}:{user_id}"

        return hashlib.sha256(key_raw.encode()).hexdigest()[:64]

    async def check(
        self,
        idempotency_key: str,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Check if command was already executed.

        Returns:
            (is_duplicate, status, response_hash)
            - is_duplicate: True if command already processed
            - status: 'pending', 'completed', 'failed', or None
            - response_hash: Hash of cached response if completed
        """
        result = await self.session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.idempotency_key == idempotency_key
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            return False, None, None

        # Check expiry
        if record.expires_at < datetime.utcnow():
            # Expired - treat as new request
            logger.debug("Idempotency key expired: %s", idempotency_key)
            return False, None, None

        return True, record.status, record.response_hash

    async def register(
        self,
        idempotency_key: str,
        command_type: str,
        user_id: int,
        event_id: Optional[int] = None,
        expires_in_hours: int = DEFAULT_EXPIRY_HOURS,
    ) -> IdempotencyKey:
        """
        Register a new idempotency key with pending status.

        Should be called BEFORE executing the command.
        """
        now = datetime.utcnow()
        record = IdempotencyKey(
            idempotency_key=idempotency_key,
            command_type=command_type,
            user_id=user_id,
            event_id=event_id,
            status="pending",
            created_at=now,
            expires_at=now + timedelta(hours=expires_in_hours),
        )
        self.session.add(record)
        await self.session.flush()

        logger.debug(
            "Registered idempotency key",
            extra={
                "key": idempotency_key,
                "command": command_type,
                "user": user_id,
                "event": event_id,
            },
        )

        return record

    async def complete(
        self,
        idempotency_key: str,
        response_hash: Optional[str] = None,
    ) -> bool:
        """
        Mark idempotency key as completed with response hash.

        Should be called AFTER successful command execution.
        """
        result = await self.session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.idempotency_key == idempotency_key
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            logger.warning("Attempted to complete unknown key: %s", idempotency_key)
            return False

        record.status = "completed"
        record.completed_at = datetime.utcnow()
        if response_hash:
            record.response_hash = response_hash

        logger.debug("Completed idempotency key: %s", idempotency_key)
        return True

    async def fail(self, idempotency_key: str) -> bool:
        """
        Mark idempotency key as failed.

        Should be called if command execution fails.
        """
        result = await self.session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.idempotency_key == idempotency_key
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            return False

        record.status = "failed"
        record.completed_at = datetime.utcnow()
        return True

    async def cleanup_expired(self) -> int:
        """
        Remove expired idempotency keys.

        Should be run periodically (e.g., daily).
        Returns count of deleted records.
        """
        from sqlalchemy import delete

        now = datetime.utcnow()
        result = await self.session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expires_at < now)
        )
        deleted_count = result.rowcount
        logger.info("Cleaned up %d expired idempotency keys", deleted_count)
        return deleted_count
