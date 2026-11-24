"""T12: query counts and index use on the hot paths.

Two kinds of regression guard:

* Rendering scales by constant query count. A view over N participants or
  N events must not issue O(N) statements; the tests render at two sizes and
  require the same count.
* The hot read paths use the indexes built for them. On a seeded database
  of realistic shape (and after ANALYZE), EXPLAIN must pick the intended
  index for every entry in db.hot_queries.HOT_QUERIES.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from config.settings import settings
from core.query_counter import count_queries
from db.connection import get_session
from db.hot_queries import HOT_QUERIES, explain_indexes
from db.identity import resolve_telegram_user
from db.models import Event, EventParticipant, Group, ParticipantStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def db_settings(test_db_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    import config.settings as settings_module
    from bot.common import event_presenters

    for holder in {
        id(obj): obj
        for obj in (settings, settings_module.settings, event_presenters.settings)
    }.values():
        monkeypatch.setattr(holder, "db_url", test_db_url)
    return test_db_url


async def _event_with(url: str, participants: int, offset: int) -> tuple[int, int]:
    async with get_session(url) as session:
        group = Group(telegram_group_id=-1_007_000_000_000 - offset, group_name="q")
        session.add(group)
        await session.flush()
        users = [
            await resolve_telegram_user(
                session, 7_500_000_000 + offset * 1000 + n, display_name=f"u{n}"
            )
            for n in range(participants)
        ]
        event = Event(
            group_id=group.group_id,
            event_type="dinner",
            state="interested",
            version=0,
            organizer_user_id=users[0].user_id,
            emergency_admin_user_id=users[0].user_id,
            min_participants=3,
        )
        session.add(event)
        await session.flush()
        for n, user in enumerate(users):
            session.add(
                EventParticipant(
                    event_id=event.event_id,
                    user_id=user.user_id,
                    status=(
                        ParticipantStatus.confirmed
                        if n % 2
                        else ParticipantStatus.joined
                    ),
                )
            )
        await session.commit()
        return int(event.event_id), int(group.group_id)


async def test_event_rendering_is_constant_in_participants(db_settings: str) -> None:
    from bot.common.event_presenters import (
        format_event_details_message,
        format_status_message,
    )

    counts: dict[str, list[int]] = {"status": [], "details": []}
    for size, offset in ((2, 1), (15, 2)):
        event_id, _ = await _event_with(db_settings, size, offset)
        async with get_session(db_settings) as session:
            event = (
                await session.execute(
                    select(Event)
                    .options(selectinload(Event.participants))
                    .where(Event.event_id == event_id)
                )
            ).scalar_one()
            with count_queries() as counter:
                await format_status_message(event_id, event, 0, 0, session=session)
            counts["status"].append(counter.total)
            with count_queries() as counter:
                await format_event_details_message(event_id, event, [], [])
            counts["details"].append(counter.total)

    for view, (small, large) in counts.items():
        assert small == large, f"{view}: {small} queries at 2, {large} at 15"


async def test_lock_announcement_is_constant_in_participants(
    db_settings: str,
) -> None:
    from bot.services.event_materialization_service import (
        EventMaterializationService,
    )
    from core.notifier import NullNotifier

    totals = []
    for size, offset in ((2, 3), (15, 4)):
        event_id, _ = await _event_with(db_settings, size, offset)
        async with get_session(db_settings) as session:
            event = await session.get(Event, event_id)
            participants = list(
                (
                    await session.execute(
                        select(EventParticipant).where(
                            EventParticipant.event_id == event_id
                        )
                    )
                ).scalars()
            )
            service = EventMaterializationService(NullNotifier(), session)
            with count_queries() as counter:
                await service.announce_event_locked(event, participants, 0)
            totals.append(counter.total)
    assert totals[0] == totals[1], totals


async def test_api_event_list_is_constant_in_events(test_db_url: str) -> None:
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    from api.app import create_app
    from bot.services.membership_service import MembershipService
    from core.auth import SessionManager
    from core.state import InMemoryStateBackend

    state = InMemoryStateBackend()
    secret = "query-budget-test-secret-32-bytes!!"
    app = create_app(
        db_url=test_db_url, bot_token="1:x", auth_secret=secret, state_backend=state
    )

    async def list_count(viewer_tg: int) -> tuple[int, int]:
        async with get_session(test_db_url) as session:
            viewer = await resolve_telegram_user(session, viewer_tg)
            for group_id in (await session.execute(select(Group.group_id))).scalars():
                if not await MembershipService(session).is_member(
                    group_id, viewer.user_id
                ):
                    await MembershipService(session).add_member(
                        group_id, viewer.user_id
                    )
            viewer_id = int(viewer.user_id)
            await session.commit()
        pair = await SessionManager(state, secret).issue(viewer_id)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t"
        ) as client:
            with count_queries() as counter:
                response = await client.get(
                    "/events", headers={"Authorization": f"Bearer {pair.access_token}"}
                )
        assert response.status_code == 200
        return len(response.json()), counter.total

    await _event_with(test_db_url, 3, 10)
    few, few_queries = await list_count(7_600_000_001)
    for offset in range(11, 19):
        await _event_with(test_db_url, 3, offset)
    many, many_queries = await list_count(7_600_000_002)

    assert (few, many) == (1, 9)
    assert few_queries == many_queries, (few_queries, many_queries)


SEED_SQL = (
    # 2,000 users, half with a Telegram identity.
    "INSERT INTO users (display_name) SELECT 'user ' || n FROM generate_series(1, 2000) n",
    "INSERT INTO user_identities (user_id, provider, provider_user_id) "
    "SELECT user_id, 'telegram', (8000000000 + user_id)::text FROM users "
    "WHERE user_id % 2 = 0",
    # 200 groups, ten members each.
    "INSERT INTO groups (group_name) SELECT 'group ' || n FROM generate_series(1, 200) n",
    "INSERT INTO group_members (group_id, user_id, role, status) "
    "SELECT g.group_id, ((g.group_id * 10 + k) % 2000) + 1, 'member', "
    "CASE WHEN k = 0 THEN 'removed' ELSE 'active' END "
    "FROM groups g, generate_series(0, 9) k ON CONFLICT DO NOTHING",
    # 10,000 events across groups and states, spread over two years.
    "INSERT INTO events (group_id, event_type, state, version, scheduled_time, "
    "organizer_user_id) SELECT (n % 200) + 1, 'dinner', "
    "(ARRAY['proposed','interested','confirmed','locked','completed','cancelled'])"
    "[(n % 6) + 1], 0, now() - (n || ' hours')::interval, (n % 2000) + 1 "
    "FROM generate_series(1, 10000) n",
    # Eight participants per event: 80,000 rows.
    "INSERT INTO event_participants (event_id, user_id, status, role) "
    "SELECT e.event_id, ((e.event_id * 8 + k) % 2000) + 1, "
    "(CASE WHEN k % 3 = 0 THEN 'confirmed' ELSE 'joined' END)::participant_status, "
    "'participant'::participant_role FROM events e, generate_series(0, 7) k "
    "ON CONFLICT DO NOTHING",
    "INSERT INTO event_waitlist (event_id, user_id, added_at, status) "
    "SELECT e.event_id, ((e.event_id * 3 + k) % 2000) + 1, "
    "now() - (k || ' minutes')::interval, "
    "CASE WHEN k = 0 THEN 'waiting' ELSE 'expired' END "
    "FROM events e, generate_series(0, 3) k ON CONFLICT DO NOTHING",
    "INSERT INTO event_enrichments (event_id, user_id, enrichment_type, content) "
    "SELECT e.event_id, (e.event_id % 2000) + 1, "
    "(ARRAY['idea','hashtag','memory'])[(k % 3) + 1], 'x' "
    "FROM events e, generate_series(0, 2) k",
    "INSERT INTO event_state_transitions (event_id, from_state, to_state, "
    "actor_user_id, source, timestamp) SELECT event_id, 'proposed', state, "
    "organizer_user_id, "
    "'seed', now() FROM events",
    "ANALYZE",
)


async def test_hot_queries_use_their_indexes(test_db_url: str) -> None:
    async with get_session(test_db_url) as session:
        for statement in SEED_SQL:
            await session.execute(text(statement))
        await session.commit()

    params: dict[str, Any] = {"event_id": 4242, "group_id": 42, "user_id": 1234}
    misses = []
    async with get_session(test_db_url) as session:
        for query in HOT_QUERIES:
            used, _ = await explain_indexes(session, query, params)
            if not used & set(query.indexes):
                misses.append(f"{query.name}: wanted {query.indexes}, plan used {used}")
    assert not misses, "\n".join(misses)


def test_update_labels_are_low_cardinality() -> None:
    from telegram import CallbackQuery, Chat, Message, Update, User as TgUser

    from bot.common.query_budget import describe_update

    user = TgUser(id=1, first_name="a", is_bot=False)
    chat = Chat(id=1, type="private")
    command = Message(
        message_id=1, date=None, chat=chat, from_user=user, text="/events@bot 42"
    )
    assert describe_update(Update(1, message=command)) == "command:/events"
    callback = CallbackQuery(
        id="1", from_user=user, chat_instance="c", data="ev:4242:join"
    )
    assert describe_update(Update(2, callback_query=callback)) == "callback:ev"
    plain = Message(message_id=2, date=None, chat=chat, from_user=user, text="hi")
    assert describe_update(Update(3, message=plain)) == "message"


async def test_budget_warning_names_the_label(
    test_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core import query_counter

    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        query_counter.logger,
        "warning",
        lambda message, extra: warnings.append((message, extra)),
    )
    async with get_session(test_db_url) as session:
        with count_queries("callback:ev", warn_above=1) as counter:
            await session.execute(text("SELECT 1"))
            await session.execute(text("SELECT 2"))
        with count_queries("within", warn_above=5):
            await session.execute(text("SELECT 3"))
    assert counter.total == 2
    assert warnings == [
        ("Query budget exceeded", {"label": "callback:ev", "queries": 2, "budget": 1})
    ]
