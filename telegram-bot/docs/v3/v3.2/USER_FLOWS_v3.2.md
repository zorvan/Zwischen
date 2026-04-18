# User Flow Logics

**Document Version:** 3.2
**Date:** 2026-04-06
**Project:** Coordination Engine Telegram Bot
**Supersedes:** USER_FLOWS_v3.1.md

---

## Table of Contents

1. [Overview](#overview)
2. [Bot Conversation Orientation](#bot-conversation-orientation)
3. [Event Creation Flow](#1-event-creation-flow)
4. [Event Participation Flow](#2-event-participation-flow)
5. [Materialization Announcements Flow](#3-materialization-announcements-flow)
6. [Waitlist Flow](#4-waitlist-flow)
7. [Mention-Driven AI Orchestration Flow](#5-mention-driven-ai-orchestration-flow)
8. [Constraint Management Flow](#6-constraint-management-flow)
9. [Memory Contribution Flow](#7-memory-contribution-flow)
10. [Event Modification Flow](#8-event-modification-flow)
11. [Time Suggestion Flow](#9-time-suggestion-flow)
12. [Group Membership Sync Flow](#10-group-membership-sync-flow)
13. [Memory Layer Flow](#11-memory-layer-flow)
14. [Event Lineage & Note Flow](#12-event-lineage--note-flow)
15. [State Transition Diagram](#state-transition-diagram)
16. [Key Services](#key-services)
17. [Database Models](#database-models)
18. [Command Reference](#command-reference)
19. [Changelog](#changelog)

---

## Overview

This document describes all user flow logics for the Coordination Engine Telegram Bot. v3.2 introduces event-level adaptation without user-level judgment, and integrates findings from an academic sociological evaluation of trust formation under anomie.

### What Changed in v3.2

| New Mechanism | What It Does | What It Does NOT Do |
|---|---|---|
| Soft Buffer | Opens capacity beyond `min_participants` | Differentiate between participants |
| Waitlist Auto-Fill (FIFO) | Offers open spots in join-time order | Prioritize based on history |
| Temporal Gradient in Materialization | Adjusts tone based on time to event | Adjust tone based on user history |
| Cancellation-with-Action DM | State + inline buttons for organizer | Reveal cancellation to the group |
| Memory Hook in Announcements | Verbatim prior fragment at resonant moments | Synthesize or paraphrase anything |
| Reflexive Memory Prompt | Invites difficulty alongside celebration | Prescribe what participants remember |
| Reflexive Fragment Preference | Prefers difficulty/adaptation fragments in lineage door | LLM involvement; fabrication |
| Repeated Failure Pattern Surface | Group-level pattern mirror at meaning-formation | Name individuals or assign blame |

### Sociological Grounding Notes

These design notes connect flow decisions to the sociological framework documented in PRD Section 3.

| Mechanism | Sociological Function |
|---|---|
| Cognitive trust accumulation | Every completed event is a coordination game won; the memory layer stores this evidence |
| Generative memory hooks | Memory surfaces at formation moments — activating the past for present action, not archiving it |
| Reflexive prompt and fragment preference | Defense against Dark Social Capital: groups that only remember triumph tend toward exclusionary identity |
| Repeated failure pattern surface | Reflexive memory at the structural level — honest mirror before the next attempt |
| FIFO waitlist | Cognitive trust requires predictability; a rule everyone can understand is more trust-generative than an opaque priority algorithm |
| Thick trust scope | The system operates only within established groups — it is not designed for thin-trust anonymous coordination |

### Core Modules

| Module | Path | Purpose |
|---|---|---|
| Event Creation | `bot/commands/event_creation.py` | Meaning-formation first, then structured |
| Meaning Formation | `bot/commands/meaning_formation.py` | Open-ended intent + repeated failure surface |
| Event Flow | `bot/handlers/event_flow.py` | State machine for participant actions |
| Materialization | `bot/common/materialization.py` | Situationally-sensitive group announcements |
| Waitlist | `bot/services/waitlist_service.py` | FIFO auto-fill on cancellation |
| Mentions | `bot/handlers/mentions.py` | AI-driven natural language orchestration |
| Constraints | `bot/commands/constraints.py` | Conditional participation (DM only) |
| Memory | `bot/commands/memory.py` | Fragment collection, mosaic, lineage |
| Event Memory Service | `bot/services/event_memory_service.py` | Fragment storage, retrieval, reflexive selection |
| AI Core | `ai/core.py` | 3-layer time suggestion |
| LLM Client | `ai/llm.py` | OpenAI-compatible wrapper |

---

## Bot Conversation Orientation

The bot has four distinct postures:

**Meaning-Formation Mode:** Holds space before any structured input. Asks what the user is trying to bring together. Does not steer toward system-valid actions. In v3.2, also surfaces honest structural patterns when a group has repeatedly failed to complete the same event type — before the creation flow begins.

**Quiet Facilitation Mode:** Once intent is clear, the bot becomes a background orchestrator. Brief, specific, relational.

**Receiving Mode (Memory):** Post-event DM. No deadline, no categories, no structure. In v3.2, the opening explicitly holds space for difficulty alongside celebration: *"something that didn't quite go as planned"* is offered as a valid frame. The bot still receives whatever the participant gives — the opening just makes the full range of experience feel welcome.

**Situational Mode:** In materialization and deadline-adjacent notifications, tone shifts based on time-to-event. Light at T-72h. Warm at T-24h. Urgent at T-2h. Direct at T-0h. Never judgmental regardless of tier.

---

## 1. Event Creation Flow

**Commands:** `/organize_event`, `/organize_event_flexible`, `/private_organize_event`, `/plan`
**Source:** `bot/commands/event_creation.py`, `bot/commands/meaning_formation.py`

### Flow Diagram

```
┌──────────────────────────────────────────────────────────┐
│  Bot: "What are you trying to bring together?"           │
│  (Meaning-formation mode)                                │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│  Check: ≥3 failed attempts of same event type?           │
│  → If yes: surface pattern BEFORE memory prompt          │
│  "Your group has tried this 3 times. Each reached 5/6.  │
│   Want to approach it differently this time?"            │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│  Check: Prior completed events of same type?             │
│  → If yes: surface Fragment Mosaic excerpt               │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Type       │────▶│ Description │────▶│    Time     │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Created   │◀────│   Review    │◀────│ Min + Max   │
└─────────────┘     └─────────────┘     │  (Buffer)   │
                                        └─────────────┘
```

### Repeated Failure Pattern Surface (New in v3.2)

Before the Fragment Mosaic prompt, the system checks `get_failure_pattern(group_id, event_type)`. If ≥3 attempts of the same type completed fewer than `min_participants` confirmed:

**Bot message (meaning-formation mode):**
> *"Your group has tried something like this [N] times. Each time it reached [X] of [Y] and didn't happen. Want to approach it differently — change the minimum, the timing, or who you invite?"*

No participant is named. No blame is implied. The data is group-level: attempt count, typical dropout point. The group decides what it means.

**Sociological function:** Reflexive memory at the structural level. Groups that receive an honest mirror of their own patterns can adapt. Groups that don't receive this mirror repeat the same failure with increasing disengagement.

### Buffer Capacity (New in v3.2)

The creation flow collects two separate numbers:

- **"What's the minimum number of people this needs?"** → `min_participants`
- **"How many people can this comfortably fit?"** → `target_participants`

The gap is the soft buffer — described as capacity, not as risk hedge. Defaults: `target_participants = ceil(min_participants * 1.5)`.

### Flow Stages

| Stage | State Key | Description |
|---|---|---|
| Meaning-Formation | (open) | "What are you trying to bring together?" |
| Failure Pattern | (conditional) | Surfaces if ≥3 failed attempts of same type |
| Lineage Prompt | (conditional) | Prior Fragment Mosaic excerpt if completed events exist |
| Type Selection | `type` | social, sports, outdoor, work |
| Description | `description` | Max 500 chars |
| Date Selection | `date_preset` | Today, Tomorrow, Weekend, Next Week, Custom |
| Time Selection | `time_window` | Early-morning through Night |
| Duration | `duration` | 30m–180m |
| Location | `location_type` | Home, Outdoor, Cafe, Office, Gym |
| Budget | `budget_level` | Free, Low, Medium, High |
| Transport | `transport_mode` | Walk, Public, Drive, Any |
| Minimum | `min_participants` | Minimum to happen |
| Capacity | `target_participants` | Maximum comfortable (soft buffer) |
| Invitees | `invitees` | @handles or @all |
| Final | `final` | Confirm, Modify, Cancel |

---

## 2. Event Participation Flow

**Commands:** `/join`, `/confirm`, callback buttons
**Source:** `bot/handlers/event_flow.py`, `bot/commands/join.py`

### Flow Diagram

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  /join or   │────▶│   Check     │────▶│  Below      │
│ Join Button │     │ Conflicts   │     │  capacity?  │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                          ┌───────────────────┼───────────────────┐
                          │ Yes               │ No (at capacity)  │
                          ▼                   ▼                   │
                  ┌─────────────┐     ┌─────────────┐             │
                  │  Add to     │     │  Offer      │             │
                  │  event      │     │  Waitlist   │             │
                  └─────────────┘     └─────────────┘             │
                          │
                          ▼
                  ┌──────────────────────────────────┐
                  │  Trigger Materialization (Flow 3) │
                  └──────────────────────────────────┘
```

When `target_participants` is reached, new join attempts are offered waitlist placement. The offer is framed neutrally: *"[Event] is full at the moment. Want me to add you to the list? You'll be notified if a spot opens."*

**Sociological note:** FIFO waitlist order is not merely a fairness rule — it is the mechanism that makes the waitlist cognitively trustworthy. A rule everyone can predict is more trust-generative than an opaque priority system, even a well-intentioned one.

### Visibility of Mutual Presence

Event detail view shows confirmed and interested names, threshold progress ("4 of 6 joined"), and may show "You are one of [N] people [Name] is counting on." It does not show fragility framing, guilt language, or who cancelled.

---

## 3. Materialization Announcements Flow

**Source:** `bot/common/materialization.py`
**Trigger:** Automatic after every state transition and key participation action

### Temporal Gradient

```python
def get_time_framing_tier(event: Event) -> str:
    """
    Returns tier based on time to event.
    Operates on event state only — no user data.
    """
    if not event.scheduled_time:
        return "light"
    hours = (event.scheduled_time - datetime.utcnow()).total_seconds() / 3600
    if hours > 72:   return "light"
    elif hours > 24: return "warm"
    elif hours > 2:  return "urgent"
    else:            return "immediate"
```

### Updated Announcement Rule Table

| Trigger | Audience | Light (>72h) | Warm (24–72h) | Urgent (<24h) | Immediate (<2h) |
|---|---|---|---|---|---|
| First join | Group | "[Name] joined [event]. [N] in so far." | "[Name] joined. [N] in — getting close." | Same as warm | Same as warm |
| Participant confirms | Group | "[Name] committed. [N] in." | "[Name] committed. [N] in — [M] to go." | "[Name] committed. [N] in. [M] more needed by [time]." | Organizer DM only |
| Threshold reached | Group | "[Event] is forming. [N] confirmed." + hook | "[Event] is happening. [N] in." + hook | "[Event] is happening. [N] confirmed." | Same |
| Locked | Group | "[Event] is locked — [date/time]. [names]" + hook | Same | Same | Same |
| Near minimum | Group | "Heads up — [event] needs [M] more. Deadline: [time]." | "Still needs [M] more. Deadline in [H]h." | Organizer DM only | Organizer DM only |
| Collapse deadline passed | Group | "[Event] didn't reach the minimum and has been cancelled." | Same | Same | Same |
| Cancellation | **Organizer DM** | "[Name] stepped back. [N] still in, [min] needed. [Extend] [Waitlist]" | + time context | + urgency | + immediacy |
| Organizer note | Group | "[Event] update: [note]" | Same | Same | Same |
| 24h reminder | Group | — | "[Event] is tomorrow. [N] confirmed. [names]." | — | — |

### Memory Hook Logic

At `threshold_reached` and `locked` triggers:

```python
async def get_memory_hook(group_id: int, event_type: str) -> str | None:
    prior = await MemoryService.get_latest_with_mosaic(group_id, event_type)
    if not prior or not prior.fragments:
        return None
    shortest = min(prior.fragments, key=lambda f: f["word_count"])
    if shortest["word_count"] > 12:
        return None
    return shortest["text"]
```

If a hook is found, it is appended verbatim:
> *"[Event] is happening. 6 people confirmed — the last time your group did something like this, someone said: '[fragment]'."*

No LLM. No paraphrase. No fabrication. If no qualifying fragment exists, the announcement runs without modification.

**Sociological function:** This is the operational form of generative memory — the past appearing at the moment the group is deciding whether the present event is real. It does not tell them what to decide. It reminds them that something real happened before.

### Design Constraints

- All participant arrivals announced identically — no amplification based on history
- Cancellations never announced to the group
- Time-based framing is the only gradient — no user-based gradient
- Memory hooks are verbatim only
- "Immediate" tier routes most messages to organizer DM only

---

## 4. Waitlist Flow

**Source:** `bot/services/waitlist_service.py`
**Trigger:** Automatic when a confirmed participant cancels from an event with waitlisted users

> All positions are FIFO — determined entirely by `added_at` timestamp. No user history. No priority scoring. A rule everyone can predict is more trust-generative than an opaque algorithm, even a well-intentioned one.

### Flow Diagram

```
Confirmed participant cancels
          │
          ▼
┌─────────────────────────┐
│  WaitlistService        │
│  get_next_waitlisted()  │
└─────────────────────────┘
          │
          ├── Nobody waiting → silent (organizer notified via cancellation DM)
          │
          └── Next user found
                    │
                    ▼
          ┌───────────────────────────────────────────────────┐
          │  Response window = f(time_to_event)               │
          │  >24h → 2h  /  <24h → 30min  /  <2h → 15min      │
          └───────────────────────────────────────────────────┘
                    │
                    ▼
          ┌──────────────────────────────────────────┐
          │  DM to waitlisted user:                  │
          │  "A spot opened in [event]. You're       │
          │   next on the list. Want to join?        │
          │   [Yes, I'm in]  [No thanks]             │
          │   (Offer expires in [window].)"          │
          └──────────────────────────────────────────┘
                    │
          ┌─────────┴──────────────────────────────────┐
          │ Accepts                                    │ Declines / Times out
          ▼                                            ▼
┌─────────────────────────┐              ┌──────────────────────────┐
│  Confirm participant    │              │  Mark expired/declined   │
│  Notify organizer (DM) │              │  Move to next on list    │
│  "[Name] took the spot. │              │  (repeat from top)       │
│   [N] confirmed."       │              └──────────────────────────┘
└─────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  Standard join materialization to group             │
│  (identical to any other join — no "vacancy" framing)│
└─────────────────────────────────────────────────────┘
```

### Group Visibility

The group sees the new participant join — same announcement as any other join. It does not see:
- That someone cancelled
- That a waitlist exists
- That a spot was filled from the waitlist

The organizer sees:
- Cancellation DM with state + waitlist count + inline actions
- Follow-up DM when offer is accepted or all options exhausted

### `WaitlistService` Methods

- `add_to_waitlist(event_id, telegram_user_id)` → position
- `get_next_waitlisted(event_id)` → `EventWaitlist | None`
- `offer_spot(event_id, telegram_user_id, expires_in_minutes)` → sends DM
- `accept_offer(event_id, telegram_user_id)` → confirms + notifies organizer
- `decline_offer(event_id, telegram_user_id)` → moves to next
- `expire_offer(event_id, telegram_user_id)` → moves to next
- `get_waitlist_position(event_id, telegram_user_id)` → int | None
- `get_waitlist_count(event_id)` → int

**Invariant:** No method takes user history as input. Position is `added_at` only.

### Callbacks

| Pattern | Handler | Action |
|---|---|---|
| `waitlist_accept_{event_id}` | `waitlist.handle_accept` | Accept spot offer |
| `waitlist_decline_{event_id}` | `waitlist.handle_decline` | Decline spot offer |
| `extend_deadline_{event_id}` | `event_lifecycle.handle_extend` | Organizer extends collapse deadline |

---

## 5. Mention-Driven AI Orchestration Flow

Unchanged from v3.1, with one addition: when the bot cannot classify an action and enters meaning-formation mode, it also checks whether the group has a near-threshold active event — and may surface that as context before asking for something new.

*"Sounds like you're thinking about something outdoors. There's actually an event forming in this group right now — 3 people in, needs 1 more. Could that be it, or is this something new?"*

This is materialization-adjacent: the bot surfaces what is already forming before asking the group to create something additional.

---

## 6. Constraint Management Flow

Unchanged from v3.1. All constraints are DM-only, used for scheduling compatibility only, not for behavioral modeling.

---

## 7. Memory Contribution Flow

**Source:** `bot/handlers/feedback.py`, `bot/commands/memory.py`

### Primary Flow: Bot-Initiated DM with Reflexive Posture (Updated in v3.2)

```
Event → completed
    │
    └── [1–6 hours later] Bot DMs each confirmed participant
            │
            ├── Reflexive lineage fragment available?
            │       │
            │       └── "How was [event]?
            │            The last time your group did something like this,
            │            someone said: '[reflexive fragment]'.
            │            Anything from today you'd want to remember?
            │            A moment that worked, something that surprised you,
            │            something that didn't quite go as planned."
            │
            ├── Only triumph fragment available?
            │       └── Same structure with that fragment
            │
            └── No qualifying fragment?
                    └── "How was [event]?
                         Anything that stuck with you — a moment that worked,
                         something that surprised you, something that didn't
                         quite go as planned. Whatever comes to mind."
            │
            └── Fragment stored whenever it arrives (no deadline)
                    │
                    └── [When ≥2 fragments] Mosaic assembled + posted
```

### Reflexive Prompt Language

In all three cases above, the phrase *"something that didn't quite go as planned"* is included in the opening. This is the v3.2 change. It signals that the bot welcomes the full texture of experience — not only celebration.

**Sociological function:** A memory layer that only accepts triumph fragments builds exclusionary group identity over time ("us who always succeed"). A memory layer that holds difficulty produces reflexive identity — groups that remember how they adapted are more resilient and more open to new members. The language change is small. The identity effect accumulates over many events.

### Reflexive Fragment Preference

When selecting the fragment for the lineage door, `get_lineage_door_fragment()` applies this preference:

```python
async def get_lineage_door_fragment(
    group_id: int,
    event_type: str,
    max_words: int = 15
) -> str | None:
    prior = await get_latest_with_mosaic(group_id, event_type)
    if not prior:
        return None
    qualifying = [f for f in prior.fragments if f["word_count"] <= max_words]
    if not qualifying:
        return None
    # Prefer fragments that reference difficulty or adaptation
    reflexive_keywords = {
        "almost", "hard", "wrong", "late", "cold", "rain", "tired",
        "difficult", "unexpected", "surprised", "didn't", "couldn't",
        "changed", "figured", "adapted", "anyway", "despite", "still"
    }
    reflexive = [
        f for f in qualifying
        if any(kw in f["text"].lower() for kw in reflexive_keywords)
    ]
    if reflexive:
        return min(reflexive, key=lambda f: f["word_count"])["text"]
    return min(qualifying, key=lambda f: f["word_count"])["text"]
```

No LLM. No fabrication. Pure keyword heuristic + word count. Falls back to shortest available fragment.

### What This Flow Does NOT Do

- Set a deadline for contributions
- Prompt for structured categories
- Infer a score from the text
- Feed any behavioral formula
- Record anything beyond: this participant contributed this fragment

---

## 8. Event Modification Flow

Unchanged from v3.1.

---

## 9. Time Suggestion Flow

Unchanged from v3.1. Attendance patterns used for time suggestion are counts only (joined/completed per event type per user) — not behavioral scores.

---

## 10. Group Membership Sync Flow

Unchanged from v3.1.

---

## 11. Memory Layer Flow

**Commands:** `/memory`, `/recall`, `/remember`, `/my_history`, `/how_am_i_doing`

### Memory Activation Summary (Updated)

| When | What Surfaces | Sociological Function |
|---|---|---|
| Before event creation | Prior mosaic excerpt | Generative: past as resource for present formation |
| At failure pattern (≥3 fails) | Structural pattern mirror | Reflexive: honest mirror at group level |
| At threshold-reached | Prior fragment ≤12 words (hook) | Generative: past at the moment event becomes real |
| At event locked | Prior fragment ≤12 words (hook) | Generative: past at the moment group commits |
| In memory collection DM | Reflexive lineage door | Reflexive: full texture of experience invited |
| On `/recall` | Recent mosaic fragments | Commemorative + generative: browse group history |
| In weekly digest | Mosaic fragments + upcoming | Generative: keeps memory active between events |

Memory now surfaces at seven distinct moments. It is genuinely generative — present at the moments that matter, not archived until asked.

### Personal Attendance Mirror (`/how_am_i_doing`)

Unchanged from v3.1. Private DM. Counts only. No formula. No causal influence on system behavior.

---

## 12. Event Lineage & Note Flow

### Lineage Prompt at Event Creation (Updated)

The lineage prompt now follows the failure pattern surface. Order:

1. Failure pattern mirror (if ≥3 failed attempts) — before any memory surface
2. Fragment Mosaic excerpt from prior completed event (if available)
3. Creation flow begins

This ordering matters. The failure pattern surface is not memory — it is a structural fact about this group's coordination history. It comes first, before memory, because it may change what the group decides to create.

### Organizer Event Note Flow

Unchanged from v3.1. Notes posted verbatim, organizer-only, before event is locked.

---

## State Transition Diagram

```
                                    ┌──────────────────────────────────────────────┐
                                    │                                              │
                                    ▼                                              │
┌──────────┐   first join    ┌──────────────┐   first confirm   ┌──────────────┐  │
│ proposed │ ──────────────▶ │ interested   │ ────────────────▶ │ confirmed    │  │
└──────────┘                 └──────────────┘                   └──────────────┘  │
     │                            │                              │                │
     │ all cancel                 │ all cancel                   │ organizer lock │
     │                            │                              ▼                │
     │◀───────────────────────────┘                   ┌──────────────┐            │
     │                                                │   locked     │────────────┘
     │                                                └──────────────┘
     │                                                       │
     │                                                       │ time passed
     │                                                       ▼
     │                                                ┌──────────────┐
     │                                                │  completed   │──── triggers
     │                                                └──────────────┘     memory DM
     │                                                       │             (Flow 7)
     │                                                       │ below min at collapse_at
     │                                                       ▼
     │                                                ┌──────────────┐
     │                                                │  cancelled   │──── increments
     │                                                └──────────────┘     failure_count
     │                                                       ▲             per group+type
     └───────────────────────────────────────────────────────┘
              organizer cancel (any pre-locked state)
```

**Waitlist sub-flow (no state change to event):**
```
confirmed participant cancels
    → WaitlistService.get_next_waitlisted()
    → if found: offer_spot() DM to next user
    → if accepted: confirm participant (standard flow)
    → if declined / expired: move to next on list
```

**Failure count tracking:**
```
event cancelled (below min) OR event not completed
    → increment group_event_type_failure_count
    → check against threshold (3) for next formation attempt
```

---

## Key Services

### New in v3.2

#### `WaitlistService`

**Location:** `bot/services/waitlist_service.py`

**Purpose:** FIFO waitlist management and auto-fill.

**Invariant:** No method uses user history. Position = `added_at` only.

**Methods:** `add_to_waitlist`, `get_next_waitlisted`, `offer_spot`, `accept_offer`, `decline_offer`, `expire_offer`, `get_waitlist_position`, `get_waitlist_count`

### Updated in v3.2

#### `MaterializationService`

New dependencies: `get_time_framing_tier(event)`, `get_memory_hook(group_id, event_type)`.

Cancellation DM now includes inline buttons via `notify_organizer_private(event_id, message, buttons)`.

#### `MemoryService`

Updated methods:
- `get_lineage_door_fragment(group_id, event_type, max_words=15)` — reflexive preference, keyword heuristic, no LLM
- `get_memory_hook(group_id, event_type, max_words=12)` — shortest qualifying fragment, no LLM

New method:
- `get_failure_pattern(group_id, event_type)` — returns `{attempt_count, typical_dropout_point}` for display in meaning-formation; no individual attribution

#### `MeaningFormationService`

New method:
- `check_failure_pattern(group_id, event_type)` → `FailurePattern | None` — triggers surface in creation flow if ≥3 failed attempts

### Unchanged

`ParticipantService`, `EventLifecycleService`, `AttendanceMirrorService`, `LLMClient`, `EventMemoryService` — all unchanged from v3.1.

---

## Database Models

### Changes in v3.2

**`event_memories.fragments`:** Add `word_count` field at write time:

```json
{
  "text": "Something shifted.",
  "contributor_hash": "abc123",
  "submitted_at": "2026-04-06T20:00:00",
  "word_count": 2
}
```

Used only for hook/lineage door qualification. No behavioral inference.

**New table: `group_event_type_stats`**

```sql
CREATE TABLE IF NOT EXISTS group_event_type_stats (
    stat_id       SERIAL PRIMARY KEY,
    group_id      INTEGER NOT NULL REFERENCES groups(group_id) ON DELETE CASCADE,
    event_type    VARCHAR(100) NOT NULL,
    attempt_count INTEGER DEFAULT 0 NOT NULL,
    completed_count INTEGER DEFAULT 0 NOT NULL,
    last_dropout_point INTEGER,  -- participant count at last cancellation
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (group_id, event_type)
);
```

This table stores group-level coordination patterns. No individual user data. No attribution. Used only for the repeated failure pattern surface in meaning-formation mode.

**`event_waitlist` table:** Already in schema. Now actively used. No schema changes required.

---

## Command Reference

### New Callbacks in v3.2

| Pattern | Handler | Action |
|---|---|---|
| `waitlist_accept_{event_id}` | `waitlist.handle_accept` | Accept spot offer |
| `waitlist_decline_{event_id}` | `waitlist.handle_decline` | Decline spot offer |
| `extend_deadline_{event_id}` | `event_lifecycle.handle_extend` | Organizer extends deadline |

### Existing Commands (Unchanged)

All commands from v3.1 are preserved. See v3.1 Command Reference for the full table.

---

## Changelog

| Version | Date | Changes |
|---|---|---|
| 3.2 | 2026-04-06 | Added: soft buffer (min + capacity in creation), WaitlistService FIFO auto-fill, temporal gradient in materialization, memory hooks at threshold-reached and locked, reflexive memory prompt (invites difficulty), reflexive fragment preference in lineage door (keyword heuristic), repeated failure pattern surface in meaning-formation (group-level, no user attribution), cancellation DM with inline organizer actions, `group_event_type_stats` table. Sociological grounding integrated from academic evaluation: cognitive trust mechanism named as core product function, Dark Social Capital risk addressed via reflexive memory layer, thick trust scope boundary made explicit as design constraint. |
| 3.1 | 2026-04-05 | Pure mediation: removed all behavioral modeling, scoring, inference. |
| 3.0 | 2026-04-04 | Mediation turn: removed early feedback, surveillance, reputation algorithm. |
| 2.0 | 2026-04-02 | Added materialization, memory, lineage flows. |
| 1.0 | 2026-04-02 | Initial document. |
