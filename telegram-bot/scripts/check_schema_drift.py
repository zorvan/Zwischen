#!/usr/bin/env python3
"""Report differences between the live database schema and db/models.py.

Run this against a pre-Alembic database BEFORE first boot with migrations.
Adoption stamps the baseline, which asserts the database already matches the
models; if hand-run column scripts left it different, this is what tells you.

    .venv/bin/python -m scripts.check_schema_drift

Exit codes:
    0  schema matches the models
    1  differences found
    2  could not run the check (no DB_URL, database unreachable)
"""

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from db.migrate import check_drift  # noqa: E402

EXIT_CLEAN = 0
EXIT_DRIFT = 1
EXIT_UNAVAILABLE = 2


def redact(db_url: str) -> str:
    """Strip credentials so the target can be shown in output safely."""
    return re.sub(r"//[^/@]*@", "//", db_url)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if not settings.db_url:
        print("❌ DB_URL is not set. Add it to .env or the environment.")
        return EXIT_UNAVAILABLE

    target = redact(settings.db_url)

    try:
        differences = check_drift(settings.db_url)
    except Exception as exc:
        # A database that is simply not running is the overwhelmingly common
        # case here, and a bare traceback buries that in 60 lines of
        # SQLAlchemy/asyncpg frames. Report it as the operational condition it
        # is, and keep the detail on one line.
        print(f"❌ Could not reach the database at {target}")
        print(f"   {type(exc).__name__}: {_first_line(exc)}\n")
        print("   Is PostgreSQL running? For the local development database:")
        print("     ./resume.sh      # reuse the existing database and its data")
        print("     ./start.sh       # WARNING: resets the local database")
        print("   Or bring up the full stack: docker compose up -d db")
        return EXIT_UNAVAILABLE

    if not differences:
        print(f"✅ Schema at {target} matches db/models.py — no drift.")
        return EXIT_CLEAN

    print(f"⚠️  {len(differences)} difference(s) between {target} and db/models.py:\n")
    for line in differences:
        print(f"  - {line}")
    print(
        "\nResolve these before relying on migrations: either update db/models.py "
        "to match reality, or generate a migration that brings the database in "
        "line (alembic revision --autogenerate)."
    )
    return EXIT_DRIFT


def _first_line(exc: Exception) -> str:
    """Condense a multi-line driver error to its most useful line."""
    text = str(exc).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__


if __name__ == "__main__":
    sys.exit(main())
