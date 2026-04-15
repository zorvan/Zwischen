# Phase 3: Living Artifact

## Overview

Make the mosaic a living artifact with lineage. Fragment mosaic should:
1. Be pinned in group chat after posting
2. Support reactions and engagement
3. Link to future events of same type (lineage door)
4. Show prior fragment when creating similar event

## Implementation Tasks

---

## Task 1: Lineage Fragment Selection

### File: `bot/services/event_memory_service.py`

**Add method to select lineage fragment:**

```python
from typing import Optional


class EventMemoryService:
    # ... existing code ...
    
    async def select_lineage_fragment(self, event: Event) -> Optional[str]:
        """
        Select one fragment to serve as lineage door for next event.
        
        Two methods (configurable per group):
        - 'fixed': Use most recent fragment
        - 'llm': Context-aware selection
        
        Returns: Single fragment string (first line)
        """
        # Get all fragments for this event
        result = await self.session.execute(
            select(EventMemory)
            .where(
                EventMemory.event_id == event.event_id,
                EventMemory.fragment_text.isnot(None)
            )
            .order_by(EventMemory.created_at)
        )
        
        fragments = result.scalars().all()
        
        if not fragments:
            return None
        
        # Get group settings
        if not event.group_id:
            return None
        
        settings = await self._get_group_settings(event.group_id)
        method = settings.lineage_selection_method if settings else "llm"
        
        if method == "llm":
            return await self._select_lineage_with_llm(event, fragments)
        else:
            return await self._select_lineage_fixed(fragments)
    
    async def _select_lineage_with_llm(
        self,
        event: Event,
        fragments: list[EventMemory]
    ) -> Optional[str]:
        """Use LLM to select contextually relevant fragment."""
        from ai.llm import LLMClient
        
        # Build context
        fragment_texts = [
            f"- {f.fragment_text}" 
            for f in fragments 
            if f.fragment_text
        ]
        
        prompt = (
            f"Select one fragment that best represents what this {event.event_type} event was about.\n"
            f"Event: {event.description}\n\n"
            f"Fragments:\n"
            f"{'\n'.join(fragment_texts)}\n\n"
            "Return ONLY the fragment text, exactly as written. No commentary."
        )
        
        try:
            llm = LLMClient()
            try:
                result = await llm.generate(prompt)
                selected = result.strip().strip('"').strip("'")
                
                # Find the fragment object
                for frag in fragments:
                    if frag.fragment_text and frag.fragment_text.strip() == selected.strip():
                        frag.is_lineage_door = True
                        frag.selected_at = datetime.utcnow()
                        self.session.add(frag)
                        await self.session.commit()
                        
                        # Also save to cache
                        cache_key = f"lineage_door_{event.group_id}_{event.event_type}"
                        if hasattr(self.bot, "data"):
                            self.bot.data[cache_key] = selected
                        
                        return selected
            finally:
                await llm.close()
        except Exception as e:
            logger.error(f"LLM lineage selection failed: {e}")
        
        # Fallback to fixed
        return await self._select_lineage_fixed(fragments)
    
    async def _select_lineage_fixed(
        self,
        fragments: list[EventMemory]
    ) -> Optional[str]:
        """Use fixed rule: most recent fragment."""
        if not fragments:
            return None
        
        # Mark as lineage door
        fragments[-1].is_lineage_door = True
        fragments[-1].selected_at = datetime.utcnow()
        self.session.add(fragments[-1])
        await self.session.commit()
        
        return fragments[-1].fragment_text if fragments[-1].fragment_text else None
    
    async def get_lineage_door_fragment(
        self,
        group_id: int,
        event_type: str,
        event_description: Optional[str] = None
    ) -> Optional[str]:
        """
        Get lineage door for creating new event of same type.
        
        v3.3: Can be context-aware (LLM) or fixed.
        
        Returns: Single fragment that will be shown before creation.
        """
        # Try cache first
        cache_key = f"lineage_door_{group_id}_{event_type}"
        if hasattr(self.bot, "data") and cache_key in self.bot.data:
            return self.bot.data[cache_key]
        
        # Query DB
        result = await self.session.execute(
            select(EventMemory)
            .where(
                EventMemory.event_type == event_type,
                EventMemory.group_id == group_id,
                EventMemory.is_lineage_door == True
            )
            .order_by(EventMemory.selected_at.desc())
            .limit(1)
        )
        
        memory = result.scalar_one_or_none()
        
        if memory and memory.weave_text:
            # Use first line as lineage door
            lines = memory.weave_text.split("\n")
            return lines[0] if lines else None
        
        return None
```

---

## Task 2: Pin Mosaic Message

### File: `bot/commands/memory.py` (NEW or modify existing)

**Create memory display with pin support:**

```python
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config.settings import settings
from db.connection import get_session
from db.models import Event, EventMemory
from bot.services.event_memory_service import EventMemoryService

logger = logging.getLogger("coord_bot.commands.memory")


async def display_mosaic(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event: Event,
    session
) -> None:
    """Display fragment mosaic for event."""
    message = update.effective_message
    if not message:
        return

    bot = update.get_bot()
    service = EventMemoryService(bot, session)
    
    # Get fragments
    result = await session.execute(
        select(EventMemory)
        .where(EventMemory.event_id == event.event_id)
        .order_by(EventMemory.created_at)
    )
    fragments = result.scalars().all()
    
    if not fragments:
        await message.reply_text(
            "No memories yet. After the event, I'll ask participants to share what stuck with them."
        )
        return
    
    # Build mosaic text
    mosaic_lines = [f"📿 **Fragment Mosaic: {event.event_type}**\n"]
    
    for i, frag in enumerate(fragments, 1):
        if frag.weave_text:
            mosaic_lines.append(f"\n{i}. {frag.weave_text}")
        elif frag.fragment_text:
            mosaic_lines.append(f"\n{i}. {frag.fragment_text}")
    
    mosaic_text = "\n".join(mosaic_lines)
    
    # Post to group
    mosaic_msg = await bot.send_message(
        chat_id=event.group_id,
        text=mosaic_text,
        parse_mode="Markdown"
    )
    
    # Pin message
    try:
        await bot.pin_chat_message(
            chat_id=event.group_id,
            message_id=mosaic_msg.message_id,
            disable_notification=True
        )
        
        await message.reply_text(
            "📌 Fragment mosaic pinned in group chat!",
            reply_to_message_id=mosaic_msg.message_id
        )
    except Exception as e:
        logger.error(f"Failed to pin mosaic: {e}")
        await message.reply_text(
            "Fragment mosaic posted (pin failed).",
            reply_to_message_id=mosaic_msg.message_id
        )
    
    # Save mosaic message ID
    event.mosaic_message_id = mosaic_msg.message_id
    session.add(event)
    await session.commit()
```

---

## Task 3: Update Event Creation Wizard

### File: `bot/commands/event_creation.py`

**Show lineage fragment when pre-filling:**

```python
async def start_event_flow_from_meaning_formation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str = "public",
) -> None:
    """Start event creation from meaning-formation clarifications."""
    await start_event_flow(update, context, mode=mode)
    
    if context.user_data is None:
        return

    flow_key = "private_event_flow" if mode == "private" else "event_flow"
    event_flow_raw = context.user_data.get(flow_key)
    if not isinstance(event_flow_raw, dict):
        return
    event_flow: dict[str, Any] = event_flow_raw
    flow_data = event_flow.get("data", {})
    
    # Get group info
    group_id = flow_data.get("group_id")
    chat = update.effective_chat
    
    if group_id and chat:
        # Get lineage fragment
        lineage = await get_lineage_for_event(context, group_id, flow_data)
        
        if lineage:
            lineage_text = (
                f"Last time your group did something like this, "
                f"someone said: \"{lineage}\"\n\n"
                "You can ignore this or use it as inspiration."
            )
            
            await update.effective_message.reply_text(lineage_text)
    
    # ... rest of pre-fill logic ...
```

**Add helper function:**

```python
async def get_lineage_for_event(
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    flow_data: dict[str, Any]
) -> Optional[str]:
    """Get lineage fragment for event."""
    from bot.services.event_memory_service import EventMemoryService
    
    session = await get_session(settings.db_url).__aenter__()
    
    try:
        bot = context.bot
        service = EventMemoryService(bot, session)
        
        event_type = flow_data.get("event_type", "social")
        event_desc = flow_data.get("description", "")
        
        return await service.get_lineage_door_fragment(
            group_id=group_id,
            event_type=event_type,
            event_description=event_desc
        )
    finally:
        await session.close()
```

---

## Task 4: Hashtag Display Enhancements

### File: `bot/common/event_formatters.py`

**Enhance hashtag display:**

```python
def format_hashtags(hashtags: list[str], include_pill: bool = True) -> str:
    """Format hashtags for display."""
    if not hashtags:
        return ""
    
    if include_pill:
        return " ".join(f"#{tag}" for tag in hashtags)
    else:
        return ", ".join(f"#{tag}" for tag in hashtags)


def format_hashtags_pill(hashtags: list[str]) -> str:
    """Format hashtags as inline pills."""
    if not hashtags:
        return ""
    
    formatted = []
    for tag in hashtags:
        tag_clean = tag.lower().strip("#")
        formatted.append(f"#{tag_clean}")
    
    return " ".join(formatted)
```

**Update event_presenters.py:**

```python
def format_event_card(event: Event, include_live: bool = True) -> str:
    """Format event card for display."""
    lines = [
        f"🚀 **{event.event_type}**",
        f"{event.description[:100]}",
    ]
    
    # Hashtags
    hashtags = event.formation_hashtag or event.locked_hashtag or []
    if hashtags:
        lines.append(format_hashtags_pill(hashtags))
    
    # Time
    if event.scheduled_time:
        lines.append(f"📅 {event.scheduled_time.strftime('%d %b, %H:%M')}")
    else:
        lines.append("📅 TBD")
    
    # Stats
    if event.min_participants:
        lines.append(f"👥 {event.min_participants} min")
    
    return "\n".join(lines)
```

---

## Task 5: Search by Hashtag

### File: `bot/commands/events.py` (MODIFY)

**Add hashtag filter:**

```python
async def list_events_by_hashtag(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    hashtag: str
) -> None:
    """List events filtered by hashtag."""
    message = update.effective_message
    if not message or not update.effective_chat:
        return
    
    chat = update.effective_chat
    hashtag_clean = hashtag.lower().strip("#")
    
    async with get_session(settings.db_url) as session:
        # Query events with hashtag
        from bot.services.event_hashtag_service import EventHashtagService
        service = EventHashtagService(session)
        
        events = await service.query_by_hashtag(
            group_id=chat.id,
            hashtag=f"#{hashtag_clean}"
        )
        
        if not events:
            await message.reply_text(
                f"No events found with #{hashtag_clean}"
            )
            return
        
        # Format results
        lines = [f"Events tagged with #{hashtag_clean}:"]
        
        for event in events[:10]:  # Limit to 10
            time_str = (
                event.scheduled_time.strftime("%d %b, %H:%M")
                if event.scheduled_time else "TBD"
            )
            lines.append(
                f"- [{event.event_type}] {event.description[:50]} "
                f"({time_str})"
            )
        
        if len(events) > 10:
            lines.append(f"\n...and {len(events) - 10} more")
        
        await message.reply_text("\n".join(lines))


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /events command."""
    message = update.effective_message
    if not message:
        return
    
    text = (message.text or "").strip()
    
    # Check for hashtag filter
    import re
    hashtag_match = re.search(r"#(\w+)", text)
    
    if hashtag_match:
        hashtag = f"#{hashtag_match.group(1)}"
        await list_events_by_hashtag(update, context, hashtag)
    else:
        # List all events
        await list_all_events(update, context)
```

---

## Task 6: Mosaic Engagement

### File: `bot/handlers/membership.py` (MODIFY)

**Track mosaic reactions:**

```python
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages."""
    if not update.effective_message or not update.effective_chat:
        return
    
    message = update.effective_message
    
    # Track reactions to mosaic messages
    if message.reactions:
        await track_mosaic_reactions(update, context)
    
    # ... existing logic ...


async def track_mosaic_reactions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Track reactions to mosaic messages."""
    message = update.effective_message
    
    # Check if this is a mosaic message
    # (Could check database for pinned_message_id)
    
    # For now, track all reactions
    if message.reactions:
        total_engagement = sum(r.count for r in message.reactions)
        
        if total_engagement >= 5:  # Threshold
            logger.info(
                f"Mosaic engagement high: {total_engagement} reactions"
            )
            # Could trigger notification or analytics
```

**Track replies to mosaic:**

```python
async def handle_reply_to_mosaic(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    replied_message_id: int
) -> None:
    """Handle replies to mosaic message."""
    # If replying to mosaic, add fragment
    if replied_message_id:
        # Check if this is a mosaic message
        # Add fragment for current user
        pass
```

---

## Testing

### Unit Tests: `tests/test_lineage_service.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.services.event_memory_service import EventMemoryService


@pytest.mark.asyncio
async def test_select_lineage_fixed():
    # Setup: multiple fragments
    # Call: select_lineage_fragment
    # Verify: Returns most recent fragment
    pass


@pytest.mark.asyncio
async def test_select_lineage_llm():
    # Setup: mock LLM
    # Call: select_lineage_fragment with 'llm' method
    # Verify: LLM called, correct fragment selected
    pass


@pytest.mark.asyncio
async def test_get_lineage_door_fragment():
    # Setup: create event with lineage door
    # Call: get_lineage_door_fragment for same type
    # Verify: Returns lineage fragment
    pass
```

### Integration Tests: `tests/integration/test_lineage_door.py`

```python
import pytest


@pytest.mark.asyncio
async def test_lineage_door_shown_on_creation(bot_client):
    # Create event A with fragments
    # Complete event A
    # Create event B of same type
    # Verify: Lineage fragment shown during creation
    
    pass


@pytest.mark.asyncio
async def test_mosaic_is_pinned(bot_client):
    # Complete event
    # Verify: Mosaic message is pinned
    # Verify: Message ID saved to event
    pass


@pytest.mark.asyncio
async def test_hashtag_search(bot_client):
    # Create event with hashtags
    # Search /events #tag
    # Verify: Event appears in results
    pass
```

---

## Rollout Checklist

- [ ] Lineage fragment selection implemented (both methods)
- [ ] Mosaic message pinned after posting
- [ ] Lineage door shown when creating similar event
- [ ] Hashtag search works
- [ ] Mosaic engagement tracked
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Documentation updated

---

## Configuration Examples

### Set Lineage Selection Method

```python
# Group admin sets preference
/settings lineage fixed  # Use most recent
/settings lineage llm    # Context-aware (default)
```

### View Hashtags

```
/events #football
# Shows all football events

/events #outdoor
# Shows all outdoor events
```

---

## Future Enhancements

1. **Hashtag suggestions** - Auto-suggest hashtags based on event description
2. **Hashtag analytics** - Show popular tags for group
3. **Mosaic timeline** - Show mosaic history as scrollable feed
4. **Lineage carousel** - Show last 3 lineage fragments when creating event
