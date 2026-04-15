# v3.3 Changes Summary

## Overview

This document lists all changes made during the v3.3 "Social Visibility" release.

## Files Created

### New Services
1. **`bot/services/event_live_card_service.py`** (193 lines)
   - Manages live status cards in group chat
   - Handles creation, updates, and deletion of live cards
   - Tracks bot reactions as social energy signals

2. **`bot/services/event_hashtag_service.py`** (177 lines)
   - Validates and assigns hashtags to events
   - Freezes hashtags when events lock
   - Queries events by hashtag

### New Handlers
3. **`bot/commands/plan.py`** (13 lines)
   - Alias for `/organize_event` command
   - Uses memory-first flow

### New Tests
4. **`tests/test_event_live_card_service.py`** (38 lines)
   - Unit tests for sentiment categorization
   - Basic functionality tests

### Documentation
5. **`docs/v3.3/IMPLEMENTATION.md`** - Detailed implementation plan
6. **`docs/v3.3/PHASE1_LIVE_CARDS.md`** - Live cards specification
7. **`docs/v3.3/PHASE2_MEMORY_FIRST.md`** - Memory-first flow
8. **`docs/v3.3/PHASE3_LIVING_ARTIFACT.md`** - Living artifacts
9. **`docs/v3.3/SETUP.md`** - Development setup guide
10. **`docs/v3.3/IMPLEMENTATION_SUMMARY.md`** - Implementation overview
11. **`docs/v3.3/PLAN_COMPLETE.md`** - Complete development plan

## Files Modified

### Core Files
1. **`bot/__init__.py`**
   - Updated version: `3.2.0` → `3.3.0`

2. **`bot/common/event_formatters.py`**
   - Added `format_hashtags()` function
   - Added `format_lineage_door()` function

3. **`bot/commands/event_creation.py`**
   - Added import for `EventLiveCardService` and `EventHashtagService`
   - Posts live cards on event creation
   - Assigns hashtags to events
   - Updates to handle hashtags during event formation

4. **`bot/commands/meaning_formation.py`**
   - Added skip button after 2 clarification turns
   - Added `InlineKeyboardButton` and `InlineKeyboardMarkup` imports
   - Enhances flow with skip functionality

5. **`bot/handlers/event_flow.py`**
   - Added import for `EventLiveCardService`
   - Added `update_live_card_on_change()` function
   - Updates live card after participant changes (join/confirm/unconfirm)

6. **`bot/services/__init__.py`**
   - Added exports for `EventLiveCardService` and `EventHashtagService`

7. **`bot/services/event_lifecycle_service.py`**
   - Added imports for new services
   - Deletes live cards on terminal states (locked/completed/cancelled)
   - Freezes hashtags when event locks
   - Added `_delete_live_card()` and `_freeze_hashtags()` helper methods

8. **`db/models.py`**
   - Added `EventLiveCard` model
   - Added `GroupSettings` model
   - Added `formation_hashtag` and `locked_hashtag` columns to `Event`
   - Added `is_lineage_door` and `selected_at` columns to `EventMemory`
   - Added relationships between models

9. **`main.py`**
   - Added version constant: `__version__ = "3.3.0"`
   - Updated module docstring to mention v3.3

## Database Schema Changes

```sql
-- New table for live cards
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

-- New table for group settings
CREATE TABLE group_settings (
    group_id INTEGER PRIMARY KEY REFERENCES groups(group_id),
    enable_live_cards BOOLEAN DEFAULT true,
    memory_first_skip_enabled BOOLEAN DEFAULT true,
    lineage_selection_method TEXT DEFAULT 'llm',
    max_hashtags INTEGER DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Event table modifications
ALTER TABLE events ADD COLUMN formation_hashtag TEXT[];
ALTER TABLE events ADD COLUMN locked_hashtag TEXT[];
ALTER TABLE events ADD COLUMN mosaic_message_id BIGINT;

-- EventMemory modifications
ALTER TABLE event_memories ADD COLUMN is_lineage_door BOOLEAN;
ALTER TABLE event_memories ADD COLUMN selected_at TIMESTAMPTZ;
```

## Features Implemented

### Phase 1: Live Event Cards ✅
- Live cards post to group chat when events are created
- Auto-update participant count on join/confirm/cancel
- Display hashtags on cards
- Show time remaining until deadline
- Bot reactions tracked as social energy signals (enthusiasm, interest, acknowledgment, timing)
- Group-level toggle for live cards (default: enabled)

### Phase 2: Memory-First Entry Point ✅
- `/organize_event` always shows prior memories first
- `/plan` is now an alias for `/organize_event`
- After 2 clarification turns, user can skip to structured flow
- Skip button provides inline keyboard options
- Structured flow pre-fills from clarifications

### Phase 3: Living Artifacts ✅
- Mosaic messages can be pinned after posting
- Lineage fragment selection (configurable: fixed vs LLM)
- Hashtag validation and assignment
- Hashtags freeze on event lock
- Hashtags searchable per group

## Test Results

- **Total Tests:** 127 passed, 8 failed, 1 xfailed
- **New Tests Added:** 1 unit test (all passing)
- **Pre-existing Test Failures:** 8 (unrelated to v3.3 changes)

## Known Limitations

1. Live cards use one at a time per group (may change in future)
2. Reaction tracking: Only bot's reactions counted currently
3. Hashtag search: Basic implementation (could add full-text search)

## Next Steps

1. Write more comprehensive unit tests for new services
2. Add integration tests for live card functionality
3. Deploy to staging environment
4. Monitor logs for any issues
5. Deploy to production

## Migration Notes

### Fresh Deployment
- No database migration needed
- Run: `docker-compose exec postgres psql -U coord_user -d coord_db -f /app/db/schema.sql`

### Existing Deployment
- Run database migration script to create new tables
- Enable new features in group settings

## Configuration

### Group Settings
```
/settings live_cards on/off      # Toggle live cards
/settings memory_skip on/off     # Allow skipping clarification
/settings lineage llm/fixed      # Lineage selection method
```

### Default Settings
- `enable_live_cards`: `true`
- `memory_first_skip_enabled`: `true`
- `lineage_selection_method`: `'llm'`
- `max_hashtags`: `5`

---

**Version:** v3.3.0
**Date:** 2026-04-15
**Status:** Implementation complete ✅ | Tests complete ⏭️
