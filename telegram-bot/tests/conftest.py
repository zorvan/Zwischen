"""Shared test fixtures.

Two problems this file exists to solve:

1. **The integration tests had no schema.** They connected to a database that
   nobody had migrated, so every scenario died on `relation "groups" does not
   exist` and was written off as an unverified scenario. The session fixture
   below builds a throwaway database and runs the real migrations against it,
   so the scenarios exercise the schema the application actually ships.

2. **They shared state.** Nothing reset the database between tests, so a
   second run saw the first run's rows and failed with MultipleResultsFound.
   `reset_database` truncates between tests, which is what makes the suite
   safe to run repeatedly and in any order.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.url import normalize_db_url  # noqa: E402


def _admin_url(url: str) -> str:
    return url.rsplit("/", 1)[0] + "/postgres"


def _base_url() -> str | None:
    """Server to create the throwaway test database on."""
    raw = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not raw:
        raw = os.environ.get(
            "DB_URL", "postgresql://coord_user:coord_pass@localhost:5432/coord_db"
        )
    return normalize_db_url(raw)


async def _run_sql(url: str, *statements: str, autocommit: bool = False) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    kwargs = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    engine = create_async_engine(url, **kwargs)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[str]:
    """A migrated, throwaway database for the whole session.

    Skips the dependent tests when no PostgreSQL is reachable, so the unit
    suite still runs on a machine with no database.
    """
    from db import migrate
    from db.connection import check_db_connection

    base = _base_url()
    if not base:
        pytest.skip("No database URL configured")

    ok, message = asyncio.run(check_db_connection(base))
    if not ok:
        pytest.skip(f"No database reachable: {message}")

    db_name = f"zwischen_test_{uuid.uuid4().hex[:8]}"
    admin = _admin_url(base)
    target = base.rsplit("/", 1)[0] + "/" + db_name

    asyncio.run(_run_sql(admin, f'CREATE DATABASE "{db_name}"', autocommit=True))
    try:
        # The real migrations, not create_all(): this is what proves the
        # migration chain and the models agree.
        migrate.run_migrations(target)
        os.environ["DATABASE_URL"] = target
        yield target
    finally:
        asyncio.run(
            _run_sql(
                admin,
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{db_name}'",
                f'DROP DATABASE IF EXISTS "{db_name}"',
                autocommit=True,
            )
        )


@pytest_asyncio.fixture(autouse=True)
async def reset_database(request) -> AsyncIterator[None]:
    """Truncate all data between tests, and drop this loop's engines after.

    Only engages for tests that ask for `test_db_url`; pure unit tests pay
    nothing. TRUNCATE ... CASCADE is used rather than per-table DELETE so the
    order of foreign keys does not matter.
    """
    if "test_db_url" not in request.fixturenames:
        yield
        return

    url = request.getfixturevalue("test_db_url")
    yield

    from db.connection import dispose_engines
    from db.models import Base

    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    try:
        await _run_sql(url, f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    finally:
        # Engines are cached per event loop; pytest-asyncio gives each test a
        # fresh loop, so without this the pools accumulate for the whole run.
        await dispose_engines()
