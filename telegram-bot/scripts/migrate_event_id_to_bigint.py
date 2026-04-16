#!/usr/bin/env python3
"""
Migration script to update PostgreSQL database schema from INTEGER to BIGINT
for all event_id columns.

This script:
1. Connects to the PostgreSQL database using asyncpg
2. Reads the current schema to identify event_id columns
3. Alters all event_id columns from INTEGER to BIGINT
4. Updates the events table to use BIGSERIAL for event_id
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import asyncpg


async def get_event_id_columns(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Fetch all event_id columns from the database schema."""
    query = """
        SELECT 
            table_schema,
            table_name,
            column_name,
            data_type,
            is_nullable
        FROM information_schema.columns
        WHERE column_name = 'event_id'
        AND table_schema = 'public'
        AND data_type IN ('integer')
        ORDER BY table_name
    """
    rows = await conn.fetch(query)
    return [dict(row) for row in rows]


async def alter_column_to_bigint(
    conn: asyncpg.Connection, table_name: str, column_name: str
) -> None:
    """Alter a single column from INTEGER to BIGINT."""
    alter_sql = f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" TYPE BIGINT USING ({column_name}::BIGINT)'
    await conn.execute(alter_sql)
    print(f"  ✓ Altered {table_name}.{column_name} to BIGINT")


async def drop_existing_sequence(conn: asyncpg.Connection, sequence_name: str) -> None:
    """Drop an existing sequence if it exists."""
    await conn.execute(f'DROP SEQUENCE IF EXISTS "{sequence_name}" CASCADE')


async def create_bigserial_sequence(
    conn: asyncpg.Connection, table_name: str, column_name: str
) -> str:
    """Create a new BIGSERIAL sequence for the events table."""
    sequence_name = f"{table_name}_{column_name}_seq"

    await drop_existing_sequence(conn, sequence_name)

    create_seq_sql = f"""
        CREATE SEQUENCE "{sequence_name}"
        START WITH 1
        INCREMENT BY 1
        NO MINVALUE
        NO MAXVALUE
        CACHE 1
    """
    await conn.execute(create_seq_sql)

    set_seq_sql = f"""
        SELECT setval('{sequence_name}', (SELECT COALESCE(MAX({column_name}), 0) FROM {table_name}))
    """
    await conn.execute(set_seq_sql)

    return sequence_name


async def set_default_to_nextval(
    conn: asyncpg.Connection, table_name: str, column_name: str, sequence_name: str
) -> None:
    """Set the default value of the column to nextval of the sequence."""
    alter_sql = f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" SET DEFAULT nextval(\'{sequence_name}\'::regclass)'
    await conn.execute(alter_sql)


async def add_primary_key_if_not_exists(
    conn: asyncpg.Connection, table_name: str, column_name: str
) -> None:
    """Add primary key constraint if it doesn't exist."""
    check_sql = """
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = $1
        AND constraint_type = 'PRIMARY KEY'
    """
    result = await conn.fetchrow(check_sql, table_name)
    if not result:
        await conn.execute(
            f'ALTER TABLE "{table_name}" ADD PRIMARY KEY ("{column_name}")'
        )
        print(f"  ✓ Added primary key to {table_name}.{column_name}")


async def main() -> int:
    """Main migration function."""
    dsn = "postgresql://postgres:postgres@localhost:5432/telegram_bot"

    if len(sys.argv) > 1:
        dsn = sys.argv[1]

    print(f"Connecting to database: {dsn}")

    try:
        conn = await asyncpg.connect(dsn)
        print("✓ Connected to database")

        print("\nScanning for event_id columns...")
        event_id_columns = await get_event_id_columns(conn)

        if not event_id_columns:
            print(
                "No INTEGER event_id columns found. Migration may already be complete."
            )
            await conn.close()
            return 0

        print(f"\nFound {len(event_id_columns)} event_id columns to migrate:")
        for col in event_id_columns:
            print(f"  - {col['table_name']}.{col['column_name']} ({col['data_type']})")

        print("\nMigrating event_id columns to BIGINT...")
        for col in event_id_columns:
            if col["table_name"] == "events":
                continue
            await alter_column_to_bigint(conn, col["table_name"], col["column_name"])

        print("\nUpdating events table to use BIGSERIAL...")
        sequence_name = await create_bigserial_sequence(conn, "events", "event_id")
        await set_default_to_nextval(conn, "events", "event_id", sequence_name)
        await add_primary_key_if_not_exists(conn, "events", "event_id")

        print("\nVerifying migration...")
        remaining_columns = await get_event_id_columns(conn)
        if remaining_columns:
            print("✗ Migration incomplete. Remaining INTEGER columns:")
            for col in remaining_columns:
                print(f"  - {col['table_name']}.{col['column_name']}")
            await conn.close()
            return 1

        print("✓ All event_id columns successfully migrated to BIGINT")
        print("✓ events.event_id now uses BIGSERIAL")

        await conn.close()
        print("\n✓ Migration completed successfully!")
        return 0

    except asyncpg.PostgresError as e:
        print(f"✗ Database error: {e}")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
