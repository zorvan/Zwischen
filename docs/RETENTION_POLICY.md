# Zwischen retention policy

Zwischen remembers enough to coordinate a gathering, then deliberately forgets
the social graph behind it. Retention is measured from when an event **ended**:
`completed_at` for a completed event, and the last transition into `cancelled`
for a cancelled one. Events still in progress are never decayed, however old.

The policy is executable: `bot/services/retention_service.py` implements it,
the scheduler runs it daily under a cluster-wide advisory lock, and
`tests/test_retention.py` fails if any row outstays its window. Running the
decay job repeatedly has the same result as running it once.

| Data | Policy | Product reason |
|---|---|---|
| Users, identities, preferences, group membership | Keep while the account exists; erase on account deletion | Required for an account and its explicit memberships |
| Events and groups | After 180 days keep a minimal record: type, title, time, state. Description, planning details, organizer and admin are removed | A group can remember that something happened, without who arranged it or what was said |
| Event participants and waitlists | Delete after 180 days | Attendance must not become a durable social graph |
| Constraints ("I join if X joins") | Delete after 180 days | They name who wanted to be with whom |
| Enrichments (ideas, hashtags, memories added in the panel) | Delete after 180 days | Member-authored detail has served its coordination purpose |
| State transitions | After 180 days remove actor and free-text reason; keep state and timestamp | Retains operational history without attribution |
| Event memories | At 180 days keep only the weave, hashtags and outcome markers; delete at 365 days | Memories decay from detail to summary to nothing |
| Logs | Delete after 90 days | Short operational diagnostic window only |
| Group event-type statistics | Keep aggregate counters while the group exists | Contains no individual attribution |
| Idempotency keys | Delete once expired | Retry safety only |
| Live-card references | Delete with the event or when the referenced message/subscription disappears | Delivery metadata, not a memory |
| Rolling group chat context (for mention suggestions) | Last 40 messages, none older than 24 hours, in bot state only | A working buffer for the assistant, never a record |

## Account deletion

Users erase their account with `/delete_account` in a private chat with the
bot, or `DELETE /me` on the API. Erasure:

- removes identities, preferences, memberships, participation, constraints,
  enrichments and waitlist entries through database cascades;
- removes the user's memory fragments. Fragments carry a contributor hash
  rather than a foreign key; the hash is a pseudonym (recomputable from the
  user ID), which is exactly what lets erasure find them;
- keeps shared events, but organizer, admin, audit actor and constraint target
  references become anonymous;
- clears Telegram-side state: conversation data, the user's lines in the
  rolling chat context, and pending modification requests;
- invalidates API sessions immediately, since no token can resolve to an
  account that no longer exists.

Backups age out on the infrastructure backup schedule and are not restored to
answer ordinary product queries.

## For users

`/privacy` states this policy in product terms, in every supported language.

## Anchoring

No event content or identity is eligible for a permanent public ledger. If
optional anchoring is enabled later, only a content-free hash may leave the
system; after its source memory decays that hash is intentionally unverifiable
(see `ANCHORING_DECISION.md`).
