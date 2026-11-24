"""allow users with no telegram account

``users.telegram_user_id`` was NOT NULL, which meant every user had to have a
Telegram account -- so the identity table from the previous revision could not
actually be used to create a web or mobile user. Relaxing the constraint is
what makes non-Telegram signup possible.

This is a widening change: existing rows keep their values and every existing
query still works. Uniqueness is unaffected for rows that have a Telegram id,
because PostgreSQL does not treat NULLs as equal under a unique constraint.

Kept separate from 3fead70d5078 rather than folded into it, so a database that
already applied that revision still picks this up.

Revision ID: a1c4e93b7d20
Revises: 3fead70d5078
Create Date: 2026-07-23 18:32:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c4e93b7d20"
down_revision: Union[str, Sequence[str], None] = "3fead70d5078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users", "telegram_user_id", existing_type=sa.BIGINT(), nullable=True
    )


def downgrade() -> None:
    # Users with no Telegram account cannot satisfy the old constraint. They
    # are exactly the rows this revision exists to allow, so removing them is
    # the only way back -- and it is destructive. Refuse rather than delete
    # user accounts behind the operator's back.
    connection = op.get_bind()
    orphans = connection.execute(
        sa.text("SELECT count(*) FROM users WHERE telegram_user_id IS NULL")
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} user(s) have no Telegram account and would have to be "
            "deleted to restore NOT NULL. Reassign or remove them explicitly "
            "before downgrading past a1c4e93b7d20."
        )
    op.alter_column(
        "users", "telegram_user_id", existing_type=sa.BIGINT(), nullable=False
    )
