# Availability and Constraints Documentation

This document comprehensively covers how user availability and constraints are expressed, used, and managed throughout the Telegram bot codebase.

---

## 1. Where User Availability is Expressed

### Data Models

#### `db/models.py:147-171` — `Constraint` Model
Availability is stored as a constraint type in the `constraints` table:

```python
class Constraint(Base):
    __tablename__ = "constraints"

    constraint_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    target_user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    event_id = Column(BigInteger, ForeignKey("events.event_id"), nullable=False)
    type = Column(String(50), nullable=False)  # "availability" for time slots
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Key points:**
- Availability constraints use `type = "availability"`
- `user_id` represents the user expressing availability
- `event_id` links to the specific event
- The actual time slot is stored in `metadata_dict` of the `Log` table (see `bot/commands/event_details.py:817`)

#### `db/models.py:173-187` — `Log` Model
The `Log` table stores the actual availability slot data in JSON metadata:

```python
class Log(Base):
    __tablename__ = "logs"

    log_id = Column(Integer, primary_key=True)
    event_id = Column(BigInteger, ForeignKey("events.event_id"))
    user_id = Column(BigInteger, ForeignKey("users.user_id"))
    action = Column(String(100), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    metadata_dict = Column("metadata", JSON, default=dict)
```

When a user adds availability, the action is logged as `"availability"` with the slot in `metadata_dict`.

### Command Handlers

#### `bot/commands/event_details.py:743-922` — Availability Management
The primary availability flow is handled in `event_details.py`:

- `_show_availability_options()` (lines 743-761): Shows availability selection menu
- `_show_availability_slots()` (lines 763-820): Displays available time slot buttons
- `_handle_availability_slot()` (lines 822-880): Handles slot selection and stores pending availability
- `_save_availability()` (lines 882-922): Saves the selected slot as a constraint

#### `bot/commands/constraints.py:16-400` — Constraint Commands
The `constraints` command handles all constraint operations including availability:

```python
ALLOWED_CONSTRAINT_TYPES = {"if_joins", "if_attends", "unless_joins"}
```

- `add_availability_slots()` (lines 51-111): Command handler for availability constraint addition
- `_handle_constraint_availability_slot()` (lines 226-285): Handles inline slot selection
- `_save_constraint_availability()` (lines 287-337): Persists availability to database

#### `bot/commands/start.py:41-55` — Direct Availability Access
Users can access availability directly from start command via callback routing.

#### `bot/commands/prefill.py` — Event Draft Availability
Handles availability during event creation flow.

### Service Layer

#### `bot/services/event_lifecycle_service.py:85-92`
Triggers lifecycle events including availability validation during state transitions.

---

## 2. When and Where Availability is Used

### Scheduling and Time Slot Selection

#### `bot/commands/event_details.py:763-820`
When a user wants to express availability:

1. **Initiation**: User clicks "Add Availability" button or uses `/constraints <event_id> availability`
2. **Slot Display**: `_show_availability_slots()` presents a grid of time slots
3. **Selection**: User picks a slot via inline button callback
4. **Pending Storage**: Slot is stored in `context.user_data["pending_availability"]`
5. **Confirmation**: User confirms via inline keyboard
6. **Persistence**: `_save_availability()` stores the constraint in the database

#### `bot/commands/constraints.py:226-337`
Alternative flow through `/constraints` command:

```python
# Lines 313-320: Save availability constraint
session.add(Constraint(
    user_id=user_id,
    event_id=event_id,
    type="availability",
    confidence=1.0
))

# Log the actual slot
session.add(Log(
    event_id=event_id,
    user_id=user_id,
    action="availability",
    metadata={"slot": slot}
))
```

### AI Suggestions

#### `ai/rules.py:13-60` — Availability Checking
The rules engine checks availability for AI-driven suggestions:

```python
def check_availability(self, event: Event, constraints: List | None = None) -> Dict[Any, float]:
    """Check attendee availability constraints and return confidence scores."""
    if constraints and availability:
        return {"slot": confidence, "reason": "Using attendee availability constraints"}
```

#### `ai/core.py:44-55` — Integration with Scheduling
Availability constraints influence AI suggestions:

```python
availability = self.rules_engine.check_availability(event, constraints)
if availability:
    # Select time slot based on attendee availability
    selected_slot = find_optimal_slot(availability)
```

### Event State Transitions

#### `bot/common/deadline_check.py:13-116`
During `confirmed` → `locked` transition:

1. System checks if enough participants have committed
2. Availability constraints help determine if participants are reliable
3. Auto-lock can use availability data to predict attendance

---

## 3. User Constraints (if_joins, unless_joins, availability)

### Data Model

#### `db/models.py:147-171` — Constraint Table
All constraint types share the same model:

| Constraint Type | Description | Storage |
|-----------------|-------------|---------|
| `if_joins` | "I'll join if target joins" | `type="if_joins"`, `target_user_id` populated |
| `unless_joins` | "I won't join if target joins" | `type="unless_joins"`, `target_user_id` populated |
| `if_attends` | "I'll attend if target attends" | `type="if_attends"`, `target_user_id` populated |
| `availability` | "I'm available at these slots" | `type="availability"`, slot in `Log.metadata` |

#### `db/models.py:102-104` — Event Constraints Relationship
```python
constraints = relationship(
    "Constraint", back_populates="event", cascade="all, delete-orphan"
)
```

### Command Handlers

#### `bot/commands/constraints.py:16-400`

**Constraint Types Allowed (line 16):**
```python
ALLOWED_CONSTRAINT_TYPES = {"if_joins", "if_attends", "unless_joins"}
```

**Alias Mapping (lines 18-21):**
```python
ALIASES = {
    "if_join": "if_joins",
    "unless_join": "unless_joins"
}
```

**Usage Patterns:**

1. **Add constraint** (lines 30-70):
   ```python
   if action == "if_joins":
       # Add if_joins constraint
   elif action == "unless_joins":
       # Add unless_joins constraint
   elif action == "availability":
       # Add availability slots
   ```

2. **View constraints** (lines 72-97):
   - Shows all constraints for an event
   - Displays both target-based and availability constraints

3. **Remove constraint** (lines 99-141):
   - Deletes constraint by ID

**Availability-specific handlers (lines 226-337):**
- `_handle_constraint_availability_slot()`: Inline slot selection
- `_save_constraint_availability()`: Persists to database

### Constraint Display

#### `bot/commands/event_details.py:531-542`
Shows constraint buttons in event detail keyboard:

```python
"🔗 If Joins", callback_data=f"constraint_add_if_joins_{event_id}"
callback_data=f"constraint_add_unless_joins_{event_id}",
```

#### `bot/commands/event_details.py:640-643`
Constraint type labels:
```python
constraint_types = {
    "if_joins": "joins if target joins",
    "unless_joins": "won't join if target joins",
    "if_attends": "attends if target attends"
}
```

### Constraint Usage in Business Logic

#### `bot/commands/constraints.py:80-111`
When displaying constraints:

```python
if constraint.type == "if_joins":
    constraint_lines.append(f"- User {c.user_id} joins if {c.target_user_id} joins")
elif constraint.type == "unless_joins":
    constraint_lines.append(f"- User {c.user_id} won't join if {c.target_user_id} joins")
elif constraint.type == "availability":
    availability_lines.append(f"- User {c.user_id}: available at {slot}")
```

#### `bot/handlers/mentions.py:1158`
Mentions validation:
```python
allowed = {"if_joins", "if_attends", "unless_joins"}
```

---

## 4. How Deadline is Expressed

### Database Fields

#### `db/models.py:82-90` — Event Deadline Fields

```python
class Event(Base):
    scheduled_time = Column(DateTime)        # When event is scheduled
    commit_by = Column(DateTime)            # Deadline for commitment (lines 82-82)
    duration_minutes = Column(Integer, default=120)  # Event duration

    # PRD v2: Explicit threshold fields
    min_participants = Column(Integer, default=2)      # Absolute minimum to run
    target_participants = Column(Integer, default=6)   # Desired count
    collapse_at = Column(DateTime)                    # Auto-cancel deadline (lines 89-89)
    lock_deadline = Column(DateTime)                  # Cutoff for attendance changes (lines 90-90)
```

### Deadline Computation

#### `bot/commands/finalize.py:75-80`
Default commit-by deadline calculation:

```python
def compute_commit_by_time(scheduled_time: datetime | None) -> datetime | None:
    """Derive default commit-by deadline from scheduled time."""
    if scheduled_time is None:
        return None
    return scheduled_time - timedelta(hours=DEFAULT_COMMIT_BY_OFFSET_HOURS)
```

**Default:** Commit-by = scheduled_time - 12 hours

### Deadline Fields Purpose

| Field | Purpose | When Set | Used For |
|-------|---------|----------|----------|
| `scheduled_time` | When event should happen | Event creation | Scheduling, conflict detection |
| `commit_by` | Deadline for users to commit | Event creation (or manual override) | Auto-lock, confirmation催促 |
| `collapse_at` | Auto-cancel if under threshold | Event creation | Threshold auto-cancel |
| `lock_deadline` | Cutoff for attendance changes | Event creation | Prevent last-minute changes |

### How Deadlines are Set/Changed

#### Setting Deadlines

**During Event Creation** (`bot/commands/finalize.py:464`):
```python
commit_by = compute_commit_by_time(candidate_time)
```

**Manual Override:**
- Use `/modify <event_id>` command
- LLM can infer deadline changes from message text

#### Changing Deadlines

**Event Modification Flow:**
1. User invokes `/modify <event_id>`
2. Bot shows current event details including deadline
3. User provides new values or uses LLM suggestions
4. `apply_final_stage_patch()` updates fields (lines 193-422 in `finalize.py`)

**LLM Patch Support:**
```python
# Can infer commit_by from message like "move deadline to next Tuesday"
patch = await llm.infer_event_draft_patch(flow_data, message_text)
```

---

## 5. How Users See and Change Deadlines

### Viewing Deadlines

#### `bot/common/event_formatters.py:171-200`
Deadline formatting:

```python
def format_commit_by(commit_by, include_context: bool = True) -> str:
    """Format commit-by deadline for display."""
    if not commit_by:
        return "TBD"

    now = datetime.utcnow()
    diff = commit_by - now

    if diff.total_seconds() <= 0:
        return "⏳ Deadline passed"
    elif diff.total_seconds() < 3600:  # Less than 1 hour
        return f"⏳ {int(diff.total_seconds() / 60)}m remaining"
    else:
        return f"📅 {commit_by.strftime('%Y-%m-%d %H:%M')} ({int(diff.total_seconds() / 3600)}h)"
```

#### Display Locations

1. **Event Details** (`bot/commands/event_details.py`):
   - Shows commit-by in event summary
   - Shows lock status (`locked_at` field)

2. **DM Notifications** (`bot/commands/finalize.py:2030-2079`):
   ```python
   commit_by_text = format_commit_by(commit_by)
   f"Commit-By: {commit_by_text}\n"
   ```

3. **Status Command** (`bot/commands/status.py`):
   - Shows deadline remaining time
   - Shows locked state

#### `bot/common/deadline_check.py:118-158`
Check deadline status for specific event:

```python
async def check_deadline_status(event_id: int) -> Optional[dict]:
    """Get deadline status for a specific event."""
    return {
        "event_id": int(event.event_id),
        "state": state,
        "commit_by": commit_by.isoformat(),
        "deadline_reached": deadline_reached,
        "time_remaining_seconds": int(time_remaining.total_seconds()),
        "is_locked": is_locked,
        "locked_at": locked_at.isoformat(),
    }
```

### Changing Deadlines

#### Command-Based Modification

**`/modify <event_id>`** (not shown in files but implied):

1. User invokes modify command
2. Bot presents current deadline
3. User provides new deadline value
4. LLM parses and validates
5. Event updated in database

#### LLM-Inferred Changes

**`bot/commands/finalize.py:200-204`**:
```python
patch = await llm.infer_event_draft_patch(flow_data, message_text)
```

Users can send messages like:
- "Change deadline to tomorrow 5pm"
- "Extend commit-by 24 hours"
- "Move deadline earlier"

LLM parses these and returns a patch that updates `commit_by`.

#### Event States and Deadlines

| State | Can Change Deadline? | Notes |
|-------|---------------------|-------|
| `proposed` | ✅ Yes | Event not yet locked |
| `interested` | ✅ Yes | Still gathering interest |
| `confirmed` | ⚠️ Context-dependent | May auto-lock at deadline |
| `locked` | ❌ No | Changes frozen |
| `completed` | ❌ No | Event finished |
| `cancelled` | ❌ No | Event cancelled |

### Deadline Auto-Lock Mechanism

#### `bot/common/deadline_check.py:13-48`
System auto-checks for expired deadlines:

```python
async def check_and_lock_expired_events(bot=None) -> list[dict]:
    """Check for events that have reached their deadline and auto-lock if threshold is met."""
    events_to_check = (
        Event.state == "confirmed",
        Event.commit_by.isnot(None),
        Event.commit_by <= now,
        Event.locked_at.is_(None),
    )
```

**Auto-lock conditions:**
1. Event state is `confirmed`
2. `commit_by` time has passed
3. Event is not already locked
4. Confirmed participant count ≥ `min_participants`

If all conditions met, event auto-transitions to `locked` state.

---

## Summary

### Availability Flow
1. User expresses availability via `/constraints <event_id> availability <slot>` or inline buttons
2. Bot validates and stores as `Constraint` with `type="availability"`
3. Actual slot stored in `Log.metadata["slot"]`
4. AI uses availability to suggest optimal time slots
5. Availability displayed in event details and DMs

### Constraints Flow
1. User adds constraint via inline button or `/constraints` command
2. Constraint stored in `constraints` table with appropriate `type`
3. Target user ID stored for if_joins/unless_joins constraints
4. Constraints displayed in event details
5. AI considers constraints when suggesting schedules

### Deadlines Flow
1. `commit_by` set during event creation (default: scheduled_time - 12h)
2. Users see deadline in event details and DMs
3. Can be modified via `/modify` with LLM assistance
4. System auto-checks and locks events when deadline passed and threshold met

### Key Files Reference

| Functionality | Files |
|--------------|-------|
| Data Models | `db/models.py:147-171` (Constraint), `db/models.py:68-121` (Event deadline fields) |
| Command Handlers | `bot/commands/constraints.py`, `bot/commands/event_details.py:743-922` |
| Deadline Checking | `bot/common/deadline_check.py` |
| Deadline Computation | `bot/commands/finalize.py:75-80`, `bot/commands/flow/__init__.py:108-112` |
| Formatting | `bot/common/event_formatters.py:171-200` |
| AI Integration | `ai/rules.py:13-60`, `ai/core.py:44-55` |

---

*Generated for telegram-bot codebase. Last updated: 2026-04-16*
