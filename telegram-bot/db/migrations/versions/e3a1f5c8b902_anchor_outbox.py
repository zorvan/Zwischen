"""Optional commitment anchoring: outbox table and per-group opt-in (T16).

Revision ID: e3a1f5c8b902
Revises: b7e4d2a9c613
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e3a1f5c8b902"
down_revision = "b7e4d2a9c613"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_settings",
        sa.Column(
            "anchoring_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_table(
        "anchor_outbox",
        sa.Column("anchor_id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.event_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("commitment", sa.String(64), nullable=False),
        sa.Column("bundle", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("tx_ref", sa.String(255), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_anchor_outbox_due", "anchor_outbox", ["status", "next_attempt_at"]
    )
    op.create_index("idx_anchor_outbox_event", "anchor_outbox", ["event_id"])


def downgrade() -> None:
    op.drop_index("idx_anchor_outbox_event", table_name="anchor_outbox")
    op.drop_index("idx_anchor_outbox_due", table_name="anchor_outbox")
    op.drop_table("anchor_outbox")
    op.drop_column("group_settings", "anchoring_enabled")
