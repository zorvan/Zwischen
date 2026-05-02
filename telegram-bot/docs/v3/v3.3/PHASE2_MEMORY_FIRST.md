# Phase 2: Memory-First Entry Point

## Overview

Make `/organize_event` always surface memory first. Collapse `/plan` and `/organize_event` into unified memory-first flow.

## Current Flow (v3.2)

```
/organize_event → start_event_flow()
├── description
├── type
├── date
├── time
├── threshold
└── final confirmation
```

**Problem:** Memories never shown. Event created without prior context.

## Target Flow (v3.3)

```
/organize_event → start_meaning_formation()
├── prior_memories (if any)
├── failure_pattern (if ≥3 attempts)
├── "What are you trying to bring together?"
├── clarification Q&A (2-3 turns)
├── [optional] skip to structured
└── event_creation wizard
    ├── description (pre-filled)
    ├── type (pre-filled)
    ├── hashtags (new field)
    └── final confirmation
```

## Implementation Tasks

---

## Task 1: Modify Event Creation Entry Points

### File: `bot/commands/event_creation.py`

**Remove direct creation path:**

```python
# OLD: start_event_flow() could be called directly
# NEW: Always goes through start_meaning_formation()

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /organize_event command."""
    # OLD: await start_event_flow(update, context, mode="public")
    # NEW:
    await start_meaning_formation(update, context, mode="public")


async def handle_flexible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /organize_event_flexible command."""
    # OLD: await start_event_flow(update, context, mode="public")
    # NEW:
    await start_meaning_formation(update, context, mode="public")
```

**Add alias for /plan command:**

```python
# In bot/commands/plan.py (NEW or modify existing)
from bot.commands.meaning_formation import handle as plan_handle

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /plan command - alias for /organize_event."""
    await plan_handle(update, context)
```

---

## Task 2: Enhance Meaning Formation Flow

### File: `bot/commands/meaning_formation.py`

**Add skip button after clarification turns:**

```python
async def handle_meaning_formation_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str,
) -> bool:
    """Process a user message during meaning-formation mode."""
    # ... existing code ...

    # After 2 turns, offer skip button
    if turns >= 2:
        skip_button = InlineKeyboardButton(
            "🚀 Skip to structured",
            callback_data=f"{prefix}_skip_to_structured"
        )
        continue_button = InlineKeyboardButton(
            "🤔 Keep clarifying",
            callback_data=f"{prefix}_keep_clarifying"
        )

        keyboard = [[skip_button], [continue_button]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.effective_message.reply_text(
            "Want to build the details now, or keep clarifying?",
            reply_markup=reply_markup
        )

    # ... rest of existing logic ...
```

**Handle skip callback:**

```python
async def _handle_callback_common(
    update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str
) -> None:
    """Handle callback queries for event creation flow."""
    # ... existing code ...

    elif data == f"{prefix}_skip_to_structured":
        # Transition to structured flow
        event_flow["stage"] = "structured_transition"
        context.user_data[flow_key] = event_flow

        await query.edit_message_text(
            "Got it! Let's build the details.",
            reply_markup=None
        )

        # Jump to type selection (pre-filled)
        flow_data = event_flow.get("data", {})
        await query.message.reply_text(
            f"Type: {flow_data.get('event_type', 'social')}\n"
            f"Description: {flow_data.get('description', 'Group event')}\n\n"
            "Adjust or confirm:",
            reply_markup=build_compact_markup(
                [
                    ("✅ Confirm", f"{prefix}_structure_final"),
                    ("✏️ Edit type", f"{prefix}_edit_type"),
                    ("✏️ Edit description", f"{prefix}_edit_description"),
                ],
                columns=2
            )
        )

    elif data == f"{prefix}_keep_clarifying":
        # Continue clarification
        await query.edit_message_text(
            "What else can you tell me about this event?"
        )
```

---

## Task 3: Pre-fill Structured Flow

### File: `bot/commands/event_creation.py`

**Add function to pre-fill from meaning formation:**

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

    # Get clarifications from meaning formation
    clarified = flow_data.get("clarified", {})

    # Pre-fill structured data
    if "description" in clarified:
        flow_data["description"] = clarified["description"]
    if "event_type" in clarified:
        flow_data["event_type"] = clarified["event_type"]

    # Set next stage
    event_flow["stage"] = "type"  # Skip description, go to type

    context.user_data[flow_key] = event_flow

    # Send user to type selection
    await update.effective_message.reply_text(
        f"Type: {flow_data.get('event_type', 'social')}\n\n"
        "Event type confirmed. Adjust if needed:",
        reply_markup=build_event_type_markup(prefix=flow_key.replace("_flow", ""))
    )
```

**Update skip callback to use this function:**

```python
elif data == f"{prefix}_skip_to_structured":
    # Transition to structured flow with pre-fill
    await start_event_flow_from_meaning_formation(update, context, mode=mode)
```

---

## Task 4: Update Event Memory Service

### File: `bot/services/event_memory_service.py`

**Enhance `get_prior_event_memories` to include lineage door:**

```python
async def get_prior_event_memories(
    self,
    event_type: str,
    group_id: int,
    limit: int = 3,
) -> list[EventMemory]:
    """
    Get prior event memories for same event type.

    Returns memories sorted by recency.
    Also returns lineage door fragment for next event.
    """
    result = await self.session.execute(
        select(EventMemory)
        .where(
            EventMemory.event_type == event_type,
            EventMemory.group_id == group_id,
            EventMemory.weave_text.isnot(None)
        )
        .order_by(EventMemory.created_at.desc())
        .limit(limit)
    )

    memories = result.scalars().all()

    # Get lineage door (one fragment from most recent event)
    if memories:
        lineage_door = memories[0].weave_text.split("\n")[0] if memories[0].weave_text else None
        self.bot_data[f"lineage_door_{group_id}_{event_type}"] = lineage_door

    return list(reversed(memories))  # Chronological order
```

**Add method to retrieve lineage door:**

```python
async def get_lineage_door_fragment(
    self,
    group_id: int,
    event_type: str,
) -> Optional[str]:
    """Get lineage door fragment for group/event type."""
    cache_key = f"lineage_door_{group_id}_{event_type}"

    # Try cache first
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
        lines = memory.weave_text.split("\n")
        return lines[0] if lines else None

    return None
```

---

## Task 5: Update Event Formatters

### File: `bot/common/event_formatters.py`

**Add format function for lineage door:**

```python
def format_lineage_door(lineage_fragment: Optional[str], event_type: str) -> str:
    """Format lineage door for event creation context."""
    if not lineage_fragment:
        return ""

    # Shorten to first sentence
    first_sentence = lineage_fragment.split(".")[0] if "." in lineage_fragment else lineage_fragment

    return (
        f" getLast time your group did a {event_type} event, "
        f"someone said: \"{first_sentence}\"."
    )


def format_meaning_formation_prompt(clarified: dict[str, Any], turns: int) -> str:
    """Format the meaning formation prompt based on what's clarified."""
    if turns == 0:
        return (
            "What kind of event are you thinking about?\n\n"
            "It can be as vague as 'something outdoors' or as specific as "
            "'Friday evening football'. I'll help you figure it out."
        )

    if "description" not in clarified:
        return (
            "Can you describe it a bit more? What would people actually do? "
            "Even a sentence helps."
        )

    if "event_type" not in clarified:
        return (
            "What kind of event is this — social, sports, outdoor, work, "
            "or something else?"
        )

    return (
        "Sounds good. Want me to set up the details (time, place, etc.) "
        "or is there anything else you want to clarify first?"
    )
```

---

## Task 6: Update Group Settings

### File: `db/models.py`

**Add group settings to Group model:**

```python
class Group(Base):
    __tablename__ = "groups"

    # ... existing columns ...

    settings = relationship("GroupSettings", uselist=False, back_populates="group")
```

---

## Task 7: Update Command Handlers

### File: `bot/commands/organize_event.py`

**Update to use unified entry:**

```python
from bot.commands.meaning_formation import start_meaning_formation

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /organize_event command."""
    await start_meaning_formation(update, context, mode="public")


async def handle_flexible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /organize_event_flexible command."""
    await start_meaning_formation(update, context, mode="public")
```

---

## Testing

### Unit Tests: `tests/test_meaning_formation.py`

```python
import pytest
from unittest.mock import AsyncMock
from bot.commands.meaning_formation import (
    start_meaning_formation,
    handle_meaning_formation_message,
)


@pytest.mark.asyncio
async def test_meaning_formation_shows_memories():
    # Setup: create event memories for group
    # Call: start_meaning_formation
    # Verify: memories displayed before prompt

    pass


@pytest.mark.asyncio
async def test_skip_to_structured():
    # Setup: 2 clarification turns
    # Action: user clicks "Skip to structured"
    # Verify: transitions to event creation wizard

    pass
```

### Integration Tests: `tests/integration/test_memory_first_flow.py`

```python
import pytest


@pytest.mark.asyncio
async def test_full_memory_first_flow(bot_client):
    # User runs /organize_event
    # Verify: Prior memories shown
    # Verify: Failure pattern shown (if applicable)
    # User types: "football match with friends"
    # Verify: Clarifying question asked
    # User types: "Friday evening"
    # Verify: "Skip to structured" button appears
    # User clicks skip
    # Verify: Event creation wizard with pre-filled type/description

    pass


@pytest.mark.asyncio
async def test_full_clarification_flow(bot_client):
    # User runs /organize_event
    # User types: "something fun"
    # Verify: "What kind of event?"
    # User types: "social"
    # Verify: "Want to build details or keep clarifying?"
    # User clicks "Keep clarifying"
    # Verify: Another question

    pass
```

---

## Rollout Checklist

- [ ] `/organize_event` now calls `start_meaning_formation`
- [ ] `/plan` is alias for `/organize_event`
- [ ] Prior memories shown before prompt
- [ ] Failure pattern displayed (if ≥3 attempts)
- [ ] Skip button appears after 2 turns
- [ ] Structured flow pre-fills from clarifications
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Documentation updated

---

## Configuration Options

### Group Settings Table

```python
class GroupSettings(Base):
    __tablename__ = "group_settings"

    group_id = Column(Integer, ForeignKey("groups.group_id"), primary_key=True)
    enable_live_cards = Column(Boolean, default=True)
    memory_first_skip_enabled = Column(Boolean, default=True)  # NEW
    lineage_selection_method = Column(String, default="llm")
    max_hashtags = Column(Integer, default=5)
```

**Commands to configure:**

```
/settings memory_skip on    # Allow skipping clarification
/settings memory_skip off   # Force full clarification flow
```

**Default behavior (recommended):**
- `memory_first_skip_enabled = true`
- Skip button appears after 2 clarification turns
- Users can always skip if they're ready to build
