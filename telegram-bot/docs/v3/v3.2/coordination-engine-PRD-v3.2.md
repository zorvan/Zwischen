# Product Requirements Document
## Coordination Engine — Telegram Bot
### The Resilience Turn: Event-Level Adaptation, Sociologically Grounded

---

| Field | Value |
|---|---|
| Status | Draft — Post-Critique Revision (Sociological Alignment) |
| Version | 3.2 |
| Previous Version | 3.1 — Pure Mediation |
| Product Area | Group Coordination / Social Infrastructure |
| Platform | Telegram Bot (Python / PTB) + PostgreSQL |
| Core Claim | The system does not model users. It builds cognitive trust through predictable coordination. |

---

## Table of Contents

1. [What Changed and Why](#1-what-changed-and-why)
2. [Vision & Product Philosophy](#2-vision--product-philosophy)
3. [Sociological Foundation](#3-sociological-foundation)
4. [The Critique That Forced This Revision](#4-the-critique-that-forced-this-revision)
5. [The Resolution: A New Distinction](#5-the-resolution-a-new-distinction)
6. [The Mediation Architecture](#6-the-mediation-architecture)
7. [Feature Specifications](#7-feature-specifications)
8. [Engineering Work — Prioritized Backlog](#8-engineering-work--prioritized-backlog)
9. [Non-Functional Requirements](#9-non-functional-requirements)
10. [Open Design Decisions](#10-open-design-decisions)
11. [What This System Is (And Is Not)](#11-what-this-system-is-and-is-not)

---

## 1. What Changed and Why

Version 3.1 achieved philosophical consistency. It removed behavioral scoring, hidden surveillance, soft coercion, and LLM narrative authority. These were the right decisions and they stand.

But v3.1 had a structural gap it did not acknowledge: it removed enforcement without adding adaptation. The result is a system that is philosophically correct and operationally brittle — beautiful in high-trust contexts, but fragile when real-world variance enters. And variance always enters.

The critique that produced v3.2 identified this gap precisely:

> "You didn't remove enforcement. You removed adaptation."

That is accurate. This version adds adaptation back — but at the event level, not the user level. The distinction is the entire design. It is what separates a resilience mechanism from a reputation system.

An academic sociological evaluation was subsequently conducted against the framework of trust formation under anomie. That evaluation confirmed the system's core alignment with established sociological theory — and surfaced one open gap (the Dark Social Capital risk) that this version now addresses structurally.

**What is new in v3.2:**
- Event-level soft buffer: events may open capacity beyond `min_participants` to absorb dropout variance
- Waitlist auto-fill: FIFO spot offers when confirmed participants cancel
- Temporal gradient in materialization: tone calibrated to time-to-event, not to user history
- Memory activation at six lifecycle moments: memory is generative, not commemorative
- Reflexive memory prompt and fragment selection: difficulty and adaptation are invited alongside celebration
- Repeated failure pattern surface: honest group-level mirror during meaning-formation
- Cancellation notifications with inline organizer actions

**What is NOT new in v3.2:**
- No user-level scoring, ranking, or behavioral modeling
- No differential treatment of participants based on history
- No punitive mechanisms
- No manufactured emotional pressure
- No LLM authority over meaning

---

## 2. Vision & Product Philosophy

### 2.1 The North Star

> This system exists to help groups bring things into existence together — and to leave behind shared memories strong enough to shape future behavior.

### 2.2 Primary KPI

> Richness and frequency of shared experiences that members reference later, replicate, and use as cultural building blocks.

### 2.3 Design Principles

#### Principle 1: Mediation Over Measurement

The system's value is shaping how people relate to what is forming — not modeling who they are. The six mediation levers are the mechanism: timing, framing, visibility, language, sequence, memory surfacing. None require behavioral data. All require intentional design.

#### Principle 2: Emergence Over Stabilization (Refined)

The system adapts to event states, not to user patterns. An event that is one person from collapse at T-2h is a different thing than the same event at T-48h. The system should express that difference — through timing and framing, not through judgment of who caused it.

#### Principle 3: Visibility Without Analysis

Show who is in, how close to threshold, what the group remembered before. Do not analyze what it means about anyone.

#### Principle 4: Memory as Generative Driver, Not Commemorative Artifact

The distinction between generative memory (the past as a resource for present action) and commemorative memory (the past as a monument) is critical. This system must be a generative memory engine. Memory must also be reflexive — it should hold difficulty and adaptation alongside success. Groups that only remember their triumphs build exclusionary identity. Groups that remember how they adapted build open, resilient trust.

#### Principle 5: Event-Level Adaptation, User-Level Neutrality

When an event is structurally fragile, the system is allowed to respond — structurally. A buffer. A waitlist. Situational language. None of these responses require knowing anything about who the participants are. They require only knowing the state of the event.

#### Principle 6: Cognitive Trust Through Predictable Coordination (Sociologically Grounded)

In the sociological literature on trust under anomie, trust becomes functional before it becomes moral. Groups do not first trust each other because they feel affection — they come to trust each other because they have learned to predict each other through repeated successful coordination. Every completed event is a coordination game won. The memory layer stores that evidence in human form. The materialization layer makes it visible at the moments it matters most. This is the mechanism by which the system generates thick trust without modeling individuals.

---

## 3. Sociological Foundation

This section documents the alignment of the system's design with the sociology of trust formation under conditions of social fragility. It is not decorative. It functions as a design constraint: any future feature must be evaluated against these frameworks.

### 3.1 Thick Trust vs. Thin Trust

Sociological theory distinguishes thin trust (generalized trust in strangers and institutions) from thick trust (intense, localized bonds based on shared identity and repeated face-to-face interaction). In environments where thin trust has eroded — through anomie, institutional breakdown, or social fragmentation — groups retreat to thick trust as their primary coordination mechanism.

This system operates at the thick trust layer by design. It serves tight-knit groups who already have or are building shared identity. This is the correct scope. The coordination of strangers requires different mechanisms, different philosophy, and a different product.

**Design constraint:** The system should not be extended to anonymous group coordination without full reconsideration of its foundational assumptions.

### 3.2 Cognitive Trust and the Predictability Mechanism

In anomic or high-uncertainty environments, trust migrates from a moral quality to a functional one. Groups build trust through coordination games: repeated encounters where members demonstrate the capacity to solve practical problems together. The result is cognitive trust — reliable prediction of others' behavior. This is not warm feeling; it is evidence-based dependability.

The most potent trust-generator in a fragile environment is not the memory of shared experience as such — it is the evidence of reliability that shared experience in the present provides, which accumulates over time into a new tradition.

**Design implication:** Completion of events is not just the KPI — it is the mechanism. Every event that completes is a coordination game won. The memory layer stores the evidence. The lineage mechanism connects it to the next attempt. Reliability is not scored or ranked; it emerges from the accumulation of completed, remembered events.

**Alignment verdict:** Strong. The system's architecture is functionally a cognitive trust generator, even though it was not originally framed this way.

### 3.3 Generative vs. Commemorative Memory

Commemorative memory looks backward at shared experience as an end in itself — it reinforces group identity but does not drive new action. Generative memory is forward-looking — it uses past experience as evidence for what is possible now.

Groups that rely on purely commemorative memory tend to become defensive: high in internal cohesion, resistant to new challenges, and increasingly self-referential. Groups that maintain generative memory use the past as a resource for the present rather than a monument.

**Design implication:** The Fragment Mosaic must not become a trophy case. The memory hook mechanism — surfacing prior fragments at the moment of new event formation — is the primary mechanism that keeps memory generative. In v3.2 this hook fires at six distinct lifecycle moments, not only before creation.

**Alignment verdict:** Partially aligned in v3.1; fully aligned in v3.2 with the expanded memory hook and the reflexive prompt.

### 3.4 The Dark Social Capital Risk (The Open Gap — Now Addressed)

Bonding social capital — the intense internal trust that shared memory and repeated coordination generates — tends to develop at the expense of bridging social capital — openness to new members, cross-group cooperation, and willingness to extend trust beyond the established in-group.

If memory only records shared triumphs, it creates a narrative of "us who showed up" that implicitly defines "them who didn't." The memory ledger becomes a tool for boundary maintenance rather than trust construction.

The sociological solution is reflexive memory: memory that includes not just the experience itself, but also the moments of difficulty, adaptation, and what the group had to figure out. A group that remembers "we almost didn't make it and had to adapt" is more resilient and less exclusionary than a group that only remembers "we succeeded."

**Design implication:** Two structural changes are introduced in v3.2 to address this risk directly.

First, the memory collection prompt is updated to explicitly invite difficulty alongside celebration — "something that didn't quite go as planned" is added as a valid frame. This is a language change, but language shapes what people feel entitled to contribute.

Second, the fragment selection logic for the lineage door now carries a reflexive preference: when available and short enough, prefer a fragment that reflects difficulty or adaptation over one that reflects only triumph. The system cannot control what people remember, but it can show the range of what it values by what it chooses to surface.

Third, when a group has attempted the same event type multiple times without completing, the system surfaces this pattern honestly at the next formation attempt — not as judgment, but as raw information the group can use to reconfigure.

**Alignment verdict:** Gap identified in the academic evaluation; addressed in v3.2 through the reflexive prompt, reflexive fragment preference, and repeated failure pattern surface.

### 3.5 Competitive Victimhood and the Ledger Problem

Sociological literature on post-conflict trust identifies the "competitive victimhood" trap: when group memory focuses on who suffered most, the memory becomes a ledger of debts that cannot be paid, making trust impossible.

The Fragment Mosaic is structurally protected against this because it was never designed to record actions, failures, or attribution. It records only what people chose to remember. No participant is named in connection with any outcome. The mosaic holds experience, not accountability.

**Alignment verdict:** Strong. The design choice to exclude action logs from the memory layer, and to keep fragment contributors anonymous by default, was philosophically motivated but is also the correct sociological decision.

---

## 4. The Critique That Forced This Revision

### 4.1 The Structural Gap

In v3.1, when a 4-person tennis event loses a confirmed participant at the last minute, the system does nothing. It records the state change and goes silent. The group absorbs the asymmetry informally. An invisible hierarchy emerges outside the system — exactly the kind of social stratification the system was designed to prevent.

This is the failure mode of over-corrected neutrality: enforcing equal treatment so strictly that the system loses the capacity to protect the group at all.

### 4.2 Memory Layer Was Commemorative, Not Generative

The sociological frame clarified what the structural critique had noted in passing: memory must be generative, not merely commemorative. In v3.1, the Fragment Mosaic preserved what happened but did not activate what could happen next. The hook mechanism in v3.2 closes this gap.

### 4.3 Neutrality Was Disengaging

The system produced no hooks — nothing that made a participant feel the specific texture of this event, at this moment, in this group. Neutrality in service of dignity is correct. Neutrality as a design aesthetic is disengaging. The temporal gradient in materialization is the structural response.

### 4.4 Memory Had No Reflexive Dimension

The academic evaluation identified that a memory layer that only records triumph risks building exclusionary group identity over time. The reflexive prompt and fragment preference in v3.2 address this.

---

## 5. The Resolution: A New Distinction

> When reality becomes unstable, what is allowed to change?

**Event structure is allowed to adapt. User treatment is not.**

| Allowed to adapt | Not allowed to adapt |
|---|---|
| How many buffer slots an event opens | Who gets those slots first (all equal, FIFO) |
| Whether a waitlist is active | Who is prioritized on that waitlist |
| The urgency of language near a deadline | The warmth of language toward any individual |
| What memory is surfaced at formation | Whose memories are valued more |
| What pattern is mirrored to the group | Who in the group caused that pattern |

---

## 6. The Mediation Architecture

### Layer Overview

| Layer | Name | What It Does | What It Does NOT Do |
|---|---|---|---|
| Layer 1 | Coordination (Constraint) | Event lifecycle, thresholds, deadlines | Model users |
| Layer 1b | Resilience (Buffer + Waitlist) | Absorbs variance at event level | Distinguish between users |
| Layer 2 | Perception Shaping | Announces formation; situational sensitivity | Engineer guilt; judge anyone |
| Layer 3 | Memory (Generative + Reflexive) | Activates past for present; holds difficulty | Synthesize meaning; build exclusionary identity |

### 6.1 Layer 1b — Event Resilience

**Soft Buffer:** `target_participants` is surfaced at creation as comfortable capacity. The gap between `min_participants` and `target_participants` is active redundancy. Defaults: `target_participants = ceil(min_participants * 1.5)`.

**Waitlist Auto-Fill:** FIFO. When a confirmed participant cancels, the next waitlisted user is offered the spot with a time-scaled response window (>24h: 2h, <24h: 30min, <2h: 15min). The cancellation remains group-private. The fill appears to the group as a normal join.

**Collapse Notification:** At `collapse_at`, the organizer receives a private actionable DM — not silence. State, time remaining, waitlist count, inline buttons.

**Repeated Failure Pattern Surface:** When a group has attempted the same event type ≥3 times without completing, this is surfaced as raw information during the next meaning-formation phase — before the structured creation flow begins. No user is named. No blame is implied. The system reports a structural pattern; the group decides what to do with it.

### 6.2 Layer 2 — Perception Shaping

**Temporal Gradient:** `get_time_framing_tier(event)` returns `light | warm | urgent | immediate` based on `scheduled_time - now()`. All time-sensitive announcement templates are parameterized by tier. The gradient is time-based exclusively — no user data involved.

**Memory Hooks:** At threshold-reached and locked announcements, a prior verbatim fragment (≤12 words) from the most recent completed event of the same type may be appended. No LLM. Verbatim retrieval only.

**Cancellation-with-Action DM:** Private to organizer. Now includes: confirmed count, minimum needed, time to event or collapse, waitlist count, [Extend Deadline] and [View Waitlist] inline buttons.

### 6.3 Layer 3 — Memory (Generative + Reflexive)

**Six Activation Points:**

| When | What Surfaces | How |
|---|---|---|
| Before event creation | Prior mosaic excerpt | `start_meaning_formation` flow |
| At threshold-reached | Prior fragment (≤12 words) | Memory hook in announcement |
| At event locked | Prior fragment (≤12 words) | Memory hook in announcement |
| In memory collection DM | Reflexive lineage door | Opening of post-event DM |
| On `/recall` | Recent mosaic fragments | Command-driven retrieval |
| In weekly digest | Mosaic fragments + upcoming | Scheduled opt-in task |

**Reflexive Memory Prompt:** The memory collection DM now explicitly holds space for difficulty:
> *"How was [event]? Anything that stuck with you — a moment that worked, something that surprised you, something that didn't quite go as planned. Whatever comes to mind."*

This is a language change only. The bot still receives whatever the participant offers without structure or deadline.

**Reflexive Fragment Preference:** When selecting the fragment for the lineage door, the system prefers fragments that reference difficulty or adaptation (if one exists and is ≤15 words) over fragments that only reflect triumph. Falls back to shortest available fragment. No LLM. No fabrication.

**Reflexive Lineage Door:**
- If reflexive fragment available: *"How was [event]? The last time your group did something like this, someone said: '[fragment]'. Anything from today you'd want to remember?"*
- If only triumph fragment available: same structure, with that fragment
- If no prior fragment qualifies: *"How was [event]? Anything that stuck with you?"*

---

## 7. Feature Specifications

### 7.1 Existing Features — Status

| Feature | Status | Notes |
|---|---|---|
| Event state machine | ✅ Working | No change |
| Normalized `event_participants` | ✅ Working | No change |
| `EventStateTransitionService` | ✅ Working | No change |
| Materialization announcements | ✅ Working | Extended: temporal gradient, memory hooks |
| Memory contribution DM | ✅ Working | Extended: reflexive prompt, reflexive lineage door |
| Fragment Mosaic assembly | ✅ Working | No change to assembly rules |
| Personal Attendance Mirror | ✅ Working | No change |
| Meaning-Formation Mode | ✅ Working | Extended: repeated failure pattern surface |
| `event_waitlist` table | ✅ Schema exists | Auto-fill logic to be wired |
| `/event_note` command | ✅ Working | No change |
| Constraint management (DM) | ✅ Working | No change |
| Lineage prompt at creation | ✅ Working | Extended: also fires at threshold/locked via hook |

### 7.2 New Features — v3.2

**Soft Buffer:** Two-number creation flow (minimum + comfortable capacity). Buffer is the gap.

**Waitlist Auto-Fill:** `WaitlistService` with FIFO logic, time-scaled response windows, organizer notification on fill.

**Temporal Gradient in Materialization:** `get_time_framing_tier()` helper; all time-sensitive templates parameterized by tier.

**Cancellation-with-Action DM:** State + inline buttons for organizer on every cancellation.

**Memory Hooks:** Verbatim fragment at threshold-reached and locked announcements, ≤12 words.

**Reflexive Memory Prompt:** Language update to collection DM — invites difficulty alongside celebration.

**Reflexive Fragment Preference:** Lineage door fragment selection prefers difficulty/adaptation fragments. No LLM.

**Repeated Failure Pattern Surface:** Group-level pattern mirror in meaning-formation mode after ≥3 failed attempts of same event type.

---

## 8. Engineering Work — Prioritized Backlog

### 8.1 Priority 1 — Philosophy-Preserving Resilience (New in v3.2)

| Work Item | Effort | Test |
|---|---|---|
| `WaitlistService` with FIFO auto-fill | Medium | No user history in any method |
| Wire waitlist auto-fill to cancellation trigger | Small | Cancellation private; fill organizer-notified |
| Temporal gradient in materialization messages | Small | Time-based framing only |
| Cancellation DM: state + inline action buttons | Small | Still private to organizer |
| `get_time_framing_tier()` helper | Small | Event state only |
| Memory hook at threshold-reached and locked | Small | Verbatim fragment, no LLM |
| Reflexive memory collection prompt | Trivial | Language change only |
| Reflexive fragment preference in lineage door | Small | Preference rule, no LLM |
| Repeated failure pattern surface in meaning-formation | Small | Group-level data only, no user attribution |
| Event creation: min and capacity as separate inputs | Small | Framed as capacity |
| `event_memories.fragments` schema: add `word_count` field | Trivial | Write-time only; no inference |

### 8.2 Priority 2 — Existing Backlog

| Work Item | Effort |
|---|---|
| Organizer role rotation at lineage prompt | Medium |
| Weekly group digest | Small |
| Data minimization: log pruning after 90 days | Medium |

### 8.3 Priority 3 — Production Hardening

RBAC, rate limiting, LLM validation, callback replay protection, CI pipeline, Prometheus + SLO dashboards, secret management, database tuning and backup drills.

---

## 9. Non-Functional Requirements

### 9.1 Privacy & Data Ethics

Waitlist status is private to the participant and organizer — never shown in group context.

Repeated failure pattern data is group-level: how many times was this event type attempted and completed. No individual attribution is stored or surfaced. The system reports the structural pattern; it does not report who contributed to it.

All other privacy requirements from v3.1 are preserved.

### 9.2 The Adaptation Boundary

Any proposed mechanism must pass this test: **does it require user identity or history to function?**

If yes → user-level adaptation → do not build.
If no → event-level adaptation → evaluate for inclusion.

### 9.3 The Dark Social Capital Boundary

Any feature touching memory, lineage, or group identity must pass a second test: **does this mechanism risk producing exclusionary group identity?**

Warning signs:
- Memory that only records success, never difficulty
- Fragment selection that surfaces only triumph
- Language that implies "us who showed up" vs. "them who didn't"
- Any mechanism that makes failure invisible in the memory layer

The reflexive prompt and the reflexive fragment preference are the current defenses. They must be maintained. Any future feature that narrows the range of what the memory layer accepts should be scrutinized against this boundary.

### 9.4 Bot Persona

In v3.2 the bot has a tonal range calibrated to time-to-event: light, warm, urgent, direct. It does not adjust tone based on who is participating. The reflexive prompt is an expansion of the receiving posture, not a new persona mode — the bot still receives whatever the participant offers, but the opening it provides is broader.

---

## 10. Open Design Decisions

| Question | Options | Implication |
|---|---|---|
| Buffer size: fixed (25%) or organizer-chosen? | Fixed default vs. slider | Fixed is simpler; organizer-chosen is more expressive |
| Waitlist position shown to user? | "You're #2" vs. "You're on the list" | Position may create anxiety about being passed over |
| Memory hook: locked only, or also threshold-reached? | Both vs. locked only | Both creates more resonance |
| Repeated failure surface: after 2 or 3 failures? | 2 vs. 3 | 2 may feel premature; 3 risks too much accumulated scar tissue |
| Reflexive fragment preference: disclosed to contributors? | Disclose / Silent | Disclosure ("we especially welcome what was hard") may usefully shape contributions |
| Organizer deadline override: permitted? | Yes (extend button) / No | Yes gives agency; No enforces group commitment to declared parameters |

---

## 11. What This System Is (And Is Not)

### This system IS

- A coordination environment that helps groups bring events into existence together
- A cognitive trust generator: repeated successful coordination produces predictability, and predictability is the foundation of thick trust
- A generative memory engine: the past activates the present rather than being stored as a monument
- A reflexive memory holder: difficulty and adaptation are explicitly welcomed alongside celebration, as a defense against exclusionary group identity
- A resilience layer that absorbs variance at the event level without modeling individuals
- A perception-shaping layer with situational sensitivity calibrated to event state and time
- A micro-culture generator that takes the Dark Social Capital risk seriously

### This system is NOT

- A system that models users, scores behavior, or ranks participants
- A system that treats participants differently based on their history
- A soft surveillance platform, however well-intentioned
- A system that manufactures emotional pressure or engineered guilt
- A passive observer that does nothing when events are fragile
- A system that only records group triumphs and builds exclusionary identity from them
- A thin-trust system: it does not generalize across strangers and should not be extended to do so without full design reconsideration

---

> **The Principle This Version Is Built On**
>
> *The system does not model users. It builds cognitive trust through predictable coordination.*
>
> Every completed event is a coordination game won.
> Every remembered difficulty is a piece of reflexive identity — protection against the group becoming a closed circle.
> Every repeated failure, honestly surfaced, is an invitation to adapt.
>
> The group is not a collection of reliable and unreliable individuals.
> It is a social structure that learns — if the system gives it an honest mirror.
