# T04 — Migrate call sites from `telegram_user_id` to `user_id`

**Tier 1 · finish the identity migration · area: domain**
**Depends on:** identity expand migration (done — `3fead70d5078`, `a1c4e93b7d20`)
**Blocks:** T05 (contract migration), T09 (web API)

## Why

The expand migration added `user_id` beside every `telegram_user_id`,
backfilled it, and constrained it. Both columns are populated, so **the bot
works unchanged today** — that was deliberate, to keep Telegram running while
this proceeds.

But every read still goes through the Telegram column, which means the domain
still cannot represent a user who has no Telegram account. Until this lands,
`db/identity.py` can create a web user that no query will ever find.

## Scope

597 references across 49 files:

| Area | Refs | Files | Notes |
|---|---|---|---|
| `bot/common` | 159 | 14 | mixed domain + presentation |
| `bot/services` | 148 | 9 | **do first** — reused by the web API |
| `bot/handlers` | 135 | 5 | most Telegram-entangled |
| `bot/commands` | 91 | 13 | includes the 2,652-line `event_creation.py` |
| `db` | 63 | 7 | **do first** — everything else sits on it |
| `ai` | 1 | 1 | trivial |

## Suggested order

1. **`db/`** — `db/users.py` already delegates to `db/identity.py`. Audit the
   rest for direct `telegram_user_id` filters.
2. **`bot/services/`** — this is the layer T09 will reuse. After this step the
   services should be expressible without Telegram at all.
3. **`bot/common/`** — split as you go: domain helpers migrate, presentation
   helpers are T11's problem.
4. **`bot/handlers/` + `bot/commands/`** — the transport edge. These legitimately
   *receive* a Telegram id; they should resolve it to a `User` once, at the
   boundary, via `db.identity.resolve_telegram_user()`, and pass `user_id`
   inward. That single change is most of the work here.

## The pattern

```python
# before — Telegram id threaded through the domain
await participant_service.join(event_id, telegram_user_id=update.effective_user.id)

# after — resolve once at the edge, domain speaks user_id
user = await resolve_telegram_user(
    session, update.effective_user.id,
    display_name=update.effective_user.full_name,
    username=update.effective_user.username,
)
await participant_service.join(event_id, user_id=user.user_id)
```

## Watch for

- **Both columns must stay written** until T05. Writing only `user_id` leaves
  `telegram_user_id` NULL and breaks anything not yet migrated — and
  `event_participants.telegram_user_id` is still part of the primary key.
  Keep a single write path per table so this is enforced in one place.
- `events.organizer_telegram_user_id` → `organizer_user_id` and
  `emergency_admin_telegram_user_id` → `emergency_admin_user_id`
- `event_state_transitions.actor_telegram_user_id` → `actor_user_id`
- Group members named only in `groups.member_list` — see T07
- `bot/common/rbac.py` mixes both, plus the Telegram API fallback (T07)

## Acceptance criteria

- [ ] `bot/services/` contains zero `telegram_user_id` references
- [ ] `db/` contains none outside `db/identity.py` and the deprecated-column
      definitions in `db/models.py`
- [ ] Handlers resolve at the boundary and pass `user_id` inward
- [ ] A user with no Telegram identity can be a participant end to end —
      add a test asserting exactly this; it is the whole point
- [ ] Lifecycle suite still green

## Notes for the target architecture

This is the ticket that actually makes the codebase platform-independent. The
schema already is; the code is not. Everything in Tier 2 assumes this is done.
