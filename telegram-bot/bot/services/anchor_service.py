# mypy: disable-error-code="attr-defined,assignment,arg-type,operator"
"""Anchoring outbox: enqueue on lock, submit from a worker (T16).

See core/anchoring.py for the commitment construction and the rules, and
docs/ANCHORING_DECISION.md for why each rule exists.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.anchoring import (
    AnchorSink,
    AnchorUnavailable,
    ProofBundle,
    SealAlreadySpent,
    seal_id,
)
from db.models import AnchorOutbox, Event, EventParticipant, GroupSettings

logger = logging.getLogger("coord_bot.anchoring")

MAX_ATTEMPTS = 12
MAX_BACKOFF = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


class AnchorService:
    def __init__(self, session: AsyncSession, *, enabled: Optional[bool] = None):
        if enabled is None:
            from config.settings import settings

            enabled = settings.anchoring_enabled
        self.session = session
        self.enabled = enabled

    # -- enqueue (inside the lock's transaction) ---------------------------

    async def group_opted_in(self, group_id: Optional[int]) -> bool:
        if group_id is None:
            return False
        return bool(
            await self.session.scalar(
                select(GroupSettings.anchoring_enabled).where(
                    GroupSettings.group_id == group_id
                )
            )
        )

    async def enqueue_event_lock(self, event: Event) -> Optional[AnchorOutbox]:
        """Write the outbox row for a lock, in the caller's transaction.

        Returns None when anchoring does not apply. Never raises: a failure
        here rolls back only its own savepoint and the lock goes ahead
        unattested.
        """
        if not self.enabled:
            return None
        try:
            # Everything, reads included, runs in a savepoint: in PostgreSQL
            # any failed statement aborts the enclosing transaction, which
            # would take the lock down with it.
            async with self.session.begin_nested():
                if not await self.group_opted_in(event.group_id):
                    return None
                key = f"event_lock:{event.public_id}:{event.version}"
                existing = await self.session.scalar(
                    select(AnchorOutbox).where(AnchorOutbox.idempotency_key == key)
                )
                if existing is not None:
                    return existing
                confirmed = int(
                    await self.session.scalar(
                        select(func.count())
                        .select_from(EventParticipant)
                        .where(
                            EventParticipant.event_id == event.event_id,
                            EventParticipant.status == "confirmed",
                        )
                    )
                    or 0
                )
                bundle = ProofBundle.create(
                    {
                        "event": str(event.public_id),
                        "scheduled_time": _iso(event.scheduled_time),
                        "locked_at": _iso(event.locked_at),
                        "confirmed": confirmed,
                    }
                )
                row = AnchorOutbox(
                    event_id=event.event_id,
                    idempotency_key=key,
                    commitment=bundle.commitment,
                    bundle=bundle.as_json(),
                    status="pending",
                    attempts=0,
                    next_attempt_at=_now(),
                )
                self.session.add(row)
                await self.session.flush()
            logger.info("Anchor enqueued", extra={"event_id": event.event_id})
            return row
        except Exception:
            logger.warning(
                "Anchor enqueue failed; lock proceeds unattested",
                extra={"event_id": getattr(event, "event_id", None)},
                exc_info=True,
            )
            return None

    # -- worker -------------------------------------------------------------

    async def run_worker_once(
        self, sink: AnchorSink, *, now: Optional[datetime] = None, batch: int = 20
    ) -> dict[str, int]:
        """Submit due rows and check submitted ones. Safe to run on many
        instances at once: rows are claimed with SKIP LOCKED."""
        moment = now or _now()
        counts = {"submitted": 0, "confirmed": 0, "requeued": 0, "deferred": 0}

        # Check in-flight anchors first, so a reorg found here is
        # resubmitted in the same pass.
        submitted = (
            (
                await self.session.execute(
                    select(AnchorOutbox)
                    .where(AnchorOutbox.status == "submitted")
                    .order_by(AnchorOutbox.anchor_id)
                    .limit(batch)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in submitted:
            try:
                state = await sink.status(str(row.tx_ref))
            except AnchorUnavailable:
                continue
            if state == "confirmed":
                row.status = "confirmed"
                row.confirmed_at = moment
                counts["confirmed"] += 1
            elif state == "dropped":
                # Reorged out or expired: submit again with the same seal.
                row.status = "pending"
                row.tx_ref = None
                row.next_attempt_at = moment
                counts["requeued"] += 1
        due = (
            (
                await self.session.execute(
                    select(AnchorOutbox)
                    .where(
                        AnchorOutbox.status == "pending",
                        AnchorOutbox.next_attempt_at <= moment,
                    )
                    .order_by(AnchorOutbox.anchor_id)
                    .limit(batch)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in due:
            seal = seal_id(row.idempotency_key)
            try:
                row.tx_ref = await sink.submit(bytes.fromhex(row.commitment), seal)
            except SealAlreadySpent as spent:
                # An earlier attempt landed but its result was lost (crash
                # after submit). Adopt it rather than anchoring twice.
                row.tx_ref = spent.tx_ref
            except AnchorUnavailable as exc:
                self._defer(row, moment, str(exc))
                counts["deferred"] += 1
                continue
            except Exception as exc:  # any adapter bug: same treatment
                self._defer(row, moment, f"{type(exc).__name__}: {exc}")
                counts["deferred"] += 1
                continue
            row.status = "submitted"
            row.submitted_at = moment
            row.last_error = None
            counts["submitted"] += 1

        await self.session.flush()
        return counts

    @staticmethod
    def _defer(row: AnchorOutbox, moment: datetime, error: str) -> None:
        row.attempts = int(row.attempts or 0) + 1
        row.last_error = error[:500]
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            return
        backoff = min(timedelta(minutes=2 ** (row.attempts - 1)), MAX_BACKOFF)
        row.next_attempt_at = moment + backoff

    # -- client access -------------------------------------------------------

    async def bundle_for_event(self, event_id: int) -> Optional[dict[str, Any]]:
        """The newest proof bundle and anchor status for an event, while the
        server still holds it."""
        row = await self.session.scalar(
            select(AnchorOutbox)
            .where(AnchorOutbox.event_id == event_id)
            .order_by(AnchorOutbox.anchor_id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return {
            "status": row.status,
            "commitment": row.commitment,
            "tx_ref": row.tx_ref,
            "bundle": row.bundle,
        }
