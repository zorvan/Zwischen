# User Flow Logics

**Document Version:** 3.1 (Critique-Resolved)
**Last Updated:** 2026-04-04
**Project:** Coordination Engine Telegram Bot

---

## Table of Contents

1. [Overview — What Changed to Resolve the Critique](#overview--what-changed-to-resolve-the-critique)
2. [Bot Conversation Orientation](#bot-conversation-orientation)
3. [Event Creation Flow](#1-event-creation-flow)
4. [Event Participation Flow](#2-event-participation-flow)
5. [Materialization Announcements Flow](#3-materialization-announcements-flow)
6. [Mention-Driven AI Orchestration Flow](#4-mention-driven-ai-orchestration-flow)
7. [Constraint Management Flow](#5-constraint-management-flow)
8. [Memory Contribution Flow](#6-memory-contribution-flow)
9. [Event Modification Flow](#7-event-modification-flow)
10. [Time Suggestion Flow](#8-time-suggestion-flow)
11. [Memory Layer Flow](#9-memory-layer-flow)
12. [Event Lineage & Note Flow](#10-event-lineage--note-flow)
13. [State Transition Diagram](#state-transition-diagram)
14. [Key Services](#key-services)
15. [Database Models](#database-models)
16. [Command Reference](#command-reference)
17. [Resolved Design Decisions](#resolved-design-decisions)
18. [The Complete Test Suite for Behavioral Neutrality](#the-complete-test-suite-for-behavioral-neutrality)

---

## Overview — What Changed to Resolve the Critique

This document represents a **complete removal** of all behavioral inference from the system.

### Removed Entirely (Not Just Hidden)

| What Was Removed | Why |
|---|---|
| Any system action based on attendance history | The system does not treat users differently based on past behavior |
| Reliability-based confirmation windows | No user gets a different window than any other |
| Priority access for "reliable" users | All users have equal access to event participation |
| Silent deprioritization of any kind | No invisible steering |
| LLM synthesis of memory fragments | LLM may rearrange only; no words added, no interpretation |
| Any form of "reliability pattern" storage | Not stored, not inferred, not used |
| Different materialization messages per user | All users see the same messages for the same event state |
| Fragility framing ("if one more drops, this collapses") | Removed — shows reality without engineering guilt |
| High-reliability join amplification | All joins announced equally |

### What Replaces Nothing — The System Does Less

The system does not need replacement mechanisms for behavioral inference. It simply **does not do those things**.

The Personal Attendance Mirror (`/how_am_i_doing`) exists for user self-reflection only. It is **causally inert** — no system component reads these counts to make decisions.

### The Behavioral Neutrality Principle

> For any two users with identical declared intent at this moment, the system must produce identical behavior.

This applies to:
- Confirmation window timing
- Message content
- Event access
- Priority ordering
- Any other system output

The only allowed differences are based on:
- Different declared intent (join vs confirm vs cancel)
- Different declared constraints (availability, conditions)
- Different event states (threshold reached vs not)

---

## Bot Conversation Orientation

### Meaning-Formation Mode (Primary — Before Any Structure)

**Trigger:** User signals intent to organize something (any method)

**Bot response (first message, always):**
> *"What are you trying to bring together?"*

**If user is vague:**
> *"That sounds like it could be a few things — do you have a sense of who needs to be there for it to feel right?"*

**The bot does NOT:**
- Ask "Do you have any doubts?" as a gateway
- Steer toward system-valid actions before intent is clear
- Translate vague language into structured intent and proceed
- Assume anything about what the user wants

**The bot stays in meaning-formation mode until the user expresses clear intent.** There is no timeout that forces structure.

### Quiet Facilitation Mode (After Intent Is Clear)

Once intent is clear, the bot shifts to structured flow. In this mode:
- Messages are brief, specific, relational
- The bot does not explain itself
- The bot does not offer unsolicited options
- The bot does not manufacture urgency

### Receiving Mode (Memory Collection — No Deadline, No Structure)

**Bot DM (1–6 hours after event completion, configurable):**
> *"Hey — how was [event]? Anything that stuck with you? A word, a moment, a photo — whatever comes to mind."*

**The bot does NOT:**
- Set a deadline for response
- Ask structured questions ("Rate from 1-5...")
- Prompt for specific categories ("What was the best part?")
- Acknowledge that this is "for the system"

**The bot receives whenever the user responds** — hours, days, or weeks later. No follow-up pressure. No "you haven't responded yet" messages.

---

## 1. Event Creation Flow

### Memory-First Entry (Critical Change)

When a user initiates event creation, the system **immediately** checks for prior completed events of the same type in the same group.

**If found, before any other creation flow step:**

**Bot posts (in group or DM, depending where creation started):**
Last time your group did something like this, people remembered:

"The rain made it better."
"Best three hours in a while."

Connect this to that? [Yes, link it] [No, start fresh]


**This is not optional.** It always appears when lineage exists. The user cannot bypass it. Memory is a coordination driver, not an optional feature.

### Meaning-Formation First (Before Type Selection)

**First prompt (always):**
> *"What are you trying to bring together?"*

Only after the user answers does the bot proceed to structured flow.

### Structured Flow Stages (After Meaning-Formation)

| Stage | Prompt | Options |
|---|---|---|
| Type Selection | "What type of event?" | Social, Sports, Work |
| Description | "Tell people what this is." | Free text (max 500 chars) |
| Date | "When?" | Today, Tomorrow, Weekend, Next Week, Custom |
| Time | "What time of day?" | Early-morning, Morning, Afternoon, Evening, Night |
| Duration | "How long?" | 30m, 60m, 90m, 120m, 180m |
| Location | "Where?" | Home, Outdoor, Cafe, Office, Gym |
| Threshold | "How many people needed for this to happen?" | Number (min 1) |
| Review | Confirmation screen | Confirm, Modify, Cancel |

### Threshold Behavior

| Field | Source | Behavior |
|---|---|---|
| `min_participants` | User input at Threshold stage | Event auto-cancels if not met by `collapse_at` |
| `collapse_at` | Calculated: `scheduled_time - 2 hours` | Auto-cancellation deadline |

**No reliability adjustments.** No user gets a different threshold or different deadline based on history.

---

## 2. Event Participation Flow

### Join Flow

**User action:** `/join <event_id>` or callback button

**System behavior:**
1. Add user to participant list with status `joined`
2. Increment joined count
3. Trigger materialization announcement: "[Name] just joined [event]. [N] people are in."
4. If joined count now >= `min_participants`, trigger threshold announcement

**All joins announced identically.** No user is amplified. No "X, who's been to every session" language.

### Confirm Flow

**User action:** `/confirm <event_id>` or callback button

**Prerequisites:**
- User must have status `joined`
- Event must not be `locked` or `cancelled`

**System behavior:**
1. Update user status to `confirmed`
2. Increment confirmed count
3. Trigger materialization announcement: "[Name] has committed. [confirmed_count] people are now in."
4. If confirmed count now >= `min_participants` and event is `interested`, transition to `confirmed` state

**All confirms announced identically.** No user is prioritized.

### Cancel Flow

**User action:** `/cancel <event_id>` or callback button

**System behavior:**
1. Update user status to `cancelled`
2. Decrement appropriate count (joined or confirmed)
3. **DM to organizer only:** "[Name] had to step back. [N] still in."
4. **No public announcement of cancellation**
5. If confirmed count drops below `min_participants` and event is `locked`, event transitions to `cancelled`

**Critical:** Cancellations are never announced in the group. The group sees arrivals, not departures.

### What This Flow Does NOT Do

- Apply different confirmation window timings based on history
- Amplify any participant's join or confirm over another
- Access or use attendance history to change any outcome
- Send different messages to different users based on past behavior

---

## 3. Materialization Announcements Flow

### Complete Announcement Table (All Templates)

| Trigger | Audience | Message Template | Test Pass? |
|---|---|---|---|
| First join | Group | "[Name] just joined [event]. [N] people are in." | Pass — shows reality |
| Any subsequent join | Group | "[Name] just joined. [N] people are in." | Pass — shows reality |
| First confirm | Group | "[Name] has committed. [N] people are now in." | Pass — shows reality |
| Any subsequent confirm | Group | "[Name] has committed. [N] people are now in." | Pass — shows reality |
| Threshold reached (joined >= min) | Group | "[Event] is coming together. [N] people have joined." | Pass — shows reality |
| Event locked | Group | "[Event] is happening — [date/time]. Participants: [names]" | Pass — shows reality |
| Near minimum (within 2 of threshold) | Group | "Heads up — [event] needs [N] more to happen. Deadline: [time]." | Pass — shows reality without guilt |
| Collapse deadline passed | Group | "[Event] didn't reach the minimum and has been cancelled." | Pass — shows reality |
| Cancellation | **Organizer DM only** | "[Name] had to step back. [N] still in." | Pass — private |
| 24h before | Group | "[Event] is tomorrow. [confirmed_count] confirmed. [names]" | Pass — shows reality |

### Prohibited Messages (Will Never Appear)

| Prohibited Message | Why |
|---|---|
| "If one more person drops, this event collapses." | Engineers dread, not awareness |
| "[Name], who's been to every session, just joined." | Creates hierarchy |
| "X is counting on you." | Engineers personal responsibility |
| "You're one of the most reliable members." | Behavioral judgment |
| "We're almost there — don't let everyone down." | Guilt engineering |
| Any message that differs based on user's attendance history | Violates behavioral neutrality |

### Design Rules

1. **No public mention of cancellations** — ever
2. **All joins and confirms announced identically** — no amplification
3. **No fragility framing** — "needs N more" not "if one more drops"
4. **No personal responsibility language** — "heads up" not "don't let everyone down"
5. **Silence is valid** — minor state changes (re-joins) do not produce announcements

---

## 4. Mention-Driven AI Orchestration Flow

### Inferred Actions (Complete Set)

| Action Type | Description | Requires Approval |
|---|---|---|
| `organize_event` | Create public event | No |
| `join` | Join event | No |
| `confirm` | Confirm attendance | No |
| `cancel` | Cancel attendance | No |
| `status` | Show event status | No |
| `event_details` | Show event details | No |
| `constraint_add` | Add constraint (if mentions others) | Yes |
| `meaning_formation` | Hold space, ask what user is trying to bring | No — open-ended |

### Removed Actions (From v2)

| Removed Action | Why |
|---|---|
| `suggest_time` based on attendance patterns | Used behavioral inference |
| `request_confirmations` with targeting | Could create differential pressure |
| Any action that produces different output for different users | Violates behavioral neutrality |

### Meaning-Formation as Default

When the bot cannot clearly classify an action with confidence > 0.8, it enters meaning-formation mode:

> *"I'm not sure what you're trying to do. What are you trying to bring together?"*

The bot does not guess. It does not assume. It asks.

### Context Collection (Limited)

The bot maintains rolling chat history (last 40 messages per group) for:
- Action context only ("what event are we talking about")
- **Not** for behavioral modeling
- **Not** for reputation inference
- **Not** for any user-specific adjustment

Chat history is pruned after 90 days.

---

## 5. Constraint Management Flow

### Constraint Types (Unchanged)

| Type | Description | Example |
|---|---|---|
| `if_joins` | Join if target joins | "I join if @alice joins" |
| `if_attends` | Join if target attends | "I join if @bob attends" |
| `unless_joins` | Join unless target joins | "I join unless @charlie joins" |
| `available:{timestamp}` | Availability slot | "available:2026-03-20T18:00" |

### Privacy Rule (Strict)

- All constraints are submitted and stored via DM
- Never surfaced in group chat in any form
- Used only for scheduling compatibility checks and conditional participation

### What Constraints Do NOT Do

- Generate early feedback signals (removed entirely)
- Feed into any reputation or scoring system (does not exist)
- Affect event access or priority (no such mechanism exists)
- Become visible to any other user (strictly private)

### Conditional Participation Resolution

When a condition is met (e.g., target joins), the system:
1. Checks if the condition was declared
2. If `if_joins` and target joins → automatically joins the user
3. Notifies the user via DM: "[Target] joined [event], so you've been added per your constraint."

**No scoring. No inference. No behavioral modeling.** Simple deterministic condition evaluation.

---

## 6. Memory Contribution Flow

### Primary Flow: Bot-Initiated DM (Post-Event)
Event → completed
│
└── [1–6 hours later, configurable] Bot DMs each confirmed participant
│
└── "Hey — how was [event]? Anything that stuck with you?
A word, a moment, a photo — whatever comes to mind."
│
├── User replies via DM (text / emoji / photo)
│ │
│ └── Fragment stored in event_memories
│ (no deadline — fragments accepted anytime)
│
└── [When ≥2 fragments received OR participant requests]
│
└── Fragment Mosaic assembled
(LLM may rearrange only — no words added)
│
└── Mosaic posted to group chat

### Critical Constraints

**No deadline for contributions** — fragments accepted whenever they arrive. The bot never sends a "you haven't responded" reminder.

**No structured questions** — only open-ended invitation. No "rate from 1-5." No "what was the best part?" No categories.

**No synthesis** — the Fragment Mosaic is the fragments themselves. The LLM may rearrange for readability but may not add words, interpret, label, or synthesize.

### Fragment Mosaic Assembly (LLM Constraint)

**LLM prompt (exact):**

You are given a list of memory fragments from participants of an event.
Your task is to arrange them for readability.
You may reorder the fragments.
You may NOT add any words that were not in the original fragments.
You may NOT add punctuation that changes meaning.
You may NOT label, categorize, interpret, or synthesize.
You may NOT produce a narrative, conclusion, or takeaway.
The output must contain ONLY the participants' words, in their original form, possibly reordered.
If a fragment contains a line break, preserve it.

**Example output (correct):**
From [event name] — how people remember it:

"The rain made it better."
"Best three hours in a while."
"I didn't expect to stay that long."
"Something shifted."

**Example output (incorrect — will never happen):**
The group enjoyed a memorable hiking adventure. Several people mentioned the weather, and many felt the time was well spent.


**Fallback:** If the LLM cannot be constrained to this behavior, the mosaic is assembled without LLM — simple chronological list of fragments.

### Secondary Flow: User-Initiated (`/remember`)

**Command:** `/remember <event_id> <text>`

**Behavior:**
1. Store fragment immediately
2. If this brings total fragments for this event to ≥2, trigger mosaic assembly
3. No deadline, no approval, no scoring

### What This Flow Does NOT Do

- Infer any numeric score from narrative text (no scoring system exists)
- Feed any reputation or behavioral model (none exist)
- Record any signal for future differential treatment (no such treatment exists)
- Track anything beyond: this participant contributed a fragment to this event
- Synthesize or interpret meaning

---

## 7. Event Modification Flow

### Modifiable Fields (Unchanged)

| Field | Validation |
|---|---|
| `description` | Max 500 chars |
| `event_type` | social, sports, work |
| `scheduled_time` | ISO format, must be future |
| `duration_minutes` | 30-720 |
| `threshold_attendance` | Min 1 |
| `location_type` | Preset values |

### Modification Approval

- Organizer can modify without approval (their event)
- Any modification that changes time or threshold triggers notifications to all participants via DM
- No differential treatment based on who requested the modification

### What Modification Does NOT Do

- Log modification as a "reliability signal" (no such signals exist)
- Adjust user's standing in any way (no standing system exists)
- Produce different notifications for different users

---

## 8. Time Suggestion Flow

### Complete Removal of Attendance-Based Pattern Analysis

In v2, time suggestion used:
- Historical attendance counts per user
- Pattern analysis ("this user usually attends hiking events")

**In v3, these are completely removed.**

### What Time Suggestion Uses Now

**Only:**
- Declared availability constraints from participants
- Event time window preferences (morning, afternoon, etc.)
- Current participant list

**Not:**
- Any attendance history
- Any inferred reliability
- Any behavioral pattern

### Decision Logic (Simplified)

| Input | Weight |
|---|---|
| Declared availability slots | Deterministic — must match |
| Time window preference | Secondary filter |
| Current participant availability | Aggregate — no user weighting |

**All users are treated identically.** A user who has attended 100 events has the same weight in time suggestion as a user attending their first event.

### LLM Fallback (If No Clear Time)

If no time satisfies all availability constraints, LLM suggests compromise times. LLM is provided with:
- Availability data only (not attendance history)
- Time window preferences

**LLM is explicitly instructed not to consider attendance history or reliability.**

---

## 9. Memory Layer Flow

### Personal Attendance Mirror (`/how_am_i_doing`)

**Command:** `/how_am_i_doing` (private DM only)

**Response:**

Your attendance by event type:

• Hiking: 8 joined, 7 completed
• Work meetups: 3 joined, 3 completed
• Social: 5 joined, 4 completed


**Critical Constraints:**
- No score, no formula, no weighting
- No comparison to others ("you are in top 20%" — forbidden)
- No trend analysis ("your reliability is improving" — forbidden)
- No influence on system behavior — these counts are **never read by any algorithm** that affects outcomes
- Private to the user — no other user can query this data

**Implementation guarantee:** The function that retrieves these counts is never called by any component that makes decisions about event access, timing, messaging, or any other user-facing behavior.

### Personal History (`/my_history`)

**Command:** `/my_history` (private DM only)

**Response:** List of events the user has participated in, with dates and outcomes (completed, cancelled, no-show).

**Same constraints as Personal Attendance Mirror:** Categorically inert. For user reflection only.

### Group Memory Browse (`/recall`)

**Command:** `/recall [filter]`

**Behavior:** Returns group-shared memories (Fragment Mosaics) for the group, filtered by event type or hashtag if provided.

**Privacy:** Shows only memories that have been posted to the group. Does not show individual histories. Does not show who contributed which fragment (anonymized by default).

### Event Memory Recall (`/memory <event_id>`)

**Behavior:** Returns the Fragment Mosaic for a specific event.

**Always available** — memory is not pruned (unless user requests deletion).

---

## 10. Event Lineage & Note Flow

### Lineage Prompt (Memory as Driver)

**When:** During event creation, after meaning-formation mode, before structured flow

**Condition:** Prior completed event of same type exists in same group

**Prompt:**

Last time your group did something like this, people remembered:

[1-3 fragments from prior event's mosaic]

Connect this to this event? [Yes, link it] [No, start fresh]


**If user selects "Yes, link it":**
- Prior event ID stored in `lineage_event_ids` for new event
- Prior hashtags offered as options for new event

**If user selects "No, start fresh":**
- No lineage link created
- New event stands alone

### Organizer Event Note (`/event_note`)

**Command:** `/event_note <event_id> <text>`

**Constraint:** Only organizer can post notes

**Behavior:**
1. Store note in event record
2. Post to group: "[event] update: [note text]"

**Notes are posted verbatim** — no LLM rewriting. Human voice preserved.

**The system does not:**
- Analyze note content
- Use note content to adjust anything
- Store notes as behavioral signals

---

## State Transition Diagram

┌─────────────────────────────────────────────────────────────┐
│ │
▼ │
┌──────────────┐ first join ┌───────────────┐ first confirm ┌───────────────┐ │
│ proposed │ ───────────────► │ interested │ ─────────────────► │ confirmed │ │
└──────────────┘ └───────────────┘ └───────────────┘ │
│ │ │ │
│ all cancel │ all cancel │ lock │
│ │ │ │
└───────────────────────────────────┴──────────────────────────────────┘ │
│ │
▼ │
┌───────────────┐ │
│ locked │ │
└───────────────┘ │
│ │
│ event ends │
▼ │
┌───────────────┐ │
│ completed │ ─── triggers memory DM │
└───────────────┘ │
│ │
│ under threshold at collapse_at │
▼ │
┌───────────────┐ │
│ cancelled │ │
└───────────────┘ │
▲ │
│ │
┌────────────────────────┴─────────────────────────────────────────┘
│
└── organizer cancel (from any pre-locked state)
text


### State Descriptions

| State | Description | Allowed Actions |
|---|---|---|
| `proposed` | Event created, no participants | Join, Cancel, Modify |
| `interested` | Participants joined, none confirmed | Join, Confirm, Cancel, Modify |
| `confirmed` | At least one confirmed participant | Join, Confirm, Cancel, Lock, Modify |
| `locked` | Event finalized | View only |
| `completed` | Event finished | Memory Contribution |
| `cancelled` | Event cancelled | View only |

---

## Key Services

### ParticipantService

**Purpose:** Normalized participant tracking. No behavioral inference.

**Methods:**
- `join(event_id, user_id, source)` — adds user with status `joined`
- `confirm(event_id, user_id, source)` — updates status to `confirmed`
- `cancel(event_id, user_id, source)` — updates status to `cancelled`
- `get_counts(event_id)` — returns joined_count, confirmed_count

**No methods for:** reliability scores, attendance patterns, user weighting, or any derived quality.

### MaterializationService

**Purpose:** Posts group awareness announcements. All users see same messages for same event state.

**Methods:**
- `announce(event_id, trigger, actor_id)` — main entry point
- `build_announcement(trigger, event, actor)` — constructs from template (no user-specific logic)
- `should_announce(trigger, event)` — guards against spam

**Critical:** No conditional logic based on user identity. All users receive identical announcements for identical triggers.

### MemoryService

**Purpose:** Fragment collection, mosaic assembly, lineage.

**Methods:**
- `trigger_collection_dms(event_id)` — DM all confirmed participants (no deadline, no follow-up)
- `store_fragment(event_id, user_id, text)` — store one fragment
- `assemble_mosaic(event_id)` — arrange fragments (LLM rearrangement only, no synthesis)
- `post_mosaic_to_group(event_id)` — post to group chat
- `check_lineage(group_id, event_type)` — find prior events for memory-first display

**Removed methods:** `generate_weave`, `synthesize_meaning`, `infer_tone` — none exist in v3.

### AttendanceMirrorService

**Purpose:** Private, self-visible attendance counts. Causally inert.

**Methods:**
- `get_personal_record(user_id)` — returns attendance counts by event type

**Critical guarantee:** This method is called only in response to explicit user command `/how_am_i_doing`. It is never called by any component that makes decisions about event access, timing, messaging, or any other user-facing behavior.

---

## Database Models

### Core Tables

| Table | Purpose | Key Fields |
|---|---|---|
| `users` | User identities | `telegram_user_id`, `username` — no reputation fields |
| `groups` | Group contexts | `telegram_group_id` |
| `events` | Event lifecycle | `state`, `min_participants`, `version` — no reliability fields |
| `event_participants` | Normalized participation | `status`, `role`, `joined_at`, `confirmed_at` |
| `constraints` | Conditional participation | `type`, `target_user_id` — no confidence scores |
| `event_memories` | Fragment mosaic | `fragments` (JSON), `mosaic_text` — no tone fields |
| `event_state_transitions` | Audit trail | `from_state`, `to_state`, `actor_id` |

### Removed Tables (From v2)

| Removed Table | Why |
|---|---|
| `early_feedback` | Surveillance — removed entirely |
| `reputation_scores` | Behavioral modeling — removed entirely |
| `behavioral_signals` | Inference — removed entirely |

### Removed Fields

| Removed Field | From Table | Why |
|---|---|---|
| `reputation` | `users` | Scoring — removed |
| `expertise_per_activity` | `users` | Behavioral modeling — removed |
| `reliability_score` | `event_participants` | Inference — removed |
| `tone_palette` | `event_memories` | Meaning centralization — removed |
| `confidence` | `constraints` | Scoring — removed |

---

## Command Reference

### Event Management

| Command | Description | Behavioral Neutrality |
|---|---|---|
| `/organize_event` | Create event (meaning-formation first) | ✓ — same for all users |
| `/join <event_id>` | Join event | ✓ — all joins announced equally |
| `/confirm <event_id>` | Confirm attendance | ✓ — all confirms announced equally |
| `/cancel <event_id>` | Cancel attendance | ✓ — private to organizer |
| `/lock <event_id>` | Lock event | ✓ — precondition only |
| `/event_note <event_id> <text>` | Add organizer note | ✓ — posted verbatim |
| `/status <event_id>` | View event status | ✓ — same for all users |
| `/events` | List recent events | ✓ — same for all users |

### Memory Layer

| Command | Description | Privacy |
|---|---|---|
| `/memory <event_id>` | View fragment mosaic | Group-visible |
| `/remember <event_id> <text>` | Contribute fragment | Group-visible (anonymized) |
| `/recall [filter]` | Browse group memories | Group-visible |
| `/my_history` | Personal event history | **Private DM only** |
| `/how_am_i_doing` | Personal attendance mirror | **Private DM only, causally inert** |

### Constraints

| Command | Description | Privacy |
|---|---|---|
| `/constraints <event_id> view` | View constraints | Private DM only |
| `/constraints <event_id> add ...` | Add constraint | Private DM only |

---

## Resolved Design Decisions

| Decision | Resolution | Rationale |
|---|---|---|
| **Does the system treat users differently based on history?** | **No — never** | Core behavioral neutrality principle |
| **Does the system use LLM to synthesize memory?** | **No — rearrangement only** | Meaning cannot be centralized |
| **Does the system engineer social pressure?** | **No — awareness only** | Materialization test enforced |
| **Does the system have invisible steering?** | **No — all mechanisms visible** | Every system action is documented |
| **Does the system have a collection deadline for memory?** | **No — no deadline** | Absent friend posture |
| **Does the system prioritize some users?** | **No — all equal** | No priority mechanism exists |
| **Does the system use attendance counts for anything?** | **No — causally inert** | Mirror only, never input |

---

## The Complete Test Suite for Behavioral Neutrality

Every feature must pass these tests before implementation:

### Test 1: Identical Input, Identical Output
> If two users with identical declared intent (both joined, both confirmed, both cancelled) trigger the same system action, do they receive identical outputs?

**Expected:** Yes. No conditional logic based on user identity or history.

### Test 2: No Hidden State
> Does the system maintain any per-user value that affects outcomes that the user cannot see?

**Expected:** No. All per-user data (attendance counts, constraints) is either visible to the user or used only for self-reflection (never for outcomes).

### Test 3: No History-Based Differentiation
> Does the system behave differently for a user with 100 completed events than a user with 0 completed events?

**Expected:** No. The only allowed differences are based on declared intent at this moment.

### Test 4: Materialization Neutrality
> Are all join and confirm announcements identical across users?

**Expected:** Yes. No amplification, no "who's been to every session" language, no differential treatment.

### Test 5: Memory Without Synthesis
> Does the Fragment Mosaic contain only words from participants, with no LLM-added interpretation?

**Expected:** Yes. LLM may rearrange only. Fallback to chronological if LLM cannot be constrained.

### Test 6: No Deadline Pressure
> Does the memory collection flow have a deadline or send follow-up reminders?

**Expected:** No. One DM, no deadline, no follow-up.

### Test 7: Causally Inert Mirror
> Is the Personal Attendance Mirror ever used as an input to any system decision?

**Expected:** No. The function that retrieves attendance counts is called only in response to explicit user command and never by any decision-making component.

### Test 8: No Fragility Framing
> Does any materialization message imply that a user's departure will "collapse" the event or let others down?

**Expected:** No. "Heads up — needs N more" is permitted. "If one more drops, this collapses" is forbidden.

### Test 9: No Hidden Priority
> Does any user have faster confirmation windows, earlier access, or different timing than any other user?

**Expected:** No. All timing is identical for all users.

### Test 10: Transparent System
> Can a user, by reading this document, understand every way the system might treat them differently from another user?

**Expected:** Yes. The answer is: the system does not treat any user differently from any other user based on anything except declared intent at this moment.

---

## Changelog

| Version | Date | Changes |
|---|---|---|
| 3.0 | 2026-04-04 | Complete removal of all behavioral inference. Added Behavioral Neutrality Principle. Removed all reliability-based mechanisms. LLM constrained to rearrangement only. Materialization messages tested against awareness/pressure distinction. Personal Attendance Mirror marked causally inert. Added complete test suite for behavioral neutrality. |


