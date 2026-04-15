# v3.3 Implementation Plan

## Current State

**Infrastructure:** v3-aligned (state machine, constraints, fragment mosaic, personal attendance mirror, idempotency)

**Problems:**
1. Events socially invisible between announcement and deadline
2. `/plan` and memory-as-input are orphaned
3. Post-event mosaic arrives and stops

## Implementation Approach

### Phase 1: Live Event Cards (Priority: HIGH)

**Goal:** Make forming events socially visible in group chat

**Files to Create/Modify:**

1. **db/models.py** - Add new models
   - `EventLiveCard` table
   - `GroupSettings` table

2. **bot/services/event_live_card_service.py** (NEW)
   - `EventLiveCardService` class
   - Methods: `create_live_card`, `update_live_card`, `delete_live_card`, `get_live_card`

3. **bot/services/event_hashtag_service.py** (NEW)
   - `EventHashtagService` class
   - Methods: `validate_hashtags`, `assign_hashtags`, `freeze_hashtags`, `query_by_hashtag`

4. **bot/common/reaction_tracker.py** (NEW)
   - Track bot reactions as social energy signals
   - Sentiment categorization: enthusiasm, interest, acknowledgment, timing_concern

5. **bot/commands/organize_event.py** - MODIFY
   - Add hashtag input field
   - Post live card instead of regular announcement

6. **bot/handlers/event_flow.py** - MODIFY
   - Update join/confirm/cancel handlers to update live card
   - Add live card update on participant changes

7. **bot/services/event_lifecycle_service.py** - MODIFY
   - Delete live card when event locks/completes/cancels

**Database Changes:**
```sql
-- Live event cards
CREATE TABLE event_live_cards (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(event_id) UNIQUE,
    message_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    participant_count INTEGER DEFAULT 0,
    confirmed_count INTEGER DEFAULT 0,
    reaction_counts JSONB DEFAULT '{}',
    hashtags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Group settings
CREATE TABLE group_settings (
    group_id INTEGER PRIMARY KEY REFERENCES groups(group_id),
    enable_live_cards BOOLEAN DEFAULT true,
    memory_first_skip_enabled BOOLEAN DEFAULT true,
    lineage_selection_method TEXT DEFAULT 'llm' CHECK (lineage_selection_method IN ('fixed', 'llm')),
    max_hashtags INTEGER DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Event hashtags (permanent)
ALTER TABLE events ADD COLUMN formation_hashtag TEXT[];
ALTER TABLE events ADD COLUMN locked_hashtag TEXT[];

-- Event memory lineage
ALTER TABLE event_memories ADD COLUMN is_lineage_door BOOLEAN DEFAULT FALSE;
ALTER TABLE event_memories ADD COLUMN selected_at TIMESTAMPTZ DEFAULT NOW();
```

---

### Phase 2: Memory-First Entry Point (Priority: HIGH)

**Goal:** Make `/organize_event` always surface memory first

**Files to Create/Modify:**

1. **bot/commands/organize_event.py** - MODIFY
   - Remove `start_event_flow()` direct entry point
   - Always call `start_meaning_formation()` instead
   - Deprecate "direct creation bypass"

2. **bot/commands/meaning_formation.py** - MODIFY
   - Add failure pattern display (already exists)
   - Add skip button after 2 clarification turns (configurable per group)
   - Pre-fill structured flow with clarified intent

3. **bot/common/event_formatters.py** - MODIFY
   - Add `format_hashtags()` for live card display
   - Add `format_lineage_door()` for showing prior fragment

4. **bot/services/event_memory_service.py** - MODIFY
   - Enhance `get_prior_event_memories()` to include lineage door fragments
   - Add `get_lineage_door_fragment()` method

**Flow Changes:**

```
BEFORE:
/organize_event → start_event_flow() → description → type → date → ...

AFTER:
/organize_event → start_meaning_formation()
  → prior_memories (if any)
  → failure_pattern (if ≥3 attempts)
  → "What are you trying to bring together?"
  → clarification Q&A (2-3 turns)
  → [optional] skip to structured
  → event_creation wizard
```

---

### Phase 3: Living Artifact (Priority: MEDIUM)

**Goal:** Mosaic becomes lineage container, not endpoint

**Files to Create/Modify:**

1. **bot/services/event_memory_service.py** - MODIFY
   - Add `select_lineage_fragment()` method
   - Add `append_lineage_context()` for LLM prompts
   - Mark one fragment as `is_lineage_door` per completed event

2. **bot/commands/memory.py** - MODIFY
   - Pin mosaic message after posting
   - Show "📌 Pinned" indicator

3. **bot/common/event_presenters.py** - MODIFY
   - Add lineage fragment to event card
   - Show "Last time: ..." when creating similar event

4. **bot/handlers/mentions.py** - MODIFY
   - Include lineage context in LLM inference

**Database Changes:**
Same as Phase 1 (single migration)

---

## Testing Strategy

### Unit Tests
- `tests/test_event_live_card_service.py`
- `tests/test_event_hashtag_service.py`
- `tests/test_reaction_tracker.py`
- `tests/test_lineage_service.py`

### Integration Tests
- `tests/integration/test_live_card_creation.py`
- `tests/integration/test_memory_first_flow.py`
- `tests/integration/test_hashtag_persistence.py`
- `tests/integration/test_lineage_door.py`

### E2E Tests
- `tests/scenarios/test_v33_live_event_lifecycle.py`
  - Create event
  - Verify live card appears
  - Join/confirm participants
  - Verify card updates
  - Add hashtags
  - Lock event
  - Verify live card deleted
  - Verify mosaic pinned
  - Create similar event
  - Verify lineage fragment shown

---

## Rollout Plan

1. **Week 1:** Phase 1 (Live Cards)
2. **Week 2:** Phase 2 (Memory-First) + Phase 1 completion
3. **Week 3:** Phase 3 (Living Artifact)
4. **Week 4:** Testing, bug fixes, documentation

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Live cards clutter chat | One live card per group at a time, opt-out per group |
| LLM latency for lineage | Graceful degradation: use `fixed` fallback |
| Memory-first too slow | Skip button after 2 turns, group-level setting |
| Hashtag validation issues | Strict format: `#[a-z0-9_]+`, max 5 per event |

---

## Definition of Done

- [ ] All 3 phases implemented
- [ ] Tests pass (unit, integration, E2E)
- [ ] Documentation updated
- [ ] Migration script created (if needed)
- [ ] Rollout plan documented
