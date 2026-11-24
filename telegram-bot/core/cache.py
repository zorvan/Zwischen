"""Cache-aside reads over the shared state backend (T13).

Rules this module enforces:

* **Shared, not per-process.** Entries live in the StateBackend (Redis in any
  multi-instance deployment), so an invalidation on one instance is seen by
  all of them.
* **Short TTL plus explicit invalidation.** A write deletes the entry at once
  and again after its transaction commits, so a reader on another instance
  cannot repopulate the cache with the pre-commit value in between.
* **Correct when disabled.** ``CACHE_ENABLED=false``, or no backend
  configured, makes every read go straight to the loader.
* **Never for authorization.** Membership and role checks are deliberately
  not cached: a stale "is member" grants access after removal.
* **Shorter than retention.** TTLs are minutes; every retention window in
  docs/RETENTION_POLICY.md is months. Erasure invalidates immediately.

Values must be JSON-serializable. ``None`` is cached too (wrapped), so a user
with no language preference does not cost a query on every message.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from core.state import StateBackend

logger = logging.getLogger("coord_bot.cache")

_PENDING_KEY = "cache_invalidations"


class ReadCache:
    def __init__(
        self,
        state: Optional[StateBackend] = None,
        *,
        enabled: bool = True,
        ttl_seconds: int = 300,
    ) -> None:
        self.state = state
        self.enabled = enabled and state is not None
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, int] = {}
        self._misses: dict[str, int] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _key(namespace: str, key: Any) -> str:
        return f"cache:{namespace}:{key}"

    def _count(self, table: dict[str, int], namespace: str) -> None:
        with self._lock:
            table[namespace] = table.get(namespace, 0) + 1

    async def get_or_load(
        self,
        namespace: str,
        key: Any,
        loader: Callable[[], Awaitable[Any]],
        *,
        ttl_seconds: Optional[int] = None,
    ) -> Any:
        """Return the cached value, or load, store and return it."""
        if not self.enabled or self.state is None:
            return await loader()
        cache_key = self._key(namespace, key)
        try:
            cached = await self.state.get(cache_key)
        except Exception:
            # A cache outage degrades to direct reads, never to an error.
            logger.warning("Cache read failed", exc_info=True)
            return await loader()
        if isinstance(cached, dict) and "v" in cached:
            self._count(self._hits, namespace)
            return cached["v"]
        self._count(self._misses, namespace)
        value = await loader()
        try:
            await self.state.set(
                cache_key, {"v": value}, ttl_seconds=ttl_seconds or self.ttl_seconds
            )
        except Exception:
            logger.warning("Cache write failed", exc_info=True)
        return value

    async def invalidate(self, namespace: str, key: Any) -> None:
        if self.state is None:
            return
        try:
            await self.state.delete(self._key(namespace, key))
        except Exception:
            # Leaves at most one TTL of staleness; log loudly.
            logger.error("Cache invalidation failed", exc_info=True)

    async def invalidate_on_commit(
        self, session: Any, namespace: str, key: Any
    ) -> None:
        """Invalidate now, and again once ``session`` commits."""
        await self.invalidate(namespace, key)
        info = getattr(session, "info", None)
        if isinstance(info, dict):
            info.setdefault(_PENDING_KEY, set()).add((namespace, str(key)))

    def _schedule(self, pending: set[tuple[str, str]]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for namespace, key in pending:
            task = loop.create_task(self.invalidate(namespace, key))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for post-commit invalidations (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def stats(self) -> dict[str, Any]:
        """Hits, misses and hit rate per namespace, since process start."""
        with self._lock:
            namespaces = set(self._hits) | set(self._misses)
            report: dict[str, Any] = {"enabled": self.enabled}
            for namespace in sorted(namespaces):
                hits = self._hits.get(namespace, 0)
                misses = self._misses.get(namespace, 0)
                total = hits + misses
                report[namespace] = {
                    "hits": hits,
                    "misses": misses,
                    "hit_rate": round(hits / total, 3) if total else None,
                }
            return report


_cache = ReadCache()  # disabled until configure_cache()


def configure_cache(
    state: Optional[StateBackend], *, enabled: bool = True, ttl_seconds: int = 300
) -> ReadCache:
    """Install the process-wide cache (main.py does this at startup)."""
    global _cache
    _cache = ReadCache(state, enabled=enabled, ttl_seconds=ttl_seconds)
    return _cache


def get_cache() -> ReadCache:
    return _cache


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if pending:
        _cache._schedule(pending)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    # The immediate invalidation already ran; nothing was written.
    session.info.pop(_PENDING_KEY, None)
