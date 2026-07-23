# T12 — Query profiling and N+1 audit

**Tier 3 · performance · area: db**
**Depends on:** nothing; more valuable after T09 (real traffic shapes)

## Why

The identity migration added composite indexes for the read paths that were
*known* to scan:

- `idx_event_participants_event_status` — confirmed-count per event, hit on
  every join, lock and threshold check
- `idx_events_group_state_time` — a group's events by state, soonest first
- `idx_event_waitlist_event_status_added` — promotion order
- `idx_enrichments_event_type` — enrichments by event and type

Those were reasoned from the code, **not measured**. No profiling has been
done, and there are known N+1 patterns.

## Known starting points

`bot/common/event_presenters.py:23` — `get_user_mention()` takes a single
`telegram_user_id` and queries `users`. It is called per participant when
rendering an event, so an event with 12 participants issues 12 queries, plus
a possible Telegram API call each for users missing a `display_name`.

Batch it: `db/users.py:get_user_ids_for_telegram_ids()` already exists as the
batched shape and is the pattern to follow.

Also likely:
- `mosaic_assembly_service.py` (543 lines) — assembles from several sources
- `weekly_digest.py` — iterates groups, then events, then participants
- Anywhere a relationship is accessed in a loop without `selectinload`

## What to do

1. **Turn on measurement.** `DB_ECHO=true` exists (`config/settings.py`). For
   something durable, log queries per request with a counter and alert above a
   threshold — the counter is what catches regressions, not one-off profiling.
2. **`pg_stat_statements`** on the live database for the real top-N by total
   time. Cheap to enable, and it will disagree with intuition.
3. **Fix the N+1s** with `selectinload` / `joinedload` or explicit batch
   queries.
4. **Verify the new indexes are used** — `EXPLAIN ANALYZE` the hot queries.
   An index that is never chosen is write overhead for nothing.
5. **Add a regression guard.** A test asserting query count for a
   representative flow prevents silent reintroduction.

## Acceptance criteria

- [ ] Rendering an event with N participants issues O(1) queries, not O(N)
- [ ] Top 10 queries by total time identified from real data
- [ ] Every index added by `3fead70d5078` is either used or dropped
- [ ] Query-count regression test on at least one hot path

## Notes for the target architecture

An API amplifies this: a mobile client rendering a list view will fan out
where a chat message did not. Fixing the presenter N+1 before T09 means the
list endpoint is not born slow.
