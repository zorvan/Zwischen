"""The hot read paths, and the index each one is meant to use.

Each entry mirrors a query the application actually issues (the source is
named) with representative parameters. ``explain_indexes`` runs EXPLAIN --
never ANALYZE unless asked, so it is safe against a production database --
and returns the indexes the planner chose.

Used by ``scripts/explain_hot_queries.py`` (run it against real data) and by
``tests/test_query_budget.py`` (asserts the plan on a seeded database).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text


@dataclass(frozen=True)
class HotQuery:
    name: str
    source: str
    sql: str
    #: Any of these satisfies the query; the first is the one it was built for.
    indexes: tuple[str, ...]


HOT_QUERIES: tuple[HotQuery, ...] = (
    HotQuery(
        "confirmed count for an event",
        "ParticipantService / lifecycle threshold and lock checks",
        "SELECT count(*) FROM event_participants "
        "WHERE event_id = :event_id AND status = 'confirmed'",
        ("idx_event_participants_event_status",),
    ),
    HotQuery(
        "group events by state, soonest first",
        "events list and menus",
        "SELECT * FROM events WHERE group_id = :group_id "
        "AND state IN ('proposed', 'interested', 'confirmed', 'locked') "
        "ORDER BY scheduled_time LIMIT 20",
        ("idx_events_group_state_time",),
    ),
    HotQuery(
        "next waitlist entry to promote",
        "WaitlistService.get_next_waitlisted",
        "SELECT * FROM event_waitlist WHERE event_id = :event_id "
        "AND status = 'waiting' ORDER BY added_at LIMIT 1",
        ("idx_event_waitlist_event_status_added",),
    ),
    HotQuery(
        "enrichments of one type for an event",
        "EventEnrichmentService (hashtags, memory fragments)",
        "SELECT content FROM event_enrichments "
        "WHERE event_id = :event_id AND enrichment_type = 'hashtag'",
        ("idx_enrichments_event_type",),
    ),
    HotQuery(
        "active members of a group",
        "MembershipService.list_members",
        "SELECT user_id FROM group_members "
        "WHERE group_id = :group_id AND status = 'active'",
        ("idx_group_members_group_status", "group_members_pkey"),
    ),
    HotQuery(
        "groups a user belongs to",
        "MembershipService / my_groups, API membership filter",
        "SELECT group_id FROM group_members WHERE user_id = :user_id",
        ("idx_group_members_user",),
    ),
    HotQuery(
        "Telegram chat for internal users",
        "db.identity.telegram_chat_ids",
        "SELECT user_id, provider_user_id FROM user_identities "
        "WHERE user_id IN (:user_id) AND provider = 'telegram'",
        ("idx_user_identities_user",),
    ),
    HotQuery(
        "a user's participation history",
        "my_history, attendance mirror, erasure cascade",
        "SELECT event_id FROM event_participants WHERE user_id = :user_id",
        ("idx_event_participants_user",),
    ),
    HotQuery(
        "events a user organizes",
        "erasure SET NULL on events.organizer_user_id",
        "SELECT event_id FROM events WHERE organizer_user_id = :user_id",
        ("idx_events_organizer_user",),
    ),
    HotQuery(
        "transitions a user made",
        "erasure SET NULL on event_state_transitions.actor_user_id",
        "SELECT transition_id FROM event_state_transitions "
        "WHERE actor_user_id = :user_id",
        ("idx_event_state_transitions_actor",),
    ),
)


def _index_names(plan: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(plan, dict):
        if "Index Name" in plan:
            found.add(plan["Index Name"])
        for value in plan.values():
            found |= _index_names(value)
    elif isinstance(plan, list):
        for item in plan:
            found |= _index_names(item)
    return found


async def explain_indexes(
    conn: Any, query: HotQuery, params: dict[str, Any], *, analyze: bool = False
) -> tuple[set[str], Any]:
    """Indexes the planner uses for ``query``, and the raw JSON plan."""
    options = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "FORMAT JSON"
    result = await conn.execute(text(f"EXPLAIN ({options}) {query.sql}"), params)
    raw = result.scalar()
    plan = json.loads(raw) if isinstance(raw, str) else raw
    return _index_names(plan), plan
