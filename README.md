# Zwischen

`Zwischen` is a coordination system for small groups. The repository currently centers on a production-oriented Telegram bot that helps groups form events, track participation, surface coordination state, and carry memory from one gathering into the next.

## Repository Status

Today, the Telegram bot is the only runnable part of the repo. Client surfaces beyond Telegram (Mini App, mobile) are not present in the tree; their planning documents were removed and only the versioned product docs under `telegram-bot/docs/` remain.

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
- `db/`: SQLAlchemy models, async DB connection code, and schema reference
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
reachable. To run only those, or to exclude them:

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
- PostgreSQL is the system of record.
- The runtime dependency switches DB driver by Python version:
  - `asyncpg` for Python `< 3.14`
  - `psycopg` for Python `>= 3.14`
- The AI backend is Google Gemini via its **OpenAI-compatible** endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`). `AI_ENDPOINT` must be that compatibility base URL, not Gemini's native `:generateContent` URL.
- [telegram-bot/docker-compose.yml](/home/zorvan/Work/projects/Zwischen/telegram-bot/docker-compose.yml) runs the full stack (bot + PostgreSQL). The shell scripts remain the fastest path for host-native development.

## Running With Docker

```bash
cd telegram-bot
cp .env.example .env        # fill in TELEGRAM_TOKEN and AI_API_KEY
docker compose up --build
```

The bot waits for PostgreSQL to become healthy, creates its schema on first
boot, and stores conversation state in the `bot_state` volume.

## Documentation Map

- Product overview: [telegram-bot/README.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/README.md)
- Current PRD: [telegram-bot/docs/v3/v3.2/coordination-engine-PRD-v3.2.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/docs/v3/v3.2/coordination-engine-PRD-v3.2.md)
- User flows: [telegram-bot/docs/v3/v3.2/USER_FLOWS_v3.2.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/docs/v3/v3.2/USER_FLOWS_v3.2.md)
- Rebuild spec (v3.5): [telegram-bot/docs/v3/v3.5/Coordination_Engine_v3.5_Rebuild_Specification.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/docs/v3/v3.5/Coordination_Engine_v3.5_Rebuild_Specification.md)
- Database notes: [telegram-bot/db/README.md](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/README.md)

## Current Reality

This repository is not yet a full multi-client platform. It is a Telegram-first coordination system with a versioned product/design knowledge base for what might come next.

If you are starting work here, the practical default is:

1. begin in `telegram-bot/`
2. treat the bot and PostgreSQL schema as the source of truth
