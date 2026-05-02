"""
WaitlistService - Manages waitlist for oversubscribed events.
PRD v3.2: FIFO waitlist with time-scaled response windows.

Design principles:
- FIFO ordering based on added_at timestamp only (NOT position integer)
- Time-scaled response windows:
    >24h to event  -> 2 hours
    <24h to event  -> 30 minutes
    <2h to event   -> 15 minutes
- INVARIANT: No method takes user history as input. Position is added_at only.
- Full auto-fill flow: cancel -> offer -> accept/decline/expire -> next
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from bot.common.i18n import t
from bot.services.participant_service import ParticipantService
from db.models import Event, EventWaitlist, EventParticipant, User

logger = logging.getLogger("coord_bot.services.waitlist")


# ---------------------------------------------------------------------------
# Response-window helpers
# ---------------------------------------------------------------------------


def _compute_offer_duration(event_scheduled_time: Optional[datetime]) -> int:
    """Return the offer-validity duration in minutes based on proximity to the event.

    Time-scaled windows (PRD v3.2):
        >24h to event  -> 120 minutes (2 hours)
        <24h to event  -> 30 minutes
        <2h  to event  -> 15 minutes
    """
    if event_scheduled_time is None:
        return 120  # default 2 hours when no time set

    now = datetime.utcnow()
    delta = event_scheduled_time - now
    total_seconds = delta.total_seconds()

    if total_seconds < 2 * 3600:  # <2h
        return 15
    if total_seconds < 24 * 3600:  # <24h
        return 30
    return 120  # >24h


def _build_waitlist_offer_keyboard(
    event_id: int,
    *,
    accept: bool = True,
    decline: bool = True,
) -> InlineKeyboardMarkup:
    """Inline keyboard for a waitlist offer DM."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    if accept:
        row.append(
            InlineKeyboardButton(
                "Yes, I'm in",
                callback_data=f"waitlist_accept_{event_id}",
            )
        )
    if decline:
        row.append(
            InlineKeyboardButton(
                "No thanks",
                callback_data=f"waitlist_decline_{event_id}",
            )
        )
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WaitlistService:
    """Manages event waitlists with FIFO ordering and auto-fill flow.

    All ordering is by ``added_at`` ascending.  No position integer is used
    for determining who is next.
    """

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self.session = session
        self.bot = bot

    async def _compute_offer_duration(self, event_id: int) -> int:
        """Compatibility wrapper for tests and callers that have an event ID."""
        event_result = await self.session.execute(
            select(Event.scheduled_time).where(Event.event_id == event_id)
        )
        scheduled_time = event_result.scalar_one_or_none()
        if isinstance(scheduled_time, Event):
            scheduled_time = scheduled_time.scheduled_time
        return _compute_offer_duration(scheduled_time)

    # ------------------------------------------------------------------
    # Core waitlist operations
    # ------------------------------------------------------------------

    async def add_to_waitlist(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> int:
        """Add a user to the waitlist and return their FIFO position (1-based).

        Position is computed purely from ``added_at`` ordering.

        Raises:
            ValueError: If user is already a participant or already on the waitlist.
        """
        # Guard: already a participant
        participant = await self.session.execute(
            select(EventParticipant).where(
                EventParticipant.event_id == event_id,
                EventParticipant.telegram_user_id == telegram_user_id,
            )
        )
        if participant.scalar_one_or_none():
            raise ValueError("User is already a participant")

        # Guard: already on waitlist
        existing = await self.session.execute(
            select(EventWaitlist).where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.telegram_user_id == telegram_user_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("User is already on the waitlist")

        entry = EventWaitlist(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
            added_at=datetime.utcnow(),
            status="waiting",
        )
        self.session.add(entry)

        position = await self.get_waitlist_position(event_id, telegram_user_id)
        logger.info(
            "User %s joined waitlist for event %s (position %s)",
            telegram_user_id,
            event_id,
            position,
        )
        return position or 1

    async def leave_waitlist(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> bool:
        """Remove user from the waitlist.

        Returns True if the user was found and removed, False otherwise.
        """
        result = await self.session.execute(
            select(EventWaitlist).where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.telegram_user_id == telegram_user_id,
                EventWaitlist.status == "waiting",
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            return False

        await self.session.delete(entry)
        logger.info(
            "User %s left waitlist for event %s",
            telegram_user_id,
            event_id,
        )
        return True

    async def get_next_waitlisted(self, event_id: int) -> Optional[EventWaitlist]:
        """Return the next eligible waitlisted user (FIFO by added_at).

        Returns the first ``waiting`` entry ordered by ``added_at ASC``,
        or None if nobody is waiting.
        """
        result = await self.session.execute(
            select(EventWaitlist)
            .where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.status == "waiting",
            )
            .order_by(EventWaitlist.added_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Offer lifecycle
    # ------------------------------------------------------------------

    async def offer_spot(
        self,
        event_id: int,
        telegram_user_id: int,
        expires_in_minutes: Optional[int] = None,
    ) -> Optional[EventWaitlist]:
        """Mark a waitlist entry as ``offered`` and send a DM to the user.

        If *expires_in_minutes* is not provided it is derived from the
        event's ``scheduled_time`` via the time-scaled window rules.

        Returns the updated waitlist record, or None if no matching entry
        was found.
        """
        entry = await self._get_waiting(event_id, telegram_user_id)
        if entry is None:
            return None

        # Determine expiration
        if expires_in_minutes is not None:
            duration = expires_in_minutes
        else:
            event = await self.session.execute(
                select(Event.scheduled_time).where(Event.event_id == event_id)
            )
            scheduled_time = event.scalar_one_or_none()
            duration = _compute_offer_duration(scheduled_time)

        entry.status = "offered"
        entry.expires_at = datetime.utcnow() + timedelta(minutes=duration)

        await self._send_offer_dm(event_id, telegram_user_id, duration)

        logger.info(
            "Offered spot to user %s for event %s (expires in %s min)",
            telegram_user_id,
            event_id,
            duration,
        )
        return entry

    async def accept_offer(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> bool:
        """Confirm the user's acceptance of a waitlist offer.

        Flow:
        1. Validate the entry exists and is ``offered`` (not expired).
        2. Add the user as a confirmed participant.
        3. Remove the waitlist entry.
        4. Notify the organizer via DM.

        Returns True on success, False if the offer is invalid/expired.
        """
        entry = await self._get_offered(event_id, telegram_user_id)
        if entry is None:
            return False

        # Check expiration
        if entry.expires_at and datetime.utcnow() > entry.expires_at:
            await self.expire_offer(event_id, telegram_user_id)
            return False

        # Promote to participant
        participant_service = ParticipantService(self.session)
        await participant_service.join(event_id, telegram_user_id, source="waitlist")
        await participant_service.confirm(event_id, telegram_user_id, source="waitlist")

        # Remove from waitlist
        await self.session.delete(entry)

        # Notify organizer
        await self._notify_organizer_accepted(event_id, telegram_user_id)

        logger.info(
            "User %s accepted waitlist offer for event %s",
            telegram_user_id,
            event_id,
        )
        return True

    async def decline_offer(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> bool:
        """User declines the offer.  Mark as ``cancelled`` and offer to next.

        Returns True if an entry was found and declined, False otherwise.
        """
        entry = await self._get_offered(event_id, telegram_user_id)
        if entry is None:
            return False

        entry.status = "cancelled"
        logger.info(
            "User %s declined waitlist offer for event %s",
            telegram_user_id,
            event_id,
        )

        # Offer to next person in FIFO order
        await self._auto_fill_next(event_id)
        return True

    async def expire_offer(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> bool:
        """Mark an offer as expired and offer to the next person.

        Returns True if an entry was found and expired, False otherwise.
        """
        entry = await self._get_offered(event_id, telegram_user_id)
        if entry is None:
            return False

        entry.status = "expired"
        logger.info(
            "Waitlist offer expired for user %s on event %s",
            telegram_user_id,
            event_id,
        )

        # Offer to next person in FIFO order
        await self._auto_fill_next(event_id)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_waitlist_position(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> Optional[int]:
        """Return the user's 1-based FIFO position on the waitlist, or None."""
        entry = await self._get_waiting(event_id, telegram_user_id)
        if entry is None:
            return None

        # Count how many ``waiting`` entries have an earlier added_at
        count_result = await self.session.execute(
            select(func.count(EventWaitlist.waitlist_id)).where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.status == "waiting",
                EventWaitlist.added_at <= entry.added_at,
            )
        )
        return count_result.scalar_one()

    async def get_waitlist_count(self, event_id: int) -> int:
        """Return the number of users currently in ``waiting`` status."""
        result = await self.session.execute(
            select(func.count(EventWaitlist.waitlist_id)).where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.status == "waiting",
            )
        )
        return result.scalar_one() or 0

    async def get_waitlist(self, event_id: int) -> list[EventWaitlist]:
        """Return the current waitlist ordered by FIFO eligibility."""
        result = await self.session.execute(
            select(EventWaitlist)
            .where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.status.in_(["waiting", "offered"]),
            )
            .order_by(EventWaitlist.added_at.asc())
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Auto-fill orchestration
    # ------------------------------------------------------------------

    async def trigger_auto_fill(self, event_id: int) -> None:
        """Entry point called when a confirmed participant cancels.

        Finds the next waitlisted user (FIFO by added_at) and offers them
        the spot.
        """
        await self._auto_fill_next(event_id)

    async def _auto_fill_next(self, event_id: int) -> None:
        """Internal: offer the spot to the next waiting user, if any."""
        next_entry = await self.get_next_waitlisted(event_id)
        if next_entry is None:
            return

        event_result = await self.session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()
        if event is None:
            return

        duration = _compute_offer_duration(event.scheduled_time)
        await self.offer_spot(event_id, next_entry.telegram_user_id, duration)

    # ------------------------------------------------------------------
    # Expired-offer sweep (periodic job)
    # ------------------------------------------------------------------

    async def sweep_expired_offers(self, event_id: Optional[int] = None) -> int:
        """Mark all expired ``offered`` entries as ``expired`` and auto-fill.

        Returns the number of entries that were swept.
        """
        now = datetime.utcnow()
        query = select(EventWaitlist).where(
            EventWaitlist.status == "offered",
            EventWaitlist.expires_at.isnot(None),
            EventWaitlist.expires_at < now,
        )
        if event_id is not None:
            query = query.where(EventWaitlist.event_id == event_id)

        result = await self.session.execute(query)
        expired_entries = list(result.scalars().all())

        swept = 0
        event_ids_to_fill: set[int] = set()
        for entry in expired_entries:
            entry.status = "expired"
            event_ids_to_fill.add(entry.event_id)
            swept += 1
            logger.info(
                "Swept expired offer for user %s on event %s",
                entry.telegram_user_id,
                entry.event_id,
            )

        for eid in event_ids_to_fill:
            await self._auto_fill_next(eid)

        return swept

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_waiting(
        self, event_id: int, telegram_user_id: int
    ) -> Optional[EventWaitlist]:
        """Fetch a ``waiting`` entry for the given event+user."""
        result = await self.session.execute(
            select(EventWaitlist).where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.telegram_user_id == telegram_user_id,
                EventWaitlist.status == "waiting",
            )
        )
        return result.scalar_one_or_none()

    async def _get_offered(
        self, event_id: int, telegram_user_id: int
    ) -> Optional[EventWaitlist]:
        """Fetch an ``offered`` entry for the given event+user."""
        result = await self.session.execute(
            select(EventWaitlist).where(
                EventWaitlist.event_id == event_id,
                EventWaitlist.telegram_user_id == telegram_user_id,
                EventWaitlist.status == "offered",
            )
        )
        return result.scalar_one_or_none()

    async def _send_offer_dm(
        self,
        event_id: int,
        telegram_user_id: int,
        expires_in_minutes: int,
    ) -> None:
        """Send a DM to the waitlisted user with accept/decline buttons."""
        keyboard = _build_waitlist_offer_keyboard(event_id)

        expiry_text = self._format_expiry(expires_in_minutes)

        # Fetch event details for the message
        event_result = await self.session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()
        event_type = event.event_type if event else "event"

        try:
            await self.bot.send_message(
                chat_id=telegram_user_id,
                text=t(
                    "waitlist_offer_spot",
                    lang="en",
                    event_type=event_type,
                    event_id=event_id,
                    expiry=expiry_text,
                ),
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception(
                "Failed to send waitlist offer DM to user %s for event %s",
                telegram_user_id,
                event_id,
            )

    async def _notify_organizer_accepted(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> None:
        """Notify the event organizer that a waitlisted user accepted."""
        event_result = await self.session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()
        if event is None or event.organizer_telegram_user_id is None:
            return

        organizer_id = int(event.organizer_telegram_user_id)

        # Fetch user display info
        user_result = await self.session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        user = user_result.scalar_one_or_none()
        display_name = self._display_name(user, telegram_user_id)

        event_type = event.event_type

        try:
            await self.bot.send_message(
                chat_id=organizer_id,
                text=t(
                    "waitlist_organizer_notification",
                    lang="en",
                    display_name=display_name,
                    event_type=event_type,
                    event_id=event_id,
                ),
            )
        except Exception:
            logger.exception(
                "Failed to notify organizer %s about waitlist acceptance "
                "for event %s by user %s",
                organizer_id,
                event_id,
                telegram_user_id,
            )

    @staticmethod
    def _display_name(user: Optional[User], fallback_id: int) -> str:
        if user is None:
            return f"User #{fallback_id}"
        if user.display_name:
            return user.display_name
        if user.username:
            return f"@{user.username}"
        return f"User #{fallback_id}"

    @staticmethod
    def _format_expiry(minutes: int) -> str:
        if minutes < 60:
            return f"{minutes} minutes"
        hours = minutes // 60
        remaining = minutes % 60
        if remaining:
            return f"{hours}h {remaining}m"
        return f"{hours} hours"
