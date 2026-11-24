"""Drop indexes that are strict prefixes of another index.

Each dropped index covers columns that a wider index (or the primary key)
already leads with, so PostgreSQL can serve every query it served from the
wider one. Keeping both only doubles the write cost on the hottest tables
(every join, waitlist change and enrichment). Found by T12's catalog audit:

    idx_events_group                 ⊂ idx_events_group_state_time
    idx_event_participants_event_id  ⊂ event_participants_pkey (event_id, user_id)
    idx_event_waitlist_event_id      ⊂ uq_waitlist_event_user (event_id, user_id)
    idx_enrichments_event            ⊂ idx_enrichments_event_type
    idx_lineage_parent               ⊂ event_lineage_pkey (parent, child)
    idx_user_preferences_user        = user_preferences_user_id_key (unique)

Revision ID: b7e4d2a9c613
Revises: 6d29b321f144
Create Date: 2026-11-24
"""

from alembic import op

revision = "b7e4d2a9c613"
down_revision = "6d29b321f144"
branch_labels = None
depends_on = None

REDUNDANT = (
    ("idx_events_group", "events", ["group_id"]),
    ("idx_event_participants_event_id", "event_participants", ["event_id"]),
    ("idx_event_waitlist_event_id", "event_waitlist", ["event_id"]),
    ("idx_enrichments_event", "event_enrichments", ["event_id"]),
    ("idx_lineage_parent", "event_lineage", ["parent_event_id"]),
    ("idx_user_preferences_user", "user_preferences", ["user_id"]),
)


def upgrade() -> None:
    for name, _table, _columns in REDUNDANT:
        op.execute(f"DROP INDEX IF EXISTS {name}")


def downgrade() -> None:
    for name, table, columns in REDUNDANT:
        op.create_index(name, table, columns, if_not_exists=True)
