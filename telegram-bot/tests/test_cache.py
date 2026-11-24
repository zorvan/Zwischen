"""T13: the shared read cache.

The cross-instance tests use two independent Redis clients as two
instances. They need a Redis server (REDIS_TEST_URL, default a local one) and
skip without it; the remaining tests use the in-memory backend.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio

from core import cache as cache_module
from core.cache import ReadCache, configure_cache, get_cache
from core.state import InMemoryStateBackend

REDIS_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:56990/15")


@pytest.fixture(autouse=True)
def restore_cache() -> Any:
    previous = cache_module._cache
    yield
    cache_module._cache = previous


@pytest_asyncio.fixture
async def redis_instances() -> AsyncIterator[tuple[Any, Any]]:
    """Two StateBackends on one Redis server, as two app instances see it."""
    from core.state import RedisStateBackend

    namespace = f"zwischen-test-{uuid.uuid4().hex[:8]}"
    first = RedisStateBackend.from_url(REDIS_URL, namespace=namespace)
    second = RedisStateBackend.from_url(REDIS_URL, namespace=namespace)
    try:
        await first._redis.ping()
    except Exception:
        await first.close()
        await second.close()
        pytest.skip(f"No Redis at {REDIS_URL}")
    try:
        yield first, second
    finally:
        await first.close()
        await second.close()


async def test_disabled_or_unconfigured_cache_always_loads() -> None:
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        return "fa"

    for cache in (ReadCache(None), ReadCache(InMemoryStateBackend(), enabled=False)):
        assert await cache.get_or_load("language", 1, loader) == "fa"
        assert await cache.get_or_load("language", 1, loader) == "fa"
    assert calls == 4


async def test_hits_misses_and_none_values_are_cached() -> None:
    cache = ReadCache(InMemoryStateBackend())
    calls = 0

    async def loader() -> None:
        nonlocal calls
        calls += 1
        return None

    for _ in range(3):
        assert await cache.get_or_load("language", 7, loader) is None
    assert calls == 1
    assert cache.stats()["language"] == {"hits": 2, "misses": 1, "hit_rate": 0.667}


async def test_backend_outage_degrades_to_direct_reads() -> None:
    class Broken(InMemoryStateBackend):
        async def get(self, key: str) -> Any:
            raise ConnectionError("redis down")

    cache = ReadCache(Broken())

    async def loader() -> str:
        return "en"

    assert await cache.get_or_load("language", 1, loader) == "en"


@pytest.mark.integration
async def test_write_on_one_instance_invalidates_the_other(
    test_db_url: str, redis_instances: tuple[Any, Any]
) -> None:
    from bot.common.user_preferences import (
        get_language_preference,
        set_language_preference,
    )
    from db.connection import get_session
    from db.identity import resolve_telegram_user

    instance_a, instance_b = redis_instances
    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 6_100_000_001)
        user_id = int(user.user_id)
        await set_language_preference(session, user_id, "en")
        await session.commit()

    # Instance A reads and populates the shared cache.
    configure_cache(instance_a)
    async with get_session(test_db_url) as session:
        assert await get_language_preference(session, user_id) == "en"
    # Instance B is served from it: one cache, not one per process.
    cache_b = configure_cache(instance_b)
    async with get_session(test_db_url) as session:
        assert await get_language_preference(session, user_id) == "en"
    assert cache_b.stats()["language"]["hits"] == 1

    # Instance B writes; the invalidation reaches A immediately.
    async with get_session(test_db_url) as session:
        await set_language_preference(session, user_id, "fa")
        await session.commit()
    await cache_b.drain()
    cache_a = configure_cache(instance_a)
    async with get_session(test_db_url) as session:
        assert await get_language_preference(session, user_id) == "fa"
    assert cache_a.stats()["language"] == {"hits": 0, "misses": 1, "hit_rate": 0.0}


@pytest.mark.integration
async def test_reader_between_write_and_commit_cannot_pin_stale_value(
    test_db_url: str,
) -> None:
    """The post-commit invalidation closes the write/commit window."""
    from bot.common.user_preferences import (
        get_language_preference,
        set_language_preference,
    )
    from db.connection import get_session
    from db.identity import resolve_telegram_user

    cache = configure_cache(InMemoryStateBackend())
    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 6_100_000_002)
        user_id = int(user.user_id)
        await set_language_preference(session, user_id, "en")
        await session.commit()

    async with get_session(test_db_url) as writer:
        await set_language_preference(writer, user_id, "fa")
        # Another reader runs before the writer commits and caches "en".
        async with get_session(test_db_url) as reader:
            assert await get_language_preference(reader, user_id) == "en"
        await writer.commit()
    await cache.drain()

    async with get_session(test_db_url) as session:
        assert await get_language_preference(session, user_id) == "fa"


@pytest.mark.integration
async def test_erasure_invalidates_cached_preferences(test_db_url: str) -> None:
    from bot.common.user_preferences import (
        get_language_preference,
        set_language_preference,
    )
    from bot.services.retention_service import RetentionService
    from db.connection import get_session
    from db.identity import resolve_telegram_user

    cache = configure_cache(InMemoryStateBackend())
    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 6_100_000_003)
        user_id = int(user.user_id)
        await set_language_preference(session, user_id, "fa")
        await session.commit()
    async with get_session(test_db_url) as session:
        assert await get_language_preference(session, user_id) == "fa"
        await RetentionService(session).erase_user(user_id)
        await session.commit()
    await cache.drain()
    async with get_session(test_db_url) as session:
        assert await get_language_preference(session, user_id) is None


@pytest.mark.integration
async def test_live_card_setting_is_read_for_real_group_ids(test_db_url: str) -> None:
    """Regression: groups were looked up by abs(chat_id), which never matched."""
    from bot.common.live_card_service import LiveCardService, invalidate_group_settings
    from db.connection import get_session
    from db.models import Group, GroupSettings

    configure_cache(InMemoryStateBackend())
    chat_id = -1_006_100_000_001
    async with get_session(test_db_url) as session:
        group = Group(telegram_group_id=chat_id, group_name="cards")
        session.add(group)
        await session.flush()
        settings_row = GroupSettings(group_id=group.group_id, enable_live_cards=False)
        session.add(settings_row)
        await session.commit()
        group_id = int(group.group_id)

    async with get_session(test_db_url) as session:
        service = LiveCardService(session, bot=None)  # type: ignore[arg-type]
        assert await service._is_live_cards_enabled(chat_id) is False

        row = await session.get(GroupSettings, group_id)
        row.enable_live_cards = True
        await invalidate_group_settings(session, group_id)
        await session.commit()
    await get_cache().drain()

    async with get_session(test_db_url) as session:
        service = LiveCardService(session, bot=None)  # type: ignore[arg-type]
        assert await service._is_live_cards_enabled(chat_id) is True
