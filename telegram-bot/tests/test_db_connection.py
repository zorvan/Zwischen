"""Tests for engine caching and pool configuration.

These guard the fix for a bug that made the whole integration suite
unrunnable: async engines were cached by URL alone, so an engine created on
one event loop was handed to a caller running on another. asyncpg binds its
pool to the creating loop, so the reused engine failed at query time with
"got Future attached to a different loop".
"""

from __future__ import annotations

import asyncio

import pytest

from db.connection import create_engine, dispose_engines

URL = "postgresql+asyncpg://u:p@localhost:5432/never_connected"


def test_engine_is_reused_within_one_loop() -> None:
    """The cache must still do its job: one engine per URL per loop."""

    async def scenario() -> bool:
        try:
            return create_engine(URL) is create_engine(URL)
        finally:
            await dispose_engines()

    assert asyncio.run(scenario()) is True


def test_engine_is_not_shared_across_loops() -> None:
    """The regression itself.

    Two loops must never receive the same engine. Before the fix this
    returned the identical object and every query on the second loop failed.
    """
    engines = []

    async def capture() -> None:
        engines.append(create_engine(URL))
        await dispose_engines()

    asyncio.run(capture())
    asyncio.run(capture())

    assert (
        engines[0] is not engines[1]
    ), "engine leaked across event loops; asyncpg pools are loop-bound"


def test_engine_outside_a_loop_is_not_cached() -> None:
    """Engines built with no running loop must not poison the cache.

    Sync tooling calls this path. Caching there would attach an engine to
    whichever loop happened to run next.
    """
    first = create_engine(URL)
    second = create_engine(URL)
    assert first is not second


def test_pool_is_configured_for_multi_instance_deployment() -> None:
    """Pool settings that matter once more than one process is running."""

    async def scenario() -> tuple:
        try:
            # getattr: these live on QueuePool, not the base Pool type that
            # engine.pool is annotated as, so direct access fails type checking.
            pool = create_engine(URL).pool
            return (
                getattr(pool, "size")(),
                getattr(pool, "_recycle"),
                getattr(pool, "_pre_ping"),
            )
        finally:
            await dispose_engines()

    size, recycle, pre_ping = asyncio.run(scenario())

    assert size > 0
    # Without recycling, pooled connections outlive the idle timeout of any
    # proxy in front of PostgreSQL and come back dead.
    assert recycle > 0, "pool_recycle must be set behind a connection proxy"
    assert pre_ping is True


@pytest.mark.parametrize(
    "env,expected",
    [("5", 5), ("25", 25)],
)
def test_pool_size_is_configurable(monkeypatch, env: str, expected: int) -> None:
    """Pool size must be tunable per deployment.

    Total connections are pool_size * instance_count, so this has to come
    down as instances scale out, not be hardcoded.
    """
    import importlib

    import config.settings

    monkeypatch.setenv("DB_POOL_SIZE", env)
    importlib.reload(config.settings)
    try:
        assert config.settings.settings.db_pool_size == expected
    finally:
        monkeypatch.delenv("DB_POOL_SIZE", raising=False)
        importlib.reload(config.settings)
