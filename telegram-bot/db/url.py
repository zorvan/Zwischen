"""Database URL normalization.

Deliberately dependency-free (stdlib only) so both config.settings and
db.connection can import it without creating an import cycle.
"""

import importlib.util


def available_async_driver() -> str:
    """Return the async PostgreSQL driver actually installed.

    requirements.txt installs asyncpg on Python < 3.14 and psycopg on
    Python >= 3.14, so the driver cannot be hardcoded.
    """
    if importlib.util.find_spec("asyncpg") is not None:
        return "asyncpg"
    if importlib.util.find_spec("psycopg") is not None:
        return "psycopg"
    raise RuntimeError(
        "No async PostgreSQL driver installed. Install asyncpg (Python < 3.14) "
        "or psycopg[binary] (Python >= 3.14)."
    )


def normalize_db_url(db_url: str | None) -> str | None:
    """Ensure DB_URL names an async driver SQLAlchemy can use.

    A bare "postgresql://" URL -- what docker-compose and most hosted database
    add-ons hand you -- selects SQLAlchemy's *sync* psycopg2 dialect, which
    create_async_engine() cannot drive. Rewrite it to whichever async driver is
    installed rather than assuming asyncpg.

    This runs in Settings.__init__ so that all ~90 call sites reading
    settings.db_url get a usable URL, not just the startup path.
    """
    if not db_url:
        return db_url
    if db_url.startswith("postgresql+"):
        return db_url
    if db_url.startswith("postgresql://"):
        return db_url.replace(
            "postgresql://", f"postgresql+{available_async_driver()}://", 1
        )
    if db_url.startswith("postgres://"):
        # Heroku-style scheme; SQLAlchemy does not accept it at all.
        return db_url.replace(
            "postgres://", f"postgresql+{available_async_driver()}://", 1
        )
    return db_url
