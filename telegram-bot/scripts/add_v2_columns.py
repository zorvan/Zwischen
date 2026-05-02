#!/usr/bin/env python3
"""
Simple async migration to add v2 columns to events table.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg


async def run_migration():
    """Add missing v2 columns to events table."""
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("ERROR: DB_URL environment variable not set")
        sys.exit(1)

    # Convert asyncpg URL to sync for psycopg2 compatibility if needed
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    print("Connecting to database...")
    conn = await asyncpg.connect(db_url)

    try:
        columns_to_add = [
            ("min_participants", "INTEGER DEFAULT 2"),
            ("target_participants", "INTEGER DEFAULT 6"),
            ("collapse_at", "TIMESTAMP"),
            ("lock_deadline", "TIMESTAMP"),
            ("version", "INTEGER DEFAULT 0 NOT NULL"),
        ]

        # Get existing columns
        existing = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'events'
        """
        )
        existing_columns = {row["column_name"] for row in existing}

        print(f"Found {len(existing_columns)} existing columns in events table")

        for col_name, col_def in columns_to_add:
            if col_name not in existing_columns:
                print(f"  Adding column: {col_name}")
                await conn.execute(
                    f"ALTER TABLE events ADD COLUMN {col_name} {col_def}"
                )
            else:
                print(f"  Column already exists: {col_name}")

        print("\n✓ Migration completed successfully!")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
