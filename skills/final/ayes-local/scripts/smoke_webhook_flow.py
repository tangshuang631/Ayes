#!/usr/bin/env python3
"""Run a local webhook round-trip smoke without external network dependencies."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any, Dict, Callable
from urllib import request


def build_webhook_payload(
    *,
    task_id: str,
    summary: str,
    timestamp: float,
    process_name: str,
    window_title: str,
    priority: str,
    confidence: float,
    event_id: str,
) -> Dict[str, Any]:
    return {
        "msgtype": "text",
        "text": {
            "content": (
                "[Ayes] 命中监控目标\n\n"
                f"任务：{task_id}\n"
                f"时间：{int(timestamp)}\n"
                f"进程：{process_name}\n"
                f"窗口：{window_title}\n"
                f"优先级：{priority}\n"
                f"置信度：{confidence}\n\n"
                f"摘要：{summary}\n"
                f"事件：{event_id}"
            )
        },
    }


def collect_local_webhook_smoke_summary(
    *,
    payload: Dict[str, Any],
    round_trip_fn: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    callback = round_trip_fn or _default_round_trip
    return callback(payload)


def capture_single_webhook_request(
    *,
    trigger_fn: Callable[[str], Any],
    host: str = "127.0.0.1",
    path: str = "/webhook",
    timeout_sec: float = 5.0,
) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "received": False,
        "request_count": 0,
        "last_path": None,
        "body": None,
        "response_status": None,
        "response_body": None,
        "trigger_error": None,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                body = {"raw_body": raw.decode("utf-8", errors="replace")}
            response_body = json.dumps({"ok": True}, ensure_ascii=False)
            state["received"] = True
            state["request_count"] = int(state["request_count"]) + 1
            state["last_path"] = self.path
            state["body"] = body
            state["response_status"] = 200
            state["response_body"] = response_body
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(response_body.encode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((host, 0), Handler)
    server.daemon_threads = True
    webhook_url = f"http://{host}:{server.server_port}{path}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started_at = time.time()
    try:
        try:
            trigger_fn(webhook_url)
        except Exception as exc:  # pragma: no cover - surfaced via summary
            state["trigger_error"] = str(exc)
        deadline = started_at + max(timeout_sec, 0.1)
        while time.time() < deadline:
            if state["received"]:
                break
            time.sleep(0.05)
    finally:
        server.shutdown()
        thread.join(timeout=1.0)
        server.server_close()

    return {
        "webhook_url": webhook_url,
        "received": bool(state["received"]),
        "request_count": int(state["request_count"]),
        "last_path": state["last_path"],
        "body": state["body"],
        "response_status": state["response_status"],
        "response_body": state["response_body"],
        "trigger_error": state["trigger_error"],
        "waited_sec": round(time.time() - started_at, 3),
    }


def post_webhook_payload(webhook_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        body = response.read().decode("utf-8", errors="replace")
        return {
            "status": response.status,
            "body": body,
        }


def _default_round_trip(payload: Dict[str, Any]) -> Dict[str, Any]:
    return capture_single_webhook_request(
        trigger_fn=lambda webhook_url: post_webhook_payload(webhook_url, payload),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ayes local webhook round-trip smoke")
    parser.add_argument("--task-id", default="task_webhook_smoke")
    parser.add_argument("--summary", default="库存恢复")
    parser.add_argument("--timestamp", type=float, default=time.time())
    parser.add_argument("--process-name", default="Safari")
    parser.add_argument("--window-title", default="商品页")
    parser.add_argument("--priority", default="medium")
    parser.add_argument("--confidence", type=float, default=0.91)
    parser.add_argument("--event-id", default="evt_webhook_smoke")
    args = parser.parse_args(argv)

    payload = build_webhook_payload(
        task_id=args.task_id,
        summary=args.summary,
        timestamp=args.timestamp,
        process_name=args.process_name,
        window_title=args.window_title,
        priority=args.priority,
        confidence=args.confidence,
        event_id=args.event_id,
    )
    summary = collect_local_webhook_smoke_summary(payload=payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["received"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
