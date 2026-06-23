#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/runtime"
PID_FILE="$RUNTIME_DIR/ayes-server.pid"
MONITOR_PID_FILE="$RUNTIME_DIR/ayes-idle-monitor.pid"
LOG_FILE="$RUNTIME_DIR/ayes-server.log"
MONITOR_LOG_FILE="$RUNTIME_DIR/ayes-idle-monitor.log"
HOST="127.0.0.1"
PORT="8770"
URL="http://${HOST}:${PORT}"
IDLE_TIMEOUT_SEC="${AYES_IDLE_TIMEOUT_SEC:-120}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LAUNCHER_PY="$ROOT_DIR/scripts/run_ayes_service.py"

server_pid=""

mkdir -p "$RUNTIME_DIR"

is_pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    cat "$path" 2>/dev/null || true
  fi
}

is_service_healthy() {
  curl -fsS "$URL/api/status" >/dev/null 2>&1
}

cleanup_stale_pid() {
  local path="$1"
  local pid
  pid="$(read_pid_file "$path")"
  if ! is_pid_alive "$pid"; then
    rm -f "$path"
  fi
}

wait_until_ready() {
  local i
  for i in $(seq 1 40); do
    if is_service_healthy; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_server() {
  cd "$ROOT_DIR"
  "$PYTHON_BIN" "$LAUNCHER_PY"
}

start_idle_monitor() {
  cleanup_stale_pid "$MONITOR_PID_FILE"
  local existing_monitor_pid
  existing_monitor_pid="$(read_pid_file "$MONITOR_PID_FILE")"
  if is_pid_alive "$existing_monitor_pid"; then
    return 0
  fi

  (
    while true; do
      server_pid="$(read_pid_file "$PID_FILE")"
      if ! is_pid_alive "$server_pid"; then
        rm -f "$PID_FILE"
        exit 0
      fi

      if curl -fsS "$URL/api/app/can-shutdown" | grep -q '"can_shutdown_service":[[:space:]]*true'; then
        sleep "$IDLE_TIMEOUT_SEC"
        if curl -fsS "$URL/api/app/can-shutdown" | grep -q '"can_shutdown_service":[[:space:]]*true'; then
          kill "$server_pid" 2>/dev/null || true
          rm -f "$PID_FILE"
          exit 0
        fi
      fi

      sleep 5
    done
  ) >>"$MONITOR_LOG_FILE" 2>&1 &
  echo $! > "$MONITOR_PID_FILE"
  disown || true
}

cleanup_stale_pid "$PID_FILE"

if ! is_service_healthy; then
  server_pid="$(read_pid_file "$PID_FILE")"
  if ! is_pid_alive "$server_pid"; then
    start_server
  fi
fi

wait_until_ready
start_idle_monitor
open "$URL"
