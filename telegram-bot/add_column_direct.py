#!/usr/bin/env python3
"""Directly add column using psycopg2."""
import psycopg2

conn = psycopg2.connect(
    dbname="coord_db",
    user="coord_user",
    password="coord_pass",
    host="localhost",
    port=5432,
)
cursor = conn.cursor()

# Check if column exists
cursor.execute(
    """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'events' AND column_name = 'admin_telegram_user_id'
"""
)
exists = cursor.fetchone()

if not exists:
    print("Adding admin_telegram_user_id column...")
    cursor.execute("ALTER TABLE events ADD COLUMN admin_telegram_user_id BIGINT")
    conn.commit()
    print("✅ Column added!")
else:
    print("Column already exists")

# Verify
cursor.execute(
    """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'events'
"""
)
for col in cursor.fetchall():
    print(f"  {col[0]}: {col[1]}")

cursor.close()
conn.close()
