"""Thin local tool wrapper for Ayes HTTP APIs."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict


def _request_json(base_url: str, path: str, *, method: str = "GET", payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    body = None
    headers: Dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ayes-agent")
    parser.add_argument("--base-url", default="http://127.0.0.1:8770", help="Ayes 本地服务地址")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("contracts", help="读取当前 agent 接口合同")
    subparsers.add_parser("status", help="读取当前监控状态")
    subparsers.add_parser("start", help="启动当前已装载任务")
    subparsers.add_parser("stop", help="停止当前持续监控")

    recent_parser = subparsers.add_parser("recent", help="读取最近事件")
    recent_parser.add_argument("--task-id", default="", help="任务 id")
    recent_parser.add_argument("--minutes", type=int, default=5, help="最近多少分钟")
    recent_parser.add_argument("--limit", type=int, default=20, help="事件条数")

    ask_parser = subparsers.add_parser("ask", help="对当前任务提问")
    ask_parser.add_argument("--task-id", default="", help="任务 id")
    ask_parser.add_argument("--minutes", type=int, default=5, help="最近多少分钟")
    ask_parser.add_argument("--question", required=True, help="问题文本")

    screenshot_parser = subparsers.add_parser("screenshot", help="读取当前截图证据")
    screenshot_parser.add_argument("--task-id", default="", help="任务 id")

    load_parser = subparsers.add_parser("load-spec", help="装载一份最小配置化任务")
    load_parser.add_argument("--task-id", default="task_web", help="任务 id")
    load_parser.add_argument("--mode", default="observe", choices=["observe", "triggered"], help="任务模式")
    load_parser.add_argument("--target-type", default="screen", choices=["screen", "process", "window"], help="目标类型")
    load_parser.add_argument("--screen-id", type=int, default=1, help="屏幕 id")
    load_parser.add_argument("--process-name", default="", help="进程名")
    load_parser.add_argument("--window-id", type=int, default=0, help="窗口 id")
    load_parser.add_argument("--query", default="", help="triggered 查询文本")
    return parser


def _scoped_query(task_id: str, minutes: int | None = None, limit: int | None = None, question: str = "") -> str:
    params = urllib.parse.urlencode(
        {
            key: value
            for key, value in {
                "task_id": task_id or None,
                "minutes": minutes,
                "limit": limit,
                "question": question or None,
            }.items()
            if value not in {None, ""}
        }
    )
    return f"?{params}" if params else ""


def _build_target_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.target_type == "screen":
        return {"type": "screen", "screen_id": args.screen_id}
    if args.target_type == "process":
        return {"type": "process", "process_name": args.process_name}
    return {"type": "window", "window_id": args.window_id}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    base_url = args.base_url.rstrip("/")
    if args.command == "contracts":
        payload = _request_json(base_url, "/api/agent/contracts")
    elif args.command == "status":
        payload = _request_json(base_url, "/api/watch/status")
    elif args.command == "start":
        payload = _request_json(base_url, "/api/watch/start", method="POST")
    elif args.command == "stop":
        payload = _request_json(base_url, "/api/watch/stop", method="POST")
    elif args.command == "recent":
        payload = _request_json(base_url, f"/api/timeline/recent{_scoped_query(args.task_id, args.minutes, args.limit)}")
    elif args.command == "ask":
        payload = _request_json(base_url, f"/api/ask{_scoped_query(args.task_id, args.minutes, question=args.question)}")
    elif args.command == "screenshot":
        payload = _request_json(base_url, f"/api/screenshot{_scoped_query(args.task_id)}")
    elif args.command == "load-spec":
        watch_intent = {"enabled": False}
        if args.mode == "triggered":
            watch_intent = {
                "enabled": True,
                "summary": args.query or "命中条件时提醒我",
                "queries": [args.query or "状态变化"],
            }
        payload = _request_json(
            base_url,
            "/api/watch/load-configured",
            method="POST",
            payload={
                "task_id": args.task_id,
                "mode": args.mode,
                "target": _build_target_payload(args),
                "sampling": {
                    "screenshot_interval_ms": 1000,
                    "ocr_interval_ms": 1000,
                    "change_detection_interval_ms": 1000,
                    "max_fps": 2,
                    "skip_ocr_when_no_change": True,
                },
                "watch_intent": watch_intent,
            },
        )
    else:
        parser.print_help()
        return 1

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
