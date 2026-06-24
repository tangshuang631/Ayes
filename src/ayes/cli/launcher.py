"""Launcher commands for the local Ayes background service."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from ayes.app.service_control import default_service_config, ensure_service_started, start_idle_monitor


def _open_browser(url: str) -> None:
    subprocess.run(["open", url], check=False)


def cmd_start() -> int:
    config = default_service_config(Path(__file__).resolve().parents[3])
    result = ensure_service_started(config)
    start_idle_monitor(config, idle_timeout_sec=max(int(os.environ.get("AYES_IDLE_TIMEOUT_SEC", "120")), 1))
    _open_browser(config.base_url)
    print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ayes launcher helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start", help="确保后台服务为单实例并打开前端页面")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "start":
        return cmd_start()
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
