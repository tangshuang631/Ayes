#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:${PATH:-}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IDLE_TIMEOUT_SEC="${AYES_IDLE_TIMEOUT_SEC:-120}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
AYES_IDLE_TIMEOUT_SEC="$IDLE_TIMEOUT_SEC" \
"$PYTHON_BIN" -m ayes.cli.launcher start
