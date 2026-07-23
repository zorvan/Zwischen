"""Provider-agnostic identity resolution.

The single place that answers "which User is this?" regardless of how the
request arrived. A Telegram update, a web session and a mobile token all
resolve through :func:`resolve_identity` and differ only in the provider they
name.

``db/users.py`` remains the Telegram-shaped view of the same data and is
implemented on top of this module, so both paths agree on the answer.

Two rules this module enforces, both of which the old telegram-only path got
for free from a UNIQUE column and now have to be explicit:

- One provider account maps to exactly one User. Enforced by
  ``uq_identity_provider``; the races are handled here rather than left to
  blow up as IntegrityError at a call site.
- Linking a second provider to an existing User is additive. It never
  rewrites the first, so connecting a web login to a Telegram account cannot
  orphan the Telegram history.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuthProvider, User, UserIdentity

logger = logging.getLogger("coord_bot.identity")


class IdentityConflictError(Exception):
    """Raised when a provider identity is already linked to a different user."""


def _normalize_username(username: Optional[str]) -> Optional[str]:
    """Lowercase, strip a leading @, and treat blank as absent."""
    if not username:
        return None
    normalized = username.strip().lstrip("@").lower()
    return normalized or None


def _normalize_provider_id(provider: str, provider_user_id: str | int) -> str:
    """Provider ids are stored as text so non-numeric providers fit.

    Email is additionally lowercased: addresses are case-insensitive in
    practice, and without this the same person could hold two accounts that
    differ only in capitalization.
    """
    value = str(provider_user_id).strip()
    if provider == AuthProvider.email.value:
        return value.lower()
    return value


async def get_user_by_identity(
    session: AsyncSession,
    provider: str,
    provider_user_id: str | int,
) -> Optional[User]:
    """Return the User behind a provider account, or None."""
    normalized = _normalize_provider_id(provider, provider_user_id)
    result = await session.execute(
        select(User)
        .join(UserIdentity, UserIdentity.user_id == User.user_id)
        .where(
            UserIdentity.provider == provider,
            UserIdentity.provider_user_id == normalized,
        )
    )
    return result.scalar_one_or_none()


async def resolve_identity(
    session: AsyncSession,
    provider: str,
    provider_user_id: str | int,
    *,
    display_name: Optional[str] = None,
    username: Optional[str] = None,
    create: bool = True,
) -> Optional[User]:
    """Resolve a provider account to a User, creating one if allowed.

    This is the entry point every transport should use. `create=False` is for
    flows that must not silently mint accounts -- an invitation accept, say,
    where an unknown identity is an error rather than a new user.

    Profile fields are refreshed on each resolve, because a display name or
    username changed on the provider side should follow the user here.
    """
    normalized = _normalize_provider_id(provider, provider_user_id)
    user = await get_user_by_identity(session, provider, normalized)

    if user is not None:
        await _refresh_profile(session, user, display_name, username)
        return user

    if not create:
        return None

    user = User(display_name=display_name, username=_normalize_username(username))
    # telegram_user_id is still NOT NULL during the expand phase, so a
    # Telegram resolve has to populate it. A user arriving from any other
    # provider cannot, which is precisely what the contract migration frees.
    if provider == AuthProvider.telegram.value:
        user.telegram_user_id = int(normalized)
    session.add(user)
    await session.flush()

    session.add(
        UserIdentity(
            user_id=user.user_id,
            provider=provider,
            provider_user_id=normalized,
        )
    )

    try:
        await session.flush()
    except IntegrityError:
        # Two concurrent requests for the same new identity: one wins, and
        # this one re-reads rather than failing. Without this the second
        # request surfaces a unique-violation to the user for what is a
        # perfectly ordinary double-tap.
        await session.rollback()
        existing = await get_user_by_identity(session, provider, normalized)
        if existing is None:
            raise
        logger.info(
            "Concurrent identity creation for %s:%s resolved to user %s",
            provider,
            normalized,
            existing.user_id,
        )
        return existing

    return user


async def _refresh_profile(
    session: AsyncSession,
    user: User,
    display_name: Optional[str],
    username: Optional[str],
) -> None:
    normalized_username = _normalize_username(username)
    changed = False
    if display_name and user.display_name != display_name:
        user.display_name = display_name
        changed = True
    if normalized_username and user.username != normalized_username:
        user.username = normalized_username
        changed = True
    if changed:
        await session.flush()


async def link_identity(
    session: AsyncSession,
    user_id: int,
    provider: str,
    provider_user_id: str | int,
) -> UserIdentity:
    """Attach another provider account to an existing user.

    This is how a Telegram user gains a web login, or the reverse. Raises
    IdentityConflictError if the provider account already belongs to somebody
    else -- merging two populated accounts is a product decision, not
    something to do implicitly here.
    """
    normalized = _normalize_provider_id(provider, provider_user_id)

    existing = await session.execute(
        select(UserIdentity).where(
            UserIdentity.provider == provider,
            UserIdentity.provider_user_id == normalized,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        if found.user_id == user_id:
            return found
        raise IdentityConflictError(
            f"{provider} account {normalized} is already linked to user "
            f"{found.user_id}"
        )

    identity = UserIdentity(
        user_id=user_id, provider=provider, provider_user_id=normalized
    )
    session.add(identity)
    await session.flush()
    return identity


async def get_identities(session: AsyncSession, user_id: int) -> list[UserIdentity]:
    """Every provider account linked to a user."""
    result = await session.execute(
        select(UserIdentity).where(UserIdentity.user_id == user_id)
    )
    return list(result.scalars().all())


async def get_user_by_public_id(
    session: AsyncSession, public_id: str | UUID
) -> Optional[User]:
    """Look up by the UUID external clients use.

    API request handlers should resolve through this rather than accepting an
    internal user_id from a client, which would be enumerable.
    """
    try:
        value = public_id if isinstance(public_id, UUID) else UUID(str(public_id))
    except (ValueError, AttributeError, TypeError):
        return None
    result = await session.execute(select(User).where(User.public_id == value))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Telegram-shaped conveniences
# ---------------------------------------------------------------------------


async def resolve_telegram_user(
    session: AsyncSession,
    telegram_user_id: int,
    *,
    display_name: Optional[str] = None,
    username: Optional[str] = None,
) -> User:
    """Resolve a Telegram id to a User, creating one if needed."""
    user = await resolve_identity(
        session,
        AuthProvider.telegram.value,
        telegram_user_id,
        display_name=display_name,
        username=username,
        create=True,
    )
    assert user is not None  # create=True never returns None
    return user
