# Test System Plan
## Coordination Engine Telegram Bot v3.2

This document defines the full test system for the bot as implemented against `docs/v3.2`. It is intentionally product-facing, not just code-facing: the goal is to verify behavior, permissions, invariants, and philosophy boundaries, not only individual functions.

## 1. Why A New Test System Is Needed

The current test suite proves basic imports, some isolated service behavior, and a few neutrality checks. It does **not** yet provide:

- contract-level coverage for every v3.2 feature
- stateful lifecycle tests across modules
- permission matrix coverage
- explicit negative-path coverage
- philosophy boundary tests that prevent future behavioral drift

The new system must treat the PRD and user flows as executable contracts.

## 2. Test Philosophy

Every test must answer one of these questions:

1. Does the bot do the correct thing when the happy path occurs?
2. Does it fail safely and predictably when inputs, permissions, or state are wrong?
3. Does it preserve v3.2 philosophy under pressure?

Three permanent boundaries must be encoded in tests:

- `Event-level adaptation, user-level neutrality`
- `Visibility without analysis`
- `Memory as participant-owned fragments, not bot-authored synthesis`

That means we do not only test outcomes. We also test forbidden behavior:

- no user-history-based prioritization
- no behavioral scoring or reputation logic
- no guilt/friction language in materialization
- no individual blame in failure pattern surfaces
- no non-verbatim memory hooks or lineage fragments

## 3. Quality Criteria

The suite is complete only when it can detect regressions in:

- feature correctness
- permission enforcement
- state-machine integrity
- timing rules
- privacy boundaries
- neutrality/philosophy boundaries
- failure handling and idempotency

Definition of done for a feature:

- at least one happy-path integration test
- unit tests for decision branches and helpers
- negative tests for invalid state/input/permission
- privacy and philosophy assertions where relevant

## 4. Test Taxonomy

### A. Pure Unit Tests

Use for deterministic helpers and branch logic.

Examples:

- `get_time_framing_tier`
- `events_overlap`
- waitlist offer duration calculation
- memory fragment qualification and selection
- state-transition validation
- RBAC decision helper branches

### B. Service Integration Tests

Use real database models with transactional rollback. Mock Telegram and LLM boundaries only.

Examples:

- `ParticipantService`
- `EventLifecycleService`
- `WaitlistService`
- `EventMemoryService`
- `GroupEventTypeStatsService`

### C. Flow Integration Tests

Use synthetic PTB `Update` / callback objects plus real DB session and mocked outbound side effects.

Examples:

- event creation flow
- join/confirm/cancel flow
- waitlist callback flow
- memory contribution flow
- constraint DM flow

### D. Contract / Philosophy Tests

These are regression guards for product doctrine.

Examples:

- no user-history parameter accepted by waitlist ordering
- materialization templates never mention reliability or fragility blame
- repeated failure surface is group-level only
- mosaic output never contains invented words

### D2. Production Contract Tests

These guard runtime hardening assumptions that are now part of the deployable
system contract.

Examples:

- production settings require explicit webhook configuration
- active entry points do not expose deprecated feedback/rating UX
- waitlist schema/service/handler contract stays aligned
- package imports stay lightweight enough for focused unit testing

### E. End-to-End Scenario Tests

A small number of full-lifecycle stories using a test database:

- create -> join -> confirm -> lock -> complete -> memory collect -> weave
- oversubscribe -> waitlist -> cancel -> offer -> accept -> organizer notified
- repeated failed attempts -> new creation -> failure pattern surfaced

## 5. Proposed Test Layout

```text
tests/
  unit/
    common/
    services/
    ai/
    commands/
  integration/
    db/
    services/
    handlers/
    commands/
  contracts/
    test_behavioral_neutrality.py
    test_privacy_boundaries.py
    test_memory_contracts.py
    test_materialization_contracts.py
  scenarios/
    simulator.py
    test_event_lifecycle_scenarios.py
    test_waitlist_scenarios.py
    test_memory_scenarios.py
  fixtures/
    factories.py
    telegram.py
    clocks.py
    llm.py
```

Current top-level tests should be progressively migrated into this structure.

## 6. Test Infrastructure Plan

### Database

- use a dedicated async test database
- prefer transactional rollback per test
- seed only minimal required rows
- provide factories for `User`, `Group`, `Event`, `EventParticipant`, `EventWaitlist`, `EventMemory`

### Time Control

- freeze time for materialization tiers, collapse deadlines, waitlist expiry, and memory timestamps
- avoid assertions against raw `datetime.utcnow()` without time control

### Telegram Boundary

- mock `bot.send_message`, `get_chat_member`, and callback answers
- assert audience, content, and privacy target
- verify when messages are *not* sent as well

### Runtime Compatibility

- keep a repo-local virtualenv for test execution in environments where the
  system Python is externally managed
- separate app-level contract tests from database-driver compatibility issues
- where pinned dependencies lag the interpreter, prefer running the pure unit
  and contract layers with a compatible subset rather than skipping validation

### LLM Boundary

- mock `LLMClient` for deterministic mosaic tests
- test both constrained success and fallback path

### Fixture Families

- `group_member_user`
- `non_member_user`
- `organizer_user`
- `admin_user`
- `participant_user`
- `event_at_light_tier`, `event_at_warm_tier`, `event_at_urgent_tier`, `event_at_immediate_tier`
- `full_event_with_waitlist`
- `completed_event_with_memory`
- `group_with_failure_pattern`
- `ultimate_chat_group`

### Scenario Simulator

- maintain a stateful scenario harness over a real async test database
- drive repeated event attempts with the actual participant, lifecycle,
  waitlist, stats, confirmation, and memory services
- cover the supported interaction verbs as reusable journey steps:
  modify, join, confirm, uncommit, exit, waitlist offer/accept/decline,
  lock, complete, cancel, constraints, and availability updates
- make long-form fictional chats executable by mapping transcript turns into:
  actor, timestamp, inferred interaction, expected private/public surfaces,
  and branch outcomes
- keep transcript fixtures separable from assertions so one fictional chat can
  produce multiple scenario branches: completion, cancellation, retry, drift

## 7. Feature Coverage Matrix

### 7.1 Event Creation

Working cases:

- creation starts in meaning-formation posture
- prior completed event surfaces lineage excerpt
- repeated failure pattern surfaces before lineage prompt
- minimum and target capacity are collected separately
- valid invitee parsing accepts `@all` and valid handles

Failing cases:

- invalid event type
- invalid handle format
- duplicate handles
- target capacity lower than minimum
- scheduling/commit-by values impossible or malformed
- missing required stage data during review/finalization

### 7.2 Event Participation

Working cases:

- member can join visible event
- participant can confirm after joining
- participant can cancel and rejoin
- conflicts block overlapping participation
- state menu changes according to user status

Failing cases:

- join locked/completed/cancelled event
- confirm without event visibility
- confirm after cancellation when forbidden by service
- duplicate join is idempotent
- duplicate confirm is idempotent
- cancel non-participant raises correct error path

### 7.3 Event State Machine

Working cases:

- valid transitions succeed and are logged
- lifecycle triggers fire on `locked`, `completed`, `cancelled`
- completion records group stats and starts memory collection

Failing cases:

- illegal transitions raise transition errors
- stale expected version rejects concurrent update
- transition without event returns not-found path

### 7.4 Waitlist

Working cases:

- join beyond `target_participants` offers waitlist instead of event entry
- FIFO order is by `added_at` only
- offer window is `120`, `30`, or `15` minutes based on event time
- accept promotes user to joined+confirmed and removes waitlist entry
- decline and expiry advance to next waitlisted user
- organizer receives acceptance DM

Failing cases:

- adding existing participant to waitlist rejected
- duplicate waitlist entry rejected
- accepting expired offer fails safely
- offering for missing event or missing waitlist entry is no-op
- full event does not expose waitlist to group context

### 7.5 Materialization

Working cases:

- time framing tier matches event time only
- first join / join / threshold / locked templates render correctly by tier
- threshold and locked announcements include hook only when qualifying fragment exists
- cancellation creates organizer-only DM

Failing cases:

- no message if group chat is unavailable
- immediate-tier confirm avoids wrong audience path if spec says organizer DM only
- hook omitted when fragment exceeds max words
- cancellation never posts cancelled-user identity to group

### 7.6 Memory Layer

Working cases:

- completed event triggers memory request to eligible participants
- prompt includes reflexive language about difficulty
- lineage door prefers reflexive fragment when available
- fragment write stores `word_count`
- weave uses participant words only
- fallback chronological weave works when LLM path fails

Failing cases:

- incomplete event cannot start memory collection
- non-qualifying long fragment not used as hook
- no fragments means no weave
- malformed or empty LLM response triggers fallback
- memory flow never imposes deadline logic

### 7.7 Repeated Failure Pattern Surface

Working cases:

- 3+ failed attempts of same group+type surface attempt count and dropout point
- completed attempts increase completion counts
- surface appears before lineage prompt

Failing cases:

- less than 3 failed attempts shows nothing
- cross-group attempts do not leak
- surface never names participants or assigns blame

### 7.8 Constraint Management

Working cases:

- DM-only access path
- declared constraints affect scheduling compatibility only
- conditional participation rules are evaluated deterministically

Failing cases:

- group-chat use denied or redirected
- constraints never affect prioritization, permissions, or waitlist ordering
- malformed constraint payload rejected

### 7.9 Personal Attendance Mirror

Working cases:

- user sees only their own counts
- counts are grouped by event type

Failing cases:

- inaccessible outside private context if required by command
- no score, trend, rank, or recommendation language
- mirror data never changes downstream system decisions

### 7.10 Mention-Driven AI Orchestration / Time Suggestion

Working cases:

- meaning-formation mode activates on unclassified intent
- near-threshold active event may be surfaced as context
- time suggestion uses declared availability and factual counts only

Failing cases:

- no reliability inference methods
- no threshold probability / collapse prediction resurrected
- no user history modifies treatment

## 8. Permission Matrix

This must be tested explicitly, not implicitly.

Roles:

- organizer
- admin
- group member
- participant in this event
- prior participant in same group
- non-member

Operations:

- view event list
- view event details
- join event
- confirm event
- cancel participation
- lock event
- modify event
- manage constraints
- receive organizer-only cancellation DM

Required assertions:

- organizer always retains event visibility
- admin always retains event visibility
- same-group-chat interaction can auto-enroll membership
- proven membership via prior participation works
- non-members cannot view or join out-of-group events
- private data paths never leak into group chat

## 9. Philosophy Regression Suite

These tests should be treated as release blockers.

### Neutrality Guards

- no `reputation`, `reliability_score`, or similar columns/models/imports
- no waitlist/order method accepts user history
- no materialization template differentiates users except by explicit factual name

### Privacy Guards

- cancellation identity stays organizer-private
- waitlist status stays private to participant and organizer
- repeated failure surface is aggregate only
- personal mirror is private only

### Memory Guards

- no synthesis beyond allowed mosaic arrangement
- no fragment mutation
- no deadline-based rejection
- no blame or “who failed” language introduced into memory prompts

## 10. Suggested Implementation Phases

### Phase 1: Foundation

- real async DB fixtures
- factories
- clock/freezing utilities
- Telegram bot mocks
- LLM stubs

### Phase 2: Core Risk Areas

- state machine
- RBAC
- waitlist
- materialization
- memory contracts
- production contracts

### Phase 3: Command and Handler Flows

- event creation flow
- join/confirm/cancel callbacks
- constraint DM flows
- memory contribution handlers

### Phase 4: Scenario Suites

- full lifecycle stories
- oversubscription/waitlist stories
- repeated-failure/adaptation stories

## 11. CI And Gating Plan

Run test layers separately:

- fast unit + contracts on every push
- service integrations on every push
- scenario suite on PR and main branch

Recommended minimum gates:

- all contract tests required
- no flaky time-dependent assertions
- changed modules must include corresponding tests
- coverage target should be module-risk-based, not vanity-based

Recommended risk-based target:

- `bot/services/*`, `bot/handlers/*`, `bot/common/rbac.py`, `bot/common/materialization.py`: very high
- command modules: medium to high
- formatting/presenter helpers: medium

## 12. Immediate Gaps In Current Repository

The highest-value missing tests right now are:

- real waitlist auto-fill scenarios
- organizer-private cancellation DM behavior
- repeated failure pattern behavior
- hook/lineage fragment qualification
- event creation min/target buffer validation
- end-to-end lifecycle with memory collection
- permission matrix beyond current membership helper checks

## 13. Final Principle

This system should be hard to regress in the exact places where the product is philosophically distinctive.

If a future change accidentally makes the bot:

- predictive instead of mediating
- judgmental instead of neutral
- leaky instead of private
- synthetic instead of participant-owned

the test suite should fail immediately.
