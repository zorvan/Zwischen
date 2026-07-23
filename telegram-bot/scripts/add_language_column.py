#!/usr/bin/env python3
"""Add language_preference column to user_preferences table.

Idempotent: safe to re-run. init_db()'s create_all() only creates missing
tables, never adds columns to existing ones, so column additions need a script
like this until a real migration tool is adopted.
"""

import asyncio

from sqlalchemy import text

from config.settings import settings
from db.connection import create_engine


async def add_language_column() -> None:
    """Add language_preference column to user_preferences table."""
    if not settings.db_url:
        raise SystemExit("DB_URL is not set.")

    # Was get_engine(), which does not exist in db.connection — this script
    # failed on import before it could do anything.
    engine = create_engine(settings.db_url)

    async with engine.begin() as conn:
        # SQLAlchemy 2.0 requires text() for raw SQL; bare strings raise.
        result = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'user_preferences'
                AND column_name = 'language_preference'
                """
            )
        )
        if result.fetchone():
            print("Column 'language_preference' already exists.")
            return

        await conn.execute(
            text(
                "ALTER TABLE user_preferences "
                "ADD COLUMN language_preference VARCHAR(10) DEFAULT NULL"
            )
        )
        print("Column 'language_preference' added successfully.")


if __name__ == "__main__":
    asyncio.run(add_language_column())
