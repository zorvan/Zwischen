# Coordination Engine Bot

**Pure Mediation: From Behavioral Inference to Relational Perception**

Current release: `v3.3.0` - Social Visibility
Supported Python: `3.13` to `3.14`

New features:
- Live event cards with participant counts and hashtags
- Memory-first event creation flow
- Living artifacts with event lineage
- Hashtag search and permanent event identity

A Telegram bot that mediates group coordination through perception, not prediction. It shapes how people relate to what is forming — without modeling users, inferring reliability, or steering outcomes.

---

## The Problem This Solves

Traditional coordination systems create hidden asymmetries:

- They observe and model user behavior over time
- They infer "reliability" and adjust access/priorities accordingly
- They engineer social pressure through fragility framing
- They synthesize memory into unified narratives
- They create surveillance dynamics, even when well-intentioned

The result: groups coordinate around system-defined variables, not shared intention. Trust becomes computational, not relational. Meaning gets centralized, not plural.

This system rejects that foundation entirely.

---

## What This System Is

### A Pure Mediation System

The system's only mechanism is **shaping how people perceive what is forming**.

It does not:

- Predict behavior or model users
- Score participation or infer reliability
- Steer outcomes or adjust treatment based on history
- Learn from user behavior over time

It does:

- Show who has joined and confirmed equally
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

## The Six Mediation Levers

These are the only mechanisms the system has. None require behavioral data. All are about perception.

### 1. Timing

When the system speaks matters. A threshold announcement at 48 hours feels different than at 2 hours.

### 2. Framing

"3 people joined" vs. "This is close to happening" — same fact, different relational experience.

### 3. Visibility (Without Analysis)

Who is in. How many are needed. What the group remembered. These facts, made visible at the right moment.

### 4. Language

Every word the bot uses is a design decision. "Confirm participation" and "others are counting on you" are not the same.

### 5. Sequence

What comes first shapes what is possible. Memory surfaces before creation. The bot asks about intent before asking about structure.

### 6. Memory Surfacing

Not memory analysis. Not memory synthesis. Simply: when a group tries to do something again, they first see what they remembered last time.

---

## The Complete List of System Inputs That Affect Outcomes

This is exhaustive. If it's not on this list, the system does not use it to change what happens.

| Input | Used For | Different Outcomes for Different Users? |
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

## The Bot's Voice

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

## The Materialization Test

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

## The Memory Mosaic Test

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

## The Personal Attendance Mirror

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

The Fragment Mosaic is the fragments themselves — arranged for readability, but with no words added, no interpretation, no synthesis. The LLM is constrained to rearrangement only. If it cannot be constrained, the mosaic is assembled without it.

### Not a Surveillance System

This system does not:

- Store chat history for behavioral inference
- Track user behavior beyond factual attendance
- Maintain logs that connect behavior to future treatment
- Observe what users cannot observe about themselves

Chat history (40 messages) is retained for action context only — "what event are we talking about" — and is pruned after 90 days. It is never used for modeling.

---

## What This System Delivers

Telegram gives communication.

This system adds **relational structure over communication** — through timing, framing, visibility, language, sequence, and memory surfacing.

No behavioral data needed. No inference required. No hidden steering.

The value is not knowing more about people.

The value is shaping how people relate to what they already know is forming.

When people can see who else is in — genuinely, not through engineered perception — they act accordingly. Not because the system pressured them. Because they chose to.

That is the system.

---

## Quick Start

**Get running in 15 minutes:** See [docs/v2/QUICKSTART.md](docs/v2/QUICKSTART.md)

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Telegram token and database URL

# Run database migrations
PGPASSWORD=coord_pass psql -h localhost -U coord_user -d coord_db -f db/schema.sql

# Start the bot
python main.py
```

---

## Architecture Overview

### Clean Architecture Layers

```
coordination_engine/
├── domain/                    # Core — ZERO external dependencies
│   ├── entities.py            # Event (aggregate root), User, Group, EventParticipant
│   ├── value_objects.py       # EventType, EventState, ConstraintType, enums
│   ├── events.py              # 14 domain events (EventCreated, ParticipantJoined, etc.)
│   ├── services.py            # Pure domain logic: state checks, thresholds, conflicts
│   ├── repositories.py        # 8 repository interfaces (ports)
│   └── exceptions.py          # 8 domain exceptions
│
├── application/               # Use cases — orchestrates domain
│   ├── dto.py                 # Commands, Queries, Result envelope
│   ├── commands.py            # 8 command handlers (CreateEvent, Join, Confirm, etc.)
│   ├── queries.py             # 4 query handlers (GetEvent, GetEventsForGroup, etc.)
│   ├── event_bus.py           # Pub/sub with exception isolation
│   ├── ports.py               # Service interfaces (IMessage, ILLM, IScheduler, INotification)
│   └── services.py            # EventApplicationService facade
│
├── infrastructure/            # External implementations
│   ├── persistence.py         # SQLAlchemy UoW + 6 repository implementations
│   ├── telegram_adapter.py    # TelegramMessageService + TelegramNotificationService
│   └── llm_adapter.py         # LLMServiceAdapter wrapping ai.llm.LLMClient
│
├── presentation/              # Input adapters
│   ├── presenters.py          # format_event_card(), format_event_details()
│   ├── command_handlers.py    # Telegram handlers using EventApplicationService
│   ├── event_flow.py          # Callback-based event interaction
│   └── mention_handler.py     # MentionHandler with LLM inference
│
└── shared/
    └── container.py           # Simple DI container
```

**Dependency Rule**: Inner layers know NOTHING about outer layers. All dependencies flow inward through interfaces (ports).

### Three-Layer Business Architecture

```
┌─────────────────────────────────────────┐
│  Layer 3: Memory (Post-Event Narratives)│
│  - Fragment Mosaic assembly             │
│  - Memory surfacing at event creation   │
│  - Event lineage                        │
└─────────────────────────────────────────┘
              ▲
┌─────────────────────────────────────────┐
│  Layer 2: Materialization (Announcements)│
│  - Group chat announcements at transitions│
│  - Threshold celebrations               │
│  - Visible momentum                     │
└─────────────────────────────────────────┘
              ▲
┌─────────────────────────────────────────┐
│  Layer 1: Coordination (State Management)│
│  - Event state machine                  │
│  - Participant management               │
│  - Constraint handling                  │
└─────────────────────────────────────────┘
```

**Layer Details:**

1. **Coordination Layer** (`EventStateTransitionService`, `ParticipantService`)
   - Manages event state transitions with validation
   - Enforces business rules and preconditions
   - Provides optimistic concurrency control
   - Single write path for all participant operations

2. **Materialization Layer** (`EventMaterializationService`, `MaterializationOrchestrator`)
   - Automated group announcements at state transitions
   - Milestone notifications ("We hit threshold!", "Event locked", etc.)
   - Progress updates and status broadcasts
   - Private cancellation notices (no public shaming)

3. **Memory Layer** (`EventMemoryService`)
   - Collects post-event narratives via DM (no deadline)
   - Generates Fragment Mosaics (rearrangement only, no synthesis)
   - Maintains event lineage and hashtags
   - Preserves plurality of voices (not a summary)

### Service Integration

**Clean Architecture Services:**

| Layer | Component | Purpose |
|-------|-----------|---------|
| Domain | `Event` (aggregate) | State machine, invariants, optimistic concurrency |
| Domain | `ParticipantService` | Pure domain logic: can_join, can_confirm, threshold checks |
| Application | `EventApplicationService` | Facade: create_event, join_event, transition_event, etc. |
| Application | `EventBus` | Domain event pub/sub → notification wiring |
| Infrastructure | `SQLAlchemyEventStore` | Unit of Work + 6 repository implementations |
| Infrastructure | `TelegramMessageService` | Telegram API adapter |
| Infrastructure | `LLMServiceAdapter` | AI inference adapter |

**Legacy Services (still functional):**

| Service | Purpose |
|---------|---------|
| `ParticipantService` (bot/) | All join/confirm/cancel operations |
| `EventStateTransitionService` | State machine with validation + concurrency |
| `EventLifecycleService` | Orchestrates transitions across all three layers |
| `EventMaterializationService` | Group announcements and DM notifications |
| `EventMemoryService` | Fragment collection and mosaic generation |
| `IdempotencyService` | Prevents duplicate command execution |

All services use async SQLAlchemy with proper transaction management.

---

## Core Interaction Modes

### 1) Classic slash commands (deterministic)

When a message starts with `/`, command handlers are used directly. This is the fast and predictable mode.

### 2) Mention/reply AI mode (group chat)

When users mention the bot (or reply to a bot message), the bot can infer intent and execute actions such as:

- `organize_event` or `organize_event_flexible`
- `status`, `event_details`, `suggest_time`
- `join`, `confirm` (interested), `cancel`, `lock`
- `constraint_add`, `request_confirmations`
- `opinion` response for advisory text

For sensitive inferred actions with mentioned participants (`constraint_add`, `organize_event*`), the bot requests inline approvals from mentioned users before execution.

### 3) Hybrid private mode (DM with bot)

The bot sends deep links for private interactions:

- private availability input
- private feedback submission
- private attendee notes to organizer

---

## Event Model and Lifecycle

**Event States:**

```
proposed → interested → confirmed → locked → completed
                                   ↘ cancelled (from any pre-locked state)
```

| State | Description |
|-------|-------------|
| `proposed` | Event created, waiting for participants |
| `interested` | At least one participant has joined |
| `confirmed` | At least one participant has confirmed attendance |
| `locked` | Finalized, attendance closed, commitments finalized |
| `completed` | Event finished (terminal state) |
| `cancelled` | Event cancelled (terminal state) |

**Automatic State Transitions:**

- `proposed` → `interested`: When first participant joins
- `interested` → `confirmed`: When first participant confirms
- `confirmed` → `locked`: Manual organizer action (with threshold validation)
- `locked` → `completed`: Manual or automatic completion

**Participant Statuses:**

| Status | Description |
|--------|-------------|
| `joined` | Interested in attending |
| `confirmed` | Committed to attend |
| `cancelled` | Withdrawn from event |
| `no_show` | Confirmed but didn't attend |

**Materialization Announcements:**

The bot automatically posts to group chat at key state transitions:

| Trigger | Message |
|---------|---------|
| First join | "🌱 [Name] just joined. We need [N] more for it to happen." |
| Threshold reached | "✨ We have enough. It's happening! [N] people in." |
| Event locked | "🔒 [Event] is locked. See you [time]. [participants]" |
| Event completed | "✅ [Event] is complete! Thanks to all [N] participants." |

*Note: Cancellations are sent privately to organizer only (no public shaming).*

---

## Key Capabilities

### Event Creation

- `/organize_event`:
  - Group-only flow with structured wizard
  - Description → type → calendar date → time → threshold → duration → invitees → confirmation
- `/organize_event_flexible`:
  - Same flow but without fixed initial time
  - Attendees add availability constraints, then `/suggest_time` proposes optimal time
- Inline calendar for date selection
- Invitee selection supports handles, `@all`, or individual mentions
- Automatic participant record creation for organizer

### Participant Management

- `/join <event_id>`: Join event (creates participant record)
- `/confirm <event_id>`: Confirm attendance commitment
- `/cancel <event_id>`: Cancel participation
- `/back <event_id>`: Unconfirm (revert from confirmed to joined)
- All operations use ParticipantService with proper validation and logging

### Event Coordination

- `/lock <id>`: Finalize event (requires organizer, validates thresholds)
  - Automatically finalizes all joined participants to confirmed status
  - Triggers materialization announcement
- `/request_confirmations <id>`: Send DM prompts to pending participants
- `/suggest_time <id>`: AI-assisted optimal time selection based on constraints

### Constraints and Availability

- `/constraints <id> view|add|remove|availability`
- Supports structured and natural language formats
- Private constraints in DM (attendee-only)
- Availability supports multiple time slots
- Integration with time suggestion algorithms

### Feedback and Memory

- `/feedback <id>`: Post-event feedback collection
- `/early_feedback <id>`: Pre-event feedback and notes
- `/event_note <id>`: Private attendee notes to organizer
- Automatic memory collection triggers on event completion (no deadline)

---

## Data Model (PostgreSQL v2)

### Core Tables

| Table | Description |
|-------|-------------|
| `users` | User profiles and Telegram metadata |
| `groups` | Group information and membership |
| `events` | Event details with normalized schema |
| `event_participants` | **NEW** - Normalized participant records |
| `constraints` | Availability and constraint rules |
| `reputation` | User reputation scores (deprecated in v3) |
| `logs` | Audit trail for all actions |
| `feedback` | Post-event feedback |
| `early_feedback` | Pre-event signals |
| `ailog` | AI interaction history |
| `event_state_transitions` | **NEW** - Audit trail for state changes |
| `idempotency_keys` | **NEW** - Prevents duplicate command execution |
| `event_memories` | **NEW** - Fragment Mosaic storage |

### Event Fields (v2)

| Field | Description |
|-------|-------------|
| `description`, `event_type` | Event details |
| `organizer_telegram_user_id`, `admin_telegram_user_id` | Ownership |
| `scheduled_time`, `duration_minutes`, `threshold_attendance` | Timing |
| `min_participants`, `target_participants` | **NEW** - Viability thresholds |
| `collapse_at`, `lock_deadline` | **NEW** - Auto-cancel and lock deadlines |
| `state`, `version` | State machine + optimistic concurrency |
| `planning_prefs` | JSON configuration |

**Deprecated:** `attendance_list` (migrated to `event_participants` table)

### EventParticipant Table

| Column | Description |
|--------|-------------|
| `event_id`, `telegram_user_id` | Composite primary key |
| `status` | Enum: `joined`, `confirmed`, `cancelled`, `no_show` |
| `role` | Enum: `organizer`, `participant`, `observer` |
| `source` | `slash`, `callback`, `mention`, `dm` |
| `joined_at`, `confirmed_at`, `cancelled_at` | Timestamps |

---

## Commands

### Core Commands

| Command | Description |
|---------|-------------|
| `/start`, `/help` | Bot introduction |
| `/my_groups` | Your group memberships |
| `/profile` | Personal reputation stats |
| `/reputation` | Group reputation rankings |

### Event Management

| Command | Description |
|---------|-------------|
| `/organize_event` | Create structured event |
| `/organize_event_flexible` | Create flexible event (no fixed time) |
| `/modify_event <id> <changes>` | Edit event (organizer only) |
| `/lock <id>` | Finalize event |
| `/status` | Events overview |
| `/events` | List all events |
| `/event_details <id>` | Detailed event view |

### Participation

| Command | Description |
|---------|-------------|
| `/join <id>` | Join event |
| `/confirm <id>` | Confirm attendance |
| `/cancel <id>` | Cancel participation |
| `/back <id>` | Unconfirm attendance |

### Coordination

| Command | Description |
|---------|-------------|
| `/constraints <id> <action>` | Manage constraints |
| `/suggest_time <id>` | AI time suggestion |
| `/request_confirmations <id>` | Send confirmation requests |

### Feedback & Memory

| Command | Description |
|---------|-------------|
| `/feedback <id>` [text] | Post-event feedback |
| `/early_feedback <id> <@user> <text>` | Pre-event feedback |
| `/event_note <id> <note>` | Private attendee notes |
| `/memory <id>` | View event memory mosaic |
| `/recall` | List recent group memories |
| `/remember <id> <text>` | Add memory fragment |

---

## Migration from v1/v2

### Key Changes in v3

| Change | Impact |
|--------|--------|
| Complete removal of behavioral inference | System never acts on inferred user qualities |
| Memory Weave → Fragment Mosaic | LLM rearranges only; no synthesis, no interpretation |
| Materialization messages rewritten | Tested against "show reality, not engineer response" |
| Personal Attendance Mirror | Causally inert counts for self-reflection only |
| No reliability-based adjustments | All users treated identically regardless of history |
| Memory surfacing at event creation | Past memory becomes input to future coordination |

### Backward Compatibility

- ✅ Legacy `attendance_list` parsing maintained for read operations
- ✅ Gradual migration of display logic to new schema
- ✅ All v1/v2 commands supported with improved internals
- ✅ Migration helper: `ParticipantService.migrate_from_legacy()`

---

## Development

### Testing

```bash
# Run all tests
pytest

# Run service tests specifically
pytest tests/test_services.py

# Run with coverage
pytest --cov=bot --cov-report=html
```

### Architecture Principles

| Principle | Implementation |
|-----------|----------------|
| **Single Write Paths** | All participant operations → `ParticipantService` |
| **Service Integration** | `EventLifecycleService` coordinates state changes |
| **Validation First** | All transitions validated before execution |
| **Audit Everything** | Comprehensive logging for debugging |
| **Async by Default** | All database operations use async SQLAlchemy |
| **Idempotency** | Duplicate command prevention (feature-flagged) |

### Code Quality Standards

- ✅ Type hints on all public APIs
- ✅ Comprehensive docstrings
- ✅ Async/await throughout
- ✅ Service layer testing with mocks
- ✅ Integration tests for end-to-end flows

---

## Setup

### Requirements

- Python 3.13-3.14
- PostgreSQL 15+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### 1) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure environment

Create `.env` with:

```env
# Required
TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
DB_URL=postgresql+asyncpg://coord_user:coord_pass@localhost:5432/coord_db

# Optional: LLM Configuration
AI_ENDPOINT=http://127.0.0.1:8080/v1
AI_MODEL=qwen/qwen3-coder-next
AI_API_KEY=dummy-key

# Optional: Feature Flags (PRD v2)
ENABLE_MATERIALIZATION=true
ENABLE_MEMORY_LAYER=true
ENABLE_REPUTATION_EFFECTS=false
ENABLE_IDEMPOTENCY=false

# Optional: Logging
LOG_LEVEL=INFO
LOG_LEVEL_TELEGRAM=INFO
LOG_LEVEL_HTTPX=WARNING
JSON_LOGS=false
```

**Note:** The `DB_URL` must use an async driver.
Use `postgresql+asyncpg://` on Python `<3.14` or `postgresql+psycopg://` on Python `>=3.14`.

### 3) Initialize database

**Option A: Using Docker (Recommended)**

```bash
docker-compose up -d postgres
sleep 5
docker-compose exec postgres psql -U coord_user -d coord_db -f /app/db/schema.sql
```

**Option B: Manual PostgreSQL**

```bash
# Create database and user
sudo -u postgres psql -c "CREATE USER coord_user WITH PASSWORD 'coord_pass';"
sudo -u postgres psql -c "CREATE DATABASE coord_db OWNER coord_user;"

# Apply schema
PGPASSWORD=coord_pass psql -h localhost -U coord_user -d coord_db -f db/schema.sql
```

### 4) Run bot

```bash
python main.py
```

Expected output:

```
INFO: Startup LLM check: LLM available at http://127.0.0.1:8080/v1
INFO: Startup DB check: Database accessible
INFO: Database initialization complete
INFO: Bot started. Press Ctrl+C to stop.
```

---

## AI and LLM Configuration

LLM client is OpenAI-compatible and expects:

- `GET /models` for availability check
- `POST /chat/completions` for inference calls

**Used for:**

- Mention intent inference
- Event draft inference and modification patching
- Natural-language constraint parsing
- Fragment Mosaic rearrangement (readability only, no synthesis)

---

## Current Limitations

| Limitation | Status | Workaround |
|------------|--------|------------|
| `/feedback` requires `completed` state | ⚠️ Known | Manual state completion via admin |
| Test suite outdated | ⚠️ In Progress | Being updated for v3 architecture |
| `reputation` command basic | ⚠️ Known | Use `/profile` for detailed stats |
| Webhook support | ❌ TODO | Use polling (default) |
| RBAC coverage | ⚠️ Partial | Lock command done, more coming |
| Rate limiting | ❌ TODO | Manual monitoring |
| Callback replay protection | ❌ TODO | Short session timeouts |

---

## Production Deployment

### Docker

```bash
docker-compose up -d
docker-compose logs -f bot
```

### Environment Variables for Production

```env
ENVIRONMENT=production
ENABLE_IDEMPOTENCY=true
ENABLE_REPUTATION_EFFECTS=false
LOG_LEVEL=WARNING
JSON_LOGS=true
```

### Webhook (Optional)

For production, use webhooks instead of polling. See [QUICKSTART.md](docs/v2/QUICKSTART.md) for details.

---

## Troubleshooting

**Database connection errors:**

```
Error: could not connect to server
```

→ Check PostgreSQL is running: `docker-compose ps` or `systemctl status postgresql`  
→ Verify credentials in `.env`  
→ Ensure `DB_URL` uses an async driver prefix: `postgresql+asyncpg://` on Python `<3.14` or `postgresql+psycopg://` on Python `>=3.14`

**LLM unavailable:**

```
Warning: Startup LLM check: LLM unavailable
```

→ Check AI endpoint is accessible  
→ Verify `AI_ENDPOINT` and `AI_API_KEY` in `.env`  
→ AI features gracefully degrade if unavailable

See [QUICKSTART.md](docs/v2/QUICKSTART.md) for more troubleshooting tips.

---

## License

Apache-2.0

---

## Contributing

1. Read [PRD v3.1](docs/v3/PRD_v3.1.md) for product philosophy
2. Review [USER_FLOWS_v3.1.md](docs/v3/USER_FLOWS_v3.1.md) for interaction patterns
3. Check [IMPLEMENTATION.md](docs/v2/IMPLEMENTATION.md) for architecture decisions
4. Review [REFACTORING_SUMMARY.md](docs/v2/REFACTORING_SUMMARY.md) for implementation status
5. Run tests: `pytest`
6. Submit PR with description of changes

---

## Implementation Status

| Phase | Status | Features |
|-------|--------|----------|
| Phase 1 | ✅ Complete | Services, Materialization, Memory, Idempotency |
| Phase 2 | ✅ Complete | RBAC, Threshold Enforcement, Mutual Dependence |
| Phase 3 | 📋 Planned | Webhook, Callback Protection, Weekly Digest |
| Phase 4 | 📋 Planned | CI/CD, Observability, Secret Management |

See [IMPLEMENTATION.md](docs/v2/IMPLEMENTATION.md) for detailed TODO list.
