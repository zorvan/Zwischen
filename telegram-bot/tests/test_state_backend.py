"""Tests for shared state backends.

Both implementations are run through the same suite, because the whole value
of the abstraction is that they behave identically -- a difference between
them is a bug that would only appear in production.
"""

from __future__ import annotations

import pytest

from core.state import (
    InMemoryStateBackend,
    RedisStateBackend,
    StateBackend,
    build_state_backend,
)


@pytest.fixture(params=["memory", "redis"])
async def backend(request):
    """Every test runs against both backends."""
    if request.param == "memory":
        instance: StateBackend = InMemoryStateBackend()
    else:
        fakeredis = pytest.importorskip("fakeredis")
        instance = RedisStateBackend(
            fakeredis.aioredis.FakeRedis(decode_responses=True)
        )
    yield instance
    await instance.close()


async def test_set_and_get_round_trip(backend: StateBackend) -> None:
    await backend.set("flow:1", {"stage": "pick_time", "event_id": 42})
    assert await backend.get("flow:1") == {"stage": "pick_time", "event_id": 42}


async def test_missing_key_is_none(backend: StateBackend) -> None:
    assert await backend.get("nope") is None


async def test_delete_removes(backend: StateBackend) -> None:
    await backend.set("k", "v")
    await backend.delete("k")
    assert await backend.get("k") is None


async def test_deleting_a_missing_key_is_not_an_error(backend: StateBackend) -> None:
    await backend.delete("never-existed")


async def test_expired_values_are_gone(backend: StateBackend) -> None:
    """TTL is what stops abandoned creation flows accumulating forever."""
    import time

    await backend.set("short", "v", ttl_seconds=1)
    assert await backend.get("short") == "v"

    if isinstance(backend, InMemoryStateBackend):
        # Move the clock rather than sleeping.
        backend._values["short"] = (backend._values["short"][0], time.time() - 1)
    else:
        assert isinstance(backend, RedisStateBackend)
        await backend._redis.pexpire(backend._key("short"), 1)
        import asyncio

        await asyncio.sleep(0.05)

    assert await backend.get("short") is None


async def test_values_must_be_serializable(backend: StateBackend) -> None:
    """Reject in-memory what Redis would reject, so behaviour matches.

    Without this, a value works in development and fails only once Redis is
    configured.
    """
    with pytest.raises(TypeError):
        await backend.set("bad", {1, 2, 3})


async def test_nested_structures_survive(backend: StateBackend) -> None:
    payload = {"a": [1, 2, {"b": None}], "c": True, "d": "unicode ✓ فارسی"}
    await backend.set("nested", payload)
    assert await backend.get("nested") == payload


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------


async def test_window_counts_hits(backend: StateBackend) -> None:
    counts = [await backend.hit_window("u:1", 60, now=1000.0 + i) for i in range(3)]
    assert counts == [1, 2, 3]


async def test_window_forgets_old_hits(backend: StateBackend) -> None:
    for i in range(5):
        await backend.hit_window("u:2", 60, now=1000.0 + i)

    # Far enough ahead that every earlier hit has left the window.
    assert await backend.hit_window("u:2", 60, now=2000.0) == 1


async def test_window_is_per_key(backend: StateBackend) -> None:
    await backend.hit_window("u:3", 60, now=1000.0)
    await backend.hit_window("u:3", 60, now=1001.0)
    assert await backend.hit_window("u:4", 60, now=1001.0) == 1


async def test_simultaneous_hits_are_counted_separately(
    backend: StateBackend,
) -> None:
    """Two hits at an identical timestamp must count as two.

    In a sorted set, identical members collapse -- which would under-count
    exactly the burst a rate limiter exists to catch.
    """
    first = await backend.hit_window("u:5", 60, now=1000.0)
    second = await backend.hit_window("u:5", 60, now=1000.0)
    assert (first, second) == (1, 2)


async def test_window_boundary_is_exclusive(backend: StateBackend) -> None:
    """A hit exactly one window old has left the window."""
    await backend.hit_window("u:6", 60, now=1000.0)
    assert await backend.hit_window("u:6", 60, now=1060.0) == 1


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_no_redis_url_falls_back_to_memory() -> None:
    assert isinstance(build_state_backend(None), InMemoryStateBackend)
    assert isinstance(build_state_backend(""), InMemoryStateBackend)


def test_redis_url_selects_redis() -> None:
    pytest.importorskip("redis")
    backend = build_state_backend("redis://localhost:6379/0")
    assert isinstance(backend, RedisStateBackend)


def test_both_backends_satisfy_the_protocol() -> None:
    pytest.importorskip("redis")
    assert isinstance(InMemoryStateBackend(), StateBackend)
    assert isinstance(build_state_backend("redis://localhost:6379/0"), StateBackend)


def test_state_module_does_not_import_telegram() -> None:
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent / "core" / "state.py"
    ).read_text()
    assert "import telegram" not in source
    assert "from telegram" not in source
