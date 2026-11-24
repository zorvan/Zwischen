#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DB_CONTAINER_NAME="${DB_CONTAINER_NAME:-coord_bot_db}"
REDIS_CONTAINER_NAME="${REDIS_CONTAINER_NAME:-coord_bot_redis}"
BOT_PID_FILE="${BOT_PID_FILE:-$ROOT/.coord_bot.pid}"
SERVICES_ONLY=false

if [ "${1:-}" = "--services-only" ]; then
  SERVICES_ONLY=true
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: required command '$1' is not available."
    exit 1
  fi
}

stop_container() {
  local container_name="$1"
  local service_name="$2"

  if docker ps --format '{{.Names}}' | grep -qx "$container_name"; then
    echo "Stopping $service_name container: $container_name"
    docker stop "$container_name" >/dev/null
  elif docker ps -a --format '{{.Names}}' | grep -qx "$container_name"; then
    echo "$service_name container is already stopped: $container_name"
  else
    echo "$service_name container does not exist: $container_name"
  fi
}

stop_bot() {
  if [ ! -f "$BOT_PID_FILE" ]; then
    echo "No tracked bot process is running."
    return
  fi

  local bot_pid=""
  bot_pid="$(<"$BOT_PID_FILE")"
  if [[ ! "$bot_pid" =~ ^[0-9]+$ ]] || ! kill -0 "$bot_pid" 2>/dev/null; then
    echo "Removing stale bot PID file."
    rm -f "$BOT_PID_FILE"
    return
  fi

  local process_cwd=""
  local process_command=""
  process_cwd="$(readlink -f "/proc/$bot_pid/cwd" 2>/dev/null || true)"
  process_command="$(tr '\0' ' ' <"/proc/$bot_pid/cmdline" 2>/dev/null || true)"
  if [ "$process_cwd" != "$ROOT" ] || [[ "$process_command" != *"main.py"* ]]; then
    echo "Refusing to stop PID $bot_pid: it is not this workspace's bot process."
    return 1
  fi

  echo "Stopping bot process gracefully: $bot_pid"
  kill -TERM "$bot_pid"
  for _ in $(seq 1 50); do
    if ! kill -0 "$bot_pid" 2>/dev/null; then
      rm -f "$BOT_PID_FILE"
      return
    fi
    sleep 0.2
  done

  echo "Bot did not stop within 10 seconds; forcing shutdown."
  kill -KILL "$bot_pid" 2>/dev/null || true
  rm -f "$BOT_PID_FILE"
}

if [ "$SERVICES_ONLY" = false ]; then
  stop_bot
fi
require_command docker
stop_container "$REDIS_CONTAINER_NAME" "Redis"
stop_container "$DB_CONTAINER_NAME" "PostgreSQL"

echo "Local service containers stopped. Data volumes were preserved."
