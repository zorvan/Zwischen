"""
EventMaterializationService — Layer 2: Event Materialization (v3.2).

Posts natural-language updates to the group chat at key state transitions,
transforming events from silent records to visible social objects.

v3 Design:
- Show reality, don't engineer response
- All announcements identical regardless of user history
- No dread framing around event instability
- No user amplification based on behavioral judgment
- Cancellations stay private to organizer

v3.2 Additions:
- Temporal gradient in announcements (light/warm/urgent/immediate)
- Memory hooks at threshold-reached and locked
- Cancellation DM with inline action buttons (extend deadline, view waitlist)
"""

from __future__ import annotations

import logging
import sqlalchemy
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from bot.common.i18n import t
from db.models import Event, EventParticipant, ParticipantStatus, User
from bot.common.materialization import get_time_framing_tier

logger = logging.getLogger("coord_bot.services.materialization")


class EventMaterializationService:
    """
    Posts materialization announcements to group chat.

    v3 principle: Show what is. The bot reports reality; it does not try to
    change behavior through framing.
    """

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def announce_first_join(
        self,
        event: Event,
        user: User,
        group_chat_id: int,
    ) -> None:
        """
        v3: State the fact. No fragility framing.

        "Name joined. 1 person in."
        """
        name = self._get_display_name(user)

        message = f"{name} joined the {event.event_type}. 1 person in."

        await self._send_to_group(group_chat_id, message)
        logger.info(
            "Announced first join",
            extra={"event_id": event.event_id, "user": user.user_id},
        )

    async def announce_join(
        self,
        event: Event,
        user: User,
        confirmed_count: int,
        group_chat_id: int,
    ) -> None:
        """
        v3: Same format for every join. Just the count.

        "Name joined. N people in."
        """
        name = self._get_display_name(user)

        message = f"{name} joined the {event.event_type}. {confirmed_count} people in."

        await self._send_to_group(group_chat_id, message)
        logger.info(
            "Announced join", extra={"event_id": event.event_id, "user": user.user_id}
        )

    async def announce_threshold_reached(
        self,
        event: Event,
        confirmed_count: int,
        group_chat_id: int,
        memory_hook: Optional[str] = None,
    ) -> None:
        """
        v3.2: State the threshold was met with temporal gradient and optional memory hook.

        Light (>72h): "[Event] is forming. N confirmed." + hook
        Warm (24-72h): "[Event] is happening. N in." + hook
        Urgent (<24h): "[Event] is happening. N confirmed."
        """
        tier = get_time_framing_tier(event)

        event_type = event.event_type
        if tier == "light":
            message = (
                f"The {event_type} is forming. {confirmed_count} people in so far."
            )
        elif tier == "warm":
            message = f"The {event_type} is happening. {confirmed_count} people in."
        else:  # urgent, immediate
            message = (
                f"The {event_type} is happening. {confirmed_count} people confirmed."
            )

        # v3.2: Append memory hook if available
        if memory_hook:
            message += f'\n\nThe last time your group did something like this, someone said: "{memory_hook}".'

        await self._send_to_group(group_chat_id, message)
        logger.info(
            "Announced threshold reached",
            extra={"event_id": event.event_id, "count": confirmed_count, "tier": tier},
        )

    async def announce_event_locked(
        self,
        event: Event,
        participants: List[EventParticipant],
        group_chat_id: int,
        memory_hook: Optional[str] = None,
    ) -> None:
        """
        Announce event is locked with participant list.
        v3.2: Added temporal gradient and optional memory hook.

        "[Event] is locked. Date/time. Who's in: names." + optional hook
        """
        time_str = self._format_event_time(event)
        tier = get_time_framing_tier(event)

        names = []
        for p in participants:
            if p.status in {ParticipantStatus.confirmed, ParticipantStatus.joined}:
                user_result = await self.session.execute(
                    sqlalchemy.select(User).where(
                        User.telegram_user_id == p.telegram_user_id
                    )
                )
                user = user_result.scalar_one_or_none()
                if user:
                    names.append(self._get_display_name(user))

        names_str = ", ".join(names) if names else "TBD"

        message = (
            f"{event.event_type} is locked.\n"
            f"{time_str}.\n\n"
            f"Who's in: {names_str}"
        )

        # v3.2: Append memory hook if available
        if memory_hook:
            message += f'\n\nThe last time your group did something like this, someone said: "{memory_hook}".'

        await self._send_to_group(group_chat_id, message)
        logger.info(
            "Announced event locked", extra={"event_id": event.event_id, "tier": tier}
        )

    async def announce_cancellation_private(
        self,
        event: Event,
        user: User,
        organizer_chat_id: int,
        remaining_count: int,
        waitlist_count: int = 0,
        min_needed: int = 0,
        time_context: Optional[str] = None,
        show_action_buttons: bool = True,
    ) -> None:
        """
        Private notice to organizer only. No public announcement.
        v3.2: Added state + inline action buttons (extend deadline, view waitlist).

        Includes:
        - Who cancelled
        - Confirmed count, minimum needed
        - Time context for the event
        - Waitlist count
        - Inline buttons: [Extend Deadline] [View Waitlist]
        """
        name = self._get_display_name(user)
        tier = get_time_framing_tier(event)

        message = f"{name} stepped back from the {event.event_type}.\n"
        message += f"{remaining_count} still in"
        if min_needed > 0:
            message += f", {min_needed} still needed"
        message += "."

        if time_context:
            message += f"\n{time_context}"

        if waitlist_count > 0:
            message += f"\n{waitlist_count} people on the waitlist."

        await self._send_dm(organizer_chat_id, message)
        logger.info(
            "Sent private cancellation notice",
            extra={
                "event_id": event.event_id,
                "cancelled_user": user.user_id,
                "tier": tier,
            },
        )

    async def announce_cancellation_with_actions(
        self,
        event: Event,
        cancelled_user_name: str,
        organizer_chat_id: int,
        confirmed_count: int,
        min_needed: int,
        waitlist_count: int,
        time_context: Optional[str] = None,
        lang: str = "en",
    ) -> None:
        """
        v3.2: Cancellation DM with inline action buttons for organizer.

        Buttons: [Extend Deadline] [View Waitlist]
        """
        message = f"{cancelled_user_name} stepped back from the {event.event_type}.\n"
        message += f"{confirmed_count} still in, {min_needed} still needed."

        if time_context:
            message += f"\n{time_context}"

        if waitlist_count > 0:
            message += f"\n{waitlist_count} people on the waitlist."
        else:
            message += "\nNo one on the waitlist."

        # Inline action buttons
        keyboard = [
            [
                InlineKeyboardButton(
                    t("waitlist_extend_deadline", lang=lang),
                    callback_data=f"extend_deadline_{event.event_id}",
                ),
            ],
        ]

        if waitlist_count > 0:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        t("waitlist_view_waitlist", lang=lang),
                        callback_data=f"view_waitlist_{event.event_id}",
                    ),
                ]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)

        await self._send_dm_with_markup(organizer_chat_id, message, reply_markup)
        logger.info(
            "Sent cancellation-with-action DM", extra={"event_id": event.event_id}
        )

    async def announce_event_completed(
        self,
        event: Event,
        participant_count: int,
        group_chat_id: int,
        lang: str = "en",
    ) -> None:
        """
        Announce event completion.
        """
        message = t(
            "materialization_event_complete",
            lang=lang,
            type=event.event_type,
            count=participant_count,
        )

        await self._send_to_group(group_chat_id, message)
        logger.info("Announced event completed", extra={"event_id": event.event_id})

    def _get_display_name(self, user: User) -> str:
        """Get user display name with fallbacks. Escaped for HTML parse mode."""
        import html

        if user.display_name:
            return html.escape(user.display_name)
        if user.username:
            return f"@{html.escape(user.username)}"
        return f"User #{user.telegram_user_id}"

    def _format_event_time(self, event: Event, lang: str = "en") -> str:
        """Format event scheduled time for display."""
        if not event.scheduled_time:
            return t("format_scheduled_time_tbd", lang=lang)

        time_str = event.scheduled_time.strftime("%a %d %b, %H:%M")
        return time_str

    async def _send_to_group(self, chat_id: int, message: str) -> None:
        """Send message to group chat."""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(
                "Failed to send materialization message to group %s: %s",
                chat_id,
                e,
            )

    async def _send_dm(self, chat_id: int, message: str) -> None:
        """Send DM to user."""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(
                "Failed to send materialization DM to %s: %s",
                chat_id,
                e,
            )

    async def _send_dm_with_markup(
        self,
        chat_id: int,
        message: str,
        reply_markup: InlineKeyboardMarkup,
    ) -> None:
        """Send DM to user with inline keyboard markup."""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(
                "Failed to send materialization DM with markup to %s: %s",
                chat_id,
                e,
            )
