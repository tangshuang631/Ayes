"""CLI entrypoint for the macOS menu bar control surface."""

from __future__ import annotations

import argparse
import sys

from ayes.app.menubar import run_menu_bar


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ayes macOS menu bar controller")
    parser.add_argument("--base-url", default="http://127.0.0.1:8770")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_menu_bar(base_url=args.base_url)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
