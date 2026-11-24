"""Schema migrations via Alembic.

Replaces the previous ``Base.metadata.create_all`` bootstrap. create_all only
ever creates *missing tables* -- it never adds a column to an existing one, so
every schema change since the first deploy needed a hand-written script
(add_admin_column.py, add_language_column.py, add_v2_columns.py, ...). Those
scripts had to be remembered and run by hand, in order, on every environment.

Adoption safety
---------------
An existing database already has all the tables but no alembic_version, so a
plain ``upgrade head`` would try to CREATE TABLE over live data and fail. When
that state is detected we *stamp* the baseline instead -- recording "this
database already looks like revision X" without executing it -- and then apply
anything newer. That makes adoption a no-op for a running deployment.
"""

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from db.url import normalize_db_url

logger = logging.getLogger("coord_bot.db")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

# The revision that reproduces the pre-Alembic schema exactly. A database
# containing these tables but no alembic_version is stamped here.
BASELINE_REVISION = "2120cd3866bc"

# Tables that must exist for a database to count as "already provisioned".
_CORE_TABLES = ("events", "users", "groups", "event_participants")


def _async_url(db_url: str) -> str:
    """Return the async URL used for all database access here.

    Inspection deliberately uses the *async* driver rather than psycopg2:
    psycopg2-binary is a dev-only dependency, so a sync engine would fail at
    startup inside the runtime container, which ships asyncpg alone.
    """
    return normalize_db_url(db_url) or db_url


def _alembic_config(db_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "db" / "migrations"))
    # env.py prefers this over DB_URL in the environment, so a programmatic
    # caller always targets the database it asked for.
    config.set_main_option("sqlalchemy.url", _async_url(db_url))
    return config


def _read_state(connection) -> tuple[bool, bool, str | None]:
    """Sync callback run inside the async connection."""
    tables = set(inspect(connection).get_table_names())
    has_version = "alembic_version" in tables
    has_core = all(t in tables for t in _CORE_TABLES)
    current = None
    if has_version:
        current = MigrationContext.configure(connection).get_current_revision()
    return has_version, has_core, current


def _inspect_state(db_url: str) -> tuple[bool, bool, str | None]:
    """Return (has_alembic_version, has_core_tables, current_revision)."""

    async def _run() -> tuple[bool, bool, str | None]:
        engine = create_async_engine(_async_url(db_url), poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read_state)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def run_migrations(db_url: str, revision: str = "head") -> None:
    """Bring the database to `revision` (the latest by default).

    Safe to call on every boot: it is a no-op once the database is current.
    Synchronous by design -- Alembic drives its own event loop through env.py,
    so this must not be called from inside a running loop.

    A non-head `revision` moves in whichever direction is required, so callers
    can pin a deployment to a known revision or step back from a bad one
    without needing to know where the database currently sits. Tests use it to
    build a database at an earlier revision and migrate forward over seeded
    data.
    """
    config = _alembic_config(db_url)
    has_version, has_core, current = _inspect_state(db_url)

    if not has_version and has_core:
        # Pre-Alembic database: adopt it without re-running the baseline.
        logger.info(
            "Existing schema found without migration history. "
            "Stamping baseline %s before upgrading.",
            BASELINE_REVISION,
        )
        command.stamp(config, BASELINE_REVISION)
    elif not has_version:
        logger.info("Fresh database detected; applying all migrations.")
    else:
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()
        # An empty versions directory has no head; nothing to move toward.
        target = (head if revision == "head" else revision) or revision
        if current == target:
            logger.info("Database schema is up to date (revision %s).", current)
            return
        # Walking back from the target tells us whether it sits ahead of or
        # behind where we are; Alembic has no "go to this revision" command.
        ancestors = {rev.revision for rev in script.iterate_revisions(target, "base")}
        if current in ancestors:
            logger.info("Upgrading schema from %s to %s.", current, target)
        else:
            logger.info("Downgrading schema from %s to %s.", current, target)
            command.downgrade(config, target)
            logger.info("Database migrations complete.")
            return

    command.upgrade(config, revision)
    logger.info("Database migrations complete.")


def check_drift(db_url: str) -> list[str]:
    """Report differences between the live schema and the models.

    Stamping a pre-Alembic database asserts that it already matches the
    baseline. If years of hand-run column scripts left it slightly different,
    that mismatch is otherwise invisible until a query fails in production.
    This surfaces it as a list of human-readable differences (empty == clean).

    Run via: python -m scripts.check_schema_drift
    """
    from alembic.autogenerate import compare_metadata

    from db.models import Base

    def _compare(connection):
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "include_object": (
                    lambda obj, name, type_, reflected, compare_to: not (
                        type_ == "table" and name == "alembic_version"
                    )
                ),
            },
        )
        return compare_metadata(context, Base.metadata)

    async def _run():
        engine = create_async_engine(_async_url(db_url), poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_compare)
        finally:
            await engine.dispose()

    return [_describe_diff(d) for d in asyncio.run(_run())]


def _describe_diff(diff) -> str:
    """Render one autogenerate diff tuple as a readable line."""
    if isinstance(diff, list):
        return "; ".join(_describe_diff(d) for d in diff)
    kind = diff[0]
    if kind in ("add_table", "remove_table"):
        return f"{kind}: {diff[1].name}"
    if kind in ("add_column", "remove_column"):
        return f"{kind}: {diff[2]}.{diff[3].name}"
    # modify_type / modify_nullable / modify_default share a shape:
    # (kind, schema, table, column, opts, old_value, new_value)
    if kind.startswith("modify_") and len(diff) >= 7:
        return f"{kind}: {diff[2]}.{diff[3]} {diff[5]} -> {diff[6]}"
    if kind in ("add_index", "remove_index", "add_constraint", "remove_constraint"):
        obj = diff[1]
        name = getattr(obj, "name", None)
        table = getattr(getattr(obj, "table", None), "name", None)
        columns = ", ".join(c.name for c in getattr(obj, "columns", []))
        # Unnamed constraints report name=None; the table and columns are what
        # actually identify them to a human.
        label = name or (f"{table}({columns})" if table else str(obj))
        detail = f" on {table}({columns})" if name and table else ""
        return f"{kind}: {label}{detail}"
    return str(kind)
