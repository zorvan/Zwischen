# Connection budget (T14)

## The arithmetic

```
peak server connections = processes × (DB_POOL_SIZE + DB_MAX_OVERFLOW)
available               = max_connections − superuser_reserved_connections − 5
```

The 5 is headroom for `psql`, migrations, backups and monitoring. A
"process" is anything holding its own pool: each bot replica and each API
worker. Pools are also scoped per event loop (`db/connection.py`). Both the
bot and the API run one loop per process, so each process holds one pool.

At stock PostgreSQL (`max_connections = 100`, 3 reserved) **92** are
available:

| Processes | Pool + overflow each | Peak | Fits |
|---|---|---|---|
| 1 | 10 + 20 (defaults) | 30 | yes |
| 2 | 10 + 20 | 60 | yes |
| 3 | 10 + 20 | 90 | yes, barely |
| 4 | 10 + 20 | 120 | **no**: the fourth process fails under load |
| 4 | 10 + 10 | 80 | yes |
| 8 | 5 + 5 | 80 | yes |
| more | — | — | PgBouncer, or raise `max_connections` |

More server connections than CPU cores mostly adds contention, so past a
handful of processes PgBouncer is better than a larger `max_connections`.

**The API holds connections longer than the bot.** A request handler keeps its
pooled connection for the whole await-heavy request. Give API workers their own
`DB_POOL_SIZE` in their own environment instead of copying the bot's, and count
them in `DB_PROCESSES` on every process so each startup check sees the whole
deployment.

## What the application checks

At startup (`main.py` → `db.pool_budget.check_connection_budget`) the bot
reads `max_connections` and `superuser_reserved_connections` from the live
server and logs one of:

```
INFO  Connection budget OK: 1 process(es) × (10 pool + 20 overflow) = 30 peak connections; server allows 92 ...
ERROR Connection budget EXCEEDED: 4 process(es) × (10 pool + 20 overflow) = 120 peak ...; at this pool size at most 3 process(es) fit
```

It also logs an error when `DB_POOL_RECYCLE` is not shorter than
`DB_IDLE_TIMEOUT` (see below).

At runtime:

- **Exhaustion fails fast and clearly.** When no connection frees up within
  `DB_POOL_TIMEOUT`, the caller gets `PoolExhaustedError` ("Database pool
  exhausted: no connection free within 30s (DB_POOL_SIZE=10,
  DB_MAX_OVERFLOW=20) ...") rather than a generic timeout. It is logged and
  counted.
- **Saturation is the early warning.** Each checkout that takes the last free
  connection logs `DB pool saturated` and increments a counter. A rising rate
  means exhaustion is coming.
- **`GET /health`** on the API returns those counters (`checkouts`,
  `saturated`, `exhausted`) for the process. They contain no user data.
- On the server side, watch `SELECT count(*) FROM pg_stat_activity` against
  the budget above.

## PgBouncer

Set `DB_PGBOUNCER=true` when the database URL points at PgBouncer in
**transaction** mode. That passes asyncpg `statement_cache_size=0`, turns off
SQLAlchemy's asyncpg prepared-statement cache, and gives each prepared
statement a unique name. Without these you get intermittent
`prepared statement "__asyncpg_stmt_x__" already exists` errors under load.

With PgBouncer in front, the app's pools are PgBouncer *clients*, and the
startup check says so instead of comparing them with `max_connections`. Size
PgBouncer's `default_pool_size` × databases against `max_connections` instead.

**Verification status:** `tests/test_pool_budget.py` runs 40 concurrent
workers with these options against PostgreSQL directly; that passes. The
test that goes through a real transaction-mode PgBouncer is
`test_through_real_pgbouncer_transaction_mode`. It runs only when
`PGBOUNCER_TEST_URL` is set, because no PgBouncer was available where this was
written. Run it before relying on PgBouncer:

```
PGBOUNCER_TEST_URL=postgresql://user:pass@pgbouncer:6432/coord_db \
    pytest tests/test_pool_budget.py -k pgbouncer
```

Use a PgBouncer with `pool_mode = transaction` and a `default_pool_size`
smaller than the 40 workers, so statements really do move between server
connections.

## Idle timeouts and `DB_POOL_RECYCLE`

A pooled connection that sits idle longer than any hop's idle timeout is
silently closed by that hop and handed out dead. `pool_pre_ping` catches most
of these at a cost of one round trip. `DB_POOL_RECYCLE` avoids them by
retiring connections first, so it must be **shorter than the shortest idle
timeout between the app and its database server**:

| Hop | Typical idle timeout |
|---|---|
| AWS Network Load Balancer | 350 s |
| GCP Cloud SQL proxy / TCP LB | 600 s |
| PgBouncer `client_idle_timeout` | 0 (disabled) by default |
| PgBouncer `server_idle_timeout` | 600 s, but this governs PgBouncer's own server connections, not ours |

The 1800 s default is right only when nothing in the path times out sooner.
Set `DB_IDLE_TIMEOUT` to the real minimum for the deployment (for example 350
behind an AWS NLB, with `DB_POOL_RECYCLE=300`), and startup will report a
mismatch.

## Read replicas

Not needed yet. `db.connection.get_session(db_url)` already takes the URL per
call, so a read path can later be pointed at a replica URL without changing
the session factory.
