"""
Database connection module for async operations.
PRD v2: Updated with sync engine support for migrations.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Callable, Any
from weakref import WeakKeyDictionary
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
    AsyncSession,
)
from sqlalchemy import create_engine as create_sync_engine
from db.models import Base
from db.url import normalize_db_url


logger = logging.getLogger("coord_bot.db")

# Async engines are cached per (event loop, URL), never by URL alone.
#
# An asyncpg connection pool binds to the event loop that created it. Caching
# by URL alone hands an engine built on loop A to a caller running on loop B,
# which fails with "got Future attached to a different loop" -- and it fails
# at *query* time, far from the cause. That is why the lifecycle tests could
# never run: pytest-asyncio gives each test its own loop.
#
# The same trap is waiting in production for anything that owns its own loop:
# a Gunicorn/Uvicorn worker restart, a scheduler thread, or Alembic (which
# calls asyncio.run()). Keying on the loop makes the cache correct by
# construction instead of relying on every caller to know the rule.
#
# WeakKeyDictionary so a finished loop's engines become collectable with it
# rather than pinning pools for the process lifetime.
_engines: "WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, AsyncEngine]]" = (
    WeakKeyDictionary()
)
_sync_engines: dict[str, Any] = {}


# Re-exported so callers can normalize without reaching past db.connection.
__all__ = [
    "create_engine",
    "get_sync_engine",
    "create_session",
    "get_session",
    "check_db_connection",
    "normalize_db_url",
    "wait_for_db",
    "retry_operation",
    "init_db",
    "dispose_engines",
]


def _engine_kwargs() -> dict[str, Any]:
    """Pool configuration, read at call time so tests can override env."""
    from config.settings import settings

    return {
        "echo": settings.db_echo,
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_recycle": settings.db_pool_recycle,
        "pool_timeout": settings.db_pool_timeout,
    }


def create_engine(db_url: str) -> AsyncEngine:
    """Create or retrieve the async engine for this URL on the running loop.

    Must be called from within a running event loop. The engine is scoped to
    that loop; see the note on ``_engines`` for why URL-only caching is unsafe.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop: the caller is outside async context (startup
        # scripts, sync tooling). Build an uncached engine so we never seed
        # the cache with an engine bound to a loop that is about to be
        # replaced -- that is exactly how the stale-binding bug propagates.
        logger.debug("create_engine() called with no running loop; not caching")
        return create_async_engine(db_url, **_engine_kwargs())

    per_loop = _engines.get(loop)
    if per_loop is None:
        per_loop = {}
        _engines[loop] = per_loop

    if db_url not in per_loop:
        per_loop[db_url] = create_async_engine(db_url, **_engine_kwargs())
    return per_loop[db_url]


async def dispose_engines() -> None:
    """Dispose every engine cached for the running loop.

    Call on shutdown so connections are returned to PostgreSQL promptly
    instead of lingering until the server's own idle timeout -- which matters
    when many instances cycle at once during a rolling deploy.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    per_loop = _engines.pop(loop, None)
    if not per_loop:
        return
    for engine in per_loop.values():
        try:
            await engine.dispose()
        except Exception:  # shutdown must not raise
            logger.debug("Engine dispose failed", exc_info=True)


def get_sync_engine(db_url: str) -> Any:
    """Create or retrieve cached sync database engine (for migrations)."""
    if db_url not in _sync_engines:
        _sync_engines[db_url] = create_sync_engine(
            db_url, echo=False, pool_pre_ping=True, pool_size=5, max_overflow=10
        )
    return _sync_engines[db_url]


def create_session(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session(db_url: str):
    """Get an async database session context manager."""
    engine = create_engine(db_url)
    Session = create_session(engine)
    async with Session() as session:
        try:
            yield session
        except Exception as e:
            logger.debug("Database session error: %s", e)
            raise


async def check_db_connection(db_url: str) -> tuple[bool, str]:
    """Check if database connection is available.

    Uses a throwaway NullPool engine rather than the module-level cache.
    Cached asyncpg engines stay bound to the event loop that created them, so
    reusing one from a different loop fails with "attached to a different
    loop" -- which this function would then report as "database unavailable",
    a false negative in the check that gates startup and the drift tooling.
    """
    from sqlalchemy import text
    from sqlalchemy.pool import NullPool

    engine = None
    try:
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True, "Database connection OK"
    except Exception as e:
        return False, f"Database connection failed: {type(e).__name__}: {e}"
    finally:
        if engine is not None:
            await engine.dispose()


async def retry_operation(
    operation: Callable,
    max_retries: int = 3,
    retry_delay: float = 0.5,
    db_url: str | None = None,
) -> Any:
    """Retry a database operation with exponential backoff."""
    import asyncio

    for attempt in range(max_retries):
        try:
            if db_url:
                async with get_session(db_url) as session:
                    return await operation(session)
            return await operation()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(
                    "Operation failed after %d attempts: %s",
                    max_retries,
                    type(e).__name__,
                    exc_info=True,
                )
                raise
            logger.warning(
                "Database operation failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                type(e).__name__,
            )
            await asyncio.sleep(retry_delay * (2**attempt))


async def wait_for_db(
    db_url: str,
    max_attempts: int = 30,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
) -> None:
    """Block until the database accepts connections.

    Containers routinely start before PostgreSQL is ready. Without this the
    process dies on an unhandled connection error at boot and relies on the
    orchestrator's restart loop to paper over it.

    Raises the last connection error if the database never becomes reachable.
    """
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        ok, message = await check_db_connection(db_url)
        if ok:
            if attempt > 1:
                logger.info("Database reachable after %d attempts", attempt)
            return
        if attempt == max_attempts:
            raise RuntimeError(
                f"Database unreachable after {max_attempts} attempts: {message}"
            )
        logger.warning(
            "Database not ready (attempt %d/%d), retrying in %.1fs: %s",
            attempt,
            max_attempts,
            delay,
            message,
        )
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables directly from the models, bypassing migrations.

    DEPRECATED for application startup -- use db.migrate.run_migrations().
    create_all() only ever creates *missing tables*; it silently ignores
    columns added to existing ones, which is why schema changes previously
    needed hand-run scripts.

    Retained for tests and tooling that want a throwaway schema without a
    migration history. A database built this way has no alembic_version, so
    run_migrations() will adopt it via the baseline stamp on first run.

    Args:
        engine: SQLAlchemy async engine for database operations
    """
    async with engine.begin() as conn:
        # Create PostgreSQL enum types first (must match SQLAlchemy SQLEnum name= parameter)
        await conn.execute(
            text(
                """
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'participant_status') THEN
                    CREATE TYPE participant_status AS ENUM ('joined', 'confirmed', 'cancelled', 'no_show');
                END IF;
            END $$;
        """
            )
        )

        await conn.execute(
            text(
                """
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'participant_role') THEN
                    CREATE TYPE participant_role AS ENUM ('organizer', 'participant', 'observer');
                END IF;
            END $$;
        """
            )
        )

        # Then create all tables
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")
