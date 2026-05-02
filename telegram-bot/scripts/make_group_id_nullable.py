#!/usr/bin/env python3
"""Make events.group_id nullable to support private events without a group."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg


async def run_migration():
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("ERROR: DB_URL environment variable not set")
        sys.exit(1)

    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    print("Connecting to database...")
    conn = await asyncpg.connect(db_url)

    try:
        current_nullable = await conn.fetchval(
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'events' AND column_name = 'group_id'"
        )
        print(f"Current group_id nullable: {current_nullable}")

        if current_nullable == "YES":
            print("group_id is already nullable. Nothing to do.")
        else:
            await conn.execute("ALTER TABLE events ALTER COLUMN group_id DROP NOT NULL")
            print("Done: events.group_id is now nullable")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
