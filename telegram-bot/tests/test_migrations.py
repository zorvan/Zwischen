"""Tests for the Alembic migration setup.

The structural tests run without a database. The end-to-end adoption test is
marked `integration` and skips when no database is reachable.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import migrate  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_alembic_config_exists() -> None:
    assert migrate.ALEMBIC_INI.exists(), "alembic.ini is missing"
    assert (PROJECT_ROOT / "db" / "migrations" / "env.py").exists()


def test_exactly_one_head() -> None:
    """Multiple heads mean `upgrade head` is ambiguous and will fail.

    This is the usual result of two branches each adding a migration.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(migrate.ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "db" / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected a single head, found {heads}"


def test_baseline_revision_is_present() -> None:
    """The stamp target must exist, or adoption of a live database fails."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(migrate.ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "db" / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(migrate.BASELINE_REVISION) is not None


def test_baseline_covers_every_model_table() -> None:
    """The baseline must create every table the models declare.

    A model added without a migration would otherwise only surface as a
    missing-table error at runtime.
    """
    from db.models import Base

    baseline = next(
        (PROJECT_ROOT / "db" / "migrations" / "versions").glob(
            f"{migrate.BASELINE_REVISION}_*.py"
        )
    )
    source = baseline.read_text(encoding="utf-8")

    missing = [
        name
        for name in Base.metadata.tables
        if f"'{name}'" not in source and f'"{name}"' not in source
    ]
    assert not missing, f"baseline migration does not create: {missing}"


def test_inspection_uses_an_async_driver() -> None:
    """Inspection must not need psycopg2, which is a dev-only dependency.

    A sync engine here would crash at startup in the runtime container, which
    ships asyncpg alone.
    """
    assert migrate._async_url("postgresql+asyncpg://u:p@h/d").startswith(
        "postgresql+asyncpg://"
    )
    # A bare URL is normalized to whichever async driver is installed.
    assert "+asyncpg" in migrate._async_url("postgresql://u:p@h/d") or (
        "+psycopg" in migrate._async_url("postgresql://u:p@h/d")
    )
    assert "psycopg2" not in migrate._async_url("postgresql://u:p@h/d")


@pytest.mark.integration
def test_migration_adopts_existing_database() -> None:
    """A pre-Alembic database is stamped, not recreated, and keeps its data."""
    import asyncio
    import uuid

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from db.connection import check_db_connection, create_engine, init_db
    from db.url import normalize_db_url

    base_url = normalize_db_url(
        os.getenv(
            "DB_URL", "postgresql://coord_user:coord_pass@localhost:5432/coord_db"
        )
    )
    assert base_url

    ok, message = asyncio.run(check_db_connection(base_url))
    if not ok:
        pytest.skip(f"No database available: {message}")

    # Work in a throwaway database so the developer's data is never touched.
    db_name = f"test_adopt_{uuid.uuid4().hex[:8]}"
    admin_url = base_url.rsplit("/", 1)[0] + "/postgres"
    target = base_url.rsplit("/", 1)[0] + "/" + db_name

    async def admin_exec(*statements: str) -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                for statement in statements:
                    await conn.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(admin_exec(f'CREATE DATABASE "{db_name}"'))

    try:
        # Build it the old way: tables, data, and no alembic_version.
        async def build() -> None:
            engine = create_engine(target)
            await init_db(engine)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO groups (telegram_group_id, group_name, "
                        "group_type) VALUES (-1, 'kept', 'casual')"
                    )
                )
            await engine.dispose()

        asyncio.run(build())

        migrate.run_migrations(target)

        async def read_back() -> tuple[str | None, str | None]:
            engine = create_async_engine(target)
            try:
                async with engine.connect() as conn:
                    revision = (
                        await conn.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).scalar()
                    kept = (
                        await conn.execute(
                            text(
                                "SELECT group_name FROM groups "
                                "WHERE telegram_group_id = -1"
                            )
                        )
                    ).scalar()
                    return revision, kept
            finally:
                await engine.dispose()

        revision, kept = asyncio.run(read_back())

        assert revision is not None, "database was not stamped"
        assert kept == "kept", "adoption destroyed existing data"

        # Second run must be a no-op, and the result must match the models.
        migrate.run_migrations(target)
        assert not migrate.check_drift(target), "schema drifted from models"
    finally:
        asyncio.run(
            admin_exec(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{db_name}'",
                f'DROP DATABASE IF EXISTS "{db_name}"',
            )
        )
