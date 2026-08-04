"""Cross-instance domain-event fan-out and reconnect-safe subscriptions."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable


class InMemoryEventBus:
    def __init__(self) -> None:
        self._rooms: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        for queue in tuple(self._rooms[channel]):
            await queue.put(payload)

    @asynccontextmanager
    async def subscribe(
        self, channel: str
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
        self._rooms[channel].add(queue)

        async def messages() -> AsyncIterator[dict[str, Any]]:
            while True:
                yield await queue.get()

        try:
            yield messages()
        finally:
            self._rooms[channel].discard(queue)


class RedisEventBus:
    def __init__(self, redis: Any, namespace: str = "zwischen") -> None:
        self.redis, self.namespace = redis, namespace

    def _channel(self, channel: str) -> str:
        return f"{self.namespace}:{channel}"

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self.redis.publish(self._channel(channel), json.dumps(payload))

    @asynccontextmanager
    async def subscribe(
        self, channel: str
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self._channel(channel))

        async def messages() -> AsyncIterator[dict[str, Any]]:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield json.loads(message["data"])

        try:
            yield messages()
        finally:
            await pubsub.unsubscribe(self._channel(channel))
            await pubsub.aclose()


class EventUpdates:
    """Publish one change and debounce expensive transport renders."""

    def __init__(self, bus: Any, debounce_seconds: float = 0.25) -> None:
        self.bus, self.debounce_seconds = bus, debounce_seconds
        self._pending: dict[int, asyncio.Task[None]] = {}

    async def changed(self, event_id: int, public_id: str) -> None:
        await self.bus.publish(
            f"event:{public_id}", {"type": "event.changed", "event_id": public_id}
        )

    def debounce(self, event_id: int, render: Callable[[], Awaitable[None]]) -> None:
        existing = self._pending.get(event_id)
        if existing and not existing.done():
            existing.cancel()

        async def later() -> None:
            try:
                await asyncio.sleep(self.debounce_seconds)
                await render()
            finally:
                self._pending.pop(event_id, None)

        self._pending[event_id] = asyncio.create_task(later())
