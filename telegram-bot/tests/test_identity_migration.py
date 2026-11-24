"""End-to-end test for the platform-neutral identity migration.

Builds a database at the *previous* revision, fills it with data shaped like
production -- including the orphan Telegram IDs the old schema permitted --
then upgrades and asserts the backfill preserved every relationship.

The orphan case is the one that matters. The old columns carried no foreign
key, so child tables reference Telegram IDs that have no `users` row. A
backfill that joined straight to `users` would leave those rows with a NULL
user_id and silently drop them from the new model.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from db import migrate
from db.connection import check_db_connection
from db.url import normalize_db_url

PREVIOUS_REVISION = "f4a4512c63a8"
IDENTITY_REVISION = "3fead70d5078"
CONTRACT_REVISION = "c8f0e2a913b4"

pytestmark = pytest.mark.integration


def _base_url() -> str:
    raw = os.environ.get("DATABASE_URL") or os.environ.get(
        "DB_URL", "postgresql://coord_user:coord_pass@localhost:5432/coord_db"
    )
    url = normalize_db_url(raw)
    assert url
    return url


async def _exec(url: str, *statements: str, autocommit: bool = False):
    kwargs = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    engine = create_async_engine(url, **kwargs)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def _fetch(url: str, query: str):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(query))).fetchall()
    finally:
        await engine.dispose()


@pytest.fixture()
def legacy_db():
    """A database at the pre-identity revision, dropped afterwards."""
    base = _base_url()
    ok, message = asyncio.run(check_db_connection(base))
    if not ok:
        pytest.skip(f"No database reachable: {message}")

    name = f"zwischen_ident_{uuid.uuid4().hex[:8]}"
    admin = base.rsplit("/", 1)[0] + "/postgres"
    target = base.rsplit("/", 1)[0] + "/" + name

    asyncio.run(_exec(admin, f'CREATE DATABASE "{name}"', autocommit=True))
    try:
        migrate.run_migrations(target, revision=PREVIOUS_REVISION)
        yield target
    finally:
        asyncio.run(
            _exec(
                admin,
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{name}'",
                f'DROP DATABASE IF EXISTS "{name}"',
                autocommit=True,
            )
        )


def _seed(url: str) -> None:
    """Data shaped like production, including the awkward cases.

    - user 1001 is a normal user with a `users` row
    - user 2002 participates but has NO `users` row (the orphan case)
    - user 3003 appears only in the group's member_list JSON blob
    """
    asyncio.run(
        _exec(
            url,
            """
            INSERT INTO groups (group_id, telegram_group_id, group_name, member_list)
            VALUES (1, -500, 'Test Group', '[1001, 3003]'::jsonb)
            """,
            """
            INSERT INTO users (user_id, telegram_user_id, display_name)
            VALUES (1, 1001, 'Has A Row')
            """,
            """
            INSERT INTO events (event_id, group_id, event_type, state, version,
                                organizer_telegram_user_id,
                                emergency_admin_telegram_user_id)
            VALUES (1, 1, 'social', 'proposed', 0, 1001, 2002)
            """,
            """
            INSERT INTO event_participants
                (event_id, telegram_user_id, status, role)
            VALUES (1, 1001, 'confirmed', 'organizer'),
                   (1, 2002, 'joined', 'participant')
            """,
            """
            INSERT INTO event_waitlist (event_id, telegram_user_id, status, added_at)
            VALUES (1, 2002, 'waiting', now())
            """,
            """
            INSERT INTO event_enrichments
                (event_id, telegram_user_id, enrichment_type, content)
            VALUES (1, 2002, 'idea', 'bring snacks')
            """,
            """
            INSERT INTO event_state_transitions
                (event_id, from_state, to_state, actor_telegram_user_id,
                 source, timestamp)
            VALUES (1, 'proposed', 'interested', 1001, 'callback', now())
            """,
        )
    )


def test_backfill_creates_users_for_orphan_telegram_ids(legacy_db: str) -> None:
    """Participants with no users row must gain one, not be dropped."""
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=IDENTITY_REVISION)

    rows = asyncio.run(
        _fetch(
            legacy_db, "SELECT telegram_user_id FROM users ORDER BY telegram_user_id"
        )
    )
    assert [r[0] for r in rows] == [1001, 2002, 3003], (
        "orphan Telegram IDs referenced by child tables, and IDs present only "
        "in member_list, must all get users rows"
    )


def test_every_participation_row_is_repointed(legacy_db: str) -> None:
    """No row may be left with a NULL user_id after the backfill."""
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=IDENTITY_REVISION)

    checks = {
        "event_participants": "user_id",
        "event_waitlist": "user_id",
        "event_enrichments": "user_id",
        "event_state_transitions": "actor_user_id",
    }
    for table, column in checks.items():
        rows = asyncio.run(
            _fetch(legacy_db, f"SELECT count(*) FROM {table} WHERE {column} IS NULL")
        )
        assert rows[0][0] == 0, f"{table}.{column} left unpopulated by the backfill"

    orphaned = asyncio.run(
        _fetch(
            legacy_db,
            "SELECT count(*) FROM events "
            "WHERE organizer_user_id IS NULL OR emergency_admin_user_id IS NULL",
        )
    )
    assert orphaned[0][0] == 0


def test_user_id_matches_the_original_telegram_id(legacy_db: str) -> None:
    """The repointing must preserve *which* user each row referred to."""
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=IDENTITY_REVISION)

    mismatched = asyncio.run(
        _fetch(
            legacy_db,
            """
            SELECT count(*) FROM event_participants p
            JOIN users u ON u.user_id = p.user_id
            WHERE u.telegram_user_id <> p.telegram_user_id
            """,
        )
    )
    assert mismatched[0][0] == 0, "backfill attached rows to the wrong user"


def test_telegram_identities_are_migrated_to_the_identity_table(
    legacy_db: str,
) -> None:
    """Every user gets exactly one telegram identity row."""
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=IDENTITY_REVISION)

    rows = asyncio.run(
        _fetch(
            legacy_db,
            """
            SELECT i.provider, i.provider_user_id
            FROM user_identities i
            JOIN users u ON u.user_id = i.user_id
            ORDER BY i.provider_user_id
            """,
        )
    )
    assert [(r[0], r[1]) for r in rows] == [
        ("telegram", "1001"),
        ("telegram", "2002"),
        ("telegram", "3003"),
    ]


def test_group_membership_is_materialized(legacy_db: str) -> None:
    """Membership comes from both the JSON blob and observed participation.

    2002 is in neither member_list nor any explicit member record -- it is a
    member only by virtue of having participated, which is exactly what the
    old Telegram-API fallback inferred at runtime.
    """
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=IDENTITY_REVISION)

    rows = asyncio.run(
        _fetch(
            legacy_db,
            """
            SELECT u.telegram_user_id
            FROM group_members m
            JOIN users u ON u.user_id = m.user_id
            WHERE m.group_id = 1
            ORDER BY u.telegram_user_id
            """,
        )
    )
    assert [r[0] for r in rows] == [1001, 2002, 3003]


def test_contract_migration_preserves_seeded_relationships(legacy_db: str) -> None:
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=CONTRACT_REVISION)

    columns = asyncio.run(
        _fetch(
            legacy_db,
            """SELECT table_name, column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND column_name LIKE '%telegram_user_id'
               ORDER BY table_name, column_name""",
        )
    )
    assert columns == []
    participants = asyncio.run(
        _fetch(legacy_db, "SELECT count(*) FROM event_participants")
    )
    assert participants[0][0] == 2


def test_public_ids_are_unique_and_populated(legacy_db: str) -> None:
    """Every externally addressable row gets a distinct UUID."""
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=IDENTITY_REVISION)

    for table in ("users", "groups", "events"):
        rows = asyncio.run(
            _fetch(
                legacy_db,
                f"SELECT count(*), count(public_id), count(DISTINCT public_id) "
                f"FROM {table}",
            )
        )
        total, populated, distinct = rows[0]
        assert total == populated == distinct, f"{table}.public_id not unique/populated"


def test_migration_is_reversible(legacy_db: str) -> None:
    """Downgrade must restore the previous shape without losing event data."""
    _seed(legacy_db)
    migrate.run_migrations(legacy_db, revision=IDENTITY_REVISION)
    migrate.run_migrations(legacy_db, revision=PREVIOUS_REVISION)

    rows = asyncio.run(
        _fetch(
            legacy_db,
            "SELECT telegram_user_id FROM event_participants ORDER BY telegram_user_id",
        )
    )
    assert [r[0] for r in rows] == [1001, 2002], "downgrade lost participation rows"
