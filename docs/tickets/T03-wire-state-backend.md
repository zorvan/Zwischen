# T03 — Wire the shared state backend into the running code

**Tier 0 · correctness under scale · area: state**
**Depends on:** nothing (backend already exists and is tested)
**Blocks:** T02's multi-instance criterion, T04 (they overlap in one big file)

## Why

`core/state.py` was added on the `platform-independence` branch with in-memory
and Redis implementations, both covered by the same test suite. **Nothing uses
it yet.** Three process-local mechanisms are still live:

| Mechanism | Location | Failure with N instances |
|---|---|---|
| `PicklePersistence` | `main.py:189` | N pickle files; flow state depends on which instance answers |
| `StateStore` singleton | `bot/services/state_store.py:308` | `_store_for_user` dict is per-process |
| Rate limiter | `bot/common/rate_limiter.py` | N× the intended rate — its own docstring says so |

216 `user_data` call sites across `bot/`.

## What to do

Three sub-tasks, independently shippable. Order matters: the rate limiter is
smallest and proves the backend in production.

### T03a — rate limiter (smallest, do first)

`bot/common/rate_limiter.py` already has the right shape. Replace the
in-memory `defaultdict` with `StateBackend.hit_window()`, which is already a
sliding window and pipelined. Roughly a 30-line change.

Note the limiter is currently **not even enabled** — `main.py:200` has the
middleware registration commented out. Enabling it is part of this.

### T03b — StateStore

`bot/services/state_store.py` has typed accessors and TTLs already; the
storage underneath becomes the backend. Its TTL constants
(`EVENT_FLOW_TTL`, `ENRICHMENT_TTL`, `MODIFY_REQUEST_TTL` in
`state_models.py`) map directly onto `ttl_seconds`.

Watch for: the store holds `asyncio.Lock` objects for per-event locking. Those
do **not** survive serialization and are meaningless across processes — a
cross-instance lock needs Redis (`SET NX`) or a Postgres advisory lock, same
as T01. Decide whether the locking is load-bearing or belongs to the
optimistic-concurrency `Event.version` column that already exists.

### T03c — conversation state / PicklePersistence

The big one. Replace `PicklePersistence` with a PTB `BasePersistence`
implementation over `StateBackend`, or move flows off `user_data` entirely.

**`bot/commands/event_creation.py` is 2,652 lines with 56 `user_data`
touches.** It will also appear in T04. Doing it once — reshaped as a
form-style flow rather than ported button-wizard verbatim — is much less work
than doing it twice, and it is the single biggest simplification available in
this codebase.

Values must be JSON-serializable (`core/state.py` enforces this on both
backends deliberately, so a value cannot work locally and fail in production).
Anything currently stashing a `datetime` or an ORM object in `user_data` needs
converting.

## Acceptance criteria

- [ ] `REDIS_URL` set → two instances share flow state; a creation flow spanning
      both completes
- [ ] `REDIS_URL` unset → single-instance behaviour unchanged, warning logged
- [ ] Rate limits are enforced globally, not per-instance, and the middleware
      is actually enabled
- [ ] No `PicklePersistence` in `main.py`; `bot_state` volume no longer needed
- [ ] TTLs still expire abandoned flows

## Notes for the target architecture

Conversation state is a *bot* concept — a web client keeps wizard state in the
browser. What must be shared is anything the server treats as authoritative.
While migrating, prefer moving state into the database (where it becomes
visible to every transport) over moving it into Redis (where it stays a bot
implementation detail). Redis is right for ephemeral flow position; wrong for
anything another client should see.
