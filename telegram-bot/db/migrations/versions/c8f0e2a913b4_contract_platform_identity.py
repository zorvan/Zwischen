"""contract platform-specific identity columns

The downgrade can reconstruct Telegram-backed values from user_identities,
but values for users whose identity rows were removed are unrecoverable.

Revision ID: c8f0e2a913b4
Revises: a1c4e93b7d20
Create Date: 2026-08-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8f0e2a913b4"
down_revision: Union[str, Sequence[str], None] = "a1c4e93b7d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for table in ("event_participants", "event_waitlist", "event_enrichments"):
        missing = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE user_id IS NULL")
        ).scalar()
        if missing:
            raise RuntimeError(f"{table} contains {missing} rows without user_id")

    op.alter_column("event_participants", "user_id", nullable=False)
    op.alter_column("event_waitlist", "user_id", nullable=False)
    op.alter_column("event_enrichments", "user_id", nullable=False)

    op.drop_constraint("event_participants_pkey", "event_participants", type_="primary")
    op.create_primary_key(
        "event_participants_pkey", "event_participants", ["event_id", "user_id"]
    )
    op.drop_constraint(
        "uq_participant_event_user", "event_participants", type_="unique"
    )

    op.drop_index("idx_events_organizer_tg", table_name="events")
    op.drop_index("idx_events_emergency_admin_tg", table_name="events")
    op.drop_index("idx_event_participants_user_id", table_name="event_participants")
    op.drop_index("idx_event_waitlist_user_id", table_name="event_waitlist")
    op.drop_constraint("uq_waitlist_event_user", "event_waitlist", type_="unique")
    op.create_unique_constraint(
        "uq_waitlist_event_user", "event_waitlist", ["event_id", "user_id"]
    )

    op.drop_column("event_participants", "telegram_user_id")
    op.drop_column("event_waitlist", "telegram_user_id")
    op.drop_column("event_enrichments", "telegram_user_id")
    op.drop_column("events", "organizer_telegram_user_id")
    op.drop_column("events", "emergency_admin_telegram_user_id")
    op.drop_column("event_state_transitions", "actor_telegram_user_id")
    op.drop_column("groups", "member_list")
    op.drop_column("users", "telegram_user_id")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("telegram_user_id", sa.BigInteger(), nullable=True)
    )
    op.create_unique_constraint(
        "users_telegram_user_id_key", "users", ["telegram_user_id"]
    )
    op.execute(
        """UPDATE users u SET telegram_user_id = i.provider_user_id::bigint
           FROM user_identities i
           WHERE i.user_id = u.user_id AND i.provider = 'telegram'"""
    )
    op.add_column("groups", sa.Column("member_list", sa.JSON(), nullable=True))
    op.execute("UPDATE groups SET member_list = '[]'::jsonb")
    op.add_column("events", sa.Column("organizer_telegram_user_id", sa.BigInteger()))
    op.add_column(
        "events", sa.Column("emergency_admin_telegram_user_id", sa.BigInteger())
    )
    op.add_column(
        "event_state_transitions", sa.Column("actor_telegram_user_id", sa.BigInteger())
    )
    for table in ("event_participants", "event_waitlist", "event_enrichments"):
        op.add_column(
            table, sa.Column("telegram_user_id", sa.BigInteger(), nullable=True)
        )
        op.execute(
            f"""UPDATE {table} t SET telegram_user_id = i.provider_user_id::bigint
                FROM user_identities i
                WHERE i.user_id = t.user_id AND i.provider = 'telegram'"""
        )
    op.drop_constraint("event_participants_pkey", "event_participants", type_="primary")
    op.create_primary_key(
        "event_participants_pkey",
        "event_participants",
        ["event_id", "telegram_user_id"],
    )
    op.create_unique_constraint(
        "uq_participant_event_user", "event_participants", ["event_id", "user_id"]
    )
