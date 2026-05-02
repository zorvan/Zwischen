"""
Organizer Rotation Service - Prevents coordination authority accumulation.
PRD v2 Section 2.2.5: Organizer as temporary role (TODO-011).

Design principles:
- Organizer = role for this event, not permanent identity
- System suggests rotation after consecutive events
- Never forces rotation - just surfaces opportunity
- Recognizes past organizers' contributions

Features:
- Track organizer history per event type
- Suggest rotation after N consecutive events
- Surface "Who wants to organize next?" prompt
- Log rotation for transparency
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from db.models import Event, User, EventParticipant, ParticipantStatus

logger = logging.getLogger("coord_bot.services.organizer_rotation")


class OrganizerRotationService:
    """
    Manages organizer role rotation.

    Handles:
    - Tracking organizer history
    - Rotation suggestions
    - Recognizing past organizers
    """

    # Suggest rotation after organizing 3 consecutive events of same type
    CONSECUTIVE_THRESHOLD = 3

    # Look back 6 months for history
    HISTORY_WINDOW_MONTHS = 6

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_organizer_history(
        self,
        telegram_user_id: int,
        group_id: Optional[int] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get user's organizer history.

        Args:
            telegram_user_id: User's Telegram ID
            group_id: Optional group filter
            event_type: Optional event type filter

        Returns:
            List of organized events with details
        """
        cutoff = datetime.utcnow() - timedelta(days=self.HISTORY_WINDOW_MONTHS * 30)

        query = (
            select(Event)
            .where(
                Event.organizer_telegram_user_id == telegram_user_id,
                Event.created_at >= cutoff,
            )
            .order_by(desc(Event.created_at))
            .limit(limit)
        )

        if group_id:
            query = query.where(Event.group_id == group_id)

        if event_type:
            query = query.where(Event.event_type == event_type)

        result = await self.session.execute(query)
        events = result.scalars().all()

        return [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "created_at": e.created_at,
                "state": e.state,
            }
            for e in events
        ]

    async def count_consecutive_organized(
        self,
        telegram_user_id: int,
        event_type: str,
        group_id: Optional[int] = None,
    ) -> int:
        """
        Count consecutive events organized by user (same type).

        Returns:
            Count of consecutive events
        """
        # Get all events of this type organized by user
        query = (
            select(Event)
            .where(
                Event.organizer_telegram_user_id == telegram_user_id,
                Event.event_type == event_type,
            )
            .order_by(desc(Event.created_at))
        )

        if group_id:
            query = query.where(Event.group_id == group_id)

        result = await self.session.execute(query)
        events = result.scalars().all()

        if not events:
            return 0

        # Count consecutive (no gaps > 30 days)
        consecutive = 1
        for i in range(1, len(events)):
            gap = events[i - 1].created_at - events[i].created_at
            if gap.days <= 30:
                consecutive += 1
            else:
                break

        return consecutive

    async def should_suggest_rotation(
        self,
        telegram_user_id: int,
        event_type: str,
        group_id: Optional[int] = None,
    ) -> Tuple[bool, int]:
        """
        Check if rotation should be suggested.

        Returns:
            (should_suggest, consecutive_count)
        """
        consecutive = await self.count_consecutive_organized(
            telegram_user_id, event_type, group_id
        )

        should_suggest = consecutive >= self.CONSECUTIVE_THRESHOLD

        if should_suggest:
            logger.info(
                "Rotation suggested for user %s (%d consecutive %s events)",
                telegram_user_id,
                consecutive,
                event_type,
            )

        return should_suggest, consecutive

    async def suggest_next_organizer(
        self,
        event_id: int,
        exclude_user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Suggest next potential organizer from participants.

        Prioritizes:
        1. Participants who haven't organized recently
        2. High-reliability participants
        3. Random selection from eligible

        Args:
            event_id: Current event ID
            exclude_user_id: User to exclude (current organizer)

        Returns:
            Suggested user info or None
        """
        # Get confirmed participants
        result = await self.session.execute(
            select(EventParticipant, User)
            .join(User, EventParticipant.telegram_user_id == User.telegram_user_id)
            .where(
                EventParticipant.event_id == event_id,
                EventParticipant.status.in_(
                    [
                        ParticipantStatus.confirmed,
                        ParticipantStatus.joined,
                    ]
                ),
            )
        )
        participants = result.all()

        if not participants:
            return None

        # Filter out current organizer
        eligible = []
        for participant, user in participants:
            if exclude_user_id and participant.telegram_user_id == exclude_user_id:
                continue
            eligible.append((participant, user))

        if not eligible:
            return None

        # Get organizer history for each eligible participant
        candidates = []
        for participant, user in eligible:
            # Count recent organizing activity
            history = await self.get_organizer_history(
                user.telegram_user_id, limit=10
            )  # Last 10 events
            organized_count = len(history)

            candidates.append(
                {
                    "user_id": user.user_id,
                    "telegram_user_id": user.telegram_user_id,
                    "display_name": user.display_name or user.username,
                    "organized_count": organized_count,
                }
            )

        # Sort by organized_count (ascending - prefer those who organized less)
        candidates.sort(key=lambda c: c["organized_count"])

        # Return top candidate
        return candidates[0] if candidates else None

    async def get_rotation_prompt(
        self,
        event_type: str,
        consecutive_count: int,
        current_organizer_name: str,
        suggested_organizer: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate rotation suggestion prompt.

        Framing: Opportunity, not obligation. Recognition of past contributions.
        """
        base_prompts = [
            f"🎯 {current_organizer_name} has organized {consecutive_count} {event_type} events in a row!\n\n"
            f"Would someone else like to organize the next one? "
            f"Fresh perspectives make events more interesting!",
            f"✨ Shoutout to {current_organizer_name} for organizing "
            f"{consecutive_count} consecutive {event_type} events!\n\n"
            f"Who wants to take a turn organizing next? "
            f"It's a great way to shape the group's experience!",
            f"🙏 {current_organizer_name} has been awesome at organizing {event_type} events!\n\n"
            f"To spread the coordination love, would someone else like to organize next time? "
            f"The bot can help with all the logistics!",
        ]

        prompt = base_prompts[
            min(consecutive_count - self.CONSECUTIVE_THRESHOLD, len(base_prompts) - 1)
        ]

        # Add suggested organizer if available
        if suggested_organizer:
            prompt += (
                f"\n\n💡 {suggested_organizer['display_name']} hasn't organized recently "
                f"and might be interested!"
            )

        return prompt

    async def log_rotation(
        self,
        old_organizer_id: int,
        new_organizer_id: int,
        event_type: str,
        group_id: int,
        reason: str = "voluntary",
    ) -> None:
        """
        Log organizer rotation for transparency.

        Reasons:
        - voluntary: New organizer volunteered
        - suggested: System suggestion accepted
        - rotation: Automatic rotation policy
        """
        from db.models import Log

        log = Log(
            event_id=None,  # Not event-specific
            user_id=old_organizer_id,
            action="organizer_rotation",
            metadata_dict={
                "old_organizer": old_organizer_id,
                "new_organizer": new_organizer_id,
                "event_type": event_type,
                "group_id": group_id,
                "reason": reason,
            },
        )
        self.session.add(log)

        logger.info(
            "Organizer rotation: %s -> %s (%s)",
            old_organizer_id,
            new_organizer_id,
            reason,
        )


async def check_and_suggest_rotation(
    session: AsyncSession,
    organizer_telegram_user_id: int,
    event_type: str,
    group_id: Optional[int] = None,
) -> Optional[str]:
    """
    Convenience function to check and generate rotation prompt.

    Returns:
        Prompt string if rotation suggested, None otherwise
    """
    service = OrganizerRotationService(session)

    should_suggest, count = await service.should_suggest_rotation(
        organizer_telegram_user_id, event_type, group_id
    )

    if not should_suggest:
        return None

    # Get organizer name
    user_result = await session.execute(
        select(User).where(User.telegram_user_id == organizer_telegram_user_id)
    )
    organizer = user_result.scalar_one_or_none()
    organizer_name = organizer.display_name or organizer.username or "Organizer"

    return await service.get_rotation_prompt(
        event_type=event_type,
        consecutive_count=count,
        current_organizer_name=organizer_name,
    )
