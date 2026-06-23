"""Minimal CLI entry for Ayes."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from ayes.config.models import WatchSpec
from ayes.targets.discovery.macos import MacOSWindowDiscovery


def main() -> int:
    parser = argparse.ArgumentParser(prog="ayes")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate-spec", help="校验 watch spec JSON 文件")
    validate_parser.add_argument("path", help="watch spec JSON 路径")

    subparsers.add_parser("list-windows", help="列出 macOS 窗口候选")

    args = parser.parse_args()
    if args.command == "validate-spec":
        with open(args.path, "r", encoding="utf-8") as file:
            data = json.load(file)
        spec = WatchSpec.from_dict(data)
        print(json.dumps(asdict(spec), ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-windows":
        discovery = MacOSWindowDiscovery()
        windows = [asdict(item) for item in discovery.list_windows()]
        print(json.dumps(windows, ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
