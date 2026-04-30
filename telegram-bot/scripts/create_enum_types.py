#!/usr/bin/env python3
"""
Create PostgreSQL enum types for PRD v2.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg


async def run_migration():
    """Create enum types in database."""
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("ERROR: DB_URL environment variable not set")
        sys.exit(1)

    # Convert asyncpg URL to sync for psycopg2 compatibility if needed
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    print(f"Connecting to database...")
    conn = await asyncpg.connect(db_url)

    try:
        # Create participant_status enum (matches SQLAlchemy model with name="participant_status")
        print("Creating participant_status enum type...")
        await conn.execute(
            """
            DO $$ BEGIN
                CREATE TYPE participant_status AS ENUM (
                    'joined', 'confirmed', 'cancelled', 'no_show'
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """
        )
        print("  ✓ participant_status type created")

        # Create participant_role enum (matches SQLAlchemy model with name="participant_role")
        print("Creating participant_role enum type...")
        await conn.execute(
            """
            DO $$ BEGIN
                CREATE TYPE participant_role AS ENUM (
                    'organizer', 'participant', 'observer'
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """
        )
        print("  ✓ participant_role type created")

        print("\n✓ Enum types migration completed successfully!")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
