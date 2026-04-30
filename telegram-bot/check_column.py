#!/usr/bin/env python3
"""Verify admin column in events table."""
import asyncio
from config.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def check():
    settings = Settings()
    db_url = settings.db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'events' AND column_name = 'admin_telegram_user_id';"
            )
        )
        row = result.fetchone()
        print(f"Admin column exists: {row is not None}")
        if row:
            print(f"Column: {row[0]}")

        # List all columns
        print("\\nAll columns in events table:")
        result2 = await conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'events' ORDER BY ordinal_position;"
            )
        )
        columns = result2.fetchall()
        for col in columns:
            print(f"  - {col[0]}: {col[1]}")


asyncio.run(check())
