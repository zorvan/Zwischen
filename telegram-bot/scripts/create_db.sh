#!/bin/bash
# Create database using Python since psql requires password

python3 << 'PYTHON'
import asyncio
import asyncpg

async def create_database():
    try:
        conn = await asyncpg.connect(
            host='localhost',
            port=5432,
            user='coord_user',
            password='coord_pass',
            database='postgres'
        )

        # Check if database exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            'coord_db'
        )

        if not exists:
            await conn.execute("CREATE DATABASE coord_db")
            print("Database 'coord_db' created successfully")
        else:
            print("Database 'coord_db' already exists")

        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(create_database())
PYTHON
