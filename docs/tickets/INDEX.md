# Zwischen — development tickets

Next steps after the `platform-independence` branch, which delivered: async
engines scoped per event loop, a working integration test harness, the
platform-neutral identity schema and resolution layer, the transport-neutral
`Notifier`, and the shared `StateBackend`.

**Standing constraint: Telegram keeps working throughout.** Every ticket is
written to preserve the running bot. Nothing here is a big-bang rewrite; the
identity migration is already in expand/contract form precisely so the bot
runs unchanged while call sites move.

## Tickets

| # | Title | Tier | Depends on |
|---|---|---|---|
| [T01](T01-scheduler-leader-lock.md) | Scheduler double-fires on every instance | 0 | — |
| [T02](T02-webhook-mode.md) | Polling forbids a second instance | 0 | T01 |
| [T03](T03-wire-state-backend.md) | Wire the shared state backend | 0 | — |
| [T04](T04-migrate-call-sites-to-user-id.md) | Migrate call sites to `user_id` | 1 | — |
| [T05](T05-contract-migration.md) | Contract migration: drop Telegram columns | 1 | T04 |
| [T06](T06-services-onto-notifier.md) | Move services onto `Notifier` | 1 | — |
| [T07](T07-membership-service.md) | Membership service over `group_members` | 1 | T04 |
| [T08](T08-authentication.md) | Authentication and sessions | 2 | T04, T07 |
| [T09](T09-http-api.md) | HTTP API over domain services | 2 | T04, T06, T07, T08 |
| [T10](T10-realtime-live-cards.md) | Real-time updates replacing live cards | 2 | T06, T09 |
| [T11](T11-extract-presentation.md) | Extract presentation from the domain | 2 | T06 |
| [T12](T12-query-profiling.md) | Query profiling and N+1 audit | 3 | — |
| [T13](T13-caching.md) | Caching layer | 3 | T03 |
| [T14](T14-connection-budget.md) | Connection budget and pooling | 3 | T02 |
| [T15](T15-data-minimization-and-decay.md) | Data minimization and memory decay | 2 | T05 |
| [T16](T16-commitment-anchoring.md) | Commitment anchoring (CSV, single-use seals) | 2/3 | T15, T08 |
| [T17](T17-diewan-interop.md) | Interop boundary with Diewan | 3 | T09, T15, T16 |

## Dependency graph

```
T01 ──▶ T02 ──▶ T14
T03 ──▶ T13
        │
T04 ──▶ T05 ──▶ T15 ──▶ T16 ──▶ T17
 │       │               ▲       ▲
 ├──▶ T07 ──▶ T08 ────────┘      │
 │             │                 │
T06 ──────────▶ T09 ─────────────┘
 │              │
 ├──▶ T10 ◀─────┘
 └──▶ T11

T12  (independent; more useful after T09)
```

## Tiers

**Tier 0 — running a second instance today would be *incorrect*.** Not
performance: T01 double-sends DMs and digests to real users, and T02 means
Telegram refuses the second instance outright. Do these before scaling
anything.

**Tier 1 — finish what the branch started.** The schema is platform-neutral;
the code is not. `db/identity.py` can create a web user that no query will
find, and `core/notifier.py` is unused. Tier 1 closes that gap.

**Tier 2 — new platform surface.** Web and mobile become possible here.

**Tier 3 — performance and exploration.** Measure before optimizing; T12 will
likely disagree with intuition.

## Suggested order

**First slice (unblocks multi-instance):** T01 → T03 → T02.
T01 is the one with user-visible damage if skipped.

**Second slice (unblocks web/mobile):** T04 → T07 → T06 → T05.
T04 is the largest single body of work — 597 refs across 49 files — and
everything in Tier 2 assumes it.

**Third slice:** T08 → T09 → T10/T11.

**In parallel, whenever:** T15's *written policy* costs nothing to start and
constrains T16 and T17. Doing it late means anchoring things the policy would
have said to forget.

## Two overlaps worth planning around

**`bot/commands/event_creation.py`** (2,652 lines, 56 `user_data` touches)
appears in both T03 and T04. Doing it once — reshaped as a form-style flow
rather than a ported button wizard — is substantially less work than twice,
and is the largest simplification available in the codebase.

**`live_card_service.py`** appears in both T06 and T10. Consider deferring it
from T06 and doing it once, in T10.

## On the blockchain direction

The identity layer is already wallet-ready: `user_identities` takes
`provider='wallet:ton'` with an address as `provider_user_id`, no schema
change (T08).

The deeper decision is T15/T16. Zwischen's premise — storing nothing except
decaying memories — is in direct tension with anchoring, which is permanent by
construction. Client-side validation with single-use seals resolves it: only
content-free commitments go on-chain, so once a memory decays the commitment
reveals nothing. That model also matches Diewan, which makes T17 tractable
later.

The three properties to preserve, whatever else changes: **commitments stay
content-free, identity stays provider-agnostic, anchoring stays optional.**
Keep those and a later connection stays possible without compromising either
project.
