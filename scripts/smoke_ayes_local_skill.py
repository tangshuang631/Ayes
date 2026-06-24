#!/usr/bin/env python3
"""Install and smoke test the local ayes-local skill flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, Optional


def ensure_project_root_on_path(root_dir: Path | None = None) -> Path:
    resolved_root = (root_dir or Path(__file__).resolve().parents[1]).resolve()
    root_text = str(resolved_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return resolved_root


ensure_project_root_on_path()

from scripts.install_ayes_local_skill import install_skill


def run_wrapper_json(wrapper_path: Path, args: list[str], *, env: Optional[dict[str, str]] = None) -> Dict[str, Any]:
    completed = subprocess.run(
        [str(wrapper_path), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    output = completed.stdout.strip()
    return json.loads(output) if output else {}


def choose_trigger_query(recent_payload: Dict[str, Any], *, fallback: str = "Codex") -> str:
    items = recent_payload.get("items") or []
    for item in items:
        candidates = [
            ((item.get("text") or {}).get("ocr_text") or "").strip(),
            ((item.get("text") or {}).get("normalized_text") or "").strip(),
            (item.get("summary") or "").strip(),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,16}", candidate):
                if token.isdigit():
                    continue
                return token
    return fallback


def collect_skill_smoke_summary(
    *,
    wrapper_path: Path,
    task_id: str,
    webhook_url: str,
    run_wrapper_json_fn: Callable[..., Dict[str, Any]] = run_wrapper_json,
    sleep_sec: float = 1.0,
    env: Optional[dict[str, str]] = None,
) -> Dict[str, Any]:
    run_wrapper_json_fn(wrapper_path, ["ensure-service"], env=env)
    run_wrapper_json_fn(
        wrapper_path,
        [
            "load-spec",
            "--task-id",
            task_id,
            "--mode",
            "observe",
            "--target-type",
            "screen",
            "--screen-id",
            "1",
            "--screenshot-interval-ms",
            "500",
            "--ocr-interval-ms",
            "500",
            "--change-detection-interval-ms",
            "500",
        ],
        env=env,
    )
    run_wrapper_json_fn(wrapper_path, ["run-once"], env=env)
    preflight_recent = run_wrapper_json_fn(wrapper_path, ["recent", "--task-id", task_id, "--minutes", "5", "--limit", "20"], env=env)
    trigger_query = choose_trigger_query(preflight_recent)
    run_wrapper_json_fn(
        wrapper_path,
        [
            "load-spec",
            "--task-id",
            task_id,
            "--mode",
            "triggered",
            "--target-type",
            "screen",
            "--screen-id",
            "1",
            "--query",
            trigger_query,
            "--webhook-url",
            webhook_url,
            "--screenshot-interval-ms",
            "500",
            "--ocr-interval-ms",
            "500",
            "--change-detection-interval-ms",
            "500",
        ],
        env=env,
    )
    run_wrapper_json_fn(wrapper_path, ["start"], env=env)
    run_wrapper_json_fn(wrapper_path, ["run-once"], env=env)
    time.sleep(max(sleep_sec, 0))

    status = run_wrapper_json_fn(wrapper_path, ["status"], env=env)
    recent = run_wrapper_json_fn(wrapper_path, ["recent", "--task-id", task_id, "--minutes", "5", "--limit", "20"], env=env)
    alerts = run_wrapper_json_fn(wrapper_path, ["alerts", "--task-id", task_id, "--minutes", "15", "--limit", "20"], env=env)
    screenshot = run_wrapper_json_fn(wrapper_path, ["screenshot", "--task-id", task_id], env=env)
    memory_items = run_wrapper_json_fn(wrapper_path, ["memory-items", "--task-id", task_id, "--minutes", "5", "--limit", "20"], env=env)
    logs = run_wrapper_json_fn(wrapper_path, ["logs", "--task-id", task_id, "--minutes", "15"], env=env)
    ask = run_wrapper_json_fn(wrapper_path, ["ask", "--task-id", task_id, "--minutes", "5", "--question", "最近发生了什么"], env=env)
    run_wrapper_json_fn(wrapper_path, ["stop"], env=env)

    alert_items = alerts.get("items") or []
    return {
        "task_id": task_id,
        "trigger_query": trigger_query,
        "status_has_runner": status.get("has_runner"),
        "status_is_running": status.get("is_running"),
        "timeline_count": recent.get("count", len(recent.get("items") or [])),
        "alert_count": alerts.get("count", len(alert_items)),
        "latest_alert_event_type": (alert_items[0] if alert_items else {}).get("event_type"),
        "screenshot_path": screenshot.get("path"),
        "screenshot_capture_status": screenshot.get("capture_status"),
        "memory_item_count": memory_items.get("count", len(memory_items.get("items") or [])),
        "log_count": logs.get("count", len(logs.get("items") or [])),
        "ask_answer": ask.get("answer"),
        "ask_matched_event_count": len(ask.get("matched_events") or []),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="安装并验证 ayes-local 本地 skill 调用链路")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--skill-root", default=None, help="默认使用临时目录")
    parser.add_argument("--task-id", default="task_skill_smoke")
    parser.add_argument("--webhook-url", required=True, help="用于接收 smoke 告警的企业微信 webhook 或本地测试 webhook")
    parser.add_argument("--sleep-sec", type=float, default=1.0)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.skill_root:
        skill_root = Path(args.skill_root).resolve()
        temp_dir_ctx = None
    else:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="ayes-skill-smoke-")
        skill_root = Path(temp_dir_ctx.name)

    try:
        paths = install_skill(repo_root=repo_root, skill_root=skill_root)
        summary = collect_skill_smoke_summary(
            wrapper_path=paths.wrapper_path,
            task_id=args.task_id,
            webhook_url=args.webhook_url,
            sleep_sec=args.sleep_sec,
        )
        print(json.dumps({"installed_skill_dir": str(paths.target_skill_dir), "wrapper_path": str(paths.wrapper_path), **summary}, ensure_ascii=False, indent=2))
        return 0
    finally:
        if temp_dir_ctx is not None:
            temp_dir_ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
