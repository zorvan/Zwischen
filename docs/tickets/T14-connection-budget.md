# T14 — Connection budget and pooling at scale

**Tier 3 · performance · area: db / infra**
**Depends on:** T02 (only matters once instances multiply)

## Why

Pool configuration became per-deployment in the Phase-0 fix
(`config/settings.py`): `DB_POOL_SIZE` (10), `DB_MAX_OVERFLOW` (20),
`DB_POOL_RECYCLE` (1800), `DB_POOL_TIMEOUT` (30).

The arithmetic that matters:

```
peak connections = instances × (pool_size + max_overflow)
```

At defaults, 4 instances is 120 connections. PostgreSQL's stock
`max_connections` is 100. **The fifth instance fails to connect**, and it
fails as connection-refused under load rather than at boot, which is the worst
time to discover it.

## What to do

1. **Size deliberately.** Lower per-instance pools as instance count rises.
   Each PostgreSQL connection is a backend process with real memory cost; more
   connections past the CPU count reduces throughput.
2. **Add PgBouncer past ~4 instances.** Transaction-mode pooling lets many
   application connections share few server ones.

   **Critical caveat:** transaction-mode pooling breaks server-side prepared
   statements. asyncpg prepares by default, so it needs:

   ```python
   create_async_engine(url, connect_args={"statement_cache_size": 0})
   ```

   Without this you get intermittent `prepared statement "__asyncpg_stmt_x__"
   already exists` — nondeterministic, load-dependent, and painful to
   diagnose. If PgBouncer is on the roadmap, add this now.
3. **Verify `pool_recycle` against the proxy's idle timeout.** It must be
   *shorter* than PgBouncer's `server_idle_timeout` and any load balancer idle
   timeout, or connections come back dead. 1800s is a reasonable default but
   must be checked against actual infrastructure.
4. **Monitor.** Pool checkout wait time and `pg_stat_activity` count. Rising
   checkout wait is the leading indicator of exhaustion.
5. **Separate the read path** if load justifies it later — read replicas for
   list views, primary for writes. Not yet; noted so the session factory is
   not written in a way that precludes it.

## Acceptance criteria

- [x] Documented connection budget: instances × pool size vs `max_connections`
      (`docs/CONNECTION_BUDGET.md`, plus a startup check against the live server)
- [x] Sizing guidance in `.env.example` beside the knobs
- [ ] If PgBouncer: `statement_cache_size=0` set and verified under
      concurrent load, not just a smoke test
      (set via `DB_PGBOUNCER=true` and load-tested against PostgreSQL; the
      through-PgBouncer test needs `PGBOUNCER_TEST_URL`, unavailable here)
- [x] `pool_recycle` shorter than every idle timeout in the path
      (checked at startup against `DB_IDLE_TIMEOUT`; the real value is per deployment)
- [x] Pool exhaustion surfaces as a clear error and a metric, not a hang

## Notes for the target architecture

The API (T09) will hold connections for longer than the bot does — a request
handler with an await-heavy code path occupies a pooled connection the whole
time. Budget for the API separately rather than reusing the bot's numbers.
