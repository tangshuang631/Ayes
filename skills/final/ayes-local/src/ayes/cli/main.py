"""Minimal CLI entry for Ayes."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from ayes.app.runner import WatchRunner
from ayes.cli.agent_tool import main as agent_tool_main
from ayes.cli.helpers import load_watch_spec, to_pretty_json
from ayes.cli.spec_builder import build_window_observe_spec
from ayes.targets.discovery import create_window_discovery


def main() -> int:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "agent-tool":
        return agent_tool_main(sys.argv[2:])

    parser = argparse.ArgumentParser(prog="ayes")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate-spec", help="校验 watch spec JSON 文件")
    validate_parser.add_argument("path", help="watch spec JSON 路径")

    subparsers.add_parser("list-windows", help="列出当前系统窗口候选")

    run_once_parser = subparsers.add_parser("run-once", help="按 watch spec 执行一次最小监控链路")
    run_once_parser.add_argument("path", help="watch spec JSON 路径")

    run_loop_parser = subparsers.add_parser("run-loop", help="连续执行多次最小监控链路")
    run_loop_parser.add_argument("path", help="watch spec JSON 路径")
    run_loop_parser.add_argument("--iterations", type=int, default=3, help="执行次数")
    run_loop_parser.add_argument("--sleep-seconds", type=float, default=0.5, help="每次执行间隔秒数")
    run_loop_parser.add_argument("--dump-path", default="runtime/mvp-events.json", help="事件导出路径")

    ask_recent_parser = subparsers.add_parser("ask-recent", help="对最近短期记忆做一次最小问答")
    ask_recent_parser.add_argument("path", help="watch spec JSON 路径")
    ask_recent_parser.add_argument("--minutes", type=int, default=5, help="查询最近多少分钟")
    ask_recent_parser.add_argument("--keyword", default=None, help="关键词过滤")

    check_watch_parser = subparsers.add_parser("check-watch", help="检查最近短期记忆中是否命中当前 watch_intent")
    check_watch_parser.add_argument("path", help="watch spec JSON 路径")
    check_watch_parser.add_argument("--minutes", type=int, default=5, help="查询最近多少分钟")

    create_window_spec_parser = subparsers.add_parser("create-window-spec", help="基于 window id 生成最小窗口监控 spec")
    create_window_spec_parser.add_argument("window_id", type=int, help="窗口 id")
    create_window_spec_parser.add_argument("--output", default="runtime/mvp-observe-window.json", help="输出 spec 路径")

    subparsers.add_parser("agent-tool", help="转发到面向 Agent 的本地 HTTP 薄工具")

    args = parser.parse_args()
    if args.command == "validate-spec":
        spec = load_watch_spec(args.path)
        print(to_pretty_json(asdict(spec)))
        return 0
    if args.command == "list-windows":
        discovery = create_window_discovery()
        windows = [asdict(item) for item in discovery.list_windows()]
        print(to_pretty_json(windows))
        return 0
    if args.command == "create-window-spec":
        output = build_window_observe_spec(window_id=args.window_id, output_path=args.output)
        print(to_pretty_json({"output_path": output, "window_id": args.window_id}))
        return 0
    if args.command in {"run-once", "run-loop", "ask-recent", "check-watch"}:
        runner = WatchRunner(load_watch_spec(args.path))
        events = runner.run_once()
        if args.command == "run-once":
            print(to_pretty_json([asdict(event) for event in events]))
            return 0
        if args.command == "run-loop":
            if args.iterations > 1:
                runner.run_for_iterations(iterations=args.iterations - 1, sleep_seconds=args.sleep_seconds)
            runner.dump_events(args.dump_path)
            result = runner.ask_recent(minutes=5, now=None)
            print(
                to_pretty_json(
                    {
                        "events_written": len(runner.events),
                        "dump_path": args.dump_path,
                        "recent_answer": result.answer,
                        "recent_event_ids": [event.event_id for event in result.matched_events],
                    }
                )
            )
            return 0
        if args.command == "check-watch":
            result = runner.check_watch_condition_recent(minutes=args.minutes)
            print(
                to_pretty_json(
                    {
                        "answer": result.answer,
                        "confidence": result.confidence,
                        "matched_events": [event.event_id for event in result.matched_events],
                        "memory_layers_used": result.memory_layers_used,
                    }
                )
            )
            return 0
        result = runner.ask_recent(minutes=args.minutes, keyword=args.keyword)
        print(
            to_pretty_json(
                {
                    "answer": result.answer,
                    "confidence": result.confidence,
                    "matched_events": [event.event_id for event in result.matched_events],
                    "memory_layers_used": result.memory_layers_used,
                }
            )
        )
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
