#!/usr/bin/env python3
"""Add language_preference column to user_preferences table."""

import asyncio

from config.settings import settings
from db.connection import get_engine


async def add_language_column() -> None:
    """Add language_preference column to user_preferences table."""
    engine = get_engine(settings.db_url)

    async with engine.begin() as conn:
        result = await conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'user_preferences'
            AND column_name = 'language_preference'
            """
        )
        if result.fetchone():
            print("Column 'language_preference' already exists.")
            return

        await conn.execute(
            "ALTER TABLE user_preferences ADD COLUMN language_preference VARCHAR(10) DEFAULT NULL"
        )
        print("Column 'language_preference' added successfully.")


if __name__ == "__main__":
    asyncio.run(add_language_column())
