# T02 — Polling forbids a second instance

**Tier 0 · correctness under scale · area: transport**
**Depends on:** T01 (otherwise scaling out multiplies scheduled sends)
**Blocks:** any horizontal scaling of the bot

## Why

`main.py:423` runs `application.run_polling()`. Telegram permits exactly one
`getUpdates` consumer per bot token — a second instance receives:

```
Conflict: terminated by other getUpdates request;
make sure that only one bot instance is running
```

So the bot cannot be scaled horizontally at all while polling. Webhook mode is
the only path, and it is currently the *least* exercised one: `main.py:409`
gates it behind `ENVIRONMENT=production`, and `Settings` requires
`WEBHOOK_URL` only in that case. Development, tests and every local run
exercise the polling path exclusively.

## Current state

- `main.py:423` — `run_polling()` for non-production
- `main.py:405-415` — `setup_webhook()`, blocking, owns the loop
- `bot/common/webhook.py` — `WorkerQueue`, an async fan-out queue
- `config/settings.py` — `webhook_url`, `webhook_port`, `webhook_secret`,
  `webhook_host`

## What to do

1. **Make webhook mode runnable locally.** Behind a tunnel (ngrok/cloudflared)
   or with a `WEBHOOK_MODE=true` override independent of `ENVIRONMENT`. The
   path that production depends on should not be one nobody runs.
2. **Verify multi-instance behaviour behind a load balancer.** Telegram
   delivers each update once to the endpoint; the balancer decides which
   instance handles it. That is fine *provided* conversation state is shared —
   see T03. Without T03, a user's multi-step flow breaks the moment two
   consecutive updates land on different instances.
3. **Validate `WEBHOOK_SECRET`.** Confirm the secret-token header is checked on
   every request; an unauthenticated webhook endpoint accepts forged updates.
4. **Health/readiness endpoints** for the balancer. `docker/healthcheck.py`
   exists — check whether it is HTTP-reachable.
5. **Graceful shutdown**: drain in-flight updates before exit so a rolling
   deploy does not drop them. `stop_grace_period: 30s` is set in compose;
   confirm the app actually uses it, and call `dispose_engines()`
   (`db/connection.py`) on the way down.

## Acceptance criteria

- [ ] Webhook mode runs locally without `ENVIRONMENT=production`
- [ ] Two instances behind a balancer both serve updates with no `Conflict`
- [ ] A multi-step flow (event creation) completes correctly when consecutive
      updates hit different instances — this is the real test, and it will
      fail until T03 lands
- [ ] Requests without a valid secret token are rejected
- [ ] SIGTERM drains in-flight work and disposes the pool

## Ordering note

T03 is a hard prerequisite for the *third* criterion but not for the others.
Doing T02 first gets you a correct single-instance webhook deployment, which
is a fine intermediate state and de-risks the production path.

## Notes for the target architecture

The webhook endpoint is the first piece of real HTTP surface in this codebase.
Whatever framework it lands on is the natural host for the web API in T09 —
worth choosing with that in mind rather than picking the minimal thing PTB
happens to bundle.
