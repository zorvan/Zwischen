#!/usr/bin/env python3
"""Add admin_telegram_user_id column to events table."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from config.settings import Settings


async def add_admin_column():
    settings = Settings()
    db_url = settings.db_url
    if not db_url:
        print("❌ No database URL configured")
        return
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    print("Connecting to database...")

    engine = create_async_engine(db_url)

    try:
        async with engine.begin() as conn:
            # Check if column exists
            result = await conn.execute(
                text(
                    """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'events' AND column_name = 'admin_telegram_user_id'
            """
                )
            )
            exists = result.fetchone()

            if not exists:
                print("Adding admin_telegram_user_id column to events table...")
                await conn.execute(
                    text(
                        """
                    ALTER TABLE events
                    ADD COLUMN admin_telegram_user_id BIGINT;
                """
                    )
                )
                print("✅ Column added successfully!")
            else:
                print("⚠️ Column already exists!")

            # Verify
            result2 = await conn.execute(
                text(
                    """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'events' AND column_name = 'admin_telegram_user_id'
            """
                )
            )
            verified = result2.fetchone()
            print(f"Verification - column exists: {verified is not None}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(add_admin_column())
