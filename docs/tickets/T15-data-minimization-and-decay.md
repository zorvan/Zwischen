# T15 — Enforce data minimization and memory decay

**Tier 2 · product-defining · area: schema / privacy**
**Depends on:** T05 (schema settled)
**Blocks:** T16 (what may be anchored), T17 (what may be shared)

## Why

Zwischen's stated character is a system for **shared experience in a maximally
ethical environment that stores nothing except some decaying memories**. That
is a product invariant, not a preference — and the schema currently does not
honour it.

Today exactly one retention rule exists: `bot/common/scheduler.py:96`
`prune_old_logs()` deletes `Log` rows older than 90 days, labelled GDPR
compliance. Everything else is retained indefinitely:

| Table | Contents | Retention today |
|---|---|---|
| `event_memories` | post-event reflections | forever |
| `event_enrichments` | ideas, hashtags, memories contributed by members | forever |
| `event_state_transitions` | full audit trail, actor + timestamp + reason | forever |
| `event_participants` | who attended what, with whom | forever |
| `group_event_type_stats` | aggregated behaviour per group | forever |
| `user_identities` | provider account linkage (new) | forever |
| `events` | every gathering ever proposed | forever |

`event_participants` in particular is a durable social graph: who was with
whom, when, how often. That is precisely the dataset the project's philosophy
says should not accumulate.

## What to do

### 1. Write the retention policy down first

This is a product decision, not an implementation one. For each table decide:

- **Decay** — degrade over time (full detail → summary → aggregate → nothing).
  This is what "decaying memories" implies, and it is different from deletion.
- **Delete** — hard removal after a fixed window.
- **Keep** — with a written justification for why it is exempt.

The interesting middle case is decay. An event six months old might reduce to
"a dinner happened, it went well" with participants dropped — retaining the
*memory* while discarding the *record*. `event_memories` already carries this
intent; the mechanism does not exist.

### 2. Implement decay as a scheduled job

Extends the existing scheduler (see T01 — must run under a leader lock, or N
instances decay the same rows concurrently). Idempotent by construction:
running it twice must not double-degrade.

### 3. Right to erasure

A user deleting their account should remove their data, not just detach it.
Current FK behaviour is a mix — `ondelete="CASCADE"` on participation,
`SET NULL` on `event_state_transitions.actor_user_id` (chosen deliberately so
deleting a user does not erase an event's audit trail). Confirm that split is
the intended policy and that "erasure" means something specific and testable.

### 4. Minimize at write time

Cheaper than deleting later:
- Does `Log` need per-action rows at all, or only aggregates?
- `mentions.record_group_history` keeps rolling group message history for AI
  context — how long, and is it in the retention model?
- Does `event_state_transitions` need `reason` text indefinitely?

### 5. Make it observable

A test asserting that data older than the policy window does not exist. That
turns the philosophy into something CI enforces rather than something the
README claims.

## Tension to resolve explicitly

**Decay and anchoring pull in opposite directions.** T16 anchors commitments
that are by construction permanent. The resolution is that only *commitments*
(hashes) go on-chain, never content — once the content decays, the commitment
is an opaque value revealing nothing. Client-side validation makes this work,
and it is why that model suits this project far better than on-chain state.

Decide the ordering deliberately: if anchoring ships before the retention
policy is written, it will anchor things the policy would later have said to
forget.

## Acceptance criteria

- [ ] Written retention policy covering every table, with justifications
- [ ] Decay job implemented, idempotent, running under a leader lock
- [ ] Account deletion removes or anonymizes per policy, with a test
- [ ] CI test asserting no data outstays its window
- [ ] Policy documented for users in product terms, not just in code
