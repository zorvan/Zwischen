"""Focused acceptance tests for the multi-instance Tier 0 work."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from bot.common.rate_limiter import RateLimiter
from bot.common import scheduler
from config.settings import Settings
from core.persistence import StateBackendPersistence
from core.state import InMemoryStateBackend


async def test_two_persistence_instances_share_user_flow() -> None:
    backend = InMemoryStateBackend()
    first = StateBackendPersistence(backend)
    second = StateBackendPersistence(backend)

    await first.update_user_data(42, {"creation_step": "time", "title": "Dinner"})
    state_on_second: dict = {}
    await second.refresh_user_data(42, state_on_second)

    assert state_on_second == {"creation_step": "time", "title": "Dinner"}


async def test_shared_rate_limiter_counts_across_instances() -> None:
    backend = InMemoryStateBackend()
    first = RateLimiter(backend)
    second = RateLimiter(backend)
    first.ACTION_LIMITS = {"message": {"limit": 1, "window": 60}}
    second.ACTION_LIMITS = first.ACTION_LIMITS

    assert await first.check_rate_limit(user_id=7) == (True, None)
    assert await second.check_rate_limit(user_id=7) == (False, 60)


def test_webhook_mode_is_independent_of_environment(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("WEBHOOK_MODE", "true")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.test/telegram-webhook")
    assert Settings().webhook_mode is True


def test_production_still_defaults_to_webhook(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("WEBHOOK_MODE", raising=False)
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    assert Settings().webhook_mode is True


class _LockState:
    locked = False


class _Connection:
    def __init__(self, state: _LockState) -> None:
        self.state = state

    async def scalar(self, statement, parameters) -> bool:
        if self.state.locked:
            return False
        self.state.locked = True
        return True

    async def execute(self, statement, parameters) -> None:
        self.state.locked = False


class _ConnectionContext:
    def __init__(self, state: _LockState) -> None:
        self.connection = _Connection(state)

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        # PostgreSQL releases a session lock when a connection dies.
        self.connection.state.locked = False


class _Engine:
    def __init__(self, state: _LockState) -> None:
        self.state = state

    def connect(self) -> _ConnectionContext:
        return _ConnectionContext(self.state)


async def test_concurrent_scheduler_ticks_elect_exactly_one(monkeypatch) -> None:
    state = _LockState()
    monkeypatch.setattr("db.connection.create_engine", lambda _url: _Engine(state))
    started = asyncio.Event()
    release = asyncio.Event()
    executions = 0

    async def work(bot, db_url) -> None:
        nonlocal executions
        executions += 1
        started.set()
        await release.wait()

    monkeypatch.setattr(scheduler, "_run_scheduled_tasks_unlocked", work)
    leader = asyncio.create_task(scheduler.run_scheduled_tasks(AsyncMock(), "db"))
    await started.wait()
    follower = await scheduler.run_scheduled_tasks(AsyncMock(), "db")
    release.set()

    assert follower is False
    assert await leader is True
    assert executions == 1


async def test_cancelled_scheduler_leader_releases_lock(monkeypatch) -> None:
    state = _LockState()
    monkeypatch.setattr("db.connection.create_engine", lambda _url: _Engine(state))
    started = asyncio.Event()

    async def interrupted(bot, db_url) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(scheduler, "_run_scheduled_tasks_unlocked", interrupted)
    leader = asyncio.create_task(scheduler.run_scheduled_tasks(AsyncMock(), "db"))
    await started.wait()
    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader

    monkeypatch.setattr(
        scheduler, "_run_scheduled_tasks_unlocked", AsyncMock(return_value=None)
    )
    assert await scheduler.run_scheduled_tasks(AsyncMock(), "db") is True
