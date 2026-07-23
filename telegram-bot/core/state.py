"""Shared state that survives more than one process.

Three pieces of runtime state were process-local, and each one silently breaks
the moment a second instance exists:

- conversation state, held in ``context.user_data`` and persisted to a single
  ``PicklePersistence`` file. Two instances get two files and a user's
  half-finished event-creation flow depends on which one answers.
- rate limiter counters (``bot/common/rate_limiter.py``), whose own docstring
  already warned about this: N instances means N times the allowed rate.
- the per-user ``StateStore`` singleton in ``bot/services/state_store.py``.

This module gives them one home behind a protocol, so the backend is a
deployment choice rather than a code change. :class:`InMemoryStateBackend`
keeps single-process runs and tests dependency-free;
:class:`RedisStateBackend` is what makes horizontal scaling actually work.

Values are JSON, not pickle. Pickle ties the stored format to Python -- and to
the exact classes present when it was written -- which is the wrong contract
for state that a future service in another language may need to read.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger("coord_bot.state")


@runtime_checkable
class StateBackend(Protocol):
    """Key-value state with expiry, plus the primitives rate limiting needs."""

    async def get(self, key: str) -> Optional[Any]: ...

    async def set(
        self, key: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def hit_window(
        self, key: str, window_seconds: int, now: float | None = None
    ) -> int:
        """Record one hit and return the count within the trailing window.

        A sliding window rather than a fixed bucket: fixed buckets let a
        caller spend the whole allowance at the end of one bucket and again at
        the start of the next, i.e. twice the intended rate across the seam.
        """
        ...

    async def close(self) -> None: ...


class InMemoryStateBackend:
    """Process-local backend. Correct for one instance, and for tests.

    Deliberately not a drop-in for production with more than one process --
    it is the thing whose limitations motivated this module. Chosen when no
    REDIS_URL is configured.
    """

    def __init__(self) -> None:
        self._values: dict[str, tuple[Any, Optional[float]]] = {}
        self._windows: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, expires_at: Optional[float], now: float) -> bool:
        return expires_at is not None and expires_at <= now

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._is_expired(expires_at, time.time()):
                # Lazy expiry: cheaper than sweeping, and the only observable
                # difference is memory held until the key is next touched.
                del self._values[key]
                return None
            return value

    async def set(
        self, key: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> None:
        # Round-trip through JSON so this backend rejects exactly what the
        # Redis one would; otherwise a value works locally and fails in
        # production.
        json.dumps(value)
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        async with self._lock:
            self._values[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._values.pop(key, None)

    async def hit_window(
        self, key: str, window_seconds: int, now: float | None = None
    ) -> int:
        moment = now if now is not None else time.time()
        cutoff = moment - window_seconds
        async with self._lock:
            hits = [t for t in self._windows.get(key, []) if t > cutoff]
            hits.append(moment)
            self._windows[key] = hits
            return len(hits)

    async def close(self) -> None:
        async with self._lock:
            self._values.clear()
            self._windows.clear()


class RedisStateBackend:
    """Redis-backed state, shared across every instance.

    Expiry is Redis's own TTL rather than anything swept here, so a crashed
    instance cannot leave state behind forever.
    """

    def __init__(self, client: Any, namespace: str = "zwischen") -> None:
        self._redis = client
        self._ns = namespace

    @classmethod
    def from_url(cls, url: str, namespace: str = "zwischen") -> "RedisStateBackend":
        from redis.asyncio import Redis

        # decode_responses so values come back as str; this module owns
        # serialization and does not want bytes leaking into callers.
        return cls(Redis.from_url(url, decode_responses=True), namespace)

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    async def get(self, key: str) -> Optional[Any]:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            # A value written by an older format should not crash a handler.
            logger.warning("Discarding unreadable state at %s", key)
            return None

    async def set(
        self, key: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> None:
        payload = json.dumps(value)
        if ttl_seconds:
            await self._redis.set(self._key(key), payload, ex=ttl_seconds)
        else:
            await self._redis.set(self._key(key), payload)

    async def delete(self, key: str) -> None:
        await self._redis.delete(self._key(key))

    async def hit_window(
        self, key: str, window_seconds: int, now: float | None = None
    ) -> int:
        """Sliding window over a sorted set, in one round trip.

        Pipelined so the trim, insert, count and expire cannot interleave with
        another instance's -- which is the whole reason this moved out of
        process memory.
        """
        moment = now if now is not None else time.time()
        redis_key = self._key(f"window:{key}")

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, 0, moment - window_seconds)
        # Member must be unique or concurrent hits at the same timestamp
        # collapse into one entry and under-count exactly the burst a rate
        # limiter exists to catch. uuid4, not id() -- a temporary object's
        # address is reused as soon as it is collected, so id() produced
        # duplicate members for hits in the same instant.
        pipe.zadd(redis_key, {f"{moment}:{uuid.uuid4().hex}": moment})
        pipe.zcard(redis_key)
        # Expire the key itself, so an idle limiter does not linger forever.
        pipe.expire(redis_key, window_seconds + 1)
        results = await pipe.execute()
        return int(results[2])

    async def close(self) -> None:
        await self._redis.aclose()


def build_state_backend(
    redis_url: Optional[str], namespace: str = "zwischen"
) -> StateBackend:
    """Pick a backend from configuration.

    Falls back to in-memory when no Redis is configured, so a developer can
    run the bot with nothing else installed -- while a multi-instance deploy
    that forgets REDIS_URL degrades visibly (a warning, and per-instance
    state) rather than silently corrupting shared counters.
    """
    if not redis_url:
        logger.warning(
            "No REDIS_URL set; using in-process state. Safe for a single "
            "instance only -- conversation state and rate limits will not be "
            "shared if more than one process is running."
        )
        return InMemoryStateBackend()
    return RedisStateBackend.from_url(redis_url, namespace)
