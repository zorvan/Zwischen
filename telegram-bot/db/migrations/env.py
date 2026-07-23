"""Alembic environment for the coordination bot.

Reads the database URL from the application's own settings (DB_URL in the
environment or .env) rather than alembic.ini, so migrations always target the
same database the bot uses and credentials live in exactly one place.
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make the project importable when alembic runs from the telegram-bot root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config.settings import settings  # noqa: E402
from db.models import Base  # noqa: E402
from db.url import normalize_db_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate compares against the SQLAlchemy models, which are the primary
# schema source (db/schema.sql is reference documentation only).
target_metadata = Base.metadata


def get_url() -> str:
    """Resolve the database URL.

    Precedence matters: a caller that passed an explicit URL (db/migrate.py
    sets it on the Config) must win over DB_URL in the environment. Otherwise
    .env silently redirects programmatic migrations at the wrong database --
    including tests, which would then migrate the developer's real database.
    """
    configured = config.get_main_option("sqlalchemy.url")
    if configured and not configured.startswith("driver://"):
        url = configured
    else:
        url = os.environ.get("DB_URL") or settings.db_url or ""

    if not url or url.startswith("driver://"):
        raise RuntimeError(
            "No database URL. Set DB_URL in the environment or .env before "
            "running alembic."
        )
    normalized = normalize_db_url(url)
    assert normalized is not None
    return normalized


def include_object(obj, name, type_, reflected, compare_to):
    """Keep autogenerate focused on tables the models own."""
    # alembic_version is managed by alembic itself.
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL without connecting (alembic upgrade --sql)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against an async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
