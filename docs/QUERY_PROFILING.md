# Query profiling (T12)

How the database read paths are measured and kept from regressing.

## Signals that run all the time

**Per-update and per-request query budget.** Every Telegram update and every
API request runs inside `core.query_counter.count_queries`. One that issues
more than `QUERY_BUDGET` statements (default 40) logs:

```
WARNING coord_bot.queries Query budget exceeded label=callback:ev queries=57 budget=40
```

Labels are low-cardinality: `command:/events`, `callback:ev`, `message`,
`GET /events/{event_id}`. No IDs or message text appear in them. A warning
that keeps coming back for the same label is an N+1 introduced in that flow.

**Tests.** `tests/test_query_budget.py` fails if:

- rendering an event (status card, details) issues more queries at 15
  participants than at 2;
- the lock announcement does the same;
- `GET /events` issues more queries for 9 events than for 1;
- any hot query in `db/hot_queries.py` stops using the index built for it,
  on a seeded database of realistic shape (10k events, 80k participants).

## Measuring production

The ticket's "top 10 queries by total time from real data" needs the live
database, so it is a runbook step rather than something this repository can
assert.

1. `docker-compose.yml` starts PostgreSQL with
   `shared_preload_libraries=pg_stat_statements`. On a managed database, set
   the equivalent parameter. Then, once per database:
   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
   SELECT pg_stat_statements_reset();
   ```
2. Let a representative window pass (a week covers the weekly digest).
3. Read the top 10 statements and the never-used indexes:
   ```
   psql "$DB_URL" -f telegram-bot/scripts/top_queries.sql
   ```
   Statement text is normalized (`$1`, `$2`), so the output holds no user
   data.
4. Check that the hot paths still plan onto their indexes against real
   statistics. EXPLAIN only, safe on production:
   ```
   DB_URL=... python telegram-bot/scripts/explain_hot_queries.py \
       --event-id <busy event> --group-id <busy group> --user-id <active user>
   ```
   It exits non-zero if any query misses its index.

Record the findings in T12 when this has been run.

## What the audit found and changed

- **N+1s fixed:** `GET /events` (two queries per event, now three in total),
  the lock announcement (one user lookup per participant), `/my_history`
  (one memory lookup per event; status counts were five queries, now one)
  and the waitlist view (one user lookup per entry). The event status and
  details renderers named in the ticket were already batched; the tests now
  keep them that way.
- **`GET /events` is bounded** by a `limit` parameter (default 100, max
  500) instead of returning a group's whole history.
- **Indexes from `3fead70d5078`:** each is used by the query listed in
  `db/hot_queries.py`. The per-user foreign-key indexes also serve account
  erasure, whose `ON DELETE CASCADE` / `SET NULL` would otherwise scan each
  table.
- **Redundant indexes dropped** (migration `b7e4d2a9c613`): six older
  indexes whose columns were a strict prefix of another index or the
  primary key, so they only added write cost. They are listed in the
  migration.

Background jobs (scheduler reminders, collapse checks, weekly digest) still
loop over events with per-event queries. They run twice an hour over small
sets and are not on a user's critical path; the budget warning will flag
them if that changes.
