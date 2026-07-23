"""tighten required foreign keys and name waitlist unique constraint

db/schema.sql created these four foreign keys as nullable, but the models have
always declared them NOT NULL and the code assumes it -- a constraint row with
no event_id, or a live card with no event, is meaningless. This brings the
database in line.

It also replaces PostgreSQL's auto-generated name for the waitlist unique
constraint with the explicit uq_waitlist_event_user the models declare, so the
name is stable across environments.

Requires no NULLs in those columns. Check before deploying to an environment
with data:

    SELECT count(*) FROM constraints WHERE user_id IS NULL OR event_id IS NULL;
    SELECT count(*) FROM event_enrichments WHERE event_id IS NULL;
    SELECT count(*) FROM event_live_cards WHERE event_id IS NULL;

Revision ID: f4a4512c63a8
Revises: 2120cd3866bc
Create Date: 2026-07-23 15:19:03.819564

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4a4512c63a8"
down_revision: Union[str, Sequence[str], None] = "2120cd3866bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "constraints", "user_id", existing_type=sa.INTEGER(), nullable=False
    )
    op.alter_column(
        "constraints", "event_id", existing_type=sa.INTEGER(), nullable=False
    )
    op.alter_column(
        "event_enrichments", "event_id", existing_type=sa.BIGINT(), nullable=False
    )
    op.alter_column(
        "event_live_cards", "event_id", existing_type=sa.BIGINT(), nullable=False
    )
    # The starting name depends on how the database was built: db/schema.sql
    # let PostgreSQL auto-name this constraint, while create_all() from the
    # models produced the explicit name. Both shapes exist in the wild, so
    # rename conditionally rather than assuming one.
    _rename_waitlist_unique(
        old="event_waitlist_event_id_telegram_user_id_key",
        new="uq_waitlist_event_user",
    )


def _constraint_exists(name: str, table: str = "event_waitlist") -> bool:
    """True if a named constraint is present on the table."""
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE c.conname = :name AND t.relname = :table"
            ),
            {"name": name, "table": table},
        )
        .scalar()
    )


def _rename_waitlist_unique(old: str, new: str) -> None:
    """Ensure the waitlist unique constraint carries the expected name."""
    if _constraint_exists(new):
        # Already correct (database was built from the models).
        if _constraint_exists(old):
            op.drop_constraint(old, "event_waitlist", type_="unique")
        return

    if _constraint_exists(old):
        op.drop_constraint(old, "event_waitlist", type_="unique")

    op.create_unique_constraint(new, "event_waitlist", ["event_id", "telegram_user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    _rename_waitlist_unique(
        old="uq_waitlist_event_user",
        new="event_waitlist_event_id_telegram_user_id_key",
    )
    op.alter_column(
        "event_live_cards", "event_id", existing_type=sa.BIGINT(), nullable=True
    )
    op.alter_column(
        "event_enrichments", "event_id", existing_type=sa.BIGINT(), nullable=True
    )
    op.alter_column(
        "constraints", "event_id", existing_type=sa.INTEGER(), nullable=True
    )
    op.alter_column("constraints", "user_id", existing_type=sa.INTEGER(), nullable=True)
