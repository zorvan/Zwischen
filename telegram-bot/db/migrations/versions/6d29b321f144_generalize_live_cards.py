"""generalize live cards for multiple transports

Revision ID: 6d29b321f144
Revises: c8f0e2a913b4
"""

from alembic import op
import sqlalchemy as sa

revision = "6d29b321f144"
down_revision = "c8f0e2a913b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_live_cards",
        sa.Column(
            "transport", sa.String(32), server_default="telegram", nullable=False
        ),
    )
    op.add_column(
        "event_live_cards", sa.Column("channel_id", sa.String(255), nullable=True)
    )
    op.execute("UPDATE event_live_cards SET channel_id = chat_id::text")
    op.alter_column("event_live_cards", "channel_id", nullable=False)
    op.alter_column(
        "event_live_cards",
        "message_id",
        type_=sa.String(255),
        postgresql_using="message_id::text",
    )
    op.drop_constraint(
        "event_live_cards_event_id_key", "event_live_cards", type_="unique"
    )
    op.create_unique_constraint(
        "uq_live_card_transport",
        "event_live_cards",
        ["event_id", "transport", "channel_id"],
    )
    op.drop_column("event_live_cards", "chat_id")


def downgrade() -> None:
    op.add_column(
        "event_live_cards", sa.Column("chat_id", sa.BigInteger(), nullable=True)
    )
    op.execute(
        "UPDATE event_live_cards SET chat_id = channel_id::bigint WHERE transport = 'telegram'"
    )
    op.drop_constraint("uq_live_card_transport", "event_live_cards", type_="unique")
    op.create_unique_constraint(
        "event_live_cards_event_id_key", "event_live_cards", ["event_id"]
    )
    op.alter_column(
        "event_live_cards",
        "message_id",
        type_=sa.BigInteger(),
        postgresql_using="message_id::bigint",
    )
    op.drop_column("event_live_cards", "channel_id")
    op.drop_column("event_live_cards", "transport")
    op.alter_column("event_live_cards", "chat_id", nullable=False)
