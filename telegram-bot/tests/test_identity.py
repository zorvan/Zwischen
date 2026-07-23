"""Tests for provider-agnostic identity resolution."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from db.connection import get_session
from db.identity import (
    AuthProvider,
    IdentityConflictError,
    get_identities,
    get_user_by_identity,
    get_user_by_public_id,
    link_identity,
    resolve_identity,
    resolve_telegram_user,
)
from db.models import User, UserIdentity
from db.users import get_or_create_user_id

pytestmark = pytest.mark.integration

TELEGRAM = AuthProvider.telegram.value
EMAIL = AuthProvider.email.value


async def test_resolving_a_new_telegram_id_creates_user_and_identity(
    test_db_url: str,
) -> None:
    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(
            session, 555001, display_name="Ada", username="@Ada"
        )
        await session.commit()

        assert user.user_id is not None
        assert user.public_id is not None
        # Username is normalized: no leading @, lowercased.
        assert user.username == "ada"

        identities = await get_identities(session, user.user_id)
        assert [(i.provider, i.provider_user_id) for i in identities] == [
            (TELEGRAM, "555001")
        ]


async def test_resolving_twice_returns_the_same_user(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        first = await resolve_telegram_user(session, 555002)
        await session.commit()
        second = await resolve_telegram_user(session, 555002)
        await session.commit()

        assert first.user_id == second.user_id

        count = await session.execute(
            select(UserIdentity).where(UserIdentity.provider_user_id == "555002")
        )
        assert len(list(count.scalars().all())) == 1


async def test_the_bot_path_also_creates_an_identity_row(test_db_url: str) -> None:
    """The Telegram helper must not bypass the identity table.

    If it did, users created by the bot after this migration would be
    invisible to every non-Telegram client.
    """
    async with get_session(test_db_url) as session:
        user_id = await get_or_create_user_id(
            session, 555003, display_name="Grace", username="grace"
        )
        await session.commit()

        identities = await get_identities(session, user_id)
        assert [(i.provider, i.provider_user_id) for i in identities] == [
            (TELEGRAM, "555003")
        ]


async def test_a_web_user_needs_no_telegram_account(test_db_url: str) -> None:
    """The point of the whole migration: identity without Telegram."""
    async with get_session(test_db_url) as session:
        user = await resolve_identity(
            session, EMAIL, "Ada@Example.com", display_name="Ada"
        )
        await session.commit()

        assert user is not None
        identities = await get_identities(session, user.user_id)
        # Email is lowercased, or the same person could hold two accounts
        # differing only in capitalization.
        assert [(i.provider, i.provider_user_id) for i in identities] == [
            (EMAIL, "ada@example.com")
        ]


async def test_email_lookup_is_case_insensitive(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        created = await resolve_identity(session, EMAIL, "Bob@Example.com")
        await session.commit()
        found = await get_user_by_identity(session, EMAIL, "BOB@EXAMPLE.COM")

        assert found is not None
        assert created is not None
        assert found.user_id == created.user_id


async def test_linking_a_web_login_to_a_telegram_account(test_db_url: str) -> None:
    """The migration path for an existing user adopting the web app."""
    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 555004, display_name="Alan")
        await session.commit()

        await link_identity(session, user.user_id, EMAIL, "alan@example.com")
        await session.commit()

        # Both credentials now resolve to the same account, and the Telegram
        # history is untouched.
        via_email = await get_user_by_identity(session, EMAIL, "alan@example.com")
        via_telegram = await get_user_by_identity(session, TELEGRAM, 555004)
        assert via_email is not None and via_telegram is not None
        assert via_email.user_id == via_telegram.user_id == user.user_id


async def test_linking_an_already_claimed_identity_is_refused(
    test_db_url: str,
) -> None:
    """Merging two populated accounts is a product decision, not implicit."""
    async with get_session(test_db_url) as session:
        first = await resolve_telegram_user(session, 555005)
        second = await resolve_telegram_user(session, 555006)
        await session.commit()

        await link_identity(session, first.user_id, EMAIL, "shared@example.com")
        await session.commit()

        with pytest.raises(IdentityConflictError):
            await link_identity(session, second.user_id, EMAIL, "shared@example.com")


async def test_relinking_the_same_identity_is_idempotent(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 555007)
        await session.commit()

        one = await link_identity(session, user.user_id, EMAIL, "dup@example.com")
        await session.commit()
        two = await link_identity(session, user.user_id, EMAIL, "dup@example.com")

        assert one.identity_id == two.identity_id


async def test_create_false_does_not_mint_an_account(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        result = await resolve_identity(
            session, EMAIL, "ghost@example.com", create=False
        )
        assert result is None

        rows = await session.execute(
            select(User).where(User.display_name == "ghost@example.com")
        )
        assert rows.scalar_one_or_none() is None


async def test_public_id_lookup(test_db_url: str) -> None:
    """External clients address users by UUID, never the integer key."""
    async with get_session(test_db_url) as session:
        user = await resolve_telegram_user(session, 555008)
        await session.commit()

        found = await get_user_by_public_id(session, str(user.public_id))
        assert found is not None
        assert found.user_id == user.user_id


async def test_public_id_lookup_rejects_garbage(test_db_url: str) -> None:
    """A malformed id from a client must return None, not raise."""
    async with get_session(test_db_url) as session:
        assert await get_user_by_public_id(session, "not-a-uuid") is None
        assert await get_user_by_public_id(session, "") is None


async def test_profile_updates_follow_the_provider(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        await resolve_telegram_user(session, 555009, display_name="Old", username="old")
        await session.commit()

        updated = await resolve_telegram_user(
            session, 555009, display_name="New", username="@New"
        )
        await session.commit()

        assert updated.display_name == "New"
        assert updated.username == "new"
