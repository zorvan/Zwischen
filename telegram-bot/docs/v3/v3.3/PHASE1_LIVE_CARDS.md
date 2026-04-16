# Phase 1: Live Event Cards

## Overview

Make forming events socially visible in group chat with live status cards.

## Task 1: Database Schema

### File: `db/models.py`

Add new SQLAlchemy models at the end of the file:

```python
class EventLiveCard(Base):
    __tablename__ = "event_live_cards"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.event_id"), nullable=False, unique=True)
    message_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    participant_count = Column(Integer, default=0)
    confirmed_count = Column(Integer, default=0)
    reaction_counts = Column(JSONB, default=lambda: {})
    hashtags = Column(ARRAY(Text), default=lambda: [])
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    updated_at = Column(TIMESTAMPTZ, default=datetime.utcnow)

    event = relationship("Event", back_populates="live_card")


class GroupSettings(Base):
    __tablename__ = "group_settings"

    group_id = Column(Integer, ForeignKey("groups.group_id"), primary_key=True)
    enable_live_cards = Column(Boolean, default=True)
    memory_first_skip_enabled = Column(Boolean, default=True)
    lineage_selection_method = Column(String, default="llm", 
                                       check=In(["fixed", "llm"]))
    max_hashtags = Column(Integer, default=5)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    updated_at = Column(TIMESTAMPTZ, default=datetime.utcnow)

    group = relationship("Group", back_populates="settings")
```

Also add relationships to existing models:

```python
# In Event class:
live_card = relationship("EventLiveCard", uselist=False, back_populates="event")

# In Group class:
settings = relationship("GroupSettings", uselist=False, back_populates="group")
```

---

## Task 2: EventLiveCardService

### File: `bot/services/event_live_card_service.py` (NEW)

```python
"""
EventLiveCardService - Phase 1: Live event cards in group chat.

Manages:
- Creating live status cards when events are proposed
- Updating cards as participants join/confirm/cancel
- Deleting cards when events lock/completed/cancel
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from telegram import Bot, Message
from telegram.ext import ContextTypes

from db.models import Event, EventLiveCard, EventParticipant, ParticipantStatus, GroupSettings

logger = logging.getLogger("coord_bot.services.live_card")


class EventLiveCardService:
    """
    Manages live event status cards in group chat.
    
    v3.3 Design:
    - Cards appear when event is proposed
    - Auto-update on participant changes
    - Show participant count, hashtags, reactions
    - Deleted when event locks/completes/cancels
    """

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def create_live_card(self, event: Event, hashtags: Optional[list[str]] = None) -> EventLiveCard:
        """
        Create live status card for a new event.
        
        Posts initial card to group chat, stores reference.
        """
        # Get group settings
        group_id = event.group_id
        if not group_id:
            logger.warning("Event has no group_id, cannot create live card")
            return None

        settings = await self._get_group_settings(group_id)
        if not settings.enable_live_cards:
            logger.info(f"Live cards disabled for group {group_id}")
            return None

        # Build card content
        card_text = self._build_live_card_text(event, hashtags=hashtags or [])

        # Post to group
        message = await self.bot.send_message(
            chat_id=event.group_id,
            text=card_text,
            parse_mode="Markdown"
        )

        # Store card
        card = EventLiveCard(
            event_id=event.event_id,
            message_id=message.message_id,
            chat_id=event.group_id,
            participant_count=0,
            confirmed_count=0,
            hashtags=hashtags or []
        )
        self.session.add(card)
        await self.session.commit()
        await self.session.refresh(card)

        logger.info(f"Created live card for event {event.event_id}")
        return card

    async def update_live_card(self, event: Event) -> Optional[EventLiveCard]:
        """
        Update live card after participant changes.
        
        Updates: participant count, confirmed count, hashtags
        """
        card = await self._get_live_card(event.event_id)
        if not card:
            logger.warning(f"No live card for event {event.event_id}")
            return None

        # Count participants
        result = await self.session.execute(
            select(EventParticipant)
            .where(EventParticipant.event_id == event.event_id)
        )
        participants = result.scalars().all()

        participant_count = sum(1 for p in participants if p.status == ParticipantStatus.joined)
        confirmed_count = sum(1 for p in participants if p.status == ParticipantStatus.confirmed)

        # Get hashtags
        hashtags = event.formation_hashtag or []

        # Update card text
        card_text = self._build_live_card_text(event, participant_count, confirmed_count, hashtags)

        try:
            await self.bot.edit_message_text(
                chat_id=card.chat_id,
                message_id=card.message_id,
                text=card_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to edit live card: {e}")
            return None

        # Update DB
        card.participant_count = participant_count
        card.confirmed_count = confirmed_count
        card.hashtags = hashtags
        card.updated_at = datetime.utcnow()
        await self.session.commit()

        logger.info(f"Updated live card for event {event.event_id}")
        return card

    async def delete_live_card(self, event_id: int) -> bool:
        """
        Delete live card when event locks/completes/cancels.
        
        Also deletes from DB.
        """
        card = await self._get_live_card(event_id)
        if not card:
            return False

        try:
            await self.bot.delete_message(
                chat_id=card.chat_id,
                message_id=card.message_id
            )
        except Exception as e:
            logger.error(f"Failed to delete live card message: {e}")

        await self.session.delete(card)
        await self.session.commit()

        logger.info(f"Deleted live card for event {event_id}")
        return True

    async def add_reaction(self, event_id: int, emoji: str) -> dict:
        """
        Add bot reaction to live card.
        
        Returns updated reaction counts.
        """
        card = await self._get_live_card(event_id)
        if not card:
            return {}

        # Categorize sentiment
        sentiment = self._categorize_sentiment(emoji)
        
        # Update reaction counts
        counts = card.reaction_counts or {}
        current = counts.get(sentiment, 0)
        counts[sentiment] = current + 1
        card.reaction_counts = counts
        await self.session.commit()

        logger.info(f"Added reaction {emoji} ({sentiment}) to event {event_id}")
        return counts

    def _build_live_card_text(
        self,
        event: Event,
        participant_count: Optional[int] = None,
        confirmed_count: Optional[int] = None,
        hashtags: Optional[list[str]] = None
    ) -> str:
        """Build the live card text."""
        if participant_count is None or confirmed_count is None:
            # Recount if not provided
            # (implementation simplified - in reality would use cached counts)
            pass

        # Calculate time remaining
        deadline = event.collapse_at or event.lock_deadline
        if deadline:
            remaining = deadline - datetime.utcnow()
            if remaining.total_seconds() > 0:
                hours = int(remaining.total_seconds() / 3600)
                time_str = f"{hours}h until deadline"
            else:
                time_str = "Deadline passed"
        else:
            time_str = "No deadline"

        # Format hashtags
        hashtag_str = ""
        if hashtags:
            hashtag_str = "\n" + " ".join(hashtags)

        # Build card
        text = (
            f"🚀 {event.event_type}: {event.description[:50]}\n"
            f"{hashtag_str}\n\n"
            f"📅 {event.scheduled_time.strftime('%d %b, %H:%M') if event.scheduled_time else 'TBD'}\n"
            f"⏳ {time_str}\n\n"
            f"👥 {participant_count or 0}/{event.min_participants} joined\n"
            f"✅ {confirmed_count or 0} confirmed"
        )
        
        return text

    def _categorize_sentiment(self, emoji: str) -> str:
        """Categorize emoji into sentiment type."""
        enthusiasm = {"🎉", "✨", "❤️", "😍", "🥰"}
        interest = {"🔥", "👀", "🤩", "😮"}
        acknowledgment = {"👍", "👋", "👋"}
        timing = {"⏳", "⏰", "-clock", "🕒"}

        if emoji in enthusiasm:
            return "enthusiasm"
        elif emoji in interest:
            return "interest"
        elif emoji in acknowledgment:
            return "acknowledgment"
        elif emoji in timing:
            return "timing_concern"
        else:
            return "other"

    async def _get_live_card(self, event_id: int) -> Optional[EventLiveCard]:
        """Get live card for event."""
        result = await self.session.execute(
            select(EventLiveCard).where(EventLiveCard.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def _get_group_settings(self, group_id: int) -> GroupSettings:
        """Get group settings, create defaults if not exist."""
        result = await self.session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group_id)
        )
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = GroupSettings(group_id=group_id)
            self.session.add(settings)
            await self.session.commit()
        
        return settings
```

---

## Task 3: EventHashtagService

### File: `bot/services/event_hashtag_service.py` (NEW)

```python
"""
EventHashtagService - Phase 1: Hashtag management.

Manages:
- Validating hashtags (format, count)
- Assigning hashtags to events
- Freezing hashtags after lock
- Querying by hashtag
"""

from __future__ import annotations

import logging
import re
from typing import Optional, list
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Event, EventLiveCard, EventParticipant

logger = logging.getLogger("coord_bot.services.hashtags")


class EventHashtagService:
    """
    Manages event hashtags.
    
    v3.3 Design:
    - Hashtags = event identity (permanent)
    - Format: #[a-z0-9_]+
    - Max configurable per group (default: 5)
    - Frozen on event lock
    """

    HASH_PATTERN = re.compile(r"^#[a-z0-9_]+$")
    MAX_HASHTAGS_DEFAULT = 5

    def __init__(self, session: AsyncSession):
        self.session = session

    async def validate_hashtags(
        self,
        hashtags: list[str],
        group_id: Optional[int] = None
    ) -> tuple[bool, list[str]]:
        """
        Validate hashtags format and count.
        
        Returns: (is_valid, list_of_errors)
        """
        errors = []

        if not hashtags:
            return True, errors

        if len(hashtags) > self.MAX_HASHTAGS_DEFAULT:
            errors.append(f"Maximum {self.MAX_HASHTAGS_DEFAULT} hashtags allowed")

        for tag in hashtags:
            tag_lower = tag.lower()
            if not self.HASH_PATTERN.match(tag_lower):
                errors.append(f"Invalid format: {tag}. Must be #{a-z0-9_}+")
            
            if len(tag) > 30:
                errors.append(f"Too long: {tag}. Max 30 characters")

        return len(errors) == 0, errors

    async def assign_hashtags(
        self,
        event: Event,
        hashtags: list[str]
    ) -> Event:
        """
        Assign hashtags to event (during formation).
        
        Hashtags are stored in `formation_hashtag` column.
        """
        # Validate
        valid, errors = await self.validate_hashtags(hashtags)
        if not valid:
            raise ValueError(f"Invalid hashtags: {'; '.join(errors)}")

        # Normalize
        normalized = [tag.lower() for tag in hashtags]

        # Store
        event.formation_hashtag = normalized
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)

        logger.info(f"Assigned {normalized} to event {event.event_id}")
        return event

    async def freeze_hashtags(self, event: Event) -> Event:
        """
        Freeze hashtags when event locks.
        
        Moves hashtags from `formation_hashtag` to `locked_hashtag`.
        """
        if event.formation_hashtag:
            event.locked_hashtag = event.formation_hashtag
            event.formation_hashtag = None
            self.session.add(event)
            await self.session.commit()
            await self.session.refresh(event)

            logger.info(f"Frozen hashtags for event {event.event_id}")
        
        return event

    async def query_by_hashtag(
        self,
        group_id: int,
        hashtag: str
    ) -> list[Event]:
        """
        Query events by hashtag.
        
        Searches both formation and locked hashtags.
        """
        hashtag_lower = hashtag.lower()
        
        result = await self.session.execute(
            select(Event)
            .where(
                Event.group_id == group_id,
                (Event.formation_hashtag.contains([hashtag_lower]) |
                 Event.locked_hashtag.contains([hashtag_lower]))
            )
        )
        
        return result.scalars().all()

    async def get_hashtags_for_event(
        self,
        event_id: int
    ) -> list[str]:
        """Get all hashtags for event (formation + locked)."""
        result = await self.session.execute(
            select(Event).where(Event.event_id == event_id)
        )
        event = result.scalar_one_or_none()
        
        if not event:
            return []

        hashtags = []
        if event.formation_hashtag:
            hashtags.extend(event.formation_hashtag)
        if event.locked_hashtag:
            hashtags.extend(event.locked_hashtag)
        
        return hashtags
```

---

## Task 4: Reaction Tracker

### File: `bot/common/reaction_tracker.py` (NEW)

```python
"""
ReactionTracker - Phase 1: Track bot reactions as social energy.

Counts:
- Bot's reactions to live cards
- Sentiment categorization (enthusiasm, interest, acknowledgment, timing)
- Counts as social energy signals (not behavioral scores)
"""

from __future__ import annotations

import logging
from typing import Optional
from telegram import Message, Update

logger = logging.getLogger("coord_bot.reaction_tracker")


class ReactionTracker:
    """
    Tracks bot reactions to live cards.
    
    v3.3 Design:
    - Only bot's reactions counted
    - Sentiment types: enthusiasm, interest, acknowledgment, timing_concern
    - Used as social energy signals (counts only, no personal scoring)
    """

    SENTIMENT_MAP = {
        "enthusiasm": {"🎉", "✨", "❤️", "😍", "🥰"},
        "interest": {"🔥", "👀", "🤩", "😮"},
        "acknowledgment": {"👍", "👋"},
        "timing_concern": {"⏳", "⏰", "🕒"},
    }

    @staticmethod
    def categorize_sentiment(emoji: str) -> str:
        """Categorize emoji into sentiment type."""
        for sentiment, emojis in ReactionTracker.SENTIMENT_MAP.items():
            if emoji in emojis:
                return sentiment
        return "other"

    @staticmethod
    def is_tracked_emoji(emoji: str) -> bool:
        """Check if emoji should be tracked."""
        for emojis in ReactionTracker.SENTIMENT_MAP.values():
            if emoji in emojis:
                return True
        return False

    @classmethod
    def count_reactions(cls, message: Message) -> dict[str, int]:
        """
        Count bot's reactions on a message.
        
        Returns dict: {"enthusiasm": N, "interest": N, ...}
        """
        counts = {
            "enthusiasm": 0,
            "interest": 0,
            "acknowledgment": 0,
            "timing_concern": 0,
            "other": 0,
        }

        if not message.reactions:
            return counts

        for reaction in message.reactions:
            emoji = str(reaction.emoji)
            if cls.is_tracked_emoji(emoji):
                sentiment = cls.categorize_sentiment(emoji)
                counts[sentiment] += reaction.count

        return counts

    @classmethod
    def get_total_energy(cls, counts: dict[str, int]) -> int:
        """Calculate total social energy (sum of all tracked)."""
        tracked = ["enthusiasm", "interest", "acknowledgment", "timing_concern"]
        return sum(counts.get(k, 0) for k in tracked)
```

---

## Task 5: Modify Organize Event

### File: `bot/commands/event_creation.py` (MODIFY)

Find the `start_event_flow` function and modify it:

```python
async def start_event_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str = "public",
    hashtags: Optional[list[str]] = None,  # NEW
) -> None:
    """Initialize event creation flow for public/group or private events."""
    # ... existing setup code ...

    flow_data = {
        "stage": "description",
        "data": {
            "creator": telegram_user_id,
            "date_preset": "custom",
            "time_window": "evening",
            "location_type": "cafe",
            "budget_level": "medium",
            "transport_mode": "any",
            "planning_notes": [],
            "invite_all_members": True,
            "hashtags": hashtags or [],  # NEW
        },
    }
    
    # ... rest of existing code ...
```

Add new function after existing code:

```python
async def post_live_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event: Event,
    hashtags: Optional[list[str]] = None,
) -> None:
    """Post live card for event."""
    from bot.services.event_live_card_service import EventLiveCardService
    
    message = update.effective_message
    if not message or not update.effective_chat:
        return

    chat = update.effective_chat
    bot = update.get_bot()
    
    async with get_session(settings.db_url) as session:
        service = EventLiveCardService(bot, session)
        await service.create_live_card(event, hashtags=hashtags or [])
```

Modify the event creation completion to post live card:

```python
# In the final confirmation handler, after event is created:
await post_live_card(update, context, event, hashtags=flow_data.get("hashtags", []))
```

---

## Task 6: Modify Event Flow Handlers

### File: `bot/handlers/event_flow.py` (MODIFY)

Update participant change handlers to update live card:

```python
async def handle_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle join callback."""
    # ... existing join logic ...
    
    # Update live card
    await update_live_card_on_change(context, event_id)


async def handle_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirm callback."""
    # ... existing confirm logic ...
    
    # Update live card
    await update_live_card_on_change(context, event_id)


async def update_live_card_on_change(context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Update live card after participant change."""
    from bot.services.event_live_card_service import EventLiveCardService
    
    bot = context.bot
    session = context.bot_data.get("db_session")
    
    if not session:
        return
    
    service = EventLiveCardService(bot, session)
    
    # Get event
    result = await session.execute(
        select(Event).where(Event.event_id == event_id)
    )
    event = result.scalar_one_or_none()
    
    if event:
        await service.update_live_card(event)
```

---

## Task 7: Modify Lifecycle Service

### File: `bot/services/event_lifecycle_service.py` (MODIFY)

Update the lock/completion/cancellation methods:

```python
async def lock_event(self, event: Event, user_id: int) -> Event:
    """Lock event - finalize attendance and post announcements."""
    # ... existing lock logic ...
    
    # Freeze hashtags
    from bot.services.event_hashtag_service import EventHashtagService
    async with get_session(settings.db_url) as session:
        hashtag_service = EventHashtagService(session)
        event = await hashtag_service.freeze_hashtags(event)
    
    # Delete live card
    from bot.services.event_live_card_service import EventLiveCardService
    async with get_session(settings.db_url) as session:
        card_service = EventLiveCardService(bot, session)
        await card_service.delete_live_card(event.event_id)
    
    # ... existing materialization logic ...
```

Similar changes for `complete_event` and `cancel_event`.

---

## Testing

### Unit Tests: `tests/test_event_live_card_service.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.services.event_live_card_service import EventLiveCardService


@pytest.mark.asyncio
async def test_create_live_card():
    # Mock bot, session, event
    bot = AsyncMock()
    session = AsyncMock()
    service = EventLiveCardService(bot, session)
    
    event = MagicMock()
    event.event_id = 1
    event.group_id = 100
    event.event_type = "Football"
    event.description = "Friday match"
    event.scheduled_time = datetime(2024, 1, 1, 18, 0)
    event.collapse_at = datetime(2024, 1, 2, 18, 0)
    event.min_participants = 5
    
    # Test
    card = await service.create_live_card(event)
    
    assert card.event_id == 1
    assert card.participant_count == 0
    bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_update_live_card():
    # Test updating card with participant changes
    pass
```

### Integration Tests: `tests/integration/test_live_card_creation.py`

```python
import pytest
from tests.fixtures.telegram import make_message, make_update


@pytest.mark.asyncio
async def test_live_card_posted_on_event_creation(bot_client):
    # Create event in group
    # Verify live card message appears
    # Verify card content includes event info
    pass


@pytest.mark.asyncio
async def test_live_card_updates_on_join(bot_client):
    # Create event
    # User joins
    # Verify card updates with new count
    pass
```

---

## Rollout Checklist

- [ ] Database tables created
- [ ] EventLiveCardService implemented
- [ ] EventHashtagService implemented
- [ ] ReactionTracker implemented
- [ ] `start_event_flow` modified
- [ ] `event_flow.py` handlers updated
- [ ] `event_lifecycle_service.py` updated
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Documentation updated
