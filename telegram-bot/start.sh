#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DB_CONTAINER_NAME="${DB_CONTAINER_NAME:-coord_bot_db}"
DB_VOLUME_NAME="${DB_VOLUME_NAME:-coord_bot_db_data}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:15}"
POSTGRES_USER="${POSTGRES_USER:-coord_user}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-coord_pass}"
POSTGRES_DB="${POSTGRES_DB:-coord_db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_CONTAINER_NAME="${REDIS_CONTAINER_NAME:-coord_bot_redis}"
REDIS_VOLUME_NAME="${REDIS_VOLUME_NAME:-coord_bot_redis_data}"
REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}"
REDIS_PORT="${REDIS_PORT:-6379}"
BOT_PID_FILE="${BOT_PID_FILE:-$ROOT/.coord_bot.pid}"
BOT_LOCK_FILE="${BOT_LOCK_FILE:-$ROOT/.coord_bot.lock}"
BOT_PID=""
SHUTTING_DOWN=0

load_env() {
  if [ -f .env ]; then
    local -A preserved_values=()
    local -A preserved_present=()
    local line=""
    local key=""

    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        ''|'#'*)
          continue
          ;;
      esac

      if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)= ]]; then
        key="${BASH_REMATCH[1]}"
        if [ "${!key+x}" = x ]; then
          preserved_present["$key"]=1
          preserved_values["$key"]="${!key}"
        fi
      fi
    done < .env

    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a

    for key in "${!preserved_present[@]}"; do
      export "$key=${preserved_values[$key]}"
    done
  fi
}

ensure_python() {
  if [ ! -x .venv/bin/python ]; then
    echo "Error: .venv/bin/python not found. Create the venv and install dependencies first."
    exit 1
  fi
}

default_db_url() {
  .venv/bin/python - <<'PY'
import sys
driver = "postgresql+psycopg" if sys.version_info >= (3, 14) else "postgresql+asyncpg"
print(f"{driver}://coord_user:coord_pass@localhost:5432/coord_db")
PY
}

ensure_required_env() {
  if [ -z "${TELEGRAM_TOKEN:-}" ]; then
    echo "Error: TELEGRAM_TOKEN environment variable is not set."
    exit 1
  fi

  case "${TELEGRAM_TOKEN}" in
    test-token|dummy-token|changeme|your-token-here|"<set-me>")
      echo "Error: TELEGRAM_TOKEN is still a placeholder value (${TELEGRAM_TOKEN})."
      echo "Set a real BotFather token in .env before running start.sh."
      exit 1
      ;;
  esac

  case "${TELEGRAM_TOKEN}" in
    *:*)
      ;;
    *)
      echo "Error: TELEGRAM_TOKEN does not look like a real Telegram bot token."
      echo "Expected something like '<bot_id>:<secret>' from BotFather."
      exit 1
      ;;
  esac

  if [ -z "${DB_URL:-}" ]; then
    export DB_URL="$(default_db_url)"
    echo "DB_URL not set. Defaulting to local database: $DB_URL"
  fi
}

is_local_db_url() {
  case "${DB_URL:-}" in
    postgresql+asyncpg://*localhost:${POSTGRES_PORT}/${POSTGRES_DB}|\
    postgresql+asyncpg://*127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}|\
    postgresql+psycopg://*localhost:${POSTGRES_PORT}/${POSTGRES_DB}|\
    postgresql+psycopg://*127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB})
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_local_redis_url() {
  case "${REDIS_URL:-}" in
    redis://localhost:${REDIS_PORT}/*|redis://127.0.0.1:${REDIS_PORT}/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: required command '$1' is not available."
    exit 1
  fi
}

wait_for_db_health() {
  local status=""
  for _ in $(seq 1 30); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$DB_CONTAINER_NAME" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    sleep 2
  done

  echo "Error: database container '$DB_CONTAINER_NAME' did not become healthy."
  docker logs "$DB_CONTAINER_NAME" || true
  exit 1
}

wait_for_redis_health() {
  local status=""
  for _ in $(seq 1 30); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$REDIS_CONTAINER_NAME" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    sleep 1
  done

  echo "Error: Redis container '$REDIS_CONTAINER_NAME' did not become healthy."
  docker logs "$REDIS_CONTAINER_NAME" || true
  exit 1
}

reset_local_db() {
  require_command docker

  if docker ps -a --format '{{.Names}}' | grep -qx "$DB_CONTAINER_NAME"; then
    echo "Removing existing database container: $DB_CONTAINER_NAME"
    docker rm -f "$DB_CONTAINER_NAME" >/dev/null
  fi

  if docker volume ls --format '{{.Name}}' | grep -qx "$DB_VOLUME_NAME"; then
    echo "Removing existing database volume: $DB_VOLUME_NAME"
    docker volume rm -f "$DB_VOLUME_NAME" >/dev/null
  fi

  echo "Starting fresh local PostgreSQL container: $DB_CONTAINER_NAME"
  docker run -d \
    --name "$DB_CONTAINER_NAME" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -p "${POSTGRES_PORT}:5432" \
    -v "${DB_VOLUME_NAME}:/var/lib/postgresql/data" \
    --health-cmd="pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}" \
    --health-interval=5s \
    --health-timeout=5s \
    --health-retries=10 \
    "$POSTGRES_IMAGE" >/dev/null

  wait_for_db_health

  # Schema is no longer applied from db/schema.sql here. Alembic migrations
  # run at startup (see db/migrate.py) and are the single source of truth;
  # loading schema.sql first would create tables that may not match the
  # models, leaving the database silently drifted from migration history.
  echo "Schema will be created by Alembic migrations on bot startup"
}

reset_local_redis() {
  require_command docker

  if docker ps -a --format '{{.Names}}' | grep -qx "$REDIS_CONTAINER_NAME"; then
    echo "Removing existing Redis container: $REDIS_CONTAINER_NAME"
    docker rm -f "$REDIS_CONTAINER_NAME" >/dev/null
  fi

  if docker volume ls --format '{{.Name}}' | grep -qx "$REDIS_VOLUME_NAME"; then
    echo "Removing existing Redis volume: $REDIS_VOLUME_NAME"
    docker volume rm -f "$REDIS_VOLUME_NAME" >/dev/null
  fi

  echo "Starting fresh local Redis container: $REDIS_CONTAINER_NAME"
  docker run -d \
    --name "$REDIS_CONTAINER_NAME" \
    -p "${REDIS_PORT}:6379" \
    -v "${REDIS_VOLUME_NAME}:/data" \
    --health-cmd="redis-cli ping" \
    --health-interval=5s \
    --health-timeout=3s \
    --health-retries=10 \
    "$REDIS_IMAGE" redis-server --appendonly yes >/dev/null

  wait_for_redis_health
}

acquire_bot_lock() {
  require_command flock

  exec 9>"$BOT_LOCK_FILE"
  if ! flock -n 9; then
    echo "Error: another bot instance is already running from this workspace."
    exit 1
  fi
}

start_bot() {
  echo "Starting Coordination Engine Bot with .venv/bin/python"
  .venv/bin/python main.py &
  BOT_PID=$!
  printf '%s\n' "$BOT_PID" >"$BOT_PID_FILE"
  wait "$BOT_PID"
}

shutdown() {
  local exit_code=$?
  if [ "$SHUTTING_DOWN" -eq 1 ]; then
    return
  fi
  SHUTTING_DOWN=1
  trap - INT TERM

  if [ -n "$BOT_PID" ] && kill -0 "$BOT_PID" 2>/dev/null; then
    echo "Stopping bot process gracefully: $BOT_PID"
    kill -TERM "$BOT_PID" 2>/dev/null || true
    for _ in $(seq 1 50); do
      if ! kill -0 "$BOT_PID" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
    if kill -0 "$BOT_PID" 2>/dev/null; then
      echo "Bot did not stop within 10 seconds; forcing shutdown."
      kill -KILL "$BOT_PID" 2>/dev/null || true
    fi
    wait "$BOT_PID" 2>/dev/null || true
  fi

  rm -f "$BOT_PID_FILE"
  ./stop.sh --services-only || true
  exit "$exit_code"
}

load_env
ensure_python
ensure_required_env
acquire_bot_lock
trap shutdown EXIT INT TERM

if is_local_db_url; then
  reset_local_db
else
  echo "DB_URL points to a non-local database. Skipping Docker reset and schema bootstrap."
fi

if is_local_redis_url; then
  reset_local_redis
elif [ -n "${REDIS_URL:-}" ]; then
  echo "REDIS_URL points to a non-local Redis server. Skipping Docker management."
fi

start_bot
