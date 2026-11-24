"""Connection budget, PgBouncer compatibility and pool-exhaustion signals (T14).

The arithmetic that matters::

    peak server connections = processes × (DB_POOL_SIZE + DB_MAX_OVERFLOW)

and it must stay below PostgreSQL's ``max_connections`` minus the slots
reserved for superusers and maintenance. ``check_connection_budget`` does that
sum at startup against the live server and logs the result, so an
over-subscribed deployment is reported at boot instead of as
connection-refused under load.

Pools are per process *and* per event loop (see ``db.connection``). The bot
and the API each run one loop per process, so "processes" is the number of
bot replicas plus API workers that share the database.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

logger = logging.getLogger("coord_bot.db.pool")

#: Connections kept free beyond superuser_reserved_connections, for psql,
#: migrations, backups and the monitoring agent.
MAINTENANCE_HEADROOM = 5


class PoolExhaustedError(RuntimeError):
    """No pooled connection became free within DB_POOL_TIMEOUT.

    Raised instead of SQLAlchemy's generic TimeoutError so the log line says
    what to change, and counted in ``pool_stats()``.
    """


# -- PgBouncer --------------------------------------------------------------


def pgbouncer_connect_args() -> dict[str, Any]:
    """asyncpg settings that survive PgBouncer transaction pooling.

    Transaction mode hands each transaction a possibly different server
    connection, so a statement prepared on one is unknown on the next, and a
    reused name collides: ``prepared statement "__asyncpg_stmt_x__" already
    exists``. Disabling asyncpg's statement cache and giving every prepared
    statement a unique name avoids both.
    """
    return {
        # asyncpg's own statement cache.
        "statement_cache_size": 0,
        # SQLAlchemy's asyncpg adapter keeps a second cache; the dialect pops
        # this (and the name function) from the connect arguments.
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4().hex}__",
    }


def engine_options(settings: Any) -> dict[str, Any]:
    """create_async_engine kwargs for these settings."""
    options: dict[str, Any] = {
        "echo": settings.db_echo,
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_recycle": settings.db_pool_recycle,
        "pool_timeout": settings.db_pool_timeout,
    }
    if settings.db_pgbouncer:
        options["connect_args"] = pgbouncer_connect_args()
    return options


# -- the budget --------------------------------------------------------------


@dataclass(frozen=True)
class ConnectionBudget:
    processes: int
    pool_size: int
    max_overflow: int
    max_connections: int
    reserved: int

    @property
    def per_process(self) -> int:
        return self.pool_size + self.max_overflow

    @property
    def peak(self) -> int:
        return self.processes * self.per_process

    @property
    def available(self) -> int:
        return self.max_connections - self.reserved - MAINTENANCE_HEADROOM

    @property
    def fits(self) -> bool:
        return self.peak <= self.available

    @property
    def max_processes(self) -> int:
        return max(self.available // max(self.per_process, 1), 0)

    def describe(self) -> str:
        return (
            f"{self.processes} process(es) × ({self.pool_size} pool + "
            f"{self.max_overflow} overflow) = {self.peak} peak connections; "
            f"server allows {self.available} "
            f"(max_connections {self.max_connections} − {self.reserved} reserved "
            f"− {MAINTENANCE_HEADROOM} headroom); "
            f"at this pool size at most {self.max_processes} process(es) fit"
        )


async def check_connection_budget(
    engine: AsyncEngine, settings: Any
) -> Optional[ConnectionBudget]:
    """Compare the configured peak with the server's limit and log it.

    Returns the budget, or None when the check does not apply: behind
    PgBouncer the application's connections are PgBouncer clients, and the
    server-side ceiling is PgBouncer's ``default_pool_size``, not ours.
    """
    if settings.db_pgbouncer:
        logger.info(
            "Connection budget: behind PgBouncer; size its default_pool_size "
            "against max_connections instead"
        )
        return None
    async with engine.connect() as connection:
        max_connections = int(
            (await connection.execute(text("SHOW max_connections"))).scalar() or 0
        )
        reserved = int(
            (
                await connection.execute(text("SHOW superuser_reserved_connections"))
            ).scalar()
            or 0
        )
    budget = ConnectionBudget(
        processes=settings.db_processes,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        max_connections=max_connections,
        reserved=reserved,
    )
    if budget.fits:
        logger.info("Connection budget OK: %s", budget.describe())
    else:
        logger.error(
            "Connection budget EXCEEDED: %s. Lower DB_POOL_SIZE/DB_MAX_OVERFLOW, "
            "raise max_connections, or put PgBouncer in front (DB_PGBOUNCER=true).",
            budget.describe(),
        )
    return budget


def check_recycle(settings: Any) -> bool:
    """DB_POOL_RECYCLE must be shorter than every idle timeout in the path."""
    idle = settings.db_idle_timeout
    if idle is None:
        return True
    if settings.db_pool_recycle >= idle:
        logger.error(
            "DB_POOL_RECYCLE (%ss) is not shorter than DB_IDLE_TIMEOUT (%ss): "
            "pooled connections will be handed out after the proxy closed them.",
            settings.db_pool_recycle,
            idle,
        )
        return False
    return True


# -- runtime signals -----------------------------------------------------------


class _PoolStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.checkouts = 0
        self.saturated = 0
        self.exhausted = 0

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "checkouts": self.checkouts,
                "saturated": self.saturated,
                "exhausted": self.exhausted,
            }

    def record_checkout(self, saturated: bool) -> None:
        with self._lock:
            self.checkouts += 1
            self.saturated += int(saturated)

    def record_exhausted(self) -> None:
        with self._lock:
            self.exhausted += 1


_stats = _PoolStats()


def pool_stats() -> dict[str, int]:
    """Process-wide pool counters since start (for /health and logs).

    ``saturated`` counts checkouts that took the last free connection;
    a rising rate is the leading indicator of exhaustion. ``exhausted``
    counts PoolExhaustedError raised.
    """
    return _stats.snapshot()


def instrument(engine: AsyncEngine) -> None:
    """Count checkouts and warn when a pool hands out its last connection."""
    pool: Any = engine.sync_engine.pool
    if not isinstance(pool, QueuePool):
        return  # NullPool / StaticPool: nothing to saturate

    @event.listens_for(pool, "checkout")
    def _on_checkout(dbapi_conn: Any, record: Any, proxy: Any) -> None:
        capacity = pool.size() + max(getattr(pool, "_max_overflow", 0), 0)
        saturated = capacity > 0 and pool.checkedout() >= capacity
        _stats.record_checkout(saturated)
        if saturated:
            logger.warning(
                "DB pool saturated",
                extra={"checked_out": pool.checkedout(), "capacity": capacity},
            )


def exhausted(error: Exception, settings: Any) -> PoolExhaustedError:
    """Translate SQLAlchemy's pool TimeoutError into an actionable error."""
    _stats.record_exhausted()
    message = (
        f"Database pool exhausted: no connection free within "
        f"{settings.db_pool_timeout}s (DB_POOL_SIZE={settings.db_pool_size}, "
        f"DB_MAX_OVERFLOW={settings.db_max_overflow}). Requests are holding "
        f"connections longer than the pool can absorb."
    )
    logger.error(message, extra={"pool": pool_stats()})
    return PoolExhaustedError(message)
