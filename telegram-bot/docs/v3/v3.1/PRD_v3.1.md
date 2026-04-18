# Product Description
## Coordination Engine — Telegram Bot
### Pure Mediation: From Behavioral Inference to Relational Perception

---

| Field | Value |
|---|---|
| Status | Final — Critique-Resolved |
| Version | 3.1 |
| Product Area | Group Coordination / Social Infrastructure |
| Platform | Telegram Bot (Python / PTB) + PostgreSQL |
| Core Claim | This system does not model users. It never has. It never will. |

---

## What This System Is

### A Pure Mediation System

The system's only mechanism is **shaping how people perceive what is forming**.

It does not:
- Predict behavior
- Score participation
- Steer outcomes
- Model reliability
- Adjust treatment based on history

It does:
- Show who has joined
- Show who has confirmed
- Show how close the event is to threshold
- Show what the group remembered last time
- Let participants declare constraints privately

That is the complete set of causal mechanisms.

### A Recognition Environment

Recognition means: **I see that you are here. I see what you are bringing.**

It does not mean: *The system has evaluated you and found you reliable.*

The bot announces joins and confirms equally. Every participant is announced the same way. No one is amplified. No one is silently deprioritized.

### An Absent Friend (Not a Pipeline)

An absent friend:
- Has no deadline for hearing your story
- Does not structure what you say
- Does not synthesize your words into something else
- Simply receives and holds what you offer

The memory flow has no collection window. No required categories. No synthesis. Fragments are presented as they arrived — plural, unresolved, co-existing without hierarchy.

### A Memory Driver (Not an Artifact)

Memory is not what happens after an event. Memory is what makes the next event possible.

When a group creates a new event of the same type, the system shows them what they remembered last time — before they configure anything else. The past is present at the moment of formation.

---

## What This System Is Not

### Not a Behavioral Modeling System

This system does not:
- Extract signals from participation
- Infer reliability, trust, civility, cooperation, or commitment
- Maintain scores — visible or invisible
- Use attendance history to change outcomes for any user
- Learn from user behavior over time

The attendance counts a user can see privately are just that — counts. They influence nothing the system does. They are for the user's own reflection, not for the system's decisions.

### Not a Steering System

The system does not steer individuals. It only reveals shared reality

This system does not:
- Adjust confirmation windows based on inferred reliability
- Prioritize some users over others for event access
- Send different messages to different users based on their history
- Engineer social pressure through fragility framing
- Amplify some participants' arrivals over others

The only thing that determines what a user sees or experiences is:
- Their declared intent (join, confirm, cancel)
- Their declared constraints (availability, conditions)
- The state of the event (how many have joined, confirmed)

### Not a Meaning-Centralizing System

This system does not:
- Synthesize memory fragments into a unified narrative
- Assign tone categories to contributions
- Decide which fragments matter more
- Write conclusions or takeaways
- Interpret what happened

The Fragment Mosaic is the fragments themselves — arranged for readability, but with no words added, no interpretation, no synthesis. The LLM is constrained to rearrangement only. If it cannot be constrained, the mosaic is assembled without it.

### Not a Surveillance System

This system does not:
- Store chat history for behavioral inference
- Track user behavior beyond factual attendance
- Maintain logs that connect behavior to future treatment
- Observe what users cannot observe about themselves

Chat history (40 messages) is retained for action context only — "what event are we talking about" — and is pruned after 90 days. It is never used for modeling.

---

## The Complete List of System Inputs That Affect Outcomes

This is exhaustive. If it's not on this list, the system does not use it to change what happens.

| Input | Used For | Does It Produce Different Outcomes for Different Users? |
|---|---|---|
| User joins an event | Adding to participant list; triggering join announcement | No — all joins announced equally |
| User confirms attendance | Moving to confirmed list; triggering confirmation announcement | No — all confirms announced equally |
| User cancels | Removing from participant list; DM to organizer only | No — cancellation always private |
| Event reaches minimum participants | Threshold announcement | No — based on count only |
| Event passes collapse deadline | Auto-cancellation | No — based on time and count only |
| User declares availability constraint | Time suggestion calculation | No — availability is merged neutrally |
| User declares conditional constraint | Eligibility checking | No — condition evaluated deterministically |
| User contributes memory fragment | Fragment stored; mosaic assembled when ≥2 exist | No — all fragments treated equally |
| User requests personal attendance mirror | Private display of counts by event type | No — user sees only their own data |

**There is no column for "reliability score," "trust inference," or "behavioral pattern."** Those do not exist in the system.

---

## The Six Mediation Levers (Complete Set)

These are the only mechanisms the system has. None require behavioral data. All are about perception.

### 1. Timing
When the system speaks matters. A threshold announcement at 48 hours feels different than at 2 hours. The system controls timing — not to steer behavior, but to show reality at the right moment.

### 2. Framing
"3 people joined" vs. "This is close to happening" — same fact, different relational experience. The system chooses framing that makes formation visible, not that engineers response.

### 3. Visibility (Without Analysis)
Who is in. How many are needed. What the group remembered. These facts, made visible at the right moment, shape mutual awareness. No scoring required.

### 4. Language
Every word the bot uses is a design decision. "Confirm participation" and "others are counting on you" are not the same. The bot uses language that shows reality, not that manufactures guilt.

### 5. Sequence
What comes first shapes what is possible. Memory surfaces before creation. The bot asks about intent before asking about structure. Sequence encodes philosophy.

### 6. Memory Surfacing
Not memory analysis. Not memory synthesis. Simply: when a group tries to do something again, they first see what they remembered last time.

---

## The Bot's Voice (Functional Requirement)

### Before Structure (Meaning-Formation Mode)

When a user signals they want to organize something, the bot does not immediately ask "What type of event?"

It asks:
> *"What are you trying to bring together?"*

Or:
> *"Is this something that needs a fixed time, or just a moment for a certain group?"*

The bot stays with vagueness if the user is vague:
> *"That sounds like it could be a few things — do you have a sense of who needs to be there for it to feel right?"*

Only when intent is clear does the bot shift to structured flow.

### During Coordination (Quiet Facilitation Mode)

The bot is a background orchestrator. It facilitates without crowding the space. Messages are brief, specific, relational. The bot does not explain itself, offer unsolicited options, or manufacture urgency.

### During Memory Collection (Receiving Mode)

The bot is receiving, not collecting. No deadline. No structure. No categories.

> *"Hey — how was [event]? Anything that stuck with you? A word, a moment, a photo — whatever comes to mind."*

The bot does not ask follow-up questions. It does not prompt for specific categories. It says thank you and holds what was offered.

---

## The One Question That Decides Everything

> If two users behave identically in the system, but you believe one is more reliable… should the system treat them differently?

**Answer:** No.

The system does not hold beliefs about users. It does not infer reliability. It does not compute trust. It does not maintain scores — hidden or visible. It does not adjust timing, priority, access, or any other variable based on what it thinks about a user.

The system knows three things about a user:
1. Their Telegram identity (name, ID)
2. What events they have joined or confirmed (factual attendance counts)
3. What constraints they have declared (availability, conditional participation)

That is all. None of these are used as inputs to any algorithm that produces different outcomes for different users.

---

## The Materialization Test (For Every Message)

Before any materialization announcement is sent, it must pass this test:

> **Does this show what is forming, or does it engineer a response?**

| Message | Pass/Fail | Why |
|---|---|---|
| "[Name] just joined. [N] people are in." | Pass | Shows reality |
| "We need 2 more for this to happen." | Pass (threshold context) | Shows reality |
| "If one more person drops, this event collapses." | Fail | Engineers dread |
| "[Name], who's been to every session, just joined." | Fail | Creates hierarchy |
| "Heads up — [event] needs [N] more. Deadline: [time]." | Pass | Shows reality without guilt |
| "X is counting on you." | Fail | Engineers personal responsibility |

The group is informed. The system does not engineer guilt.

---

## The Memory Mosaic Test (For LLM Constraint)

Before any Fragment Mosaic is assembled, the LLM prompt must enforce:

> **You may rearrange fragments for readability. You may not add words that were not in the fragments. You may not label, categorize, interpret, or synthesize. The output must contain only the participants' words, in their original form, possibly reordered.**

| Output Type | Pass/Fail | Why |
|---|---|---|
| "The rain made it better." / "Best three hours." | Pass | Participant words only |
| "The group enjoyed a memorable adventure with unexpected weather." | Fail | Synthesis, not fragments |
| "Fragment 1: The rain made it better. Fragment 2: Best three hours." | Pass (if labels are minimal layout) | No interpretation |
| "Several people mentioned the weather." | Fail | Interpretation, not fragment |

If the LLM cannot be constrained to this, the mosaic is assembled without LLM — simple chronological list.

---

## The Personal Attendance Mirror (Complete Specification)

When a user sends `/how_am_i_doing` (private DM only), the bot responds:

Your attendance by event type:

• Hiking: 8 joined, 7 completed
• Work meetups: 3 joined, 3 completed
• Social: 5 joined, 4 completed


**Constraints:**
- No score. No formula. No weighting.
- No comparison to others ("you are in the top 20%" — forbidden)
- No trend analysis ("your reliability is improving" — forbidden)
- No influence on system behavior (these counts are never read by any algorithm that affects outcomes)
- Private to the user — no other user can query this data

**What this is:** A mirror. The user sees their own pattern. The system does nothing with it.

**What this is not:** A reputation system, a scoring system, a behavioral model, or an input to any decision.

---

## Data: What Is Stored, What Is Not, What Is Pruned

### Stored Indefinitely
- Event metadata (type, time, threshold, location)
- Participant list per event (who joined, confirmed, cancelled)
- Memory fragments (anonymized by default)
- Constraint declarations (private to user)

### Stored for 90 Days, Then Pruned
- Chat history (40 messages per group) — for action context only, never used for modeling
- State transition logs (audit trail)
- Idempotency keys

### Never Stored
- Behavioral inferences of any kind
- Reliability scores or any derived user quality
- LLM inputs or outputs beyond what is explicitly logged for debugging (debug logs pruned at 7 days)
- Chat history beyond 40 messages per group

### Never Collected
- User location (beyond declared constraints)
- User relationships (beyond declared conditional constraints)
- User message content outside the 40-message rolling window
- Any data from Telegram that is not explicitly required for coordination

---

## The Fundamental Test for Any Future Feature

Before any feature is added, it must pass this test:

> **Does the system act on inferred qualities of users?**

| Feature Type | Pass/Fail | Condition |
|---|---|---|
| Shows who has joined | Pass | Shows reality |
| Adjusts confirmation window based on attendance history | Fail | Acts on inference |
| Prioritizes some users for event access | Fail | Acts on inference |
| Sends different messages to different users based on behavior | Fail | Acts on inference |
| Shows "you have attended 8 of 10 hiking events" (private, no system action) | Pass | Shows reality, no action |
| Uses LLM to summarize who the "core group" is | Fail | Acts on inference |
| Surfaces prior memory fragments during event creation | Pass | Shows reality |
| Hides event from users inferred to be unreliable | Fail | Acts on inference |

**The rule is simple:** If the feature would behave differently for User A than User B based on anything other than User A's and User B's declared intent at this moment, it fails.

---

## What This System Delivers (Value Proposition)

Telegram gives communication.

This system adds **relational structure over communication** — through timing, framing, visibility, language, sequence, and memory surfacing.

No behavioral data needed. No inference required. No hidden steering.

The value is not knowing more about people.

The value is shaping how people relate to what they already know is forming.

When people can see who else is in — genuinely, not through engineered perception — they act accordingly. Not because the system pressured them. Because they chose to.

That is the system.

---

## Where This Can Fail (Philosophically)

Not technically.

Philosophically.

### Failure Mode 1 — Romantic Neutrality

If the system becomes:

→ too passive

Groups may:

• repeatedly fail
• not self-correct
• lose energy

Because no mechanism helps them see patterns over time

### Failure Mode 2 — Hidden Social Hierarchy

Even without system bias:

Humans will still:

• notice reliability
• form informal cores
• create influence

Your system doesn’t create hierarchy.

But it also doesn’t surface it consciously.

That’s subtle.

### Failure Mode 3 — Memory Without Reflection

If fragments are:

• never revisited meaningfully
• never connected over time

Memory becomes:

→ archive
not
→ living context

---

## Version History

| Version | Date | Changes |
|---|---|---|
| 3.0 | 2026-04-04 | Complete removal of all behavioral inference. System never acts on inferred user qualities. Memory mosaic has no LLM synthesis — rearrangement only. Materialization messages tested against "show reality, not engineer response." Personal Attendance Mirror is causally inert. All feature tests documented. |
