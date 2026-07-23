# T01 — Scheduler double-fires on every instance

**Tier 0 · correctness under scale · area: scheduling**
**Blocks:** T02 (running >1 instance at all)
**Depends on:** nothing — do this first

## Why

`main.py:386` registers the background jobs on python-telegram-bot's in-process
`JobQueue`:

```python
job_queue = application.job_queue
if job_queue:
    job_queue.run_repeating(...)   # every 30 minutes
```

Every process that boots runs its own copy. With N instances you get N× every
scheduled side effect:

- N memory-collection DMs to the same person after an event
- N weekly digests to the same group
- N `collapse_at` auto-cancels racing each other
- N 24h reminders

This is **user-visible damage**, not a performance issue. It is the single
reason a second instance cannot be started today even if everything else were
ready. Ship this before anyone scales a replica.

## Current state

- `bot/common/scheduler.py` — `SchedulerService`, five periodic tasks
- `main.py:122` — `run_scheduled_tasks()` wrapper
- `main.py:386` — registration on the JobQueue

The tasks themselves are mostly idempotent-ish at the DB level but the
*notifications* are not: `send_message` has no dedupe.

## What to do

Pick one of two shapes. Recommendation: **leader lock** now, extraction later
if the workload grows — it is a ~40 line change and keeps deployment simple.

### Option A — leader lock (recommended)

Wrap each job in a mutually-exclusive lock so exactly one instance runs it.

PostgreSQL advisory locks are the cheapest correct option — no new
infrastructure, and the lock dies with the connection, so a crashed leader
does not wedge the schedule:

```python
# Session-level advisory lock, released when the connection returns to pool.
locked = await session.scalar(
    select(func.pg_try_advisory_lock(JOB_LOCK_NAMESPACE, job_id))
)
if not locked:
    return  # another instance owns this tick
```

Redis (`core/state.py` is already wired) also works via `SET key val NX EX`,
but needs a TTL tuned to the job's worst-case runtime; advisory locks do not.

### Option B — extract to a dedicated worker

Separate process/container, `replicas: 1`. Cleaner separation and lets the
scheduler scale independently, but adds a deployment unit and needs the
service layer to be callable without a `Bot` — so it really wants T06 first.

## Acceptance criteria

- [ ] Two instances started simultaneously produce exactly one digest, one
      reminder, one collapse-check per interval
- [ ] Test that simulates two concurrent schedulers and asserts single
      execution (in-process, two sessions, no containers needed)
- [ ] A leader that dies mid-job does not block the next tick
- [ ] Jobs that partially completed do not re-send notifications already sent
      on retry — check `IdempotencyService`, which is already DB-backed and
      may cover this

## Notes for the target architecture

Once there is a web/mobile backend, these jobs belong to the *backend*, not
the bot — they are domain events (an event collapsed, a deadline passed) that
must reach every transport. Keeping them behind a lock rather than inside the
bot process makes that move a relocation instead of a rewrite.
