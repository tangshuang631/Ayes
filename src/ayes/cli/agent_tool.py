"""Thin local CLI wrapper for Ayes agent-facing HTTP APIs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ayes.app.service_control import default_service_config, ensure_service_started
from ayes.cli.helpers import to_pretty_json


DEFAULT_BASE_URL = "http://127.0.0.1:8770"


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _build_query_path(path: str, **query: Any) -> str:
    filtered = {key: value for key, value in query.items() if value is not None}
    if not filtered:
        return path
    return f"{path}?{urlencode(filtered, doseq=True)}"


def _request_json(base_url: str, path: str, *, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_base_url = _normalize_base_url(base_url)
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(f"{normalized_base_url}{path}", data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"请求失败: {method} {path} -> HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"请求失败: {method} {path} -> {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"请求失败: {method} {path} -> {exc}") from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"响应不是合法 JSON: {method} {path}") from exc


def ensure_local_service_started(base_url: str) -> Dict[str, Any]:
    normalized_base_url = _normalize_base_url(base_url)
    if normalized_base_url != DEFAULT_BASE_URL:
        payload = _request_json(normalized_base_url, "/api/status")
        return {
            "status": "service_ready",
            "base_url": normalized_base_url,
            "service": "remote_checked",
            "status_payload": payload,
        }
    config = default_service_config()
    result = ensure_service_started(config)
    status_payload = _request_json(normalized_base_url, "/api/status")
    return {
        "status": "service_ready",
        "base_url": normalized_base_url,
        "service": result,
        "status_payload": status_payload,
    }


def _build_target_payload(args: argparse.Namespace) -> Dict[str, Any]:
    target_type = args.target_type
    if target_type == "screen":
        return {"type": "screen", "screen_id": args.screen_id}
    if target_type == "window":
        if args.window_id is None:
            raise RuntimeError("target_type=window 时必须提供 --window-id")
        return {"type": "window", "window_id": args.window_id}
    if target_type == "process":
        if not args.process_name:
            raise RuntimeError("target_type=process 时必须提供 --process-name")
        return {"type": "process", "process_name": args.process_name}
    raise RuntimeError(f"不支持的 target_type: {target_type}")


def _build_load_spec_payload(args: argparse.Namespace) -> Dict[str, Any]:
    queries = [item for item in (args.query or []) if str(item).strip()]
    payload: Dict[str, Any] = {
        "task_id": args.task_id,
        "spec_version": args.spec_version,
        "mode": args.mode,
        "target": _build_target_payload(args),
        "sampling": {
            "screenshot_interval_ms": args.screenshot_interval_ms,
            "ocr_interval_ms": args.ocr_interval_ms,
            "change_detection_interval_ms": args.change_detection_interval_ms,
            "max_fps": args.max_fps,
            "skip_ocr_when_no_change": bool(args.skip_ocr_when_no_change),
        },
        "watch_intent": {
            "enabled": bool(queries),
            "queries": queries,
        },
    }
    if args.long_term_hours is not None:
        payload["memory"] = {"long_term_hours": args.long_term_hours}
    if args.webhook_url:
        payload["alert"] = {
            "enabled": True,
            "channel": "wecom_webhook",
            "webhook_url": args.webhook_url,
        }
    if args.enable_vision:
        payload["vision"] = {"enabled": True, "provider": args.vision_provider, "model": args.vision_model}
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ayes-agent", description="Ayes 面向智能体的本地薄工具")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="本地 Ayes HTTP 服务地址")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ensure-service", help="确保本地 Ayes 服务可达")
    subparsers.add_parser("contracts", help="读取智能体接口契约")
    subparsers.add_parser("status", help="读取当前监控状态")
    subparsers.add_parser("targets", help="读取目标候选摘要")
    subparsers.add_parser("start", help="启动当前已装载的持续监控")
    subparsers.add_parser("run-once", help="执行一次即时采样")
    subparsers.add_parser("stop", help="停止当前持续监控")

    task_parser = subparsers.add_parser("task", help="读取指定任务快照")
    task_parser.add_argument("--task-id", required=True, help="任务 ID")

    recent_parser = subparsers.add_parser("recent", help="读取近期时间线事件")
    recent_parser.add_argument("--task-id", default=None)
    recent_parser.add_argument("--minutes", type=int, default=5)
    recent_parser.add_argument("--limit", type=int, default=20)

    alerts_parser = subparsers.add_parser("alerts", help="读取最近告警审计结果")
    alerts_parser.add_argument("--task-id", default=None)
    alerts_parser.add_argument("--minutes", type=int, default=15)
    alerts_parser.add_argument("--limit", type=int, default=20)

    long_term_parser = subparsers.add_parser("long-term", help="读取长期摘要")
    long_term_parser.add_argument("--task-id", default=None)
    long_term_parser.add_argument("--hours", type=int, default=None)
    long_term_parser.add_argument("--limit", type=int, default=20)

    screenshot_parser = subparsers.add_parser("screenshot", help="读取最近截图与 ROI 覆盖信息")
    screenshot_parser.add_argument("--task-id", default=None)

    ask_parser = subparsers.add_parser("ask", help="对近期或长期记忆发起提问")
    ask_parser.add_argument("--task-id", default=None)
    ask_parser.add_argument("--question", required=True)
    ask_parser.add_argument("--minutes", type=int, default=5)
    ask_parser.add_argument("--hours", type=int, default=None)

    memory_items_parser = subparsers.add_parser("memory-items", help="读取短期记忆明细")
    memory_items_parser.add_argument("--task-id", default=None)
    memory_items_parser.add_argument("--minutes", type=int, default=5)
    memory_items_parser.add_argument("--limit", type=int, default=20)
    memory_items_parser.add_argument("--keyword", default=None)

    logs_parser = subparsers.add_parser("logs", help="读取近期日志")
    logs_parser.add_argument("--task-id", default=None)
    logs_parser.add_argument("--minutes", type=int, default=15)
    logs_parser.add_argument("--category", default=None)

    load_spec_parser = subparsers.add_parser("load-spec", help="装载最小 watch spec")
    load_spec_parser.add_argument("--task-id", required=True)
    load_spec_parser.add_argument("--spec-version", default="1.0")
    load_spec_parser.add_argument("--mode", default="observe", choices=["observe", "triggered"])
    load_spec_parser.add_argument("--target-type", required=True, choices=["screen", "window", "process"])
    load_spec_parser.add_argument("--screen-id", type=int, default=1)
    load_spec_parser.add_argument("--window-id", type=int, default=None)
    load_spec_parser.add_argument("--process-name", default=None)
    load_spec_parser.add_argument("--query", action="append", default=[])
    load_spec_parser.add_argument("--screenshot-interval-ms", type=int, default=1000)
    load_spec_parser.add_argument("--ocr-interval-ms", type=int, default=1000)
    load_spec_parser.add_argument("--change-detection-interval-ms", type=int, default=1000)
    load_spec_parser.add_argument("--max-fps", type=int, default=2)
    load_spec_parser.add_argument("--skip-ocr-when-no-change", action="store_true")
    load_spec_parser.add_argument("--long-term-hours", type=int, default=None)
    load_spec_parser.add_argument("--webhook-url", default=None)
    load_spec_parser.add_argument("--enable-vision", action="store_true")
    load_spec_parser.add_argument("--vision-provider", default="ollama")
    load_spec_parser.add_argument("--vision-model", default=None)
    return parser


def _dispatch(args: argparse.Namespace) -> Dict[str, Any]:
    base_url = _normalize_base_url(args.base_url)
    if args.command == "ensure-service":
        result = ensure_local_service_started(base_url)
        if isinstance(result, dict):
            return result
        return {"status": "service_ready", "base_url": base_url}
    if args.command == "contracts":
        return _request_json(base_url, "/api/agent/contracts")
    if args.command == "status":
        return _request_json(base_url, "/api/watch/status")
    if args.command == "targets":
        return _request_json(base_url, "/api/targets")
    if args.command == "start":
        return _request_json(base_url, "/api/watch/start", method="POST", payload={})
    if args.command == "run-once":
        return _request_json(base_url, "/api/watch/run-once", method="POST", payload={})
    if args.command == "stop":
        return _request_json(base_url, "/api/watch/stop", method="POST", payload={})
    if args.command == "task":
        return _request_json(base_url, f"/api/watch/task/{args.task_id}")
    if args.command == "recent":
        path = _build_query_path("/api/timeline/recent", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "alerts":
        path = _build_query_path("/api/alerts/recent", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "long-term":
        path = _build_query_path("/api/timeline/long-term", task_id=args.task_id, hours=args.hours, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "screenshot":
        path = _build_query_path("/api/screenshot", task_id=args.task_id)
        return _request_json(base_url, path)
    if args.command == "ask":
        path = _build_query_path("/api/ask", task_id=args.task_id, question=args.question, minutes=args.minutes, hours=args.hours)
        return _request_json(base_url, path)
    if args.command == "memory-items":
        path = _build_query_path("/api/memory/items", task_id=args.task_id, minutes=args.minutes, limit=args.limit, keyword=args.keyword)
        return _request_json(base_url, path)
    if args.command == "logs":
        path = _build_query_path("/api/logs", task_id=args.task_id, category=args.category, minutes=args.minutes)
        return _request_json(base_url, path)
    if args.command == "load-spec":
        payload = _build_load_spec_payload(args)
        return _request_json(base_url, "/api/watch/load-configured", method="POST", payload=payload)
    raise RuntimeError(f"未知命令: {args.command}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _dispatch(args)
    except RuntimeError as exc:
        print(to_pretty_json({"error": str(exc)}))
        return 1
    if payload is None:
        payload = {"status": "service_ready", "base_url": _normalize_base_url(args.base_url)}
    print(to_pretty_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
