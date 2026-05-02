# Coordination Engine — v3.5 Rebuild Specification

**Document Type:** Product & Engineering Specification
**Status:** Active — For Immediate Implementation
**Addresses:** UX Fragmentation · LLM Inconsistency · DB Rigidity · Engagement Vacuum
**Philosophy:** `docs/v3/WHY_VERSION_3.md` — Relational emergence, not computational governance
**Intended Readers:** Engineers, designers, AI agents building this system

---

> **North Star**
> The value is not knowing more about people. The value is shaping how people relate to what they already know is forming. Every decision in this document is derived from that premise.

---

## Table of Contents

1. [Diagnosis: What Is Actually Broken](#0-diagnosis)
2. [Issue 1 — UX: Single Entry Point `/events`](#1-ux-redesign)
3. [Issue 2 — Database: Keep PostgreSQL, Remove Brittleness](#2-database)
4. [Issue 3 — LLM: Structured Function Dispatch](#3-llm-layer)
5. [Issue 4 — Engagement: Making Events Alive](#4-engagement)
6. [Implementation Order and File Map](#5-implementation-order)
7. [Additional Engineering Considerations](#6-additional-considerations)
8. [Design Standards](#7-design-standards)
9. [Testing Matrix](#8-testing-matrix)

---

## 0. Diagnosis

Before prescribing fixes, every engineer and designer must internalize the root failure modes. They do not exist independently — they compound each other into a system that cannot be tested, felt, or trusted.

| Failure Mode | Symptom | Root Cause |
|---|---|---|
| **UX Fragmentation** | `/status`, `/events`, `/event_details`, `/organize_event`, `/organize_event_flexible`, `/plan`, `/join`, `/confirm`, `/lock`, `/constraints` — twelve commands for three concerns | No progressive disclosure. User must know the right command before knowing what they want. |
| **LLM Inconsistency** | Bot ignores simple requests, returns nonsense, contradicts itself across turns | Every prompt is hand-crafted. No canonical action registry. Regex fallbacks contradict LLM output. No output contract enforcement before dispatch. Temperature and token budgets are wrong. |
| **DB Rigidity** | Schema migrations needed for every new event property. LLM writes crash on edge-case enum values. Member contributions are lost in unattributable JSON blobs. | `CHECK` constraints on semantic strings. `planning_prefs` JSONB as a dumping ground. No `event_enrichments` table. No queryable lineage. |
| **Engagement Vacuum** | Events form silently. No group-visible social presence. Memory never connects to the next cycle. Bot feels hollow. | No live card during formation. Memory is an artifact at the end, not a driver at the beginning. `/plan` and memory are orphaned from the main creation path. |

**Why they compound:**
A fragmented UX makes users rely on LLM interpretation. A broken LLM makes the bot feel unreliable. An unreliable bot discourages multi-event testing, so gravity, memory, and lineage never accumulate. No accumulation means the philosophical vision is untestable and appears to not work. This is a loop. Fix UX first — everything else unlocks.

---

## 1. UX Redesign — Single Entry Point: `/events`

### 1.1 The Problem in Code

Current `bot/commands/` has approximately 22 command handlers representing 3 concerns: viewing events, acting on events, and creating events. The branching happens before the user knows what they want to do, which means:

- Users must memorize command names
- LLM is overloaded as a command router for confused users
- No single mental model exists for the interaction surface

The goal: collapse everything into one command. `/events` is the only surface users need. Everything branches from it through progressive disclosure.

---

### 1.2 The New Interaction Model

**Three levels. One entry point. No event IDs in user's head.**

```
/events
  └─ Level 1: Event List (all relevant events, tappable rows)
       └─ [tap event] Level 2: Event Panel (full card + context-aware action buttons)
             ├─ [Enrich] Level 3a: Enrich Sub-Menu
             ├─ [Constraint] Level 3b: Constraint Sub-Menu
             └─ [Create New Event] → Memory-First Creation Flow
```

---

### 1.3 Level 1 — The Event List

**Trigger:** User types `/events` or taps it from main menu.

**Response:** A list of events relevant to this user in this context. Each event is a tappable button. No event IDs visible in prose. No commands to remember.

**Each row shows:**
- Event description (first 5 words)
- Date or "TBD"
- State: `forming` / `locked` / `done`
- Member's current status relative to this event: `invited` / `joined` / `confirmed` / `not involved`

**Context-aware filtering:**
- In a group chat: shows events for that group only
- In DM: shows all events across groups the user belongs to
- Sort priority: events where user has a pending action appear first (invited but not joined, joined but gravity threshold not yet met, etc.)
- Limit: 10 events per page, with Next/Previous pagination

**Always visible at bottom of list:** `[ + Create New Event ]`

**Implementation note:** `bot/commands/events.py` is the entry point. The current implementation already lists events but lacks the tappable-button-per-event pattern and the Create flow integration. These must be added.

---

### 1.4 Level 2 — Event Panel

**Trigger:** User taps an event row in Level 1.

**Response:** An inline keyboard update (the list message is edited in place — no new message). The panel replaces the list for that event.

**Panel sections:**

```
[Event Header]
  - Description
  - Type (social / sports / work)
  - Time: fixed datetime OR "Time forming..." (if flexible/TBD)
  - State: forming / confirmed / locked / done
  - Participant count vs minimum: "3 / 5 needed"
  - Deadline: "Deadline in 2 days" OR none

[Lineage Fragment — shown quietly below header if exists]
  ↩ From last time: "We stayed until midnight, completely unplanned."

[Active Hashtags — if any have been contributed]
  #hiking #weekend #trail

[Action Buttons — shown conditionally, see table below]
```

**Context-aware action button rules:**

| User Status | Event State | Button Shown | Notes |
|---|---|---|---|
| Invited, not joined | proposed / interested | **Join** | Replaces `/join` |
| Joined | proposed / interested / confirmed | **Relinquish** | Replaces `/cancel`. Non-dramatic language by design. |
| Joined | any forming state | **Enrich** | Opens Level 3a |
| Joined | any forming state | **Constraint** | Opens Level 3b |
| Joined AND count >= min_participants | forming | **Commit** | Replaces `/confirm`. Only shown when gravity threshold is met. |
| Organizer AND count >= min_participants | forming | **Lock** | Replaces `/lock` |
| Organizer | any | **Edit Event** | Opens edit flow |
| Any user, any event | any | **← Events** | Returns to Level 1 |

**Critical design rule:** Never show a button if the action would fail silently. If the event is locked and join is not possible, do not show a disabled Join button — do not show it at all. The button surface accurately reflects what is possible right now.

---

### 1.5 Level 3a — Enrich Sub-Menu

Enrich is how a member contributes meaning to a forming event. These contributions do not post publicly immediately — they accumulate and surface at the right moment.

**Options shown as buttons:**

- **Add an idea** — Free text input. Stored as a planning fragment. Visible only to organizer until event locks. Maximum 300 characters.
- **Add a hashtag** — Up to 3 hashtags per member per event. Prior hashtags from previous events of this type are offered as quick-tap suggestions. Hashtags from multiple members accumulate and appear on the live card after 2+ members have contributed them (with a short delay).
- **Add a memory** — Available only after event completes. Free text, max 200 words. Stored as a mosaic fragment. Private until mosaic assembles.
- **My contributions** — Shows what the user has already contributed for this event. Read-only view.

**Implementation note:** All content written here goes to the `event_enrichments` table (new — see Section 2). The LLM must not touch these contributions. They are the human voice. Zero LLM involvement in enrichment storage or display.

---

### 1.6 Level 3b — Constraint Sub-Menu

Constraint is how a member communicates conditional participation. This replaces `/constraints` as a standalone command. It is only reachable through the event panel.

**Options:**

- **I'll join if [person] joins** — `if_joins` type. Taps a list of group members or types a @username.
- **I'll join only if [person] attends** — `if_attends` type. Post-join confirmation dependency.
- **I won't join if [person] joins** — `unless_joins` type.
- **My availability** — Time slot grid. For flexible-schedule events only.
- **View / remove my constraints** — Shows current constraints with delete option.

**Constraint privacy rule (non-negotiable):** Constraints are always DM-only and private to the user and organizer. They never appear on the live card in the group. They never appear in the event panel's public view. This was correct in v2 and must be preserved in v3.

---

### 1.7 Memory-First Event Creation Flow

Event creation is reached through `/events` via the `[ + Create New Event ]` button. This collapses `/organize_event`, `/organize_event_flexible`, and `/plan` into a single flow that enforces the memory-first principle.

**Creation flow steps:**

1. User taps `[ + Create New Event ]` from the event list
2. System checks: does this group have prior completed events of any type?
   - **If yes:** Surface the most recent Fragment Mosaic for that event type inline. One or two sentences from a prior event, quoted. User sees what was remembered last time before filling in anything.
   - **If no:** Skip to step 3.
3. System asks: **What kind of event?** — `[ Social ]` `[ Sports ]` `[ Work ]` `[ Other ]` (buttons)
4. System asks: **When?** — `[ Fixed time ]` `[ Flexible ]` `[ TBD ]` (buttons)
5. System asks: **Describe the event in one sentence** (free text input). LLM may assist in generating a draft description from group context if available — but the user's text is always the primary source and is shown for confirmation.
6. System presents a draft card: description, type, time, suggested min participants. User confirms or edits inline.
7. On confirm: event is created, Live Card posts to group, `/events` list updates, organizer is auto-joined as participant.

**Why memory-first is non-negotiable:**
From `WHY_VERSION_3.md`: *"Memory is a coordination input, not a coordination output."* If a user can bypass prior memories by choosing a create path, then memory is still an artifact — it arrives too late to shape what forms next. The creation flow must surface prior memory even if the user taps "skip" — showing it changes the affordance.

---

### 1.8 Commands to Deprecate and Remove

**Deprecation cycle:** Commands below respond with `"Use /events instead"` for one release cycle, then handlers are removed from `main.py`.

| Command | Replaced By |
|---|---|
| `/status` | Event panel state section |
| `/event_details` | Event panel |
| `/event` (standalone duplicate) | `/events` + panel |
| `/organize_event` | `/events` creation flow |
| `/organize_event_flexible` | Same — flexible mode is a panel option |
| `/plan` | Merged into `/events` creation flow |
| `/join` | Join button in panel |
| `/confirm` | Commit button in panel |
| `/lock` | Lock button in panel |
| `/constraints` | Constraint sub-menu in panel |

**Commands to keep:**

| Command | Purpose |
|---|---|
| `/events` | Primary entry point |
| `/start` | Welcome + quick navigation (keep main menu buttons) |
| `/about` | Bot description |
| `/my_history` | Personal attendance mirror (DM only) |
| `/my_groups` | Group management |

---

## 2. Database — Keep PostgreSQL, Remove the Brittleness

### 2.1 Why Not Switch to a Document Database

This question must be addressed directly because it arises every time relational schema pain surfaces.

A document database (MongoDB, Firestore, DynamoDB) would trade the current problems for different ones:

| Current Relational Pain | Document DB Equivalent |
|---|---|
| `CHECK` constraints on enum strings break when LLM outputs edge-case values | No schema = everything breaks silently at query time, not at write time |
| `action` strings in `logs.CHECK` cannot be extended without migration | No FK enforcement = referential integrity must be written manually |
| `constraints.type` regex in `CHECK` is opaque and hard to debug | Relationships between events, participants, constraints must be denormalized |
| `planning_prefs` JSONB is untyped — LLM puts anything there | Aggregate queries require MapReduce or application-level joins |

The relational model is correct for this domain. Events have participants. Participants have statuses. Constraints link users to events with conditions. These are structural relationships, not document hierarchies. **PostgreSQL with JSONB for flexible fields gives the best of both:** structural enforcement where structure matters, flexibility where it does not.

The problem is not the paradigm. The problem is specific hostile patterns that can be fixed surgically.

---

### 2.2 Change 1 — Remove CHECK Constraints from Semantic Strings

The most hostile pattern: using SQL `CHECK` to enforce semantic values that are subject to LLM output variation.

**Remove from `db/schema.sql` and `db/models.py`:**

```sql
-- REMOVE: constraints.type CHECK
type VARCHAR(50) NOT NULL CHECK (
  type IN ('if_joins', 'if_attends', 'unless_joins')
  OR type LIKE 'available:%'
)

-- REPLACE WITH:
type VARCHAR(50) NOT NULL
-- Validation moves to application layer in bot/services/participant_service.py
```

```sql
-- REMOVE: logs.action CHECK
action VARCHAR(100) NOT NULL CHECK (action IN ('organize_event', 'join', 'confirm', 'cancel', 'suggest_time', 'nudge', 'constraint_update'))

-- REPLACE WITH:
action VARCHAR(100) NOT NULL
```

```sql
-- REMOVE: groups.group_type CHECK
group_type VARCHAR(50) DEFAULT 'casual' CHECK (group_type IN ('casual', 'gathering', 'tournament'))

-- REPLACE WITH:
group_type VARCHAR(50) DEFAULT 'casual'
```

**Application-layer canonical sets (write once, use everywhere):**

```python
# bot/services/participant_service.py
VALID_CONSTRAINT_TYPES = {"if_joins", "if_attends", "unless_joins"}
VALID_LOG_ACTIONS = {
    "organize_event", "join", "confirm", "cancel", "relinquish",
    "enrich_idea", "enrich_hashtag", "enrich_memory",
    "constraint_update", "lock", "complete", "collapse"
}

def validate_constraint_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in VALID_CONSTRAINT_TYPES:
        raise ValueError(f"Unknown constraint type: {normalized}")
    return normalized
```

When the LLM outputs a slightly different string, the service layer normalizes it or raises a `ValueError` with a clear error — not a silent crash deep in a database write.

---

### 2.3 Change 2 — Add `event_enrichments` Table

Currently, member contributions during formation are shoved into `planning_prefs` (a JSON blob on the Event). This makes them invisible to queries, unattributable, and impossible to surface selectively.

**Add to `db/schema.sql`:**

```sql
CREATE TABLE IF NOT EXISTS event_enrichments (
    enrichment_id   BIGSERIAL PRIMARY KEY,
    event_id        BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    enrichment_type VARCHAR(30) NOT NULL,
    -- Values: 'idea', 'hashtag', 'memory'
    content         TEXT NOT NULL,
    is_public       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_enrichments_event ON event_enrichments(event_id);
CREATE INDEX IF NOT EXISTS idx_enrichments_type ON event_enrichments(enrichment_type);
CREATE INDEX IF NOT EXISTS idx_enrichments_public ON event_enrichments(is_public);
```

**Add to `db/models.py`:**

```python
class EventEnrichment(Base):
    __tablename__ = "event_enrichments"

    enrichment_id    = Column(BigInteger, primary_key=True)
    event_id         = Column(BigInteger, ForeignKey("events.event_id", ondelete="CASCADE"))
    telegram_user_id = Column(BigInteger, nullable=False)
    enrichment_type  = Column(String(30), nullable=False)  # 'idea' | 'hashtag' | 'memory'
    content          = Column(Text, nullable=False)
    is_public        = Column(Boolean, default=False)
    created_at       = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="enrichments")
```

**Benefits:**
- Ideas, hashtags, and memories are now queryable by type
- Organizer can query "show me all ideas for event X" directly
- Hashtag surfacing for live cards becomes a simple `SELECT`
- Memory mosaic assembly queries this table, not a JSON array inside `event_memories`
- `is_public` flag controls when hashtags surface on the live card (not immediate)

**Boundary rule (enforced in service layer, not schema):** All member-contributed content (ideas, hashtags, memories) goes to `event_enrichments`. Organizer-level draft storage during the creation flow stays in `planning_prefs`. This boundary prevents the JSON blob from growing again.

---

### 2.4 Change 3 — Add `event_lineage` Join Table

Currently, event lineage is tracked in `event_memories.lineage_event_ids` as a JSONB array of integers. This is not queryable without parsing JSON.

**Add to `db/schema.sql`:**

```sql
CREATE TABLE IF NOT EXISTS event_lineage (
    parent_event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    child_event_id  BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    relation_type   VARCHAR(30) DEFAULT 'same_type',
    linked_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (parent_event_id, child_event_id)
);

CREATE INDEX IF NOT EXISTS idx_lineage_parent ON event_lineage(parent_event_id);
CREATE INDEX IF NOT EXISTS idx_lineage_child ON event_lineage(child_event_id);
```

This enables: "find all events descended from this one", "find the last event of this type", "show lineage chain" — without JSON parsing.

**When to write a lineage row:** After a new event is created in the same group with the same `event_type` as a prior completed event, write: `(parent=prior_event_id, child=new_event_id, relation_type='same_type')`. This happens in `EventMemoryService` after mosaic assembly.

---

### 2.5 Change 4 — Add `event_live_cards` Table (from v3.3 design)

The v3.3 `PHASE1_LIVE_CARDS.md` design for `EventLiveCard` is architecturally correct. The model belongs in `db/models.py` and must be wired to the engagement layer. If not already present, add:

```sql
CREATE TABLE IF NOT EXISTS event_live_cards (
    id               BIGSERIAL PRIMARY KEY,
    event_id         BIGINT REFERENCES events(event_id) ON DELETE CASCADE UNIQUE,
    message_id       BIGINT NOT NULL,
    chat_id          BIGINT NOT NULL,
    participant_count INTEGER DEFAULT 0,
    confirmed_count  INTEGER DEFAULT 0,
    reaction_counts  JSONB DEFAULT '{}',
    last_updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### 2.6 Change 5 — Add `group_settings` Table

Store per-group configuration that currently doesn't exist anywhere:

```sql
CREATE TABLE IF NOT EXISTS group_settings (
    group_id                   INTEGER REFERENCES groups(group_id) ON DELETE CASCADE PRIMARY KEY,
    enable_live_cards          BOOLEAN DEFAULT TRUE,
    group_timezone             VARCHAR(50) DEFAULT 'UTC',
    max_hashtags_per_event     INTEGER DEFAULT 5,
    lineage_selection_method   VARCHAR(10) DEFAULT 'fixed',
    -- 'fixed' = most recent fragment | 'llm' = context-aware (use only if LLM is reliable)
    created_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

This also solves the timezone UX gap described in Section 6.

---

### 2.7 What to Keep Unchanged

Do not migrate, alter, or second-guess:

- `events` table core structure — it is correct and well-indexed
- `event_participants` with `participant_status` / `participant_role` enums — this is the right design
- `EventStateTransition` audit trail — valuable and well-implemented
- `EventMemory.fragments` as JSONB — fragments are variable-length; JSONB is correct here
- `IdempotencyKey` table — essential for Telegram callback protection
- `event_waitlist` table — waitlist logic is correct

---

### 2.8 Migration Execution Order

Schema changes require two coordinated steps. **The migration must run before the code deploys.**

1. Remove `CHECK` constraints from `constraints.type`, `logs.action`, `groups.group_type`
2. Add `event_enrichments` table
3. Add `event_lineage` table
4. Add `event_live_cards` table (if not already present)
5. Add `group_settings` table
6. Deploy updated service layer with application-level validation
7. Add `EventEnrichment`, `EventLineage`, `EventLiveCard`, `GroupSettings` models to `db/models.py`

---

## 3. LLM Layer — Consistent, Scalable, Bounded

The LLM is not the problem. The way the bot constructs prompts, routes results, and falls back is the problem. Three root causes produce all observed inconsistency.

### 3.1 Root Cause Analysis

**Root Cause 1 — Every prompt is a snowflake**

`ai/llm.py` contains 6+ distinct prompting styles, each hand-written with different formatting, different JSON schema expectations, different validation logic, and different fallback behavior. The fallbacks use regex that contradicts the JSON the LLM was asked to produce. There is no single contract between the bot and the LLM.

The most revealing symptom: `infer_group_mention_action()` asks for `action_type` in JSON, then the except block does regex matching on raw text. If the LLM returns `{"action_type": "create_event"}` (slightly wrong key value), JSON validation rejects it, the regex runs, and the regex interprets the same message differently. Two conflicting interpreters exist. Neither is authoritative.

**Root Cause 2 — No function registry**

The LLM is given a list of string action names and asked to pick one. It has no idea what those actions do, what their preconditions are, or what parameters they require. It is guessing from names. The allowed action list in `infer_group_mention_action` includes actions that map to completely different commands, services, and validation requirements. The LLM cannot know this from names alone.

**Root Cause 3 — No output contract enforcement before dispatch**

When the LLM returns JSON, the code calls `json.loads()` directly. If the parse succeeds, fields are accessed with `.get()` with silent defaults. There is no step that validates: *"is this output structurally valid for the action type claimed?"* A response of `{"action_type": "join", "event_id": null}` will be dispatched to the join handler with no `event_id`, which fails downstream in a confusing and untraceable way.

**Root Cause 4 — Wrong temperature and token budgets**

All `_call_llm()` calls use `temperature=0.3` and `max_tokens=800` as defaults. For structured output (action routing, draft extraction), temperature should be `0.1`. For natural language responses, `0.4`. The compromise `0.3` produces neither reliable structure nor natural language. The token budgets are similarly misconfigured: action routing needs ~200 tokens; using 800 wastes context and sometimes causes the model to over-elaborate in JSON fields.

---

### 3.2 The Scalable Solution: Canonical Action Registry + Structured Dispatch

**Create `ai/actions.py` — single source of truth for all dispatchable actions:**

```python
# ai/actions.py

ACTIONS = {
    "view_events": {
        "description": "User wants to see their list of events",
        "required_params": [],
        "optional_params": ["group_id"],
    },
    "view_event_panel": {
        "description": "User wants to see details or act on a specific event",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "join_event": {
        "description": "User wants to join a specific event they were invited to",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "relinquish_event": {
        "description": "User wants to leave or withdraw from an event they joined",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "commit_event": {
        "description": "User wants to confirm/commit to an event that has reached its minimum",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "lock_event": {
        "description": "Organizer wants to lock an event (finalize attendance)",
        "required_params": ["event_id"],
        "optional_params": [],
    },
    "create_event": {
        "description": "User wants to organize, plan, or create a new event. Use when message expresses intent to gather, meet, or do something together.",
        "required_params": [],
        "optional_params": ["description", "event_type", "scheduled_time"],
    },
    "add_constraint": {
        "description": "User wants to express a conditional participation constraint (if X joins, unless Y comes, etc.)",
        "required_params": ["event_id", "constraint_type", "target_username"],
        "optional_params": [],
    },
    "suggest_time": {
        "description": "User wants to suggest or negotiate a time for an event",
        "required_params": ["event_id"],
        "optional_params": ["suggested_time"],
    },
    "opinion": {
        "description": "User is asking a general question, chatting, or the intent is unclear — no event action needed",
        "required_params": [],
        "optional_params": ["assistant_response"],
    },
}

# Mapping from action name to the handler module it dispatches to
ACTION_HANDLERS = {
    "view_events":      "bot.commands.events",
    "view_event_panel": "bot.handlers.event_flow",
    "join_event":       "bot.handlers.event_flow",
    "relinquish_event": "bot.handlers.event_flow",
    "commit_event":     "bot.handlers.event_flow",
    "lock_event":       "bot.handlers.event_flow",
    "create_event":     "bot.commands.events",
    "add_constraint":   "bot.handlers.event_flow",
    "suggest_time":     "bot.handlers.event_flow",
    "opinion":          "bot.handlers.mentions",
}
```

The key change: actions now have descriptions the LLM can reason about, not just names it must guess from. The registry is the contract.

---

### 3.3 Single Structured Prompt for Action Routing

Replace all individual `infer_*` methods in `llm.py` with one method for action routing:

```python
async def infer_action(
    self,
    text: str,
    history: list[dict],
    context: dict,
) -> dict:
    """
    Single entry point for all mention-based action inference.
    Uses action registry. Returns validated ActionResult.
    """
    from ai.actions import ACTIONS
    from ai.validator import validate_action_result

    # Build compact schema string for prompt injection
    schema_lines = []
    for name, meta in ACTIONS.items():
        req = ", ".join(meta["required_params"]) or "none"
        schema_lines.append(f'  "{name}": {meta["description"]} | required: [{req}]')
    schema_str = "\n".join(schema_lines)

    # Trim history to token budget (≈ 800 tokens for context)
    trimmed_history = self._trim_to_token_budget(history, budget=800)

    prompt = f"""You are a Telegram group coordination assistant.

Available actions:
{schema_str}

Group context:
- Active events: {context.get('active_events', [])}
- User's joined events: {context.get('user_events', [])}
- Recent chat (last 5 messages): {trimmed_history[-5:]}

User message: {text}

Select the best matching action. Return ONLY this JSON object:
{{
  "action": "<action_name from registry above>",
  "params": {{ <required and optional params, omit if not applicable> }},
  "confidence": <0.0 to 1.0>,
  "assistant_response": "<brief helpful message to show the user>"
}}

If the intent is unclear or no action matches, use "opinion".
If a required param like event_id is missing, set it to null — do not guess.
"""

    try:
        response = await self._call_llm(
            prompt,
            max_tokens=250,       # action routing needs very few tokens
            temperature=0.1,      # structured output: low temperature
            system=MEDIATOR_SYSTEM,
        )
        result = json.loads(response)
        validation = validate_action_result(result, ACTIONS)

        if not validation.valid:
            if validation.recoverable:
                # Missing required params — ask user
                return {
                    "action": "opinion",
                    "params": {},
                    "confidence": 0.0,
                    "assistant_response": validation.recovery_prompt,
                }
            else:
                raise ValueError(validation.reason)

        return result

    except Exception as e:
        logger.error("LLM action inference failed: %s", e)
        return {
            "action": "opinion",
            "params": {},
            "confidence": 0.0,
            "assistant_response": "I had trouble understanding that. Use /events to see what's happening.",
        }
```

---

### 3.4 Create `ai/validator.py`

```python
# ai/validator.py
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    valid: bool
    reason: Optional[str] = None
    recoverable: bool = False
    missing_params: list = None
    recovery_prompt: Optional[str] = None


def validate_action_result(result: dict, registry: dict) -> ValidationResult:
    if not isinstance(result, dict):
        return ValidationResult(valid=False, reason="Result is not a dict")

    action = result.get("action")
    if not action or action not in registry:
        return ValidationResult(valid=False, reason=f"Unknown action: {action}")

    required = registry[action]["required_params"]
    params = result.get("params") or {}
    missing = [p for p in required if not params.get(p)]

    if missing:
        recovery = (
            f"Which event are you referring to? Here are your active events:"
            if "event_id" in missing
            else f"I need a bit more info: {', '.join(missing)}"
        )
        return ValidationResult(
            valid=False,
            reason=f"Missing required params: {missing}",
            recoverable=True,
            missing_params=missing,
            recovery_prompt=recovery,
        )

    return ValidationResult(valid=True)
```

---

### 3.5 Eliminate All Regex Fallbacks

Every regex fallback in `llm.py` is a parallel interpretation system that conflicts with the LLM output. The long regex fallback in `infer_group_mention_action` (~80 lines) must be removed entirely. The only fallback allowed anywhere in the LLM layer is the generic opinion fallback shown in Section 3.3.

The philosophy: when the LLM fails, ask the user to clarify. This is always better than a silently wrong action. Users tolerate "I didn't quite get that — use /events" far better than they tolerate a wrong action being executed.

---

### 3.6 Event Draft Extraction — Retained but Simplified

`infer_event_draft_from_context()` is doing two jobs: inferring event fields AND inferring constraints from chat history. Split these:

- Keep `infer_event_draft_from_context()` for field extraction only
- Constraints inferred from chat context go through `infer_action()` → `add_constraint` action, not auto-added to draft

The draft extraction prompt is acceptable in structure but has problems:
1. `temperature=0.3` → change to `0.1`
2. `max_tokens` defaulting to 1200 via `_call_llm_large` → acceptable for draft extraction; keep it
3. The fallback returns hardcoded `"@all"` in invitees → remove this; return empty list instead

---

### 3.7 Fragment Mosaic LLM Constraint — Strictly Enforced

From `WHY_VERSION_3.md` Section 5: *"The LLM may arrange fragments for readability. It may not add words that were not in the fragments."*

This is not a prompt guideline. It is a system constraint. The mosaic assembly prompt must be:

```python
async def assemble_fragment_mosaic(self, fragments: list[str]) -> list[str]:
    """
    Orders fragments for readability only.
    Does NOT synthesize, summarize, label, or add words.
    Returns the same fragments in a different order.
    """
    if len(fragments) <= 1:
        return fragments

    fragment_numbered = "\n".join(f"{i+1}. {f}" for i, f in enumerate(fragments))
    prompt = f"""You are arranging memory fragments for a group.

Fragments (do not modify them):
{fragment_numbered}

Return ONLY a JSON array of the fragment numbers in the order you would arrange them for readability.
Example: [3, 1, 2, 4]
Do not add, remove, rephrase, or comment on any fragment.
"""
    try:
        response = await self._call_llm(prompt, max_tokens=100, temperature=0.1)
        order = json.loads(response)
        if isinstance(order, list) and all(isinstance(i, int) for i in order):
            valid_indices = [i - 1 for i in order if 1 <= i <= len(fragments)]
            if len(valid_indices) == len(fragments):
                return [fragments[i] for i in valid_indices]
    except Exception:
        pass
    return fragments  # fallback: return as-is
```

---

### 3.8 LLM Roles — What It Should and Should Not Do

| LLM Should Do | LLM Should NOT Do |
|---|---|
| Infer user intent from mentions (action routing) | Parse or validate constraint types from command text |
| Extract event draft fields from natural language | Interpret user behavior over time |
| Arrange Fragment Mosaic (frame only, no synthesis) | Synthesize, summarize, or editorialize memory fragments |
| Resolve scheduling conflicts from expressed availability | Add words not present in user contributions |
| Ask clarifying questions when intent is ambiguous | Make decisions about event state (state machine only) |
| Generate a draft event description from group context | Generate memory fragments on behalf of users |

---

### 3.9 Prompt Quality Standards (Non-Negotiable)

All prompts written from this point forward must follow these rules:

- Every prompt includes: (1) role statement, (2) explicit JSON schema with field descriptions, (3) example input/output pair, (4) explicit instruction for what to do when unsure
- **Temperature:** `0.1` for structured outputs (action routing, draft extraction). `0.4` for natural language (assistant_response, opinion). Never `0.3` as a compromise.
- **max_tokens:** Size to the schema. Action routing: 250. Draft extraction: 1200. Mosaic ordering: 100. Natural language opinion: 400. Never use 800 as a universal default.
- **System prompt:** `MEDIATOR_SYSTEM` is defined correctly. Pass it on every call that produces user-facing text. Do not pass it on purely structural calls (mosaic ordering, constraint analysis).
- **No f-string prompt assembly in handler layer.** Prompts are built by dedicated methods in `ai/llm.py` only. Handlers call `llm.infer_action(text, history, context)`. They do not construct prompt strings.

---

## 4. Engagement Architecture — Making Events Alive

The deepest problem is not UX, database, or LLM. The system has no feedback loop. Events form silently, lock silently, complete silently. There is nothing for a member to feel between "event announced" and "event completed." This section addresses that.

### 4.1 The Formation Window

An event in `proposed` or `interested` state is in its **formation window**. During this window, the event must be visible and alive in the group chat — not in a database. The infrastructure for this (`EventLiveCard`, `reaction_counts`) exists from the v3.3 design. It is not wired to the formation experience.

---

### 4.2 Live Card Specification

**What the Live Card must show:**

```
🎯 [Event Type]: [Description]

📅 [Fixed time] OR "Time forming..."
⏳ Deadline in [N days / N hours]

👥 [current count] / [minimum] needed
[Lineage note if not first event of this type: "Group's 3rd hiking event"]
[Hashtags if 2+ members contributed them: #hiking #weekend]
```

**What the Live Card must NOT show:**

- Participant names or identities (join/leave notifications go to organizer DM only)
- Constraint information
- Any indication of who has not joined
- Fragility language ("needs 2 more or will collapse", "at risk of cancellation")
- The word "collapse" at all

**Live card update triggers:**

- New participant joins → update count
- Participant relinquishes → update count
- New hashtag attached (after 2+ members contribute the same hashtag) → add hashtag to card
- Time is set or changed → update time line
- Gravity threshold met (count >= min_participants) → change card header visually, add Commit affordance note

**Update batching:** Minimum 30 seconds between edits to avoid Telegram rate limiting. Use a short debounce: accumulate changes, flush every 30 seconds.

**Card lifecycle:**

- **Created:** When event is created (at end of creation flow)
- **Updated:** On participant changes, hashtag additions
- **Deleted:** When event locks, completes, or is cancelled. On lock: replace with a locked confirmation message. On cancel: remove quietly.

---

### 4.3 Gravity — A Concrete, Non-Surveillance Implementation

Gravity is the system's term for the force that makes events feel real and pulls members toward commitment. It must not be a score, a per-user variable, or a computed property stored anywhere. It is the aggregate visible state of the forming event — what anyone looking at the live card can see.

**Gravity signals (all are counts, never scored, never stored per-user):**

| Signal | How It Works | Visible Where |
|---|---|---|
| Participant count vs minimum | Primary gravity signal. When count >= min, card state changes. Commit button appears. | Live card + event panel |
| Hashtag density | How many distinct hashtags members have contributed. A forming event with 5 member hashtags feels more alive than one with 0. | Live card (hashtag list) |
| Time remaining | Events near deadline feel more urgent. Shown as countdown. No pressure language — just the clock. | Live card |
| Lineage presence | If a prior mosaic fragment is quoted in the card, the group feels the event has history. Qualitative signal. | Live card (lineage note) |

**What gravity explicitly is not:**
- Not a score
- Not computed per-user
- Not stored as a number
- Not used to determine access, sequencing, or nudge timing
- Not shown as a bar, percentage, or "gravity: 73%"

---

### 4.4 The Gravity Threshold Moment

When `participant_count >= min_participants` for the first time, a specific set of things must happen:

1. **Live card header changes:** The card header updates to show `"✅ This event is happening!"` or equivalent non-fragile framing.
2. **Commit button appears** in the event panel for all joined participants. (It was hidden before this moment.)
3. **Organizer receives a DM:** "Your event has enough participants. You can lock it when ready." No pressure. Just information.
4. **Nothing else.** No group announcement. No countdown. No "lock it now!" urgency.

---

### 4.5 Memory as a Coordination Input

Currently: memory is the last step of the event lifecycle. A mosaic is assembled and posted. Then the group moves on and the next event starts from zero.

Required change: **memory is the first step of the next event.**

**Concrete implementation:**

1. After event completion, mosaic assembles and posts to group. Store `mosaic_message_id` in `event_memories`.
2. Write a row to `event_lineage`: `(parent_event_id=completed_event.event_id, child_event_id=NULL)`. The child will be filled when the next event of this type is created.
3. When a group starts creating an event: query `event_lineage` for events of the same type completed by this group.
4. If lineage exists: surface one fragment from the most recent mosaic. Show it in the creation flow before the description prompt. Keep it short (1–2 sentences from the fragment, not synthesized).
5. After new event creation, quote that fragment in the new event's live card announcement:

```
🎯 Weekend hike
↩ Last time: "We took the ridge trail and nobody wanted to leave."

📅 Saturday 9:00 AM
⏳ Deadline in 3 days
👥 1 / 5 needed
```

6. Update `event_lineage`: fill `child_event_id` with the new event's ID.

**Fragment selection rule:** Use `event_enrichments` WHERE `event_id = last_completed_event.event_id` AND `enrichment_type = 'memory'` AND `is_public = TRUE`, ORDER BY `created_at`, LIMIT 1. No LLM involvement. Most recently submitted public memory fragment. Simple.

---

### 4.6 Post-Event Memory Collection Flow

After event completes, the bot sends each confirmed participant a DM:

> "How did it go? If you want to add a memory to the group's mosaic, just type it here — a sentence, a feeling, anything that stayed with you. No deadline."

**Rules:**
- DM goes out 1–6 hours after `completed_at` (configurable in `group_settings`)
- No collection deadline. Fragments are accepted whenever they arrive.
- Mosaic assembles when at least 2 fragments exist for the event, or when a participant requests it via Enrich > Add a memory in the event panel.
- Privacy: fragments are stored as `is_public = FALSE` initially. They become `is_public = TRUE` only when the mosaic is assembled and posted to the group.
- Contributor identity: store `telegram_user_id` in `event_enrichments` but display only anonymized attribution in the mosaic (if any attribution at all — this is optional; the mosaic can simply be the collection of voices without names).

---

### 4.7 The Test That Has Never Succeeded

You have never successfully tested the bot across multiple events to see gravity, memory, and lineage accumulate. The reason is the engagement vacuum — there is nothing to feel in the group between events. Here is the minimum viable test sequence:

| Step | Action | What to Validate |
|---|---|---|
| Step 1 | Create Event A in a test group with 2 accounts. Verify live card posts to group. | Live Card creation |
| Step 2 | Have second account join. Verify live card updates with new count. | Live Card update on join |
| Step 3 | Have both accounts joined. Verify Commit button appears in panel (count >= min). | Gravity threshold |
| Step 4 | One account commits. Organizer receives DM about gravity met. | Gravity notification |
| Step 5 | Mark Event A as complete. Bot sends each participant a DM asking for memories. | Memory collection trigger |
| Step 6 | Both accounts submit memory fragments. Verify mosaic assembles and posts to group. | Mosaic assembly |
| Step 7 | Verify `mosaic_message_id` stored. Verify `event_lineage` row written. | Lineage tracking |
| Step 8 | Create Event B of the same type. Verify prior mosaic fragment appears in creation flow before description prompt. Verify lineage note appears on Event B's live card. | **Memory as Input** |
| Step 9 | Repeat steps 1-7 for Event B. Observe the group now has a felt history. | Full loop validation |

**Step 8 has never been reached.** Fix the live card first (Step 2). The rest of the loop becomes testable.

---

## 5. Implementation Order and File Map

These changes must be implemented in dependency order. Do not start a later phase before its predecessors are merged, tested, and running on the stable branch.

### Phase 1 — Schema and Infrastructure (no UX changes yet)

All schema changes and new service files. No command or handler changes. Deployed separately so the migration can run before code changes.

| File | Change |
|---|---|
| `db/schema.sql` | Remove CHECK constraints from `constraints.type`, `logs.action`, `groups.group_type`. Add `event_enrichments`, `event_lineage`, `event_live_cards`, `group_settings` tables. |
| `db/models.py` | Add `EventEnrichment`, `EventLineage`, `EventLiveCard`, `GroupSettings` models. Remove `CheckConstraint` validators from constraint and log columns. |
| `ai/actions.py` | **NEW FILE.** Canonical action registry (Section 3.2). |
| `ai/validator.py` | **NEW FILE.** Output validator (Section 3.4). |
| `ai/llm.py` | Refactor `infer_group_mention_action` → `infer_action` using registry. Remove all regex fallbacks. Fix temperature to `0.1` for structured calls. Fix `max_tokens` per method. |
| `bot/services/` | **NEW FILE:** `event_enrichment_service.py` with `add_idea`, `add_hashtag`, `add_memory`, `get_by_event`, `get_public_hashtags`. |
| `bot/services/event_memory_service.py` | Update fragment assembly to read from `event_enrichments`. Add `write_lineage_row()`. Add `get_lineage_fragment_for_group()`. |
| `bot/services/participant_service.py` | Add `VALID_CONSTRAINT_TYPES`, `VALID_LOG_ACTIONS` constants. Add `validate_constraint_type()`. |

---

### Phase 2 — Live Cards and Engagement

| File | Change |
|---|---|
| `bot/services/event_live_card_service.py` | **NEW FILE** (based on v3.3 design). Wire hashtag updates from `event_enrichments`. Add lineage fragment display. Add gravity state change logic (`proposed → forming → happening`). Implement 30-second update batching. |
| `bot/common/materialization.py` | Rewrite card text templates to remove fragility language. Add lineage fragment quote to new event announcement. |
| `bot/services/event_lifecycle_service.py` | On event creation: call `EventLiveCardService.create_live_card()`. On lock/complete/cancel: call `EventLiveCardService.delete_live_card()`. On lock: write `event_lineage` row. |
| `bot/handlers/event_flow.py` | Add `update_live_card_on_change()` call after every join/relinquish/commit. |
| `bot/services/event_state_transition_service.py` | Call `participant_state_reconcile.reconcile()` after every state transition (see Section 6.2). |

---

### Phase 3 — Event Panel and Command Consolidation

| File | Change |
|---|---|
| `bot/commands/events.py` | Add `[ + Create New Event ]` button to list. Add memory-first creation flow (check lineage, surface fragment, then creation wizard). |
| `bot/handlers/event_flow.py` | **Major addition:** Event panel handler (Level 2 view with context-aware buttons). Enrich sub-menu handler (Level 3a). Constraint sub-menu handler (Level 3b). |
| `bot/common/event_states.py` | Add helper: `get_available_actions(user_status, event_state) → list[str]`. |
| `bot/commands/organize_event.py` | Mark deprecated. Redirect to `/events` creation. |
| `bot/commands/organize_event_flexible.py` | Mark deprecated. Redirect to `/events` creation. |
| `bot/commands/status.py` | Mark deprecated. |
| `bot/commands/event_details.py` | Mark deprecated. |
| `bot/commands/join.py` | Mark deprecated. |
| `bot/commands/confirm.py` | Mark deprecated. |
| `bot/commands/lock.py` | Mark deprecated. |
| `bot/commands/constraints.py` | Mark deprecated. |
| `bot/common/keyboards.py` | Add: `build_event_panel_keyboard(user_status, event_state, event_id)`. Add: `build_enrich_keyboard(event_id)`. Add: `build_constraint_keyboard(event_id)`. |

---

### Phase 4 — Memory Loop Completion

| File | Change |
|---|---|
| `bot/services/event_memory_service.py` | Post-completion DM trigger. Fragment→mosaic assembly from `event_enrichments`. `mosaic_message_id` storage. `event_lineage` write after mosaic posts. |
| `bot/commands/events.py` | Surface lineage fragment in creation flow (query `event_lineage → event_memories → enrichments`). |
| `bot/common/materialization.py` | Add lineage fragment quote to live card on creation. |

---

### Phase 5 — Cleanup and Dead Code Removal

| File | Change |
|---|---|
| All deprecated commands | Remove handlers, remove from `main.py` registration. |
| `bot/commands/event.py` | Remove (duplicate of `events.py`). |
| `ai/llm.py` | Final pass: remove any remaining regex fallbacks. Remove `infer_feedback_from_text` (behavioral scoring — violates WHY_VERSION_3.md). |
| `db/models.py` | Remove `expertise_per_activity` from `User` (behavioral scoring artifact). |
| `main.py` | Update command registration. |
| `README.md`, `docs/` | Update to reflect new command surface. |

---

## 6. Additional Engineering Considerations

### 6.1 Callback Data Length Limits

Telegram inline keyboard `callback_data` is limited to **64 bytes**. The current codebase has callback patterns that may exceed this (`menu_event_select_123_details_constraints_available`).

**Enforce this pattern everywhere:**

```python
# Current (fragile):
callback_data=f"menu_event_select_{event_id}_details_availability"  # may exceed 64 bytes

# Required pattern:
callback_data=f"ev:{event_id}:det"    # event detail
callback_data=f"ev:{event_id}:enr"    # enrich
callback_data=f"ev:{event_id}:con"    # constraint
callback_data=f"ev:{event_id}:join"   # join
callback_data=f"ev:{event_id}:reli"   # relinquish
callback_data=f"ev:{event_id}:comm"   # commit
callback_data=f"ev:{event_id}:lock"   # lock
callback_data=f"ev:{event_id}:back"   # back to list
callback_data=f"enr:{event_id}:idea"  # enrich > idea
callback_data=f"enr:{event_id}:hash"  # enrich > hashtag
callback_data=f"enr:{event_id}:mem"   # enrich > memory
```

Any additional context needed by the handler is looked up from the database, not encoded in the callback string.

---

### 6.2 Participant State Reconciliation

`bot/common/participant_state_reconcile.py` exists but is not called consistently across all state transitions. This causes ghost participants (joined but event cancelled) and stale confirmed counts on live cards.

**Enforce:** `event_state_transition_service.py` must call `reconcile()` after every transition, unconditionally. No exceptions for "fast paths."

---

### 6.3 Rate Limiter — Restart Safety

`bot/common/rate_limiter.py` uses an in-memory dict. On bot restart, all rate limit state is lost. For the current single-instance deployment this is acceptable. Add this comment to the code:

```python
# WARNING: Rate limit state is in-memory and NOT restart-safe.
# For multi-instance deployment, move state to Redis or a dedicated DB table.
```

If the project grows to multiple workers, this must be addressed before deployment.

---

### 6.4 `organizer_telegram_user_id` vs `admin_telegram_user_id` Ambiguity

The `events` table has both `organizer_telegram_user_id` and `admin_telegram_user_id`. The distinction is not documented or enforced anywhere in the code. From v3 philosophy: organizer is a per-event ephemeral role. Admin is an emergency override path.

**Action:**
1. Rename `admin_telegram_user_id` → `emergency_admin_telegram_user_id` in schema and models
2. Add a comment: "Only set when the original organizer cannot complete their role and a confirmed participant takes over. If never used in practice, remove in v3.6."
3. Update RBAC checks in `bot/common/rbac.py` to use the new name

---

### 6.5 Timezone Handling

`datetime.utcnow()` is called throughout. Python 3.12+ deprecated this. Replace everywhere with `datetime.now(timezone.utc)`.

More importantly: the bot stores all times as UTC but has no mechanism for displaying times in the user's local timezone. For a group coordination tool, this is a significant UX gap.

**Minimum viable fix:**
- Store group timezone in `group_settings.group_timezone` (added in Phase 1 schema)
- Add a `tz_display(dt, group_id)` utility in `bot/common/event_formatters.py` that converts UTC to the group's timezone for display
- Use `tz_display()` everywhere a datetime is shown to users in the live card, event panel, and event list

**Do not ask individual users for their timezone.** Use the group's timezone as the reference. Groups coordinate together; they share a timezone context.

---

### 6.6 LLM Context Window Budget

`ai/llm.py` passes 15–20 messages of chat history to several prompts. For long-lived groups, this context may contain irrelevant messages from days ago.

**Replace message count limits with a token budget:**

```python
def _trim_to_token_budget(self, history: list[dict], budget: int = 800) -> list[dict]:
    """Trim history to approximate token budget, keeping most recent messages."""
    result = []
    total_tokens = 0
    for msg in reversed(history):
        msg_tokens = int(len(str(msg)) / 4)  # rough approximation: 4 chars per token
        if total_tokens + msg_tokens > budget:
            break
        result.insert(0, msg)
        total_tokens += msg_tokens
    return result
```

---

### 6.7 Fragment Privacy and Contributor Handling

`EventMemory.fragments` stores `contributor_hash`. When `event_enrichments` is used for memory fragments, apply the same privacy pattern: store `telegram_user_id` in the table (needed for attribution logic) but derive a `contributor_hash` for any public-facing display.

```python
import hashlib

def hash_contributor(telegram_user_id: int, event_id: int) -> str:
    """One-way hash for mosaic display. Cannot be reversed to user_id."""
    key = f"{telegram_user_id}:{event_id}:salt_v3"
    return hashlib.sha256(key.encode()).hexdigest()[:12]
```

---

### 6.8 The Three Fallback Messages

Define these as constants in `bot/common/`:

```python
# bot/common/fallbacks.py

FALLBACK_CLARIFY = (
    "I didn't quite get that. What did you want to do?",
    # Buttons: [ View Events ]  [ Create Event ]  [ Never mind ]
)

FALLBACK_EVENT_NEEDED = (
    "Which event are you referring to? Here are your active events:",
    # Followed by: short events list (inline buttons)
)

FALLBACK_GENERAL = "Type /events to see what's happening in your group."
```

Use these consistently. Never let the bot go silent on an error.

---

### 6.9 `infer_feedback_from_text` Must Be Removed

`ai/llm.py` contains `infer_feedback_from_text()` which infers a score (1–5), weight (0.0–1.0), and expertise adjustments from user text. This is behavioral scoring. It directly violates `WHY_VERSION_3.md` Section 1 and Section 9 ("Reducing Humans to Dimensions Is Always Wrong").

**Remove this method entirely.** If structured feedback is needed in the future for a legitimate purpose, it must be redesigned against the six questions in `WHY_VERSION_3.md`.

---

### 6.10 `expertise_per_activity` on User Model

`users.expertise_per_activity` is a JSON column storing expertise levels per activity tag. This is a behavioral modeling artifact from v2. It is not used by any v3 feature. Remove the column from the model and schema in Phase 5 cleanup.

---

### 6.11 Idempotency Key TTL

`IdempotencyKey.expires_at` is set but there is no scheduled job that cleans up expired keys. Over time, this table will grow unbounded.

**Add to `bot/common/scheduler.py`:** A daily cleanup job that deletes `idempotency_keys` where `expires_at < NOW() - INTERVAL '7 days'`.

---

### 6.12 The Meaning Formation Flow — Preserve What Works

`bot/commands/meaning_formation.py` and `start_meaning_formation()` are architecturally correct. They implement the conversational clarification flow that surfaces prior memories before event creation. The v3.3 design identified the problem: this flow is not the default path.

**The fix is simple:** Make `start_meaning_formation()` the entry point for all event creation. When the user taps `[ + Create New Event ]` from the `/events` list, this function is called first. The current `/organize_event` handler is deprecated (as specified in Section 1.8). Do not rewrite the meaning formation logic — just make it the mandatory entry point.

---

## 7. Design Standards

### 7.1 Language Standards for Bot Messages

All user-facing text must be evaluated against this test: **Does this show what is forming, or does it engineer a response?**

| Do Not Use | Use Instead |
|---|---|
| "This event needs 2 more or it will collapse" | "2 more people needed. Deadline: [time]." |
| "Event at risk of cancellation" | "Heads up — this event hasn't reached its minimum yet." |
| "If one more person drops, this event is cancelled" | Show count: "3 / 5 needed" |
| "[Person] who has been to every session just joined" | "[Person] joined." (all arrivals announced equivalently) |
| "Your reliability score helped this event lock" | Nothing. Do not mention scores. |
| "Commit now before it's too late" | "This event has enough participants. Commit if you're in." |

### 7.2 Button Label Standards

- **Join** — not "Accept Invitation", "Opt In", "Count Me In"
- **Relinquish** — not "Cancel", "Withdraw", "Drop Out" (chosen because it is non-dramatic and neutral)
- **Commit** — not "Confirm", "Lock In", "RSVP" (chosen because it implies agency)
- **Enrich** — not "Add Content", "Contribute", "Memories" (chosen because it is the right word for what it is)
- **Constraint** — not "Conditions", "Preferences", "Availability" (chosen because it is precise)
- **← Events** — not "Back", "Return", "Menu"

### 7.3 Event State Language

| Internal State | Display to User |
|---|---|
| `proposed` | "forming" |
| `interested` | "forming" |
| `confirmed` | "happening" |
| `locked` | "locked — attendance finalized" |
| `completed` | "done" |
| `cancelled` | "cancelled" |

The internal state machine should not be visible to users. The display layer translates.

### 7.4 Live Card Message Format

```
[emoji] [Event Type]: [Description]

📅 [time OR "Time forming..."]
⏳ [deadline countdown OR nothing]

👥 [count] / [minimum] needed
[↩ From last time: "fragment" — only if lineage exists]
[#hashtag #hashtag — only if 2+ members contributed]
```

Emoji for event types:
- `🏃` Sports
- 🍕 Social
- 💻 Work
- 🎯 Other / default

---

## 8. Testing Matrix

Before any phase is considered complete, these scenarios must pass manually (automated tests are a follow-up, not a blocker):

### Phase 1 Validation

| Test | Expected Result |
|---|---|
| LLM returns `{"action_type": "create_event"}` (wrong field name) | `infer_action()` returns `opinion` fallback, not crash |
| Write a constraint with type `"available_saturday"` | Accepted without SQL error (CHECK removed) |
| Write a log with action `"enrich_hashtag"` | Accepted without SQL error (CHECK removed) |
| Insert an `event_enrichments` row | Row persists; queryable by `enrichment_type` |
| Insert an `event_lineage` row | Row persists; queryable by parent and child |

### Phase 2 Validation

| Test | Expected Result |
|---|---|
| Create event in group | Live card appears in group chat immediately |
| Second account joins event | Live card updates within 30 seconds with new count |
| Account relinquishes | Live card updates within 30 seconds |
| Count reaches min_participants | Live card header changes; Commit button appears in event panel |
| Event is locked | Live card is deleted from group chat |
| Event is cancelled | Live card is deleted from group chat |

### Phase 3 Validation

| Test | Expected Result |
|---|---|
| `/events` in group chat | Tappable event list appears, correct context filtering |
| `/events` in DM | Shows events across all user's groups |
| Tap event in list | Event panel appears with correct context-aware buttons |
| Join button tapped | User is joined; live card updates; Join button disappears from panel |
| Commit button appears only when threshold met | Commit button absent before min reached, appears after |
| Enrich > Add hashtag | Hashtag stored in `event_enrichments`; appears on live card after 2+ contributors |
| Constraint sub-menu | Constraint stored as DM-only; does not appear on live card |

### Phase 4 Validation (The Full Loop — The Test That Must Succeed)

| Step | Expected Result |
|---|---|
| Complete Event A | Bot DMs each confirmed participant asking for memory |
| Submit memory fragments | Fragments stored in `event_enrichments` |
| Mosaic assembles | Posted to group; `mosaic_message_id` stored |
| Create Event B of same type | Prior event's fragment appears in creation flow *before* description prompt |
| Event B live card | Shows lineage note: "↩ From last time: [fragment]" |

---

## Final Note to the Team

The vision in this codebase is unusual and precise. `WHY_VERSION_3.md` is not aspirational marketing — it is a working design constraint. When in doubt about any implementation decision, ask this question:

**Does this make the forming event more legible to the people who are forming it?**

If yes: build it.
If it requires knowing more about people to work: do not build it.

The failure mode to watch for is the one that killed v2: building two systems simultaneously — one that says "people commit when they feel seen" and one that secretly scores, ranks, and models them. These two systems are not in tension they can resolve. They are architecturally incompatible.

Every recommendation in this document was evaluated against the six questions from `WHY_VERSION_3.md`:

1. Does this require modeling user behavior? — No.
2. Does this create asymmetric visibility? — No. Live cards show aggregate counts, not individual behavior.
3. Does this introduce pressure into what should be awareness? — No. Language standards enforced in Section 7.
4. Does this treat memory as an artifact or a driver? — Driver. Memory is the first step in creation.
5. Does this belong to Paradigm A (relational emergence) or Paradigm B (computational governance)? — All recommendations belong to Paradigm A.
6. Would the user be surprised to learn this exists? — No. All data collection is visible and purposeful.

---

*Document version: v3.5-rebuild-spec*
*Prepared for the Coordination Engine open source engineering team*
