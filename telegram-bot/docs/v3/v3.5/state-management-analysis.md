# State Management Architecture Analysis

## Executive Summary

This document analyzes the current state management architecture of the Zwischen Telegram bot, identifies weaknesses and issues, and proposes a three-phase migration plan toward a centralized state management system.

## 1. Current State Management Approach

### 1.1 In-Memory State Storage (`context.user_data`)

The bot uses `context.user_data` (backed by `PicklePersistence` to `bot_data.pkl`) for three distinct state categories:

**A. Event Creation Flows** (two parallel systems)

| Key | Purpose | Structure |
|-----|---------|-----------|
| `event_flow` | Public/group event creation | `{"stage": str, "data": {flow fields...}, "group_id": int, "group_title": str}` |
| `private_event_flow` | DM event creation | `{"stage": str, "data": {flow fields...}}` |
| `creation_step` | Menu-driven creation flow | `"awaiting_event_type" \| "awaiting_flexible_input"` |

**`event_flow` structure (detailed):**
```python
event_flow = {
    "stage": "description" | "type" | "date_preset" | "date" | "date_options"
           | "time_window" | "time_option" | "time_manual" | "min_participants"
           | "target_participants" | "duration" | "location" | "budget"
           | "transport" | "invitees" | "final",
    "data": {
        "creator": int,
        "description": str,
        "event_type": "social" | "sports" | "work",
        "date_preset": "today" | "tomorrow" | "weekend" | "nextweek" | "custom",
        "scheduled_date": "YYYY-MM-DD",
        "scheduled_time": "YYYY-MM-DDTHH:MM",
        "time_window": "morning" | "afternoon" | "evening" | "night",
        "scheduling_mode": "fixed" | "flexible",
        "min_participants": int,
        "target_participants": int,
        "duration_minutes": int,
        "location_type": "home" | "outdoor" | "cafe" | "office" | "gym",
        "budget_level": "free" | "low" | "medium" | "high",
        "transport_mode": "walk" | "public_transit" | "drive" | "any",
        "invitees": list[str],
        "invite_all_members": bool,
        "planning_notes": list[str],
    },
    "group_id": int,       # only for public events
    "group_title": str,    # only for public events
}
```

**B. Enrichment Prompts** (shared across event_panel and menus):
```python
enrich_event_id: int | None
enrich_action: "add_idea" | "add_hashtag" | "add_memory"
             | "add_constraint" | "add_constraint_unless" | "suggest_time"
             | None
```

**C. Modification Requests** (mentions.py):
```python
pending_modify_request_{request_id}: {
    "event_id": int,
    "event_description": str,
    "event_scheduled_time": str | None,
    "admin_id": int | None,
    "requester_id": int | None,
    "requester_username": str | None,
}
pending_mod_text_{request_id}: { ... }
```

### 1.2 Database State

**Event Model States:**
```
Event.state: String(20), default="proposed"
```

**State transition graph (from `EVENT_STATE_TRANSITIONS`):**
```
proposed  --> interested, confirmed, cancelled
interested --> confirmed, cancelled
confirmed --> interested, proposed, locked, cancelled
locked    --> completed, cancelled
cancelled --> (terminal)
completed --> (terminal)
```

**State semantics:**
| State | Meaning | User Actions Allowed |
|-------|---------|---------------------|
| `proposed` | Event created, awaiting participants | Anyone can join |
| `interested` | People joined, gathering momentum | Joined users can confirm |
| `confirmed` | At least one person committed | Confirmed users can unconfirm; organizer can lock |
| `locked` | Event finalized, attendance closed | No changes (only organizer can unlock) |
| `cancelled` | Event was cancelled | None |
| `completed` | Event finished | Memory collection triggered |

**Participant Model:**
```python
EventParticipant:
    event_id: int (PK)
    telegram_user_id: int (PK)
    status: ParticipantStatus (joined | confirmed | cancelled | no_show)
    role: ParticipantRole (organizer | participant | observer)
    joined_at: DateTime
    confirmed_at: DateTime | None
    cancelled_at: DateTime | None
    source: str (slash | callback | mention | dm | creation | waitlist)
```

**State Transition Audit Trail:**
```python
EventStateTransition:
    transition_id: int (PK)
    event_id: int (FK)
    from_state: String(20)
    to_state: String(20)
    actor_telegram_user_id: BigInteger | None
    timestamp: DateTime
    reason: Text | None
    source: String(50)  # slash | callback | AI mention | system
```

### 1.3 State Reconciliation Pattern

The bot uses a **reconciliation-after-participant-change** pattern in `participant_state_reconcile.py`:

```python
async def reconcile_event_state_after_participant_change(
    session, bot, event_id, actor_telegram_user_id, source, reason
) -> Event:
```

This function is called **after** join/unconfirm/cancel operations and:
1. Re-reads the event from DB (fresh state)
2. Counts active participants (joined + confirmed)
3. Counts confirmed participants
4. Determines if state should be **downgraded**:
   - Only organizer remains --> `proposed`
   - Was `confirmed`, 0 confirmed left --> `interested` (if active) or `proposed`
   - Was `interested`, 0 active left --> `proposed`
5. Executes the downgrade via `EventLifecycleService.transition_with_lifecycle()`

### 1.4 Optimistic Concurrency Control

The `Event.version` integer is incremented on every state transition. `EventStateTransitionService.transition()` accepts an optional `expected_version` parameter. If the current DB version doesn't match, it raises `ConcurrencyConflictError`.

## 2. State Flow Traces

### 2.1 Event Creation Flow

```
/organize_event
    |
    v
start_event_flow() --> context.user_data["event_flow"] = {stage: "description", data: {...}}
    |
    v (user provides description via text or callback)
_handle_callback_common() --> stage advances: description -> type -> date_preset -> ...
    |
    v (user confirms with final_yes)
finalize_event() -->
    1. Create Event(state="proposed") in DB
    2. ParticipantService.join(organizer, role="organizer")
    3. Send DM invitations to group members
    4. Post live card to group
    5. context.user_data.pop("event_flow")
    |
    v
Event exists in DB as state="proposed"
```

### 2.2 Event Participation Flow

```
User clicks Join button
    |
    v
handle_join() in event_flow.py:
    1. ParticipantService.join() --> EventParticipant(status="joined")
    2. If organizer is different user and event.state == "proposed":
       EventLifecycleService.transition(event_id, "interested")
    3. Refresh event, build UI
    |
    v
User clicks Confirm button
    |
    v
handle_confirm() in event_flow.py:
    1. ParticipantService.confirm() --> status="confirmed", confirmed_at=now
    2. If confirmed_count > 0 and event.state != "confirmed":
       EventLifecycleService.transition(event_id, "confirmed")
    3. Refresh event, build UI
    |
    v
User clicks Cancel button
    |
    v
handle_cancel() in event_flow.py:
    1. ParticipantService.cancel() --> status="cancelled", cancelled_at=now
    2. WaitlistService.trigger_auto_fill() --> offer to next waitlisted user
    3. reconcile_event_state_after_participant_change()
       --> may downgrade: confirmed->interested->proposed
    4. Commit, show updated UI
```

### 2.3 Event Lifecycle

```
proposed --> interested (first non-organizer joins)
interested --> confirmed (first confirmation + confirmed_count > 0)
confirmed --> locked (organizer locks, min_participants met)
locked --> completed (manual, via scheduler or command)
any state --> cancelled (organizer, auto-collapse, or all participants leave)
```

## 3. Architecture Diagram

```
                    +------------------+
                    |  Telegram User   |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
    +---------v----------+      +-----------v----------+
    |  Slash Commands    |      | Callback Queries     |
    |  (/join, /confirm, |      | (inline buttons)     |
    |   /cancel, /lock)  |      |                      |
    +--------+-----------+      +-----------+----------+
             |                             |
             +-------------+---------------+
                           |
               +-----------v-----------+
               |  Handler Layer        |
               |  (event_flow.py,      |
               |   event_panel.py,     |
               |   join.py, cancel.py) |
               +-----------+-----------+
                           |
          +----------------+----------------+
          |                                 |
  +-------v--------+              +---------v--------+
  | ParticipantService |         | EventStateTransitionService |
  | - join()         |           | - transition()              |
  | - confirm()      |           |   + validates state machine |
  | - cancel()       |           |   + optimistic concurrency  |
  | - unconfirm()    |           |   + audit logging           |
  +--------+---------+           +-----------+----------------+
           |                                 |
           v                                 v
  +--------+---------------------------------+--------+
  |              EventLifecycleService               |
  |  - transition_with_lifecycle()                   |
  |    +---> EventStateTransitionService             |
  |    +---> EventMaterializationService (announcements) |
  |    +---> EventMemoryService (memory triggers)     |
  |    +---> GroupEventTypeStatsService              |
  +-----------------------+--------------------------+
                          |
          +---------------+---------------+
          |                               |
  +-------v--------+            +---------v---------+
  |  DB: Events    |            |  DB: EventState   |
  |  - state       |            |  Transition       |
  |  - version     |            |  - from_state     |
  |  - timestamps  |            |  - to_state       |
  +-------+--------+            |  - actor          |
          |                     +-------------------+
  +-------v--------+
  | DB:            |
  | EventParticipant|
  | - status       |
  | - role         |
  | - timestamps   |
  +----------------+

    IN-MEMORY (context.user_data / bot_data.pkl):
    +------------------------------------------+
    | event_flow / private_event_flow          |
    |   - stage (string)                       |
    |   - data (dict of flow fields)           |
    | enrich_event_id / enrich_action          |
    | pending_modify_request_*                 |
    | creation_step / creation_intent          |
    +------------------------------------------+
```

## 4. Strengths

1. **Single write path for state transitions**: `EventStateTransitionService` is the only allowed path for mutating `Event.state`, with validation, preconditions, and audit logging.

2. **Optimistic concurrency control**: The `version` field on `Event` prevents lost-update bugs from concurrent modifications.

3. **Audit trail**: `EventStateTransition` table records every state change with actor, timestamp, reason, and source.

4. **Normalized participants**: `EventParticipant` replaces the old JSON `attendance_list`, enabling proper status tracking and foreign key constraints.

5. **Reconciliation pattern**: `reconcile_event_state_after_participant_change()` ensures event state is consistent with participant counts after changes.

6. **Idempotency service**: `IdempotencyKey` table prevents duplicate command execution (important for Telegram's duplicate updates).

7. **Waitlist with auto-fill**: Complete FIFO waitlist with time-scaled expiration windows and automatic cascade.

8. **PicklePersistence**: `context.user_data` survives bot restarts, preserving creation flows.

## 5. Weaknesses and Issues

### 5.1 CRITICAL: Dual Creation Flow Systems

**Problem**: `event_creation.py` and `menus.py` both write to `context.user_data["event_flow"]` but with incompatible structures.

- `event_creation.py` expects: `{"stage": "description" | "type" | "date_preset" | ..., "data": {...}}`
- `menus.py` creates: `{"stage": "time" | "type", "data": {"event_type": ..., "description": ..., "organizer_id": ...}, "participants": [...]}`

When `menus.py` sets `stage: "time"` and `event_creation.py`'s callback handler checks for known stages, it falls through all conditions silently. The `stage` values `"time"` and `"type"` from `menus.py` are not in `event_creation.py`'s expected stage progression.

**Impact**: Users who start via `/events` menu and then hit callback buttons may experience silent failures or unexpected behavior.

### 5.2 No Schema Validation for In-Memory State

**Problem**: `context.user_data` is a bare Python dict. Any handler can read/write arbitrary keys. There is no:
- TypedDict or Pydantic model for `event_flow`
- Stage enum or validation
- Key existence checks before access

**Impact**: Typos in key names (`"staged"` vs `"stage"`) cause silent failures. Missing keys cause `KeyError` or `NoneType` errors at runtime.

### 5.3 Inconsistent Reconciliation Coverage

**Problem**: `reconcile_event_state_after_participant_change()` is called after unconfirm and cancel, but NOT after join or confirm. Instead, join and confirm have their own inline state transition logic.

**Impact**: The join/confirm logic has a subtle bug: it checks `confirmed_count > 0` to transition to `confirmed`, but `get_confirmed_count()` only counts `ParticipantStatus.confirmed` rows. After `ParticipantService.confirm()` updates a participant to `confirmed`, the count is checked in the same session but the participant row may not be flushed yet, causing a race where the transition to `confirmed` is missed.

### 5.4 Stale State in UI After Concurrent Changes

**Problem**: When a user opens an event panel, the buttons are built based on the current DB state. If another user changes the event state (e.g., locks it) while the first user's panel is open, the first user's buttons become stale.

**Impact**: A user might see a "Join" button on a locked event, or a "Lock" button when they no longer have permission.

**Mitigation attempted**: The "Refresh" button re-reads from DB, but this is user-dependent.

### 5.5 No Centralized State Machine Definition

**Problem**: `EVENT_STATE_TRANSITIONS` in `event_states.py` is the single source of truth, but:
- The transition validation in `EventStateTransitionService` is the only enforcement point
- UI builders in `event_panel.py` and `event_flow.py` hardcode their own state-aware button logic
- The `get_available_actions()` function exists but is barely used

**Impact**: UI buttons can be inconsistent with the actual state machine. If a new transition is added, all UI builders must be manually updated.

### 5.6 Enrichment State Collisions

**Problem**: `enrich_event_id` and `enrich_action` are shared keys used by multiple enrichment actions. If a user triggers two enrichment prompts quickly (e.g., "add idea" then "add hashtag"), the second overwrites the first.

**Impact**: The second prompt's handler will process the first prompt's text input, leading to incorrect enrichment type.

### 5.7 No Cleanup of Stale In-Memory State

**Problem**: There is no periodic cleanup of stale `context.user_data` entries. If a user abandons a creation flow, the data persists indefinitely in `bot_data.pkl`.

**Impact**: Over time, `bot_data.pkl` grows unbounded. There is no TTL on creation flows or enrichment prompts.

### 5.8 Event State vs. Participant Status Misalignment

**Problem**: The event state (`proposed`, `interested`, `confirmed`) and participant statuses (`joined`, `confirmed`, `cancelled`) use the same terminology but represent different things:
- `Event.state = "confirmed"` means "at least one participant has confirmed"
- `EventParticipant.status = "confirmed"` means "this specific user has confirmed"

**Impact**: This naming collision is confusing for developers and can lead to bugs where code checks `event.state == "confirmed"` when it should check participant-level status, or vice versa.

### 5.9 Missing State Transition: `locked` --> `proposed`

**Problem**: The state machine allows `confirmed` --> `proposed` (when all participants leave after unconfirm), but does NOT allow `locked` --> `proposed`. Once locked, the only transitions are to `completed` or `cancelled`.

**Impact**: If an organizer wants to "unlock and restart" an event, they must cancel it and create a new one. There is no `unlock` transition in the state machine (though the UI has an "Unlock" button that calls `CALLBACK_ACTIONS["unlock"]` -- this action is defined but never implemented in the transition service).

## 6. Proposed Migration Plan

### Phase 1: Fix Immediate Issues (High Priority)

1. **Consolidate creation flows**: Choose one system (`event_creation.py` is more complete) and remove the other. If `menus.py` is needed for the `/events` menu, have it call `event_creation.start_event_flow()` or `start_event_flow_from_prefill()` instead of building its own `event_flow` dict.

2. **Add TypedDict/Pydantic models** for all `context.user_data` structures:
   ```python
   class EventFlowData(TypedDict):
       creator: int
       description: str
       event_type: str
       # ... all required fields

   class EventFlow(TypedDict):
       stage: Literal["description", "type", ...]
       data: EventFlowData
       group_id: NotRequired[int]
   ```

3. **Fix the confirmed_count race condition**: After `ParticipantService.confirm()`, ensure the session is flushed before checking `get_confirmed_count()`, or restructure to count participants directly after the update.

4. **Implement the `unlock` transition**: Either implement `locked` --> `confirmed` in the state machine (with appropriate precondition checks), or remove the "Unlock" button from the UI.

### Phase 2: Centralized State Management (Medium Priority)

5. **Add TTL to in-memory state**: Set a 30-minute expiration on `event_flow`, `enrich_*`, and `pending_*` entries. Clean them up on access (lazy cleanup) or via a periodic job.

6. **Create StateStore class**: Centralized in-memory state management with:
   - Per-event locks for atomic access
   - TTL-based cleanup
   - TypedDict models for all structures
   - Backward compatible with existing `context.user_data`

7. **Centralize UI state logic**: Use `get_available_actions()` or a new `build_event_panel_for_state()` function that reads from `EVENT_STATE_TRANSITIONS` rather than hardcoding button logic in multiple places.

8. **Add enrichment session isolation**: Use unique session IDs for enrichment prompts (e.g., `enrich_session_{uuid}`) instead of shared keys, preventing collision between concurrent enrichment actions.

### Phase 3: Advanced Features (Low Priority)

9. **Add state transition preconditions for downgrades**: Currently, `reconcile_event_state_after_participant_change()` can downgrade state without requiring the actor to have any specific permission. Consider requiring organizer-only downgrade rights for `confirmed` --> `interested`.

10. **Add event-level state machine tests**: Create unit tests for all state transitions, including edge cases like concurrent modifications, empty participant lists, and organizer-only events.

11. **Add a `last_accessed_at` field** to `Event` and use it in the scheduler to auto-archive or clean up very old events.

12. **Document the state machine** with a visual diagram (e.g., Mermaid or Graphviz) in the codebase, keeping it in sync with `EVENT_STATE_TRANSITIONS`.

## 7. Future State Store Design

### 7.1 Proposed Data Structures

```python
class StateStore:
    """Centralized in-memory state management with TTL and locks."""

    _stores: dict[str, GroupState] = {}  # group_id -> GroupState
    _locks: dict[int, asyncio.Lock] = {}  # event_id -> Lock

    async def get_or_create_group_state(self, group_id: int) -> GroupState:
        ...

    async def acquire_event_lock(self, event_id: int) -> asyncio.Lock:
        ...

    async def cleanup_expired_states(self):
        ...

class GroupState:
    """State for a single Telegram group."""

    event_flows: dict[int, EventFlowState]  # event_id -> flow state
    user_views: dict[int, CurrentView]  # user_id -> current view
    enrichment_sessions: dict[int, EnrichmentSession]  # user_id -> session

    async def cleanup_expired(self):
        ...

class EventFlowState:
    """State for an in-progress event creation flow."""

    stage: Literal["description", "type", "date_preset", ...]
    data: EventFlowData
    group_id: int
    created_at: datetime
    last_accessed: datetime
    ttl: timedelta = timedelta(minutes=30)

    def is_expired(self) -> bool:
        return datetime.now() - self.last_accessed > self.ttl

class CurrentView:
    """Tracks which message a user is viewing."""

    event_id: int
    message_id: int
    chat_id: int

class EnrichmentSession:
    """Isolated enrichment session for a user."""

    session_id: str  # UUID
    event_id: int
    action: str
    created_at: datetime
    ttl: timedelta = timedelta(minutes=10)
```

### 7.2 Integration with Existing Code

The StateStore would wrap existing `context.user_data` access:

```python
# Before (scattered across handlers)
flow = context.user_data.get("event_flow", {})
stage = flow.get("stage")
data = flow.get("data", {})

# After (centralized)
flow_state = await state_store.get_event_flow(user_id, event_id)
stage = flow_state.stage
data = flow_state.data
```

### 7.3 Benefits

1. **Type safety**: TypedDict models catch errors at development time
2. **TTL cleanup**: Automatic expiration prevents unbounded growth
3. **Atomic access**: Per-event locks prevent race conditions
4. **Centralized logic**: One place to add new state transitions
5. **Backward compatible**: Gradual migration, no breaking changes

## 8. Recommendations Summary

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| Critical | Consolidate creation flows | Medium | High |
| High | Add TypedDict models | Low | Medium |
| High | Fix confirmed_count race | Low | Medium |
| Medium | Implement unlock transition | Low | Medium |
| Medium | Add TTL to in-memory state | Low | Low |
| Medium | Create StateStore class | High | High |
| Low | Add state machine tests | Medium | Medium |
| Low | Document state machine | Low | Low |

## 9. Next Steps

1. **Immediate**: Consolidate `event_creation.py` and `menus.py` creation flows
2. **Short-term**: Add TypedDict models and TTL cleanup
3. **Mid-term**: Implement StateStore class with per-event locks
4. **Long-term**: Add comprehensive tests and documentation
