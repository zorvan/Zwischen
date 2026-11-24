"""T14: connection budget, PgBouncer settings and pool exhaustion."""

from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from db import pool_budget
from db.pool_budget import (
    ConnectionBudget,
    PoolExhaustedError,
    check_connection_budget,
    check_recycle,
    engine_options,
)


def make_settings(**overrides: Any) -> Any:
    values = {
        "db_echo": False,
        "db_pool_size": 10,
        "db_max_overflow": 20,
        "db_pool_recycle": 1800,
        "db_pool_timeout": 30,
        "db_pgbouncer": False,
        "db_processes": 1,
        "db_idle_timeout": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_budget_arithmetic_matches_the_ticket() -> None:
    # The ticket's example: 4 instances at defaults is 120 against 100.
    budget = ConnectionBudget(
        processes=4, pool_size=10, max_overflow=20, max_connections=100, reserved=3
    )
    assert budget.peak == 120
    assert budget.available == 100 - 3 - pool_budget.MAINTENANCE_HEADROOM
    assert not budget.fits
    assert budget.max_processes == 3
    assert "4 process(es)" in budget.describe()

    smaller = ConnectionBudget(
        processes=4, pool_size=5, max_overflow=5, max_connections=100, reserved=3
    )
    assert smaller.fits and smaller.peak == 40


def test_pgbouncer_mode_disables_prepared_statement_caches() -> None:
    plain = engine_options(make_settings())
    assert "connect_args" not in plain

    bounced = engine_options(make_settings(db_pgbouncer=True))
    assert bounced["connect_args"]["statement_cache_size"] == 0
    assert bounced["connect_args"]["prepared_statement_cache_size"] == 0
    name = bounced["connect_args"]["prepared_statement_name_func"]
    assert name() != name(), "statement names must be unique per prepare"


def test_recycle_must_be_shorter_than_idle_timeouts() -> None:
    assert check_recycle(make_settings())  # unknown idle timeout: nothing to check
    assert check_recycle(make_settings(db_pool_recycle=300, db_idle_timeout=600))
    assert not check_recycle(make_settings(db_pool_recycle=1800, db_idle_timeout=600))


@pytest.mark.integration
async def test_startup_budget_check_reads_the_server(test_db_url: str) -> None:
    engine = create_async_engine(test_db_url)
    try:
        ok = await check_connection_budget(engine, make_settings(db_processes=1))
        assert ok is not None and ok.fits and ok.max_connections > 0
        too_many = await check_connection_budget(
            engine, make_settings(db_processes=1000)
        )
        assert too_many is not None and not too_many.fits
        assert (
            await check_connection_budget(engine, make_settings(db_pgbouncer=True))
            is None
        )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_exhaustion_fails_fast_with_a_clear_error(
    test_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import config.settings as settings_module
    from db.connection import dispose_engines, get_session

    for name, value in {
        "db_pool_size": 1,
        "db_max_overflow": 0,
        "db_pool_timeout": 1,
    }.items():
        monkeypatch.setattr(settings_module.settings, name, value)
    await dispose_engines()  # build the engine with the tiny pool
    before = pool_budget.pool_stats()

    holder_ready = asyncio.Event()
    release = asyncio.Event()

    async def hold_the_only_connection() -> None:
        async with get_session(test_db_url) as session:
            await session.execute(text("SELECT 1"))
            holder_ready.set()
            await release.wait()

    holder = asyncio.create_task(hold_the_only_connection())
    await holder_ready.wait()
    started = time.monotonic()
    with pytest.raises(PoolExhaustedError, match="DB_POOL_SIZE=1"):
        async with get_session(test_db_url) as session:
            await session.execute(text("SELECT 2"))
    elapsed = time.monotonic() - started
    release.set()
    await holder

    assert elapsed < 5, "exhaustion must surface after DB_POOL_TIMEOUT, not hang"
    after = pool_budget.pool_stats()
    assert after["exhausted"] == before["exhausted"] + 1
    assert after["saturated"] > before["saturated"]


async def _concurrent_load(url: str, options: dict[str, Any], workers: int) -> int:
    """Many tasks, varied statements, short transactions; returns queries run."""
    engine = create_async_engine(url, **options)
    done = 0

    async def worker(n: int) -> None:
        nonlocal done
        for round_ in range(10):
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT CAST(:n AS integer) + CAST(:r AS integer)"),
                    {"n": n, "r": round_},
                )
                await conn.execute(
                    text(
                        "SELECT count(*) FROM generate_series(1, CAST(:k AS integer))"
                    ),
                    {"k": (n % 7) + 1},
                )
                done += 2

    try:
        await asyncio.gather(*(worker(n) for n in range(workers)))
    finally:
        await engine.dispose()
    return done


@pytest.mark.integration
async def test_pgbouncer_options_hold_under_concurrent_load(test_db_url: str) -> None:
    """Against PostgreSQL directly: the options must not break anything."""
    options = engine_options(
        make_settings(db_pgbouncer=True, db_pool_size=5, db_max_overflow=5)
    )
    assert await _concurrent_load(test_db_url, options, workers=40) == 40 * 10 * 2


@pytest.mark.skipif(
    not os.environ.get("PGBOUNCER_TEST_URL"),
    reason="set PGBOUNCER_TEST_URL to a transaction-mode PgBouncer to run",
)
async def test_through_real_pgbouncer_transaction_mode() -> None:
    """The verification T14 asks for. Needs a PgBouncer in transaction mode
    with fewer server connections than workers, e.g. default_pool_size=5."""
    from db.url import normalize_db_url

    url = normalize_db_url(os.environ["PGBOUNCER_TEST_URL"])
    assert url
    options = engine_options(
        make_settings(db_pgbouncer=True, db_pool_size=20, db_max_overflow=20)
    )
    assert await _concurrent_load(url, options, workers=40) == 40 * 10 * 2


@pytest.mark.integration
async def test_health_reports_pool_counters(test_db_url: str) -> None:
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    from api.app import create_app

    app = create_app(
        db_url=test_db_url,
        bot_token="1:x",
        auth_secret="health-secret-32-bytes-long!!!!",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["db_pool"]) == {"checkouts", "saturated", "exhausted"}
