"""T15: the retention policy, enforced.

docs/RETENTION_POLICY.md is the contract. These tests seed rows on both
sides of every window, run the decay job, and assert that nothing outstays
its window (RetentionService.overdue() is all zeros), that nothing inside a
window is touched, and that a second run changes nothing. Account erasure is
exercised through the service, the bot's transport scrub, and the HTTP API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select

from bot.services.event_memory_service import fragment_contributor_hash
from bot.services.retention_service import RetentionService
from db.connection import get_session
from db.identity import AuthProvider, resolve_identity, resolve_telegram_user
from db.models import (
    Constraint,
    Event,
    EventEnrichment,
    EventMemory,
    EventParticipant,
    EventStateTransition,
    EventWaitlist,
    Group,
    GroupMember,
    IdempotencyKey,
    Log,
    ParticipantStatus,
    User,
    UserIdentity,
    UserPreference,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def fragment(event_id: int, user_id: int, when: datetime, text: str) -> dict:
    return {
        "text": text,
        "contributor_hash": fragment_contributor_hash(
            event_id, user_id, when.date().isoformat()
        ),
        "submitted_at": when.replace(tzinfo=None).isoformat(),
        "word_count": len(text.split()),
    }


async def _event_with_detail(
    session: Any,
    *,
    group: Group,
    users: list[User],
    state: str,
    created: datetime,
    completed: datetime | None = None,
    cancelled: datetime | None = None,
) -> int:
    event = Event(
        group_id=group.group_id,
        event_type="dinner",
        title=f"{state} dinner",
        description="At Mina's, bring bread",
        planning_prefs={"location_type": "home"},
        state=state,
        version=0,
        created_at=created,
        completed_at=completed,
        organizer_user_id=users[0].user_id,
        emergency_admin_user_id=users[0].user_id,
    )
    session.add(event)
    await session.flush()
    eid = int(event.event_id)
    session.add_all(
        [
            EventParticipant(
                event_id=eid,
                user_id=users[0].user_id,
                status=ParticipantStatus.confirmed,
            ),
            EventParticipant(
                event_id=eid, user_id=users[1].user_id, status=ParticipantStatus.joined
            ),
            EventWaitlist(event_id=eid, user_id=users[2].user_id, position=1),
            Constraint(
                event_id=eid,
                user_id=users[1].user_id,
                target_user_id=users[0].user_id,
                type="if_joins",
            ),
            EventEnrichment(
                event_id=eid,
                user_id=users[1].user_id,
                enrichment_type="idea",
                content="Board games after",
            ),
            EventStateTransition(
                event_id=eid,
                from_state="proposed",
                to_state=state,
                actor_user_id=users[0].user_id,
                reason="because",
                source="test",
                timestamp=cancelled or completed or created,
            ),
            EventMemory(
                event_id=eid,
                fragments=[fragment(eid, int(users[1].user_id), created, "Warm night")],
                hashtags=["warm"],
                weave_text="It was a warm night.",
                lineage_event_ids=[1],
                created_at=created,
            ),
        ]
    )
    await session.flush()
    return eid


async def _seed(url: str) -> dict[str, Any]:
    async with get_session(url) as session:
        users = [
            await resolve_telegram_user(
                session, 8_100_000_000 + n, display_name=f"U{n}"
            )
            for n in range(3)
        ]
        group = Group(telegram_group_id=-1_008_100_000_000, group_name="Decay")
        session.add(group)
        await session.flush()
        ids = {
            "recent": await _event_with_detail(
                session,
                group=group,
                users=users,
                state="completed",
                created=days_ago(20),
                completed=days_ago(10),
            ),
            "old": await _event_with_detail(
                session,
                group=group,
                users=users,
                state="completed",
                created=days_ago(210),
                completed=days_ago(200),
            ),
            "ancient": await _event_with_detail(
                session,
                group=group,
                users=users,
                state="completed",
                created=days_ago(410),
                completed=days_ago(400),
            ),
            "cancelled_old": await _event_with_detail(
                session,
                group=group,
                users=users,
                state="cancelled",
                created=days_ago(300),
                cancelled=days_ago(250),
            ),
            # Old, but still in progress: coordination data must survive.
            "open_old": await _event_with_detail(
                session,
                group=group,
                users=users,
                state="proposed",
                created=days_ago(400),
            ),
        }
        session.add_all(
            [
                Log(action="old", timestamp=days_ago(100)),
                Log(action="fresh", timestamp=days_ago(5)),
                IdempotencyKey(
                    idempotency_key="expired",
                    command_type="join",
                    expires_at=days_ago(1),
                ),
                IdempotencyKey(
                    idempotency_key="live",
                    command_type="join",
                    expires_at=NOW + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()
        return ids


async def _count(session: Any, model: Any, event_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.event_id == event_id)
        )
        or 0
    )


async def test_decay_enforces_every_window(test_db_url: str) -> None:
    ids = await _seed(test_db_url)

    async with get_session(test_db_url) as session:
        service = RetentionService(session)
        assert any((await service.overdue(now=NOW)).values())
        counts = await service.decay(now=NOW)
        await session.commit()

    assert counts["logs"] == 1
    assert counts["idempotency_keys"] == 1
    assert counts["participants"] == 2 * 3  # old, ancient, cancelled_old
    assert counts["memories_deleted"] == 1  # ancient

    async with get_session(test_db_url) as session:
        # Nothing outstays its window -- the invariant CI enforces.
        assert await RetentionService(session).overdue(now=NOW) == {
            key: 0 for key in await RetentionService(session).overdue(now=NOW)
        }

        for key in ("recent", "open_old"):
            eid = ids[key]
            for model in (
                EventParticipant,
                EventWaitlist,
                Constraint,
                EventEnrichment,
                EventMemory,
            ):
                assert await _count(session, model, eid) >= 1, (key, model)
            event = await session.get(Event, eid)
            assert event.description and event.organizer_user_id

        for key in ("old", "cancelled_old"):
            eid = ids[key]
            for model in (EventParticipant, EventWaitlist, Constraint, EventEnrichment):
                assert await _count(session, model, eid) == 0, (key, model)
            event = await session.get(Event, eid)
            # A minimal, unattributed record remains.
            assert event is not None and event.title
            assert event.description is None and event.planning_prefs is None
            assert event.organizer_user_id is None
            transition = await session.scalar(
                select(EventStateTransition).where(EventStateTransition.event_id == eid)
            )
            assert transition.actor_user_id is None and transition.reason is None
            memory = await session.scalar(
                select(EventMemory).where(EventMemory.event_id == eid)
            )
            # Detail decays to summary.
            assert memory.fragments == [] and memory.lineage_event_ids == []
            assert memory.weave_text and memory.hashtags == ["warm"]

        assert await _count(session, EventMemory, ids["ancient"]) == 0
        assert await session.get(Event, ids["ancient"]) is not None
        assert [
            log.action for log in (await session.execute(select(Log))).scalars()
        ] == ["fresh"]


async def test_decay_is_idempotent(test_db_url: str) -> None:
    await _seed(test_db_url)
    async with get_session(test_db_url) as session:
        await RetentionService(session).decay(now=NOW)
        await session.commit()
    async with get_session(test_db_url) as session:
        second = await RetentionService(session).decay(now=NOW)
        await session.commit()
    assert second == {key: 0 for key in second}


async def _seed_account(url: str) -> dict[str, Any]:
    async with get_session(url) as session:
        leaving = await resolve_telegram_user(
            session, 8_200_000_001, display_name="Leaving"
        )
        staying = await resolve_telegram_user(
            session, 8_200_000_002, display_name="Staying"
        )
        group = Group(telegram_group_id=-1_008_200_000_000, group_name="Erase")
        session.add(group)
        await session.flush()
        session.add_all(
            [
                GroupMember(group_id=group.group_id, user_id=leaving.user_id),
                GroupMember(group_id=group.group_id, user_id=staying.user_id),
                UserPreference(user_id=leaving.user_id, language_preference="fa"),
            ]
        )
        eid = await _event_with_detail(
            session,
            group=group,
            users=[leaving, staying, staying],
            state="completed",
            created=days_ago(3),
            completed=days_ago(2),
        )
        memory = await session.scalar(
            select(EventMemory).where(EventMemory.event_id == eid)
        )
        memory.fragments = [
            fragment(eid, int(leaving.user_id), days_ago(1), "Mine"),
            fragment(eid, int(staying.user_id), days_ago(1), "Theirs"),
        ]
        session.add(
            IdempotencyKey(
                idempotency_key="leaving-key",
                command_type="join",
                user_id=leaving.user_id,
                event_id=eid,
                expires_at=NOW + timedelta(days=1),
            )
        )
        await session.commit()
        return {
            "leaving": int(leaving.user_id),
            "staying": int(staying.user_id),
            "event_id": eid,
        }


async def test_erase_user_removes_personal_data_and_anonymizes_shared(
    test_db_url: str,
) -> None:
    ids = await _seed_account(test_db_url)
    leaving = ids["leaving"]

    async with get_session(test_db_url) as session:
        result = await RetentionService(session).erase_user(leaving)
        await session.commit()
    assert result is not None
    assert result.provider_ids(AuthProvider.telegram.value) == ["8200000001"]
    assert result.memory_fragments_removed == 1

    async with get_session(test_db_url) as session:
        assert await session.get(User, leaving) is None
        personal: tuple[Any, ...] = (
            UserIdentity,
            UserPreference,
            GroupMember,
            EventParticipant,
            Constraint,
            EventEnrichment,
            IdempotencyKey,
        )
        for model in personal:
            remaining = await session.scalar(
                select(func.count()).select_from(model).where(model.user_id == leaving)
            )
            assert remaining == 0, model

        event = await session.get(Event, ids["event_id"])
        assert event is not None, "shared events stay for the rest of the group"
        assert event.organizer_user_id is None
        transition = await session.scalar(
            select(EventStateTransition).where(
                EventStateTransition.event_id == ids["event_id"]
            )
        )
        assert transition.actor_user_id is None
        memory = await session.scalar(
            select(EventMemory).where(EventMemory.event_id == ids["event_id"])
        )
        assert [f["text"] for f in memory.fragments] == ["Theirs"]
        assert await session.get(User, ids["staying"]) is not None

        assert await RetentionService(session).erase_user(leaving) is None


async def test_telegram_scrub_forgets_the_user() -> None:
    from bot.commands.account import scrub_telegram_state

    dropped: list[int] = []

    class Persistence:
        async def drop_user_data(self, user_id: int) -> None:
            dropped.append(user_id)

    application = SimpleNamespace(
        drop_user_data=lambda user_id: None, persistence=Persistence()
    )
    context = SimpleNamespace(
        application=application,
        bot_data={
            "chat_history": {
                -100: [
                    {"user_id": 42, "text": "mine"},
                    {"user_id": 7, "text": "theirs"},
                ]
            },
            "pending_modify_requests": {
                "modreq_a": {"requester_id": 42, "admin_id": 7},
                "modreq_b": {"requester_id": 7, "admin_id": 8},
            },
        },
    )
    await scrub_telegram_state(context, 42)

    assert context.bot_data["chat_history"][-100] == [{"user_id": 7, "text": "theirs"}]
    assert list(context.bot_data["pending_modify_requests"]) == ["modreq_b"]
    assert dropped == [42]


def test_chat_history_is_bounded_in_age_and_size() -> None:
    from bot.handlers.mentions import HISTORY_LIMIT, _fresh_history

    now = datetime.utcnow()
    stale = {"timestamp": (now - timedelta(hours=25)).isoformat(), "text": "old"}
    fresh = [
        {"timestamp": (now - timedelta(minutes=n)).isoformat(), "text": str(n)}
        for n in range(HISTORY_LIMIT + 5, 0, -1)
    ]
    kept = _fresh_history([stale, *fresh])
    assert stale not in kept
    assert len(kept) == HISTORY_LIMIT
    assert kept[-1]["text"] == "1"


async def test_api_delete_me_erases_and_revokes(test_db_url: str) -> None:
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    from api.app import create_app
    from core.auth import SessionManager
    from core.state import InMemoryStateBackend

    async with get_session(test_db_url) as session:
        user = await resolve_identity(
            session, AuthProvider.email.value, "leaving@example.com"
        )
        assert user is not None
        user_id = int(user.user_id)
        await session.commit()

    state = InMemoryStateBackend()
    secret = "test-secret-at-least-32-bytes-long!!"
    app = create_app(
        db_url=test_db_url, bot_token="1:x", auth_secret=secret, state_backend=state
    )
    pair = await SessionManager(state, secret).issue(user_id)
    headers = {"Authorization": f"Bearer {pair.access_token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/me", headers=headers)
        assert response.status_code == 204
        again = await client.get("/events", headers=headers)
        assert again.status_code == 401

    async with get_session(test_db_url) as session:
        assert await session.get(User, user_id) is None
