"""platform neutral identity

Expand phase of the Telegram-independence migration.

The schema keyed participation on ``telegram_user_id`` -- a raw BigInteger
with no foreign key -- across events, participants, waitlist, enrichments and
the state-transition audit trail. That makes Telegram the identity provider at
the storage layer, so a web or mobile client cannot represent a user at all.

This migration *adds* the platform-neutral shape and backfills it, while
leaving every existing column in place and populated. Nothing reads the new
columns yet, so this revision is safe to deploy on its own and safe to roll
back. A later contract migration drops the deprecated columns and moves the
event_participants primary key once all call sites have moved over.

Order matters here:

1. public_id columns, added nullable and filled before being made NOT NULL --
   adding a NOT NULL column with no default to a populated table fails.
2. Users for every Telegram ID referenced anywhere. Because the old columns
   had no foreign keys, child tables can and do reference IDs that were never
   inserted into ``users``; backfilling FKs before creating those rows would
   silently drop the rows.
3. user_identities, then the user_id backfills, then group_members.

Revision ID: 3fead70d5078
Revises: f4a4512c63a8
Create Date: 2026-07-23 18:07:52.328163

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3fead70d5078"
down_revision: Union[str, Sequence[str], None] = "f4a4512c63a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every table that carried a bare telegram id, and the column it used.
_TELEGRAM_REFS = [
    ("event_participants", "telegram_user_id"),
    ("event_waitlist", "telegram_user_id"),
    ("event_enrichments", "telegram_user_id"),
    ("events", "organizer_telegram_user_id"),
    ("events", "emergency_admin_telegram_user_id"),
    ("event_state_transitions", "actor_telegram_user_id"),
]


def _add_public_id(table: str) -> None:
    """Add a public UUID, fill it, then enforce NOT NULL.

    gen_random_uuid() is built into PostgreSQL 13+, so this needs no
    extension. The column is what external clients address; the integer PK
    stays internal so joins stay narrow.
    """
    op.add_column(
        table,
        sa.Column(
            "public_id",
            sa.UUID(),
            nullable=True,
            # Server-side, so rows inserted by anything that is not this ORM
            # still get an id rather than failing NOT NULL.
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.execute(f"UPDATE {table} SET public_id = gen_random_uuid()")
    op.alter_column(table, "public_id", nullable=False)
    op.create_unique_constraint(f"uq_{table}_public_id", table, ["public_id"])


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Public identifiers
    # ------------------------------------------------------------------
    for table in ("users", "groups", "events"):
        _add_public_id(table)

    # A group created from the web has no Telegram chat behind it.
    op.alter_column(
        "groups", "telegram_group_id", existing_type=sa.BIGINT(), nullable=True
    )

    # ------------------------------------------------------------------
    # 2. Users for every referenced Telegram ID
    #
    # The old columns had no foreign keys, so nothing guaranteed a users row
    # existed. Any ID missing one would produce a NULL user_id in the
    # backfills below and be silently dropped from the new model.
    # ------------------------------------------------------------------
    # Realign the users sequence before inserting. A sequence that trails
    # MAX(user_id) makes the inserts below fail on a duplicate primary key.
    # This repo has a history of hand-run schema scripts, and a dump/restore
    # that misses sequences leaves exactly this state, so do not assume the
    # sequence is sane.
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('users', 'user_id'),
            COALESCE((SELECT MAX(user_id) FROM users), 0) + 1,
            false
        )
        """
    )

    union = " UNION ".join(
        f"SELECT {column} AS tg FROM {table}" for table, column in _TELEGRAM_REFS
    )
    op.execute(
        f"""
        INSERT INTO users (telegram_user_id, public_id, created_at)
        SELECT s.tg, gen_random_uuid(), now()
        FROM ({union}) s
        WHERE s.tg IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM users u WHERE u.telegram_user_id = s.tg
          )
        """
    )

    # Members named only in the groups.member_list JSON blob also need rows,
    # or they vanish when membership becomes a real table below.
    op.execute(
        """
        INSERT INTO users (telegram_user_id, public_id, created_at)
        SELECT DISTINCT m.tg::bigint, gen_random_uuid(), now()
        FROM groups g
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(g.member_list) = 'array'
                 THEN g.member_list ELSE '[]'::jsonb END
        ) AS m(tg)
        WHERE m.tg ~ '^-?[0-9]+$'
          AND NOT EXISTS (
              SELECT 1 FROM users u WHERE u.telegram_user_id = m.tg::bigint
          )
        """
    )

    # ------------------------------------------------------------------
    # 3. user_identities -- Telegram becomes one credential among several
    # ------------------------------------------------------------------
    op.create_table(
        "user_identities",
        sa.Column("identity_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_user_identities_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("identity_id"),
        sa.UniqueConstraint(
            "provider", "provider_user_id", name="uq_identity_provider"
        ),
    )
    op.create_index("idx_user_identities_user", "user_identities", ["user_id"])

    op.execute(
        """
        INSERT INTO user_identities
            (user_id, provider, provider_user_id, created_at)
        SELECT user_id, 'telegram', telegram_user_id::text,
               COALESCE(created_at, now())
        FROM users
        WHERE telegram_user_id IS NOT NULL
        ON CONFLICT ON CONSTRAINT uq_identity_provider DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 4. user_id columns alongside the telegram ones, then backfilled
    # ------------------------------------------------------------------
    op.add_column(
        "event_participants", sa.Column("user_id", sa.Integer(), nullable=True)
    )
    op.add_column("event_waitlist", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column(
        "event_enrichments", sa.Column("user_id", sa.Integer(), nullable=True)
    )
    op.add_column("events", sa.Column("organizer_user_id", sa.Integer(), nullable=True))
    op.add_column(
        "events", sa.Column("emergency_admin_user_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "event_state_transitions",
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
    )

    for table, column in _TELEGRAM_REFS:
        target = {
            "organizer_telegram_user_id": "organizer_user_id",
            "emergency_admin_telegram_user_id": "emergency_admin_user_id",
            "actor_telegram_user_id": "actor_user_id",
        }.get(column, "user_id")
        op.execute(
            f"""
            UPDATE {table} t
            SET {target} = u.user_id
            FROM users u
            WHERE u.telegram_user_id = t.{column}
              AND t.{column} IS NOT NULL
            """
        )

    # ------------------------------------------------------------------
    # 5. group_members -- membership as stored fact
    #
    # Replaces the member_list JSON array and, more importantly, the fallback
    # in rbac.check_group_membership() that asked the Telegram API who was in
    # the chat. No such oracle exists for a web or mobile client.
    #
    # Sourced from both the declared member list and observed participation,
    # since the two disagreed in practice.
    # ------------------------------------------------------------------
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.group_id"],
            name="fk_group_members_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_group_members_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("idx_group_members_user", "group_members", ["user_id"])
    op.create_index(
        "idx_group_members_group_status", "group_members", ["group_id", "status"]
    )

    # Declared membership.
    op.execute(
        """
        INSERT INTO group_members (group_id, user_id, role, status, joined_at)
        SELECT DISTINCT g.group_id, u.user_id, 'member', 'active', now()
        FROM groups g
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(g.member_list) = 'array'
                 THEN g.member_list ELSE '[]'::jsonb END
        ) AS m(tg)
        JOIN users u ON u.telegram_user_id = m.tg::bigint
        WHERE m.tg ~ '^-?[0-9]+$'
        ON CONFLICT DO NOTHING
        """
    )

    # Observed membership: anyone who ever took part in one of the group's
    # events is a member, which is what the old code inferred at runtime.
    op.execute(
        """
        INSERT INTO group_members (group_id, user_id, role, status, joined_at)
        SELECT DISTINCT e.group_id, p.user_id, 'member', 'active', now()
        FROM event_participants p
        JOIN events e ON e.event_id = p.event_id
        WHERE e.group_id IS NOT NULL AND p.user_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO group_members (group_id, user_id, role, status, joined_at)
        SELECT DISTINCT e.group_id, e.organizer_user_id, 'member', 'active', now()
        FROM events e
        WHERE e.group_id IS NOT NULL AND e.organizer_user_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 6. Foreign keys and indexes on the new columns
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_event_participants_user",
        "event_participants",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_event_waitlist_user",
        "event_waitlist",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_event_enrichments_user",
        "event_enrichments",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_events_organizer_user",
        "events",
        "users",
        ["organizer_user_id"],
        ["user_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_events_emergency_admin_user",
        "events",
        "users",
        ["emergency_admin_user_id"],
        ["user_id"],
        ondelete="SET NULL",
    )
    # SET NULL: deleting a user must not erase the audit trail of what
    # happened to an event.
    op.create_foreign_key(
        "fk_event_state_transitions_actor",
        "event_state_transitions",
        "users",
        ["actor_user_id"],
        ["user_id"],
        ondelete="SET NULL",
    )

    op.create_unique_constraint(
        "uq_participant_event_user", "event_participants", ["event_id", "user_id"]
    )

    op.create_index("idx_event_participants_user", "event_participants", ["user_id"])
    op.create_index("idx_event_waitlist_user", "event_waitlist", ["user_id"])
    op.create_index("idx_enrichments_user", "event_enrichments", ["user_id"])
    op.create_index("idx_events_organizer_user", "events", ["organizer_user_id"])
    op.create_index(
        "idx_events_emergency_admin_user", "events", ["emergency_admin_user_id"]
    )
    op.create_index(
        "idx_event_state_transitions_actor",
        "event_state_transitions",
        ["actor_user_id"],
    )

    # ------------------------------------------------------------------
    # 7. Composite indexes for the read paths that currently scan
    # ------------------------------------------------------------------
    # "confirmed count for this event" runs on every join, lock and threshold
    # check; counting from this index avoids touching the heap.
    op.create_index(
        "idx_event_participants_event_status",
        "event_participants",
        ["event_id", "status"],
    )
    # "this group's events in these states, soonest first" -- the list view.
    op.create_index(
        "idx_events_group_state_time", "events", ["group_id", "state", "scheduled_time"]
    )
    # Promotion picks the oldest still-waiting entry for an event.
    op.create_index(
        "idx_event_waitlist_event_status_added",
        "event_waitlist",
        ["event_id", "status", "added_at"],
    )
    op.create_index(
        "idx_enrichments_event_type",
        "event_enrichments",
        ["event_id", "enrichment_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_enrichments_event_type", table_name="event_enrichments")
    op.drop_index("idx_event_waitlist_event_status_added", table_name="event_waitlist")
    op.drop_index("idx_events_group_state_time", table_name="events")
    op.drop_index(
        "idx_event_participants_event_status", table_name="event_participants"
    )

    op.drop_index(
        "idx_event_state_transitions_actor", table_name="event_state_transitions"
    )
    op.drop_index("idx_events_emergency_admin_user", table_name="events")
    op.drop_index("idx_events_organizer_user", table_name="events")
    op.drop_index("idx_enrichments_user", table_name="event_enrichments")
    op.drop_index("idx_event_waitlist_user", table_name="event_waitlist")
    op.drop_index("idx_event_participants_user", table_name="event_participants")

    op.drop_constraint(
        "uq_participant_event_user", "event_participants", type_="unique"
    )
    op.drop_constraint(
        "fk_event_state_transitions_actor",
        "event_state_transitions",
        type_="foreignkey",
    )
    op.drop_constraint("fk_events_emergency_admin_user", "events", type_="foreignkey")
    op.drop_constraint("fk_events_organizer_user", "events", type_="foreignkey")
    op.drop_constraint(
        "fk_event_enrichments_user", "event_enrichments", type_="foreignkey"
    )
    op.drop_constraint("fk_event_waitlist_user", "event_waitlist", type_="foreignkey")
    op.drop_constraint(
        "fk_event_participants_user", "event_participants", type_="foreignkey"
    )

    op.drop_index("idx_group_members_group_status", table_name="group_members")
    op.drop_index("idx_group_members_user", table_name="group_members")
    op.drop_table("group_members")

    op.drop_column("event_state_transitions", "actor_user_id")
    op.drop_column("events", "emergency_admin_user_id")
    op.drop_column("events", "organizer_user_id")
    op.drop_column("event_enrichments", "user_id")
    op.drop_column("event_waitlist", "user_id")
    op.drop_column("event_participants", "user_id")

    op.drop_index("idx_user_identities_user", table_name="user_identities")
    op.drop_table("user_identities")

    # Rows created purely to satisfy the new foreign keys are left in place:
    # deleting them here could remove users the application has since started
    # using. They are inert without the new columns.
    op.alter_column(
        "groups", "telegram_group_id", existing_type=sa.BIGINT(), nullable=False
    )
    for table in ("events", "groups", "users"):
        op.drop_constraint(f"uq_{table}_public_id", table, type_="unique")
        op.drop_column(table, "public_id")
