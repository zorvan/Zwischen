# T09 — HTTP API over the domain services

**Tier 2 · platform surface · area: api**
**Depends on:** T04, T06, T07, T08

## Why

Web and mobile clients need an API. There is no HTTP framework in
`requirements.txt` today — the only HTTP surface is the Telegram webhook.

## Starting shape

`ai/actions.py:19` already defines a canonical action registry that reads like
a route table:

```python
ACTIONS = {
    "view_events":      {"required_params": [], "optional_params": ["group_id"]},
    "view_event_panel": {"required_params": ["event_id"]},
    "join_event":       {"required_params": ["event_id"]},
    "relinquish_event": {"required_params": ["event_id"]},
    "commit_event":     {...},
}
```

These are already the domain's verbs, already validated
(`ai/validator.py`), and already transport-neutral. Deriving the API from this
registry keeps the bot, the AI mention path and the HTTP API on one set of
operations instead of three drifting copies.

## Design constraints

**Expose `public_id`, never integer keys.** `users`, `groups` and `events` all
have a UUID `public_id` with a unique index. `/events/41` is enumerable and
leaks volume; `/events/f47ac10b-…` does not. Resolve via
`identity.get_user_by_public_id()` and equivalents — note it already returns
`None` for malformed input rather than raising, because the value comes
straight from a client.

**Authorization on every endpoint** via T07's membership service. The bot got
away with implicit trust; the API cannot.

**Sessions per request**, not per process. `db/connection.py:get_session()` is
an async context manager and maps onto a framework dependency directly. The
engine cache is now loop-scoped, so a worker owning its own loop is safe —
that was the Phase-0 fix.

**Idempotency.** `IdempotencyService` is DB-backed and already exists. Wire it
to an `Idempotency-Key` header; mobile clients on flaky networks retry, and
double-joins should be no-ops.

## Framework

Whatever T02's webhook lands on. FastAPI is the obvious default — async,
Pydantic (already a dependency), OpenAPI generation for the mobile client.

## Acceptance criteria

- [ ] Endpoints for the `ACTIONS` verbs: list events, view, join, leave,
      commit, create
- [ ] Every endpoint authenticated and authorized
- [ ] Only `public_id` in request/response bodies
- [ ] Retrying a request with the same `Idempotency-Key` is a no-op
- [ ] OpenAPI schema published for client generation
- [ ] The bot and the API produce identical domain outcomes for the same
      action — worth an explicit test, since divergence here is what causes
      the two surfaces to drift

## Notes for the target architecture

Bot and API become two adapters over one core. Resist adding domain logic in
handlers on either side; if an endpoint needs a rule the bot does not have,
the rule belongs in a service.
