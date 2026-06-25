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
    src_text = str(resolved_root / "src")
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    return resolved_root


ensure_project_root_on_path()

from ayes.app.service_control import can_shutdown_service, cleanup_stale_pid, default_service_config, read_pid, stop_pid, wait_for_pid_exit
from scripts.install_ayes_local_skill import install_skill
from scripts.smoke_webhook_flow import capture_single_webhook_request


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


def recycle_reusable_local_service() -> None:
    config = default_service_config()
    if not can_shutdown_service(config):
        return
    pid = read_pid(config.pid_file)
    stop_pid(pid)
    wait_for_pid_exit(pid, timeout_sec=5.0, poll_interval_sec=0.1)
    cleanup_stale_pid(config.pid_file)


def collect_skill_smoke_summary(
    *,
    wrapper_path: Path,
    task_id: str,
    webhook_url: str,
    alert_message_title: Optional[str] = None,
    alert_message_template: Optional[str] = None,
    run_wrapper_json_fn: Callable[..., Dict[str, Any]] = run_wrapper_json,
    sleep_sec: float = 1.0,
    env: Optional[dict[str, str]] = None,
) -> Dict[str, Any]:
    run_wrapper_json_fn(wrapper_path, ["ensure-service"], env=env)
    observe_plan = run_wrapper_json_fn(
        wrapper_path,
        [
            "plan-spec",
            "--task-id",
            task_id,
            "--prompt",
            "持续观察当前主屏幕，后面我会继续追问最近发生了什么",
            "--target-type",
            "screen",
            "--screen-id",
            "1",
        ],
        env=env,
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as observe_plan_file:
        observe_plan_file.write(json.dumps(observe_plan, ensure_ascii=False))
        observe_plan_path = observe_plan_file.name
    try:
        run_wrapper_json_fn(
            wrapper_path,
            [
                "confirm-plan",
                "--plan-file",
                observe_plan_path,
                "--target-type",
                "screen",
                "--screen-id",
                "1",
            ],
            env=env,
        )
    finally:
        Path(observe_plan_path).unlink(missing_ok=True)
    run_wrapper_json_fn(wrapper_path, ["run-once"], env=env)
    preflight_recent = run_wrapper_json_fn(wrapper_path, ["recent", "--task-id", task_id, "--minutes", "5", "--limit", "20"], env=env)
    trigger_query = choose_trigger_query(preflight_recent)
    triggered_plan = run_wrapper_json_fn(
        wrapper_path,
        [
            "plan-spec",
            "--task-id",
            task_id,
            "--prompt",
            f"帮我监控当前主屏幕里出现 {trigger_query} 时提醒我",
            "--target-type",
            "screen",
            "--screen-id",
            "1",
        ],
        env=env,
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as triggered_plan_file:
        triggered_plan_file.write(json.dumps(triggered_plan, ensure_ascii=False))
        triggered_plan_path = triggered_plan_file.name
    confirm_args = [
        "confirm-plan",
        "--plan-file",
        triggered_plan_path,
        "--target-type",
        "screen",
        "--screen-id",
        "1",
        "--webhook-url",
        webhook_url,
    ]
    if alert_message_title:
        confirm_args.extend(["--alert-message-title", alert_message_title])
    if alert_message_template:
        confirm_args.extend(["--alert-message-template", alert_message_template])
    try:
        run_wrapper_json_fn(
            wrapper_path,
            confirm_args,
            env=env,
        )
    finally:
        Path(triggered_plan_path).unlink(missing_ok=True)
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


def collect_skill_smoke_with_local_webhook(
    *,
    wrapper_path: Path,
    task_id: str,
    sleep_sec: float = 1.0,
    alert_message_title: Optional[str] = None,
    alert_message_template: Optional[str] = None,
    run_wrapper_json_fn: Callable[..., Dict[str, Any]] = run_wrapper_json,
    env: Optional[dict[str, str]] = None,
) -> Dict[str, Any]:
    summary_holder: Dict[str, Any] = {}

    def trigger_fn(webhook_url: str) -> None:
        summary_holder["skill_smoke"] = collect_skill_smoke_summary(
            wrapper_path=wrapper_path,
            task_id=task_id,
            webhook_url=webhook_url,
            alert_message_title=alert_message_title,
            alert_message_template=alert_message_template,
            run_wrapper_json_fn=run_wrapper_json_fn,
            sleep_sec=sleep_sec,
            env=env,
        )

    webhook_smoke = capture_single_webhook_request(trigger_fn=trigger_fn, timeout_sec=max(5.0, sleep_sec + 2.0))
    skill_smoke = summary_holder.get("skill_smoke") or {}
    return {
        **skill_smoke,
        "webhook_smoke": webhook_smoke,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="安装并验证 ayes-local 本地 skill 调用链路")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--skill-root", default=None, help="默认使用临时目录")
    parser.add_argument("--task-id", default="task_skill_smoke")
    parser.add_argument("--webhook-url", default=None, help="用于接收 smoke 告警的企业微信 webhook；默认自动启本地 webhook round-trip")
    parser.add_argument("--alert-message-title", default=None, help="可选：覆盖 triggered 告警标题")
    parser.add_argument("--alert-message-template", default=None, help="可选：覆盖 triggered 告警正文模板")
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
        recycle_reusable_local_service()
        if args.webhook_url:
            summary = collect_skill_smoke_summary(
                wrapper_path=paths.agent_wrapper_path,
                task_id=args.task_id,
                webhook_url=args.webhook_url,
                alert_message_title=args.alert_message_title,
                alert_message_template=args.alert_message_template,
                sleep_sec=args.sleep_sec,
            )
        else:
            summary = collect_skill_smoke_with_local_webhook(
                wrapper_path=paths.agent_wrapper_path,
                task_id=args.task_id,
                sleep_sec=args.sleep_sec,
                alert_message_title=args.alert_message_title,
                alert_message_template=args.alert_message_template,
            )
        print(json.dumps({"installed_skill_dir": str(paths.target_skill_dir), "wrapper_path": str(paths.agent_wrapper_path), **summary}, ensure_ascii=False, indent=2))
        return 0
    finally:
        if temp_dir_ctx is not None:
            temp_dir_ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
