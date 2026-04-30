"""User identity helpers for mapping Telegram IDs to internal user IDs."""

from typing import Dict, Optional
from sqlalchemy import select

from db.models import User


def _normalize_username(username: Optional[str]) -> Optional[str]:
    """Normalize username to lowercase without leading @."""
    if not username:
        return None
    normalized = username.strip().lstrip("@").lower()
    return normalized or None


async def get_or_create_user_id(
    session,
    telegram_user_id: int,
    display_name: Optional[str] = None,
    username: Optional[str] = None,
) -> int:
    """Return internal users.user_id for a Telegram user, creating row if needed."""
    normalized_username = _normalize_username(username)
    result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    user = result.scalar_one_or_none()

    if user:
        changed = False
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            changed = True
        if normalized_username and user.username != normalized_username:
            user.username = normalized_username
            changed = True
        if changed:
            await session.flush()
        return int(user.user_id)

    user = User(
        telegram_user_id=telegram_user_id,
        username=normalized_username,
        display_name=display_name,
    )
    session.add(user)
    await session.flush()
    return int(user.user_id)


async def get_user_id_by_username(session, username: str) -> Optional[int]:
    """Resolve internal users.user_id from a Telegram username."""
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return None
    result = await session.execute(select(User).where(User.username == normalized_username))
    user = result.scalar_one_or_none()
    if not user:
        return None
    return int(user.user_id)


async def get_user_ids_for_telegram_ids(session, telegram_user_ids: list[int]) -> Dict[int, int]:
    """Map Telegram user IDs to internal user IDs."""
    if not telegram_user_ids:
        return {}

    result = await session.execute(select(User).where(User.telegram_user_id.in_(telegram_user_ids)))
    users = result.scalars().all()

    return {u.telegram_user_id: u.user_id for u in users}
