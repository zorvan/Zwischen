**Coordination Engine**

v3 Rebuild Specification

For Engineers & Designers

|     |     |
| --- | --- |
| **Document Type**<br><br>Product & Engineering Specification | **Status**<br><br>Active — For Immediate Implementation |
| **Addresses Issues**<br><br>UX Fragmentation, LLM Inconsistency, DB Rigidity, Engagement Vacuum | **Philosophy**<br><br>WHY_VERSION_3.md — Relational emergence, not computational governance |

**North Star Principle**

The value is not knowing more about people. The value is shaping how people relate to what they already know is forming. Every decision in this document is derived from that premise.

# **0\. Diagnosis: What Is Actually Broken**

Before prescribing fixes, engineers and designers must understand the root failure modes. The code has four compounding problems that do not exist independently — they reinforce each other.

|     |     |     |
| --- | --- | --- |
| **Failure Mode** | **Symptom** | **Ref** |
| UX Fragmentation | /status, /events, /event_details, /organize_event, /organize_event_flexible, /plan — parallel entry points for the same concern. Each learned independently; none form a coherent mental model. | Issue #1 |
| LLM Inconsistency | Prompts built by concatenating unvalidated f-strings. No system-level context. No canonical function registry the LLM can use. Regex fallbacks that conflict with LLM output. No structured output enforcement. | Issue #3 |
| Database Rigidity | CHECK constraints on enum strings in SQL. Regex patterns in constraint type columns. Action strings hardcoded in log CHECK. Schema changes require migrations and code changes simultaneously. | Issue #2 |
| Engagement Vacuum | Events announced once in group, then disappear into DMs. No live group presence during formation. Memory orphaned after completion. /plan bypassed by default /organize_event path. | Issue #4 |

**Why they compound**

A fragmented UX makes users reliant on LLM interpretation. A broken LLM makes the bot feel unreliable. An unreliable bot discourages multi-event testing, so gravity/memory/lineage never accumulate. No accumulation means the philosophical vision is untestable and appears to not work.

# **1\. UX Redesign — Single Entry Point: /events**

The entire user-facing interaction surface collapses into one command. /events is the only surface users need. Everything branches from it. This is not a convenience change — it is an architectural commitment to progressive disclosure.

## **1.1 The Problem in Code**

Current fragmentation in bot/commands/:

- /status — parallel event status command
- /event — unified command that duplicates /events
- /event_details — separate detail view
- /organize_event and /organize_event_flexible — two creation paths
- /plan — memory-first path that is almost never reached
- /constraints — separate command that users must discover independently
- /join, /confirm, /lock — standalone commands requiring event ID memory

**Core diagnosis**

There are ~12 commands that represent 3 concerns: viewing events, acting on events, and creating events. Users must know which command to pick before they know what they want to do. The LLM fallback only exists because the command surface is too fragmented to navigate without it.

## **1.2 The New Interaction Model**

One entry point. Three levels of progressive disclosure. All actions reachable without typing event IDs or knowing command names.

### **Level 1: /events — The Event List**

User types /events (or taps it from the main menu). Response: a list of events relevant to this user in this context, each as a tappable button. No event IDs visible in text. No commands to remember.

**List format — each row shows:**

- Event description (first 5 words)
- Date or TBD
- State: forming / locked / done
- Member's current status relative to this event: invited / joined / confirmed / not involved

**Context-aware filtering:**

- In a group chat: shows events for that group only
- In DM: shows all events across groups the user is part of
- Sort: events where user has a pending action first (invited but not joined, joined but gravity not met, etc.)

### **Level 2: Event Panel — Per-Event View**

User taps an event. A panel appears (inline keyboard update, not a new message) showing the full event card plus context-aware action buttons. This is the single replacement for /event_details, /event, and /status.

**Panel sections:**

- Event header: description, type, time/TBD, state, participant count vs minimum
- Lineage fragment (if exists): one sentence from a prior event of this type — shown quietly below the header
- Active hashtags (if any have been attached during formation)

**Action buttons — shown conditionally based on user's status and event state:**

|     |     |     |
| --- | --- | --- |
| **Condition** | **Button** | **Notes** |
| User is invited but has not joined | Join | Shown when event is in proposed/interested state and user is on invite list |
| User has joined | Relinquish | Shown when event is in proposed/interested/confirmed state. Replaces /cancel. |
| User has joined | Enrich | Opens enrichment sub-menu. See 1.3. |
| User has joined | Constraint | Opens constraint sub-menu. See 1.4. |
| User has joined AND event has enough gravity | Commit | Shown when participant count >= min_participants. Replaces /confirm. |
| User is organizer AND event has enough participants | Lock | Replaces /lock. |
| User is organizer | Edit Event | Opens edit flow. |
| Any user, any event | Back to List | Returns to Level 1. |

**Design rule for buttons**

Never show a button if the action would fail silently. If the event is locked and join is not possible, do not show Join with a disabled state — do not show it at all. Context-aware means the button surface accurately reflects what is possible right now.

### **Level 3a: Enrich Sub-Menu**

Enrich is how a member contributes meaning to an event during its formation. These contributions do not post publicly immediately — they accumulate and surface at the right moment.

**Enrich options (shown as buttons):**

- Add an idea — free text input, stored as a planning fragment. Can be a suggestion for the event (location, activity, timing detail). Visible only to organizer until event locks.
- Add a hashtag — up to 3 hashtags per member per event. Hashtags attach to the forming event's live card in the group (with a small delay for accumulation). Prior hashtags from previous events of this type are offered as suggestions.
- Add a memory — available only after event completes. Free text, max 200 words. Stored as a mosaic fragment. Private until mosaic assembles.
- View my contributions — shows what the user has already enriched for this event.

**Implementation note**

Ideas and hashtags during formation go to event.planning_prefs (JSON blob). They surface to the organizer in the edit flow. They do not affect any system decision. Memories go to EventMemory.fragments. The LLM's role in enrichment is zero — it should not touch, parse, or summarize these contributions. They are the human voice.

### **Level 3b: Constraint Sub-Menu**

Constraint is how a member communicates their conditional participation. This replaces /constraints as a standalone command. It is reached only through the event panel.

**Constraint options:**

- I'll join if \[person\] joins — taps a list of group members or types a @username
- I'll join only if \[person\] attends — if_attends type (for post-join confirmation dependency)
- I won't join if \[person\] joins — unless_joins type
- My availability — time slot grid for flexible-schedule events only
- View/remove my constraints — shows current constraints, allows deletion

**Constraint privacy rule**

Constraints are always DM-only and private to the user and organizer. They never appear on the live card in the group. This was correct in v2 and must be preserved.

## **1.3 Commands to Remove**

The following commands become dead code after this migration. They should be deprecated (respond with 'use /events instead') for one release cycle, then removed:

|     |     |
| --- | --- |
| **Command** | **Replaced By** |
| /status | Replaced by event panel state section |
| /event_details | Replaced by event panel |
| /event (standalone) | Replaced by /events + panel |
| /organize_event | Replaced by /events creation flow |
| /organize_event_flexible | Same — flexible mode is a panel option |
| /plan | Merged into /events creation flow |
| /join | Replaced by Join button in panel |
| /confirm | Replaced by Commit button in panel |
| /lock | Replaced by Lock button in panel |
| /constraints | Replaced by Constraint sub-menu in panel |

**Commands to keep:**

- /events — primary entry point
- /start — welcome + quick navigation (keep main menu buttons)
- /about — bot description
- /my_history — personal attendance mirror (DM only)
- /my_groups — group management

## **1.4 Event Creation via /events**

Creating an event is reached through /events, not a separate command. This collapses /organize_event and /organize_event_flexible and enforces the memory-first principle from NextStep.md.

**Creation flow steps:**

1.  User taps Create New Event button (always visible at bottom of /events list)
2.  System checks: does this group have prior completed events of any type? If yes: surface the most recent Fragment Mosaic for that event type inline. User sees what was remembered last time before filling in anything. If no prior events: skip to step 3.
3.  System asks: what kind of event? (social / sports / work / other — as buttons)
4.  System asks: when? (fixed time / flexible / TBD — as buttons)
5.  System asks: describe the event in one sentence (free text). LLM may assist in enriching the description if the group has chat history — but the user's text is always the primary source.
6.  System presents draft card with: description, type, time/TBD, suggested min participants. User confirms or edits.
7.  On confirm: event is created, Live Card posted to group, /events list updates, organizer auto-joined as participant.

**Why memory-first is non-negotiable**

From WHY_VERSION_3.md: 'Memory is a coordination input, not a coordination output.' If a user can bypass prior memories by choosing a create path, then memory is still an artifact — it arrives too late to shape what forms next. The creation flow must not allow skipping the memory surface, even if the user taps 'skip' — showing it at all changes the affordance.

# **2\. Database — Stay Relational, Remove the Brittleness**

The question is not which database paradigm. The question is: what is making the current relational schema hostile to LLM integration and iterative development? The answer is specific and fixable without migration to a document store.

## **2.1 The Case for Keeping PostgreSQL**

A document database (MongoDB, Firestore, DynamoDB) would trade the current problems for a different set:

|     |     |
| --- | --- |
| **Relational Pain Point** | **Document DB Equivalent** |
| Current problem: CHECK constraints on enum strings break silently when LLM outputs edge-case values | Document DB equivalent: no schema = everything breaks silently at query time, not at write time |
| Current problem: action strings in logs.CHECK cannot be extended without schema migration | Document DB equivalent: no foreign key enforcement = referential integrity must be written manually |
| Current problem: constraint.type regex pattern in CHECK is opaque and hard to debug | Document DB equivalent: relationships between events, participants, constraints must be denormalized |
| Current problem: planning_prefs JSON blob is untyped — LLM puts anything there | Document DB equivalent: aggregate queries (who is joining which events?) require MapReduce or application-level joins |

The relational model is correct for this domain. Events have participants. Participants have statuses. Constraints link users to events with conditions. These are structural relationships, not document hierarchies. PostgreSQL with JSONB for flexible fields gives the best of both: structural enforcement where structure matters, flexibility where it does not.

## **2.2 Specific Schema Changes Required**

### **Change 1: Remove CHECK constraints from semantic strings**

The most hostile pattern in the current schema is using SQL CHECK to enforce semantic values that are subject to LLM output variation. Remove these specific CHECK constraints:

\-- REMOVE THIS:

type VARCHAR(50) NOT NULL CHECK (

type IN ('if_joins', 'if_attends', 'unless_joins')

OR type LIKE 'available:%'

)

\-- REPLACE WITH:

type VARCHAR(50) NOT NULL

\-- Validation moves to application layer in bot/services/participant_service.py

\-- REMOVE THIS from logs:

action VARCHAR(100) NOT NULL CHECK (action IN ('organize_event', 'join', ...))

\-- REPLACE WITH:

action VARCHAR(100) NOT NULL

Application-layer validation is written once in Python as a canonical set, shared across all entry points. The LLM can now output a slightly different string without crashing a write — the service layer normalizes it.

### **Change 2: Add an event_enrichments table**

Currently, member contributions during formation are shoved into planning_prefs (a JSON blob on the Event). This makes them invisible to queries, unattributable, and impossible to surface selectively. Create a proper table:

CREATE TABLE IF NOT EXISTS event_enrichments (

enrichment_id BIGSERIAL PRIMARY KEY,

event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,

telegram_user_id BIGINT NOT NULL,

enrichment_type VARCHAR(30) NOT NULL,

\-- Values: 'idea', 'hashtag', 'memory'

content TEXT NOT NULL,

is_public BOOLEAN DEFAULT FALSE,

created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);

**Benefits:**

- Ideas, hashtags, and memories are now queryable by type
- Organizer can query 'show me all ideas for event X' directly
- Hashtag surfacing for live cards becomes a simple SELECT
- Memory mosaic assembly queries this table, not a JSON array inside event_memories
- is_public flag controls when hashtags surface on the live card (not immediate)

### **Change 3: Soften group_type CHECK**

groups.group_type has CHECK (group_type IN ('casual', 'gathering', 'tournament')). This was a v1 concern. Remove the CHECK. Keep the column. Let values be free strings.

### **Change 4: Add event lineage foreign key**

Event lineage is currently tracked in event_memories.lineage_event_ids as a JSONB array of integers. This is not queryable. Add a proper many-to-many join table:

CREATE TABLE IF NOT EXISTS event_lineage (

parent_event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,

child_event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,

relation_type VARCHAR(30) DEFAULT 'same_type',

linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

PRIMARY KEY (parent_event_id, child_event_id)

);

This enables: 'find all events descended from this one', 'find the last event of this type', 'show lineage chain' — without JSON parsing.

### **Change 5: event_enrichments replaces planning_prefs for member input**

Do not delete planning_prefs from events — it still serves as organizer-level draft storage for the creation flow. But all member-contributed content (ideas, hashtags, memories) moves to event_enrichments. This boundary is enforced at the service layer, not the schema layer.

## **2.3 What to Keep Unchanged**

Do not migrate, alter, or second-guess:

- events table structure — it is correct and well-indexed
- event_participants with status/role enums — this is the right design
- EventStateTransition audit trail — valuable and well-implemented
- EventMemory.fragments as JSONB — fragments are variable-length; JSONB is correct here
- IdempotencyKey table — essential for Telegram callback protection
- event_live_cards — the v3.3 design is correct; implementation needs the enrichment link

**Operational note for engineers**

These schema changes require two coordinated steps: (1) remove CHECK constraints and add new tables in a migration, (2) deploy updated service layer that performs application-level validation. The migration must run before the code deploys. Do not deploy the code first — the new enrichment writes will fail on the old schema.

# **3\. LLM Layer — Consistent, Scalable, Bounded**

The LLM is not the problem. The way the bot constructs prompts, routes results, and falls back is the problem. Three root causes produce all observed LLM inconsistency.

## **3.1 Root Cause Analysis**

### **Root Cause 1: Every prompt is a snowflake**

ai/llm.py contains 6+ distinct prompting styles, each hand-written with different formatting, different JSON schema expectations, different validation logic, and different fallback behavior. When a method fails, it falls back to regex string matching that contradicts the JSON the LLM was asked for. There is no single contract between the bot and the LLM.

**Example of the contradiction:**

\# LLM is asked to return this JSON:

{"action_type": "organize_event", "event_id": 123}

\# But the fallback uses regex:

if "organize" in lowered: fallback_action = "organize_event"

\# If the LLM returns:

{"action_type": "create_event"} # slightly wrong key value

\# The validation rejects it and falls back to regex

\# But the regex might match something different

\# Result: two different interpretations of the same user message

### **Root Cause 2: No function registry**

The LLM is given a list of string action names and asked to pick one. It has no idea what those actions do, what their preconditions are, or what parameters they require. It is guessing from names. The allowed action list in infer_group_mention_action includes: opinion, organize_event, organize_event_flexible, status, event_details, suggest_time, constraint_add, join, confirm, cancel, lock, request_confirmations. These map to different commands, different services, different validation requirements. The LLM cannot know this from names alone.

### **Root Cause 3: No output contract enforcement before dispatch**

When the LLM returns JSON, the code calls json.loads() directly. If the parse succeeds, fields are accessed with .get() with silent defaults. If the parse fails, the regex fallback runs. There is no step that says: 'is this output structurally valid for the action type claimed?' A response of {action_type: 'join', event_id: null} will be dispatched to the join handler with no event_id, which will fail downstream in a confusing way.

## **3.2 The Scalable Solution: Structured Function Dispatch**

Replace the prompt-per-method pattern with a single, canonical function registry that the LLM selects from. This is the Anthropic tool-use pattern adapted for an OpenAI-compatible API using JSON schema.

### **Step 1: Define a canonical action registry**

Create ai/actions.py with a single source of truth:

\# ai/actions.py

ACTIONS = {

"view_events": {

"description": "User wants to see their events list",

"required_params": \[\],

"optional_params": \["group_id"\]

},

"join_event": {

"description": "User wants to join a specific event",

"required_params": \["event_id"\],

"optional_params": \[\]

},

"create_event": {

"description": "User wants to create a new event. Use when message expresses intent to organize, plan, or gather.",

"required_params": \[\],

"optional_params": \["description", "event_type", "scheduled_time"\]

},

"add_constraint": {

"description": "User wants to express a conditional participation constraint",

"required_params": \["event_id", "constraint_type", "target_username"\],

"optional_params": \[\]

},

"opinion": {

"description": "User is asking a question or chatting — no action needed",

"required_params": \[\],

"optional_params": \["assistant_response"\]

}

}

The key change: actions now include descriptions the LLM can reason about, not just names it must guess from. The registry is the contract.

### **Step 2: Single structured prompt with schema injection**

Replace all individual infer_ methods in llm.py with one method for action routing, using schema-in-prompt:

async def infer_action(self, text: str, history: list, context: dict) -> ActionResult:

schema = self.\_build_action_schema(ACTIONS)

prompt = f'''

You are a Telegram group coordination assistant.

Available actions and when to use them:

{schema}

Group context:

\- Active events: {context\['active_events'\]}

\- User's joined events: {context\['user_events'\]}

\- Recent chat (last 5 messages): {history\[-5:\]}

User message: {text}

Select the best action. Return ONLY this JSON:

{{

"action": "&lt;action_name from registry&gt;",

"params": {{...required and optional params}},

"confidence": 0.0-1.0,

"assistant_response": "brief helpful message to user"

}}

'''.strip()

### **Step 3: Validate before dispatch**

Create ai/validator.py that enforces the contract before any handler is called:

\# ai/validator.py

def validate_action_result(result: dict, registry: dict) -> ValidationResult:

action = result.get('action')

if action not in registry:

return ValidationResult(valid=False, reason=f'Unknown action: {action}')

required = registry\[action\]\['required_params'\]

params = result.get('params', {})

missing = \[p for p in required if not params.get(p)\]

if missing:

return ValidationResult(valid=False, reason=f'Missing: {missing}',

recoverable=True, missing_params=missing)

return ValidationResult(valid=True)

When validation fails with recoverable=True (missing required params), the bot asks the user for the missing info rather than silently falling back to regex. This is a better experience and makes the LLM's limitations visible and fixable.

### **Step 4: Eliminate all regex fallbacks**

Every regex fallback in llm.py is a parallel interpretation system that conflicts with the LLM. Remove them. Replace with this single pattern:

except Exception as e:

logger.error('LLM action inference failed: %s', e)

return ActionResult(

action='opinion',

params={},

confidence=0.0,

assistant_response='I had trouble understanding that. Can you try again?'

)

The fallback is now: ask the user to clarify. This is always better than a silently wrong action.

## **3.3 LLM Roles: What It Should and Should Not Do**

|     |     |
| --- | --- |
| **LLM Should Do** | **LLM Should NOT Do** |
| Infer user intent from mentions (action routing) | Parse or validate constraint types from command text |
| Extract event draft fields from natural language | Interpret user behavior over time (removed in v3) |
| Assemble Fragment Mosaic layout (frame only, no synthesis) | Synthesize, summarize, or editorialize memory fragments |
| Resolve scheduling conflicts from expressed availability | Add words not present in user's contributions |
| Ask clarifying questions when intent is ambiguous | Make decisions about event state (state machine only) |

**The mosaic constraint, restated for engineers**

From WHY_VERSION_3.md section 5: 'The LLM may arrange fragments for readability. It may not add words that were not in the fragments. It may not label, categorize, interpret, or synthesize.' This is not a prompt guideline. It is a system constraint. The prompt must structurally prevent synthesis: give the LLM only the fragment texts and ask it to order them, nothing else.

## **3.4 Prompt Quality Standards**

All prompts must follow these rules from this document forward:

- Every prompt includes: (1) role statement, (2) explicit JSON schema with field descriptions, (3) example input/output pair, (4) explicit instruction for what to do when unsure
- Temperature: 0.1 for structured outputs (action routing, draft extraction). 0.4 for natural language responses (opinion, assistant_response). Never 0.3 as a compromise.
- max_tokens: size to the schema. Action routing needs 200 tokens. Draft extraction needs 600. Never use 800 as a default.
- System prompt: MEDIATOR_SYSTEM is currently defined correctly. Do not change it. Ensure it is passed on every call that produces user-facing text.
- No f-string prompt assembly in the handler layer. Prompts are built by dedicated methods in ai/llm.py only.

# **4\. Engagement Architecture — Making Events Alive**

The deepest problem is not UX, database, or LLM. It is that the system has no feedback loop. Events form silently, lock silently, complete silently. There is nothing for a member to feel between 'event announced' and 'event completed'. This section addresses that.

## **4.1 The Formation Window**

An event in proposed or interested state is in its formation window. During this window, the event must be visible and alive in the group chat — not in a database. The infrastructure for this (EventLiveCard, reaction_counts) already exists. It is not wired to the formation experience.

### **What the Live Card must show**

- Event description and type
- Time if fixed, 'Time forming...' if flexible
- Participant count and minimum: '3 / 5 needed'
- Countdown: 'Deadline in 2 days'
- Hashtags contributed by members (appears after 2+ hashtags exist, with small delay)
- Lineage note if this is not the first event of this type: 'Group's 3rd hiking event'

### **What the Live Card must NOT show**

- Participant names or identities (join/leave notifications go to organizer DM only)
- Constraint information
- Any indication of who has not joined
- Fragility language ('needs 2 more or will collapse')

Live card updates on: new join, relinquish, new hashtag attachment, time changes. Updates are batched — minimum 30 seconds between edits to avoid rate limiting.

## **4.2 Gravity Accumulation**

Gravity is the system's term for the force that makes events feel real and pulls members toward commitment. Currently it is not implemented in any meaningful way — it is referenced in philosophy but has no corresponding behavior. Here is a concrete, non-surveillance implementation:

**Gravity signals (all are counts, never scored, never stored per-user):**

- Participant count vs minimum — the primary gravity signal. When count >= min, the live card state changes visually ('This event is happening!'). Commit button appears.
- Hashtag density — how many different hashtags have been attached. A forming event with 5 member hashtags feels more alive than one with 0. Shown as count only.
- Time remaining — events near deadline feel more urgent. Live card shows countdown. No pressure language — just the clock.
- Lineage presence — if prior mosaic exists and a fragment is quoted in the card, the group feels the event has history. This is a qualitative gravity signal, not a count.

**What gravity explicitly is NOT**

Gravity is not a score. It is not computed per-user. It is not used to determine who gets access or when. It is not stored as a number anywhere. It is the aggregate visible state of the forming event — what anyone looking at the live card can see. Per WHY_VERSION_3.md: 'The value is shaping how people relate to what they already know is forming.' Gravity is the shape of what is forming, made visible.

## **4.3 Memory as a Coordination Input**

Currently: memory is the last step of the event lifecycle. A mosaic is assembled and posted. Then the group moves on and the next event starts from zero.

Required change: memory is the first step of the next event.

**Concrete implementation:**

1.  When a group starts creating an event: query event_lineage for events of the same type completed by this group.
2.  If lineage exists: surface one fragment from the most recent mosaic. Show it in the creation flow before the description prompt. Keep it short (1-2 sentences from the fragment, not synthesized).
3.  After event creation, quote that fragment in the new event's live card announcement: '↩ From last time: \[fragment text\]'
4.  When mosaic is posted after event completion: pin it (or reply to it). Keep a reference in event_memories.mosaic_message_id. This reference is what makes step 2 possible for the next cycle.

## **4.4 Testing Multiple Events: What to Build First**

You have never successfully tested the bot across multiple events to see gravity, memory, and lineage accumulate. The reason is the engagement vacuum — there is nothing to feel in the group between events. Here is the minimum viable sequence to test the full loop:

|     |     |     |
| --- | --- | --- |
| **Step** | **Action** | **What to Validate** |
| Step 1 | Create Event A in a test group. Verify live card posts to group. Verify it updates when a second account joins. | Live Card + Join |
| Step 2 | Have 2+ accounts join Event A. Verify Commit button appears. Have one account commit. | Gravity + Commit |
| Step 3 | Complete Event A. Have each test account submit a memory fragment via Enrich > Add a memory. | Memory Collection |
| Step 4 | Verify mosaic assembles and posts. Verify mosaic_message_id is stored. | Mosaic Assembly |
| Step 5 | Create Event B of the same type. Verify the prior mosaic fragment appears in the creation flow before description. Verify the lineage note appears on Event B's live card. | Memory as Input |
| Step 6 | Repeat steps 1-5 for Event B. Observe the group now has a felt history. | Full Loop Validation |

**This is the test that has never succeeded**

Step 5 has never been reached because steps 1-4 had no visible social presence that made testing feel meaningful. Fix the live card first. The rest of the loop will become testable.

# **5\. Implementation Order and File Map**

These changes must be implemented in dependency order. Do not start a later phase before its predecessors are merged and tested.

## **Phase 1 — Schema and Infrastructure (No UX changes yet)**

- db/schema.sql: Remove CHECK constraints from constraints.type and logs.action
- db/schema.sql: Add event_enrichments table
- db/schema.sql: Add event_lineage table
- db/models.py: Add EventEnrichment model, EventLineage model
- db/models.py: Remove SQLEnum validators from constraint and log columns
- bot/services/: Add EventEnrichmentService with methods: add_idea, add_hashtag, add_memory, get_by_event, get_public_hashtags
- bot/services/event_memory_service.py: Update to read from event_enrichments for fragment assembly
- ai/actions.py: Create canonical action registry (NEW FILE)
- ai/validator.py: Create output validator (NEW FILE)
- ai/llm.py: Refactor infer_group_mention_action to use action registry and validator
- ai/llm.py: Remove all regex fallbacks except the final generic 'opinion' fallback

## **Phase 2 — Event Panel and Command Consolidation**

- bot/commands/events.py: Add 'Create New Event' button to list, add memory-first creation flow
- bot/handlers/event_flow.py: Add event panel handler (Level 2 view with context-aware buttons)
- bot/handlers/event_flow.py: Add Enrich sub-menu handler
- bot/handlers/event_flow.py: Add Constraint sub-menu handler
- bot/commands/organize_event.py: Mark as deprecated, redirect to /events creation
- bot/commands/organize_event_flexible.py: Same
- bot/commands/plan.py: Remove. start_meaning_formation() is now called from creation flow.
- bot/commands/status.py: Mark as deprecated
- bot/commands/event_details.py: Mark as deprecated
- bot/commands/join.py: Mark as deprecated
- bot/commands/confirm.py: Mark as deprecated
- bot/common/event_states.py: Add helper: get_available_actions(user_status, event_state) → list of action names

## **Phase 3 — Live Cards and Gravity**

- bot/services/event_live_card_service.py: Wire hashtag updates from event_enrichments
- bot/services/event_live_card_service.py: Add lineage fragment display logic
- bot/services/event_live_card_service.py: Add gravity state change (proposed → forming → happening)
- bot/common/materialization.py: Rewrite card text templates to remove fragility language
- bot/common/materialization.py: Add lineage fragment quote to new event announcement
- bot/services/event_memory_service.py: After mosaic post, write to event_lineage table

## **Phase 4 — LLM Full Refactor**

- ai/llm.py: Replace infer_event_draft_from_context with registry-based method
- ai/llm.py: Replace infer_event_draft_patch with registry-based method
- ai/llm.py: Replace infer_constraint_from_text (move to service layer — LLM no longer needed for this)
- ai/schemas.py: Align all schemas to action registry output contract
- bot/handlers/mentions.py: Replace action routing with ai.actions dispatch

## **Phase 5 — Cleanup and Dead Code Removal**

- Remove deprecated command handlers once redirect period is over
- Remove bot/commands/event.py (duplicate of events.py)
- Remove bot/commands/check_deadlines.py (collapsed into scheduler)
- Update main.py command registration
- Update README and USER_FLOWS documentation

# **6\. Additional Considerations**

## **6.1 Callback Data Length Limits**

Telegram inline keyboard callback_data is limited to 64 bytes. The current codebase has several callback patterns that may exceed this: menu_event_select_123_details_constraints. Enforce a maximum: callback_data = 'action:event_id' format only. Any additional context is looked up from the database, not encoded in the callback.

\# Current pattern (fragile):

callback_data=f'menu_event_select_{event_id}' # fine

callback_data=f'event_tab_{event_id}\_details_availability' # may break

\# Enforced pattern:

callback_data=f'ev:{event_id}:det' # max 20 chars for ID+action

callback_data=f'ev:{event_id}:con'

callback_data=f'ev:{event_id}:enrich'

## **6.2 Participant State Reconciliation**

bot/common/participant_state_reconcile.py exists but is not called consistently across all state transitions. The state machine in event_state_transition_service.py must call reconcile() after every transition. Currently, state transitions in some paths bypass reconciliation. This causes ghost participants (joined but event cancelled) and stale confirmed counts on live cards.

## **6.3 Rate Limiter and Bot Restarts**

bot/common/rate_limiter.py uses an in-memory dict. On bot restart, all rate limit state is lost. For a multi-instance deployment this is a silent bug. If the project grows to multiple workers, move rate limit state to Redis or a DB table. For single-instance, add a note in the code that this is not restart-safe.

## **6.4 The organizer_telegram_user_id vs admin_telegram_user_id Confusion**

events table has both organizer_telegram_user_id and admin_telegram_user_id. The distinction is not enforced anywhere and is not documented. From v3 philosophy: organizer is a per-event ephemeral role. admin is an emergency override path. Clarify: rename admin_telegram_user_id to emergency_admin_telegram_user_id and document that it is only set when an organizer cannot complete their role and a confirmed participant takes over. If it is never actually used, remove it.

## **6.5 Timezone Handling**

datetime.utcnow() is called throughout. Python 3.12 deprecated this. Replace with datetime.now(timezone.utc) everywhere. More importantly: the bot currently stores all times as UTC but has no mechanism for displaying times in the user's local timezone. For a group coordination tool, this is a significant UX gap. Minimum viable fix: store group timezone in GroupSettings and convert on display. Do not ask individual users for their timezone — use the group's timezone as the reference.

## **6.6 LLM Context Window Budget**

ai/llm.py passes the last 15-20 messages of chat history to several prompts. For long-lived groups, this context may contain irrelevant messages. Replace message count limits with a token budget: count approximate tokens (words \* 1.3) and trim oldest messages first until the history fits within 800 tokens. This keeps the most recent context while preventing prompt bloat.

## **6.7 The Fragment Mosaic and Contributor Privacy**

EventMemory.fragments stores contributor_hash, not telegram_user_id. This is correct — fragments are private to the contributor until the mosaic assembles. The hash prevents de-anonymization. When event_enrichments is added, use the same pattern: store a hashed version of the contributor's ID, not the raw telegram_user_id, in the is_public=false records. Only when is_public becomes true (hashtag promoted to live card, memory fragment included in mosaic) should the association be visible — and even then, only as a display name, not a user_id.

## **6.8 What the Bot Should Say When It Cannot Help**

Currently, when the LLM falls back to 'opinion' or validation fails, the bot either says nothing or says a generic error. Define three explicit fallback messages as constants and use them consistently:

- FALLBACK_CLARIFY: 'I didn't quite get that. Did you want to \[view events / create an event / do something else\]?' — with three buttons
- FALLBACK_EVENT_NEEDED: 'Which event are you referring to? Here are your active events:' — followed by the short events list
- FALLBACK_GENERAL: 'Type /events to see what's happening in your group.' — the simplest possible recovery

**Document Integrity Check**

Every recommendation in this document was evaluated against the six questions from WHY_VERSION_3.md:

- Does this require modeling user behavior? — No. No behavioral scores, no user modeling.
- Does this create asymmetric visibility? — No. Live cards show aggregate counts, not individual behavior.
- Does this introduce pressure into what should be awareness? — No. Language standards enforced in Section 4.
- Does this treat memory as an artifact or a driver? — Driver. Memory is the first step in creation.
- Does this belong to Paradigm A or B? — All recommendations belong to Paradigm A.
- Would the user be surprised to learn this exists? — No. All data collection is visible and purposeful.

**Final note to the team**

The vision in this codebase is unusual and precise. The WHY_VERSION_3.md document is not aspirational marketing — it is a working design constraint. When in doubt about any implementation decision, the question to ask is: does this make the forming event more legible to the people who are forming it? If yes, build it. If it requires knowing more about people to work, do not build it.
