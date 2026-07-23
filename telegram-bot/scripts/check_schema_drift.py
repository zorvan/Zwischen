#!/usr/bin/env python3
"""Report differences between the live database schema and db/models.py.

Run this against a pre-Alembic database BEFORE first boot with migrations.
Adoption stamps the baseline, which asserts the database already matches the
models; if hand-run column scripts left it different, this is what tells you.

    python -m scripts.check_schema_drift

Exit code 0 = schema matches the models, 1 = differences found.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from db.migrate import check_drift  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if not settings.db_url:
        print("DB_URL is not set.", file=sys.stderr)
        return 1

    differences = check_drift(settings.db_url)

    if not differences:
        print("✅ Schema matches db/models.py — no drift.")
        return 0

    print(f"⚠️  {len(differences)} difference(s) between the database and models:\n")
    for line in differences:
        print(f"  - {line}")
    print(
        "\nResolve these before relying on migrations: either update db/models.py "
        "to match reality, or generate a migration that brings the database in "
        "line (alembic revision --autogenerate)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
