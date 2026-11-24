# Zwischen

`Zwischen` is a coordination system for small groups. The repository currently centers on a production-oriented Telegram bot that helps groups form events, track participation, surface coordination state, and carry memory from one gathering into the next.

## Repository Status

Today, the Telegram bot is the only runnable part of the repo. Its domain is platform-neutral, though: identities are provider-agnostic (`user_identities`), notifications go through a transport-neutral `Notifier`, and `telegram-bot/api/app.py` exposes the same services over HTTP (`create_app()`, with Telegram Mini App and wallet login). No ASGI entrypoint or client (web, Mini App, mobile) is in the tree yet.

The roadmap toward web, mobile and an optional chain lives in [docs/tickets/INDEX.md](docs/tickets/INDEX.md).

That means this repository is best understood as:

- an active backend and bot implementation
- a growing product/design knowledge base

## What The Telegram Bot Does

The bot is a Telegram-based coordination engine built in Python on top of `python-telegram-bot`, SQLAlchemy, and PostgreSQL.

Core capabilities in the current codebase include:

- event planning and creation flows
- join, confirm, cancel, lock, and modify event actions
- private constraint and availability input
- event state transitions and lifecycle handling
- waitlist and organizer-support flows
- memory capture and recall across events
- weekly digest and scheduled background tasks
- mention-driven AI assistance in group chats
- personal participation history and attendance mirror
- enforced data decay, `/privacy`, and full account erasure (`/delete_account`)

The product philosophy and detailed behavior live most clearly in:

- [telegram-bot/README.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/README.md)
- [telegram-bot/docs/v3/v3.2/coordination-engine-PRD-v3.2.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/docs/v3/v3.2/coordination-engine-PRD-v3.2.md)

## High-Level Architecture

### `telegram-bot/`

Main implementation area.

- `main.py`: bot entrypoint and handler registration
- `bot/commands/`: slash commands and DM-facing flows
- `bot/handlers/`: callback, mention, membership, and event-flow handlers
- `bot/services/`: event lifecycle, participant, waitlist, memory, and related domain services
- `bot/common/`: shared coordination logic, scheduling, formatting, menus, notifications, and access helpers
- `db/`: SQLAlchemy models, Alembic migrations, identity resolution, connection pooling and budget
- `core/`: transport-neutral pieces (notifier, shared state, auth, read cache, query counter, anchoring)
- `api/`: HTTP API over the domain services
- `ai/`: LLM client, schemas, and AI-oriented rules
- `tests/`: unit, integration, contract, scenario, and broader regression coverage
- `docs/`: versioned product/design documentation


## Quick Start

The shortest path to running the existing system is to start the Telegram bot.

### 1. Create a virtual environment

```bash
cd telegram-bot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Create a `.env`

At minimum:

```env
TELEGRAM_TOKEN=<your-botfather-token>
DB_URL=postgresql+asyncpg://coord_user:coord_pass@localhost:5432/coord_db
AI_ENDPOINT=http://127.0.0.1:8080/v1/
AI_MODEL=qwen/qwen3-coder-next
AI_API_KEY=dummy-key
ENVIRONMENT=development
LOG_LEVEL=INFO
```

Notes:

- `TELEGRAM_TOKEN` is required and validated at startup.
- If `DB_URL` is omitted, the helper scripts default to a local PostgreSQL URL.
- The bot performs startup checks for both LLM and database availability.

### 3. Start the bot

For a fresh local database reset and bootstrap:

```bash
./start.sh
```

To reuse an existing local database container:

```bash
./resume.sh
```

Both scripts live in [telegram-bot/start.sh](/home/zorvan/Work/projects/Zwischen/telegram-bot/start.sh) and [telegram-bot/resume.sh](/home/zorvan/Work/projects/Zwischen/telegram-bot/resume.sh).

## Running Tests And Checks

From `telegram-bot/`:

```bash
pytest
```

There is also a targeted quality script:

```bash
./scripts/check_quality.sh
```

Tests needing a live PostgreSQL are marked `integration` and skip when none is
reachable. They create and migrate a throwaway database on the server named by
`DB_URL`, so any disposable PostgreSQL works:

```bash
docker run -d --rm --name zwischen_test_pg -p 127.0.0.1:56987:5432 \
  -e POSTGRES_USER=coord_user -e POSTGRES_PASSWORD=coord_pass -e POSTGRES_DB=coord_db \
  postgres:16-alpine
DB_URL=postgresql://coord_user:coord_pass@localhost:56987/coord_db pytest
```

The cross-instance cache test also needs Redis (`REDIS_TEST_URL`, default
`redis://127.0.0.1:56990/15`), and the PgBouncer test runs only when
`PGBOUNCER_TEST_URL` points at a transaction-mode PgBouncer. Both skip
otherwise.

To run only the integration tests, or to exclude them:

```bash
pytest -m integration
pytest -m "not integration"
```

Useful references:

- [telegram-bot/tests/](/home/zorvan/Work/projects/Zwischen/telegram-bot/tests)
- [telegram-bot/scripts/check_quality.sh](/home/zorvan/Work/projects/Zwischen/telegram-bot/scripts/check_quality.sh)

## Database Migrations

Schema changes are managed with Alembic. Migrations run automatically at
startup, so a normal deploy needs no manual step.

```bash
# after editing db/models.py
alembic revision --autogenerate -m "describe the change"
alembic upgrade head          # applied automatically on boot too
alembic downgrade -1          # roll back one revision
alembic history               # see what exists
```

`db/models.py` is the single source of truth, and the Alembic revisions are the
authoritative DDL. The old `db/schema.sql` was deleted: it had drifted from the
models (it carried 23 indexes and 9 `jsonb` columns they never declared), and
keeping a second, non-authoritative schema file is what allowed that to happen
unnoticed.

**Adopting an existing database.** A database created before Alembic has all
the tables but no migration history. On first boot it is *stamped* with the
baseline revision — recorded as already-current, not re-executed — so adoption
is a no-op that cannot touch your data. Before that first boot, confirm the
live schema actually matches the models:

```bash
python -m scripts.check_schema_drift
```

Exit code 0 means clean. If it lists differences (likely if columns were ever
added by hand), resolve them first: either update `db/models.py` to match
reality, or generate a migration that brings the database in line.

## Infrastructure Notes

- Python support in the bot is documented as `3.13` to `3.14`.
- PostgreSQL is the system of record. Redis (`REDIS_URL`) holds shared conversation state, rate limits and the read cache, and is required once more than one instance runs.
- Size connection pools with [docs/CONNECTION_BUDGET.md](docs/CONNECTION_BUDGET.md); startup logs whether the configured pools fit the server.
- The runtime dependency switches DB driver by Python version:
  - `asyncpg` for Python `< 3.14`
  - `psycopg` for Python `>= 3.14`
- The AI backend is Google Gemini via its **OpenAI-compatible** endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`). `AI_ENDPOINT` must be that compatibility base URL, not Gemini's native `:generateContent` URL.
- [telegram-bot/docker-compose.yml](/home/zorvan/Work/projects/Zwischen/telegram-bot/docker-compose.yml) runs the full stack (bot + PostgreSQL with `pg_stat_statements` + Redis). The shell scripts remain the fastest path for host-native development; `start.sh`/`resume.sh` also manage a local Redis, and `stop.sh` stops everything.

## Running With Docker

```bash
cd telegram-bot
cp .env.example .env        # fill in TELEGRAM_TOKEN and AI_API_KEY
docker compose up --build
```

The bot waits for PostgreSQL and Redis to become healthy, runs migrations on
boot, and keeps conversation state in Redis (`redis_data` volume).

## Documentation Map

- Product overview: [telegram-bot/README.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/README.md)
- Current PRD: [telegram-bot/docs/v3/v3.2/coordination-engine-PRD-v3.2.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/docs/v3/v3.2/coordination-engine-PRD-v3.2.md)
- User flows: [telegram-bot/docs/v3/v3.2/USER_FLOWS_v3.2.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/docs/v3/v3.2/USER_FLOWS_v3.2.md)
- Rebuild spec (v3.5): [telegram-bot/docs/v3/v3.5/Coordination_Engine_v3.5_Rebuild_Specification.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/docs/v3/v3.5/Coordination_Engine_v3.5_Rebuild_Specification.md)
- Database notes: [telegram-bot/db/README.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/README.md)
- Roadmap tickets and status: [docs/tickets/INDEX.md](docs/tickets/INDEX.md)
- Retention policy (what decays, and when): [docs/RETENTION_POLICY.md](docs/RETENTION_POLICY.md)
- Query profiling and N+1 guards: [docs/QUERY_PROFILING.md](docs/QUERY_PROFILING.md)
- Connection budget and PgBouncer: [docs/CONNECTION_BUDGET.md](docs/CONNECTION_BUDGET.md)
- Read cache: [docs/CACHING.md](docs/CACHING.md)
- Optional commitment anchoring: [docs/ANCHORING_DECISION.md](docs/ANCHORING_DECISION.md)

## Current Reality

This repository is not yet a full multi-client platform. It is a Telegram-first coordination system with a versioned product/design knowledge base for what might come next.

If you are starting work here, the practical default is:

1. begin in `telegram-bot/`
2. treat the bot and PostgreSQL schema as the source of truth
