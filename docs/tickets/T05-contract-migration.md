# T05 — Contract migration: drop the deprecated Telegram columns

**Tier 1 · finish the identity migration · area: schema**
**Depends on:** T04 (hard — do not start until it is fully done)

## Why

The expand migration deliberately left both column sets in place so the bot
kept working during T04. Once nothing reads the Telegram columns, they become
a liability: two sources of truth that can disagree, a primary key that
embeds a platform id, and a `NOT NULL` constraint that misrepresents reality.

## What to do

One migration, in this order:

### 1. Verify nothing reads the old columns

Not a code search — a runtime check. Grep is necessary but not sufficient
given dynamic access. Consider running with the columns renamed (not dropped)
in staging for a cycle: anything still referencing them fails loudly and
recoverably.

### 2. Backfill gaps and enforce NOT NULL

```sql
-- must be zero before proceeding
SELECT count(*) FROM event_participants WHERE user_id IS NULL;
SELECT count(*) FROM event_waitlist      WHERE user_id IS NULL;
SELECT count(*) FROM event_enrichments   WHERE user_id IS NULL;
```

Then `ALTER COLUMN user_id SET NOT NULL` on each.

### 3. Move the `event_participants` primary key

The delicate step. Currently `(event_id, telegram_user_id)`; the target is
`(event_id, user_id)`. `uq_participant_event_user` already exists on the
target pair, so the uniqueness is proven before the swap:

```sql
ALTER TABLE event_participants DROP CONSTRAINT event_participants_pkey;
ALTER TABLE event_participants ADD PRIMARY KEY (event_id, user_id);
ALTER TABLE event_participants DROP CONSTRAINT uq_participant_event_user;
```

Takes an `ACCESS EXCLUSIVE` lock. Fine at current data volumes; if the table
has grown, do it in a maintenance window.

### 4. Drop the deprecated columns

- `event_participants.telegram_user_id`
- `event_waitlist.telegram_user_id`
- `event_enrichments.telegram_user_id`
- `events.organizer_telegram_user_id`, `events.emergency_admin_telegram_user_id`
- `event_state_transitions.actor_telegram_user_id`
- `groups.member_list` (after T07)
- `users.telegram_user_id` — **last**, and see the caveat below

Drop the now-dead indexes with them: `idx_events_organizer_tg`,
`idx_events_emergency_admin_tg`, `idx_event_participants_user_id`,
`idx_event_waitlist_user_id`.

### 5. `users.telegram_user_id`

`user_identities` is the replacement and is populated. But confirm first that
nothing resolves Telegram identity through the column — `db/identity.py`
still writes it during the expand phase (`resolve_identity`, the
`provider == telegram` branch). That write must be removed as part of this.

## Reversibility

**This migration is not cleanly reversible** — dropped columns cannot be
reconstructed from `user_identities` for rows whose user has since been
deleted. Take a dump first. Write the `downgrade()` to recreate the columns
and backfill what it can from `user_identities`, and document in the
migration docstring exactly what is unrecoverable.

## Acceptance criteria

- [ ] `check_schema_drift` clean
- [ ] Full migration chain applies from empty and round-trips as far as it can
- [ ] `tests/test_identity_migration.py` extended to cover expand → contract
      over seeded data
- [ ] Lifecycle suite green
- [ ] `db/models.py` has no column marked DEPRECATED

## Notes for the target architecture

After this, `users` has no platform-specific column and `user_identities` is
the only place a provider appears. Adding wallet login (T08) or any future
provider becomes an INSERT.
