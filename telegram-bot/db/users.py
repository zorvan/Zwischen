"""User identity helpers for mapping Telegram IDs to internal user IDs.

The Telegram-shaped view of ``db/identity.py``. Resolution is delegated there
rather than duplicated, so a user created by the bot gets the same
``user_identities`` row a web signup would -- without that, accounts created
after the identity migration would be invisible to every non-Telegram client.
"""

from typing import Dict, Optional
from sqlalchemy import select

from db.identity import _normalize_username, resolve_telegram_user
from db.models import User

__all__ = [
    "get_or_create_user_id",
    "get_user_id_by_username",
    "get_user_ids_for_telegram_ids",
]


async def get_or_create_user_id(
    session,
    telegram_user_id: int,
    display_name: Optional[str] = None,
    username: Optional[str] = None,
) -> int:
    """Return internal users.user_id for a Telegram user, creating row if needed."""
    user = await resolve_telegram_user(
        session,
        telegram_user_id,
        display_name=display_name,
        username=username,
    )
    return int(user.user_id)


async def get_user_id_by_username(session, username: str) -> Optional[int]:
    """Resolve internal users.user_id from a Telegram username."""
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return None
    result = await session.execute(
        select(User).where(User.username == normalized_username)
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    return int(user.user_id)


async def get_user_ids_for_telegram_ids(
    session, telegram_user_ids: list[int]
) -> Dict[int, int]:
    """Map Telegram user IDs to internal user IDs."""
    if not telegram_user_ids:
        return {}

    result = await session.execute(
        select(User).where(User.telegram_user_id.in_(telegram_user_ids))
    )
    users = result.scalars().all()

    return {u.telegram_user_id: u.user_id for u in users}
