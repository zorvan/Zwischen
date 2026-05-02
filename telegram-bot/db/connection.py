"""
Database connection module for async operations.
PRD v2: Updated with sync engine support for migrations.
"""

import logging
from contextlib import asynccontextmanager
from typing import Callable, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
    AsyncSession,
)
from sqlalchemy import create_engine as create_sync_engine
from db.models import Base


logger = logging.getLogger("coord_bot.db")

# Cache engines by URL to avoid recreating them
_engines: dict[str, AsyncEngine] = {}
_sync_engines: dict[str, Any] = {}


def create_engine(db_url: str) -> AsyncEngine:
    """Create or retrieve cached async database engine."""
    if db_url not in _engines:
        _engines[db_url] = create_async_engine(
            db_url, echo=False, pool_pre_ping=True, pool_size=10, max_overflow=20
        )
    return _engines[db_url]


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
    """Check if database connection is available."""
    from sqlalchemy import text

    try:
        engine = create_engine(db_url)
        Session = create_session(engine)
        async with Session() as session:
            await session.execute(text("SELECT 1"))
        return True, "Database connection OK"
    except Exception as e:
        return False, f"Database connection failed: {type(e).__name__}: {e}"


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


async def init_db(engine: AsyncEngine) -> None:
    """Initialize database by creating all tables from models.

    Args:
        engine: SQLAlchemy async engine for database operations

    Note:
        Database schema is defined in:
        - SQLAlchemy models (db/models.py) - Primary source
        - Schema reference (db/schema.sql) - Documentation
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
