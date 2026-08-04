"""
Scheduler - Periodic background tasks.
PRD v2 Priority 4: Production Hardening.

Handles:
- Automatic memory collection DM (TODO-029)
- Log pruning (90-day GDPR compliance) (TODO-015)
- collapse_at auto-cancel (TODO-021)
- 24h before event reminder (TODO-027)
- Weekly digest auto-send
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from telegram import Bot
from sqlalchemy import select, func, delete, text

from db.models import (
    Event,
    IdempotencyKey,
    Log,
    EventParticipant,
    ParticipantStatus,
    Group,
    User,
)
from sqlalchemy.exc import IntegrityError

from bot.common.i18n import t
from db.connection import get_session

logger = logging.getLogger("coord_bot.scheduler")


async def claim_scheduled_delivery(
    db_url: str,
    key: str,
    command_type: str,
    *,
    event_id: int | None = None,
    expires_in_days: int = 35,
) -> bool:
    """Atomically claim a notification before sending it.

    Claims are committed in their own transaction. If a process dies after
    Telegram accepts the send, a retry sees the existing primary key and does
    not send it again. This intentionally chooses at-most-once delivery over
    duplicate user-visible notifications.
    """
    async with get_session(db_url) as session:
        session.add(
            IdempotencyKey(
                idempotency_key=key,
                command_type=command_type,
                event_id=event_id,
                status="pending",
                expires_at=datetime.utcnow() + timedelta(days=expires_in_days),
            )
        )
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


class SchedulerService:
    """
    Manages scheduled background tasks.

    Tasks:
    - Memory collection: 2 hours after event completion
    - Log pruning: Delete logs older than 90 days (weekly)
    - Collapse check: Check underthreshold events every hour
    - 24h reminder: Remind groups of upcoming events daily
    - Weekly digest: Send to active groups weekly
    """

    def __init__(self, bot: Bot, db_url: str):
        self.bot = bot
        self.db_url = db_url

    async def check_and_start_memory_collection(self) -> int:
        """
        Check for completed events that need memory collection.

        Triggered: Every 30 minutes
        Collection starts: 2 hours after event completion
        """
        async with get_session(self.db_url) as session:
            # Find events completed 2+ hours ago without memory collection
            two_hours_ago = datetime.utcnow() - timedelta(hours=2)

            result = await session.execute(
                select(Event)
                .where(
                    Event.state == "completed",
                    Event.completed_at <= two_hours_ago,
                )
                .outerjoin(
                    EventParticipant, Event.event_id == EventParticipant.event_id
                )
                .group_by(Event.event_id)
                .having(func.count(EventParticipant.user_id) > 0)
            )
            events = result.scalars().all()

            started_count = 0
            for event in events:
                # Check if memory collection already started
                from db.models import EventMemory

                memory_result = await session.execute(
                    select(EventMemory).where(EventMemory.event_id == event.event_id)
                )
                if memory_result.scalar_one_or_none():
                    # Already collected
                    continue

                if not await claim_scheduled_delivery(
                    self.db_url,
                    f"scheduler:memory:{event.event_id}",
                    "scheduler_memory_collection",
                    event_id=event.event_id,
                ):
                    continue

                # Start collection
                from bot.services.event_memory_service import EventMemoryService

                memory_service = EventMemoryService(self.bot, session)
                await memory_service.start_memory_collection(event)
                started_count += 1

                logger.info(
                    "Started memory collection for event %s",
                    event.event_id,
                    extra={"event_id": event.event_id},
                )

            return started_count

    async def prune_old_logs(self) -> int:
        """
        Delete logs older than 90 days (GDPR compliance).

        PRD v2 Section 5.1: Data minimization policy
        - Action-level logs: 90 days retention
        - Event memories: retained long-term

        Triggered: Weekly
        """
        async with get_session(self.db_url) as session:
            ninety_days_ago = datetime.utcnow() - timedelta(days=90)

            # Delete old logs (not state transitions - those are audit trail)
            result = await session.execute(
                delete(Log).where(Log.timestamp < ninety_days_ago)
            )
            deleted_count = result.rowcount

            await session.commit()

            logger.info(
                "Pruned %d logs older than 90 days",
                deleted_count,
            )

            return deleted_count

    async def decay_retained_data(self) -> dict[str, int]:
        """Run the retention policy once cluster-wide under an advisory lock."""
        async with get_session(self.db_url) as session:
            # Transaction-scoped lock: another scheduler instance simply skips.
            acquired = await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(9472361)")
            )
            if not acquired:
                return {}
            from bot.services.retention_service import RetentionService

            counts = await RetentionService(session).decay()
            await session.commit()
            logger.info("Applied retention policy", extra={"retention": counts})
            return counts

    async def check_collapse_deadlines(self) -> int:
        """
        Auto-cancel events that passed collapse_at without meeting threshold.

        PRD v2 Section 2.1: Threshold-Based Fragility
        - collapse_at: Auto-cancel deadline for underthreshold events

        Triggered: Every hour
        """
        async with get_session(self.db_url) as session:
            now = datetime.utcnow()

            # Find events past collapse deadline
            result = await session.execute(
                select(Event).where(
                    Event.state.in_(["proposed", "interested", "confirmed"]),
                    Event.collapse_at.is_not(None),
                    Event.collapse_at <= now,
                )
            )
            events = result.scalars().all()

            cancelled_count = 0
            for event in events:
                # Check if threshold is met
                participant_result = await session.execute(
                    select(func.count(EventParticipant.user_id)).where(
                        EventParticipant.event_id == event.event_id,
                        EventParticipant.status.in_(
                            [
                                ParticipantStatus.confirmed,
                                ParticipantStatus.joined,
                            ]
                        ),
                    )
                )
                confirmed_count = participant_result.scalar() or 0

                min_required = event.min_participants or 2
                if confirmed_count < min_required:
                    # Auto-cancel
                    from bot.services.event_lifecycle_service import (
                        EventLifecycleService,
                    )

                    lifecycle = EventLifecycleService(self.bot, session)

                    try:
                        await lifecycle.transition_with_lifecycle(
                            event_id=event.event_id,
                            target_state="cancelled",
                            actor_user_id=None,  # System action
                            source="system",
                            reason=f"Auto-cancel: threshold not met by collapse_at deadline ({event.collapse_at})",
                            expected_version=event.version,
                        )
                        cancelled_count += 1

                        logger.info(
                            "Auto-cancelled event %s (threshold not met)",
                            event.event_id,
                            extra={"event_id": event.event_id},
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to auto-cancel event %s: %s",
                            event.event_id,
                            e,
                        )

            return cancelled_count

    async def send_24h_reminders(self) -> int:
        """
        Send 24h before event reminder to group chat.

        PRD v2 Section 2.2.4: Materialization announcements
        Trigger: 24h before scheduled time

        Message: "[Event] is tomorrow. [N] confirmed. [Name list]."
        """
        async with get_session(self.db_url) as session:
            now = datetime.utcnow()
            tomorrow_start = now + timedelta(hours=23)
            tomorrow_end = now + timedelta(hours=25)

            # Find events scheduled for tomorrow
            result = await session.execute(
                select(Event).where(
                    Event.state.in_(["locked", "confirmed"]),
                    Event.scheduled_time >= tomorrow_start,
                    Event.scheduled_time <= tomorrow_end,
                )
            )
            events = result.scalars().all()

            sent_count = 0
            for event in events:
                # Get group chat ID
                group_result = await session.execute(
                    select(Group).where(Group.group_id == event.group_id)
                )
                group = group_result.scalar_one_or_none()

                if not group or not group.telegram_group_id:
                    continue

                # Get confirmed participants
                participant_result = await session.execute(
                    select(EventParticipant, User)
                    .join(User, EventParticipant.user_id == User.user_id)
                    .where(
                        EventParticipant.event_id == event.event_id,
                        EventParticipant.status.in_(
                            [
                                ParticipantStatus.confirmed,
                                ParticipantStatus.joined,
                            ]
                        ),
                    )
                )
                participants = participant_result.all()
                confirmed_count = len(participants)

                # Build participant name list
                names = []
                for participant, user in participants:
                    if user:
                        name = user.display_name or (
                            f"@{user.username}"
                            if user.username
                            else f"User #{user.user_id}"
                        )
                        names.append(name)

                names_str = ", ".join(names) if names else "TBD"
                time_str = (
                    event.scheduled_time.strftime("%a %d %b, %H:%M")
                    if event.scheduled_time
                    else "TBD"
                )

                message = t(
                    "scheduler_24h_reminder",
                    lang="en",
                    type=event.event_type,
                    time=time_str,
                    count=confirmed_count,
                    names=names_str,
                )

                try:
                    reminder_date = event.scheduled_time.date().isoformat()
                    if not await claim_scheduled_delivery(
                        self.db_url,
                        f"scheduler:reminder24h:{event.event_id}:{reminder_date}",
                        "scheduler_24h_reminder",
                        event_id=event.event_id,
                    ):
                        continue
                    await self.bot.send_message(
                        chat_id=group.telegram_group_id,
                        text=message,
                        parse_mode="HTML",
                    )
                    sent_count += 1

                    logger.info(
                        "Sent 24h reminder for event %s",
                        event.event_id,
                        extra={"event_id": event.event_id},
                    )
                except Exception as e:
                    logger.error(
                        "Failed to send 24h reminder for event %s: %s",
                        event.event_id,
                        e,
                    )

            return sent_count

    async def send_weekly_digests(self) -> int:
        """
        Send weekly digest to all active groups.

        Triggered: Weekly (e.g., Sunday evening)
        """
        from bot.common.weekly_digest import send_digest_to_all_groups

        try:

            async def claim_group(group_id: int) -> bool:
                year, week, _ = datetime.utcnow().isocalendar()
                return await claim_scheduled_delivery(
                    self.db_url,
                    f"scheduler:weekly_digest:{group_id}:{year}-W{week:02d}",
                    "scheduler_weekly_digest",
                )

            async with get_session(self.db_url) as session:
                stats = await send_digest_to_all_groups(
                    self.bot, session, claim=claim_group
                )
            logger.info(
                "Weekly digest sent: %d sent, %d failed, %d skipped",
                stats.get("sent", 0),
                stats.get("failed", 0),
                stats.get("skipped", 0),
            )
            return stats.get("sent", 0)
        except Exception as e:
            logger.error("Failed to send weekly digests: %s", e)
            return 0


SCHEDULER_LOCK_NAMESPACE = 0x5A574953  # stable signed-int-safe "ZWIS"
SCHEDULER_JOB_ID = 1


async def _run_scheduled_tasks_unlocked(bot: Bot, db_url: str) -> None:
    """
    Run all scheduled tasks.

    This is called periodically by the job queue.
    """
    scheduler = SchedulerService(bot, db_url)

    try:
        # Memory collection (every 30 min)
        memory_count = await scheduler.check_and_start_memory_collection()
        if memory_count > 0:
            logger.info("Started %d memory collections", memory_count)

        # Log pruning (weekly - check if Sunday)
        if datetime.utcnow().weekday() == 6:  # Sunday
            pruned = await scheduler.prune_old_logs()
            if pruned > 0:
                logger.info("Pruned %d old logs", pruned)
            await scheduler.decay_retained_data()
            digests = await scheduler.send_weekly_digests()
            if digests > 0:
                logger.info("Sent %d weekly digests", digests)

        # Collapse check (hourly)
        collapsed = await scheduler.check_collapse_deadlines()
        if collapsed > 0:
            logger.info("Auto-cancelled %d underthreshold events", collapsed)

        # 24h reminders (daily at 9 AM)
        now = datetime.utcnow()
        if now.hour == 9:  # 9 AM UTC
            reminders = await scheduler.send_24h_reminders()
            if reminders > 0:
                logger.info("Sent %d event reminders", reminders)

        # Idempotency key cleanup (daily)
        cleaned = await cleanup_expired_idempotency_keys(db_url)
        if cleaned > 0:
            logger.info("Cleaned up %d expired idempotency keys", cleaned)

    except Exception as e:
        logger.exception("Scheduled task execution failed: %s", e)


async def run_scheduled_tasks(bot: Bot, db_url: str) -> bool:
    """Elect one replica for this tick using a session advisory lock."""
    from db.connection import create_engine

    engine = create_engine(db_url)
    async with engine.connect() as connection:
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:namespace, :job_id)"),
                {"namespace": SCHEDULER_LOCK_NAMESPACE, "job_id": SCHEDULER_JOB_ID},
            )
        )
        if not acquired:
            logger.info("Skipping scheduler tick; another instance is leader")
            return False
        try:
            await _run_scheduled_tasks_unlocked(bot, db_url)
            return True
        finally:
            try:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :job_id)"),
                    {"namespace": SCHEDULER_LOCK_NAMESPACE, "job_id": SCHEDULER_JOB_ID},
                )
            except Exception:
                # Connection close also releases session locks. If the
                # connection died, PostgreSQL has already released it.
                logger.warning(
                    "Could not explicitly release scheduler lock", exc_info=True
                )


async def cleanup_expired_idempotency_keys(db_url: str) -> int:
    """
    v3.5: Clean up expired idempotency keys.

    Deletes idempotency_keys where expires_at < NOW() - 7 days.
    Prevents unbounded table growth.
    """
    from db.models import IdempotencyKey
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=7)
    deleted = 0

    async with get_session(db_url) as session:
        result = await session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expires_at < cutoff)
        )
        deleted = result.rowcount
        await session.commit()

    if deleted > 0:
        logger.info("Cleaned up %d expired idempotency keys", deleted)

    return deleted
