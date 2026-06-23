#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Ayes 启动器"
APP_PATH="$ROOT_DIR/runtime/${APP_NAME}.app"
WRAPPER_SCRIPT="$ROOT_DIR/scripts/start_ayes_service.sh"

mkdir -p "$ROOT_DIR/runtime"

osacompile -o "$APP_PATH" <<EOF
do shell script "bash $(printf '%q' "$WRAPPER_SCRIPT") >/dev/null 2>&1 &"
EOF

echo "$APP_PATH"
