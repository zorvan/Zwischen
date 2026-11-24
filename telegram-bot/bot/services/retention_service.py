# mypy: disable-error-code="attr-defined"
"""Executable data-retention policy (see docs/RETENTION_POLICY.md).

Two operations:

* ``decay`` -- the scheduled, cluster-wide job. Detail decays in stages
  measured from when an event *ended*, so a gathering leaves behind a
  shrinking memory rather than a permanent record of who was with whom.
* ``erase_user`` -- the right to erasure. Personal rows go, shared rows are
  anonymized, and the caller is told which provider accounts were removed so
  transport-side state (Telegram conversation data, chat history) can be
  scrubbed too.

Both are idempotent: running either twice has the same result as once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    Text,
    and_,
    cast,
    delete,
    func,
    null,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from bot.services.event_memory_service import fragment_contributor_hash
from db.models import (
    AnchorOutbox,
    Constraint,
    Event,
    EventEnrichment,
    EventMemory,
    EventParticipant,
    EventStateTransition,
    EventWaitlist,
    IdempotencyKey,
    Log,
    User,
    UserIdentity,
)

#: An event's lifecycle is over in either of these states.
TERMINAL_STATES = ("completed", "cancelled")


@dataclass
class ErasureResult:
    """What an account erasure removed."""

    user_id: int
    #: (provider, provider_user_id) for every identity that was linked.
    identities: list[tuple[str, str]] = field(default_factory=list)
    memory_fragments_removed: int = 0

    def provider_ids(self, provider: str) -> list[str]:
        return [pid for prov, pid in self.identities if prov == provider]


class RetentionService:
    #: Proof bundles stay fetchable this long after their anchor confirms...
    ANCHOR_BUNDLE_DAYS = 7
    #: ...and anchor rows (commitment, tx ref) are deleted after this long.
    ANCHOR_ROW_DAYS = 30
    LOG_DAYS = 90
    SOCIAL_GRAPH_DAYS = 180
    DETAIL_DAYS = 180
    MEMORY_DAYS = 365

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- when did an event end? ---------------------------------------------

    def _ended_at(self) -> Any:
        """SQL expression: the moment an event's lifecycle ended, or NULL.

        Completed events carry ``completed_at``. Cancelled events have no such
        column, so the last transition into ``cancelled`` is used, falling
        back to ``created_at`` for rows that predate the audit trail. Events
        still in progress are never eligible.
        """
        cancelled_at = (
            select(func.max(EventStateTransition.timestamp))
            .where(
                EventStateTransition.event_id == Event.event_id,
                EventStateTransition.to_state == "cancelled",
            )
            .correlate(Event)
            .scalar_subquery()
        )
        return func.coalesce(
            Event.completed_at,
            func.coalesce(cancelled_at, Event.created_at),
        )

    def _events_ended_before(self, cutoff: datetime) -> Any:
        ended = self._ended_at()
        return select(Event.event_id).where(
            or_(
                and_(Event.state == "completed", Event.completed_at < cutoff),
                and_(Event.state == "cancelled", ended < cutoff),
                # A completed_at with a stale state is still an ended event.
                and_(Event.state.not_in(TERMINAL_STATES), Event.completed_at < cutoff),
            )
        )

    # -- scheduled decay ------------------------------------------------------

    async def decay(self, *, now: datetime | None = None) -> dict[str, int]:
        """Idempotently remove detail in stages; returns affected row counts."""
        moment = now or datetime.now(timezone.utc)
        detail_cutoff = moment - timedelta(days=self.DETAIL_DAYS)
        memory_cutoff = moment - timedelta(days=self.MEMORY_DAYS)
        old_events = self._events_ended_before(detail_cutoff)
        ancient_events = self._events_ended_before(memory_cutoff)

        counts: dict[str, int] = {}

        async def run(name: str, statement: Any) -> None:
            result = await self.session.execute(statement)
            counts[name] = result.rowcount or 0

        await run(
            "logs",
            delete(Log).where(Log.timestamp < moment - timedelta(days=self.LOG_DAYS)),
        )
        # The social graph: who was there, who wanted in, who set conditions.
        await run(
            "participants",
            delete(EventParticipant).where(EventParticipant.event_id.in_(old_events)),
        )
        await run(
            "waitlist",
            delete(EventWaitlist).where(EventWaitlist.event_id.in_(old_events)),
        )
        await run(
            "constraints",
            delete(Constraint).where(Constraint.event_id.in_(old_events)),
        )
        await run(
            "enrichments",
            delete(EventEnrichment).where(EventEnrichment.event_id.in_(old_events)),
        )
        # Keep that a transition happened; drop who did it and why.
        await run(
            "transitions_anonymized",
            update(EventStateTransition)
            .where(
                EventStateTransition.event_id.in_(old_events),
                or_(
                    EventStateTransition.actor_user_id.is_not(None),
                    EventStateTransition.reason.is_not(None),
                ),
            )
            .values(actor_user_id=None, reason=None),
        )
        # The event itself shrinks to a minimal record: type, title, time,
        # state. Member-authored description and planning detail go.
        await run(
            "events_minimized",
            update(Event)
            .where(
                Event.event_id.in_(old_events),
                or_(
                    Event.description.is_not(None),
                    _has_items(Event.planning_prefs),
                    Event.organizer_user_id.is_not(None),
                    Event.emergency_admin_user_id.is_not(None),
                ),
            )
            .values(
                description=None,
                # SQL NULL, not JSON null, so the predicate above sees it.
                planning_prefs=null(),
                organizer_user_id=None,
                emergency_admin_user_id=None,
            ),
        )
        # Memories decay from detail (fragments) to summary (weave, tags).
        await run(
            "memories_summarized",
            update(EventMemory)
            .where(
                EventMemory.event_id.in_(old_events),
                EventMemory.event_id.not_in(ancient_events),
                or_(
                    _has_items(EventMemory.fragments),
                    _has_items(EventMemory.lineage_event_ids),
                ),
            )
            .values(fragments=[], lineage_event_ids=[]),
        )
        # ...and then to nothing.
        await run(
            "memories_deleted",
            delete(EventMemory).where(EventMemory.event_id.in_(ancient_events)),
        )
        await run(
            "idempotency_keys",
            delete(IdempotencyKey).where(IdempotencyKey.expires_at < moment),
        )
        # Anchoring (T16): the server's copy of a proof bundle goes first;
        # after that only consenting clients can open the commitment.
        await run(
            "anchor_bundles_dropped",
            update(AnchorOutbox)
            .where(self._anchor_bundle_expired(moment))
            .values(bundle=null()),
        )
        await run(
            "anchor_rows",
            delete(AnchorOutbox).where(self._anchor_row_expired(moment)),
        )
        return counts

    def _anchor_bundle_expired(self, moment: datetime) -> Any:
        bundle_cutoff = moment - timedelta(days=self.ANCHOR_BUNDLE_DAYS)
        row_cutoff = moment - timedelta(days=self.ANCHOR_ROW_DAYS)
        return and_(
            AnchorOutbox.bundle.is_not(None),
            text_not_null(AnchorOutbox.bundle),
            or_(
                AnchorOutbox.confirmed_at < bundle_cutoff,
                # Never confirmed (chain down, or failed): give up holding it.
                AnchorOutbox.created_at < row_cutoff,
            ),
        )

    def _anchor_row_expired(self, moment: datetime) -> Any:
        row_cutoff = moment - timedelta(days=self.ANCHOR_ROW_DAYS)
        return or_(
            AnchorOutbox.confirmed_at < row_cutoff,
            and_(
                AnchorOutbox.status == "failed",
                AnchorOutbox.created_at < row_cutoff,
            ),
        )

    async def overdue(self, *, now: datetime | None = None) -> dict[str, int]:
        """Rows that the policy says should no longer exist.

        All zeros right after ``decay`` is the invariant CI enforces; anything
        else means data outstays its window.
        """
        moment = now or datetime.now(timezone.utc)
        old_events = self._events_ended_before(
            moment - timedelta(days=self.DETAIL_DAYS)
        )
        ancient_events = self._events_ended_before(
            moment - timedelta(days=self.MEMORY_DAYS)
        )

        async def count(statement: Any) -> int:
            return int(await self.session.scalar(statement) or 0)

        return {
            "logs": await count(
                select(func.count())
                .select_from(Log)
                .where(Log.timestamp < moment - timedelta(days=self.LOG_DAYS))
            ),
            "participants": await count(
                select(func.count())
                .select_from(EventParticipant)
                .where(EventParticipant.event_id.in_(old_events))
            ),
            "waitlist": await count(
                select(func.count())
                .select_from(EventWaitlist)
                .where(EventWaitlist.event_id.in_(old_events))
            ),
            "constraints": await count(
                select(func.count())
                .select_from(Constraint)
                .where(Constraint.event_id.in_(old_events))
            ),
            "enrichments": await count(
                select(func.count())
                .select_from(EventEnrichment)
                .where(EventEnrichment.event_id.in_(old_events))
            ),
            "attributed_transitions": await count(
                select(func.count())
                .select_from(EventStateTransition)
                .where(
                    EventStateTransition.event_id.in_(old_events),
                    or_(
                        EventStateTransition.actor_user_id.is_not(None),
                        EventStateTransition.reason.is_not(None),
                    ),
                )
            ),
            "detailed_events": await count(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.event_id.in_(old_events),
                    or_(
                        Event.description.is_not(None),
                        _has_items(Event.planning_prefs),
                        Event.organizer_user_id.is_not(None),
                        Event.emergency_admin_user_id.is_not(None),
                    ),
                )
            ),
            "detailed_memories": await count(
                select(func.count())
                .select_from(EventMemory)
                .where(
                    EventMemory.event_id.in_(old_events),
                    _has_items(EventMemory.fragments),
                )
            ),
            "memories": await count(
                select(func.count())
                .select_from(EventMemory)
                .where(EventMemory.event_id.in_(ancient_events))
            ),
            "idempotency_keys": await count(
                select(func.count())
                .select_from(IdempotencyKey)
                .where(IdempotencyKey.expires_at < moment)
            ),
            "anchor_bundles": await count(
                select(func.count())
                .select_from(AnchorOutbox)
                .where(self._anchor_bundle_expired(moment))
            ),
            "anchor_rows": await count(
                select(func.count())
                .select_from(AnchorOutbox)
                .where(self._anchor_row_expired(moment))
            ),
        }

    # -- right to erasure -----------------------------------------------------

    async def erase_user(self, user_id: int) -> ErasureResult | None:
        """Erase an account per policy. Returns None if it does not exist.

        * Identities, preferences, memberships, participation, waitlist
          entries, constraints and enrichments go with the user row
          (``ON DELETE CASCADE``).
        * Shared records stay but lose the attribution: events' organizer and
          admin, audit-trail actors, logs and constraints that *target* the
          user are set to NULL by the schema.
        * Memory fragments are pseudonymous, not linked by foreign key, so
          they are found by recomputing the contributor hash and removed.
        * Idempotency keys reference users without a cascade; they are retry
          bookkeeping only and are deleted first.
        """
        exists = await self.session.scalar(
            select(User.user_id).where(User.user_id == user_id)
        )
        if exists is None:
            return None

        identities = (
            await self.session.execute(
                select(UserIdentity.provider, UserIdentity.provider_user_id).where(
                    UserIdentity.user_id == user_id
                )
            )
        ).all()
        result = ErasureResult(
            user_id=user_id,
            identities=[(str(p), str(pid)) for p, pid in identities],
        )

        result.memory_fragments_removed = await self._remove_memory_fragments(user_id)
        await self.session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.user_id == user_id)
        )
        # A Core DELETE, not session.delete(): the ORM would first try to
        # NULL the children's user_id (NOT NULL columns) instead of letting
        # the schema's ON DELETE CASCADE / SET NULL apply the policy.
        await self.session.execute(delete(User).where(User.user_id == user_id))
        self.session.expire_all()
        # Cached reads must not outlive the account they mirror.
        from bot.common.user_preferences import LANGUAGE_CACHE
        from core.cache import get_cache

        await get_cache().invalidate_on_commit(self.session, LANGUAGE_CACHE, user_id)
        return result

    async def _remove_memory_fragments(self, user_id: int) -> int:
        """Drop the fragments this user contributed, wherever they are."""
        # Not limited to events the user still participates in: participation
        # rows decay at 180 days while fragments can live a little longer.
        memories = (
            (
                await self.session.execute(
                    select(EventMemory).where(_has_items(EventMemory.fragments))
                )
            )
            .scalars()
            .all()
        )
        removed = 0
        for memory in memories:
            fragments = list(memory.fragments or [])
            kept = [
                fragment
                for fragment in fragments
                if not _is_contribution(fragment, int(memory.event_id), user_id)
            ]
            if len(kept) != len(fragments):
                removed += len(fragments) - len(kept)
                memory.fragments = kept  # type: ignore[assignment]
                flag_modified(memory, "fragments")
        return removed


def text_not_null(column: Any) -> Any:
    """SQL: a JSON column is not JSON null."""
    return cast(column, Text) != "null"


def _has_items(column: Any) -> Any:
    """SQL: a JSON column holds a non-empty value (not NULL, null or [])."""
    text_value = cast(column, Text)
    return and_(column.is_not(None), text_value.not_in(["[]", "null", "{}"]))


def _is_contribution(fragment: Any, event_id: int, user_id: int) -> bool:
    if not isinstance(fragment, dict):
        return False
    stamp = fragment.get("contributor_hash")
    submitted = str(fragment.get("submitted_at") or "")
    if not stamp or len(submitted) < 10:
        return False
    return stamp == fragment_contributor_hash(event_id, user_id, submitted[:10])
