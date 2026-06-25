"""Thin local CLI wrapper for Ayes agent-facing HTTP APIs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
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


def ensure_local_menubar_started() -> Dict[str, Any]:
    if os.environ.get("AYES_AUTO_MENUBAR", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"status": "disabled"}
    if sys.platform != "darwin":
        return {"status": "skipped", "reason": "not_macos"}
    config = default_service_config()
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_file = config.runtime_dir / "ayes-menubar.pid"
    existing_pid = None
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing_pid = None
    from ayes.app.service_control import is_pid_alive

    if is_pid_alive(existing_pid):
        return {"status": "reused", "pid": existing_pid}
    log_file = config.runtime_dir / "ayes-menubar.log"
    env = os.environ.copy()
    src_path = str(config.root_dir / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    try:
        with log_file.open("ab") as output:
            process = subprocess.Popen(
                [config.python_bin, "-m", "ayes.cli.menubar", "--base-url", DEFAULT_BASE_URL],
                cwd=str(config.root_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        pid_file.write_text(str(process.pid), encoding="utf-8")
        return {"status": "started", "pid": process.pid, "log_file": str(log_file)}
    except Exception as exc:  # pragma: no cover - defensive startup path
        return {"status": "failed", "error": str(exc), "log_file": str(log_file)}


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


def _build_optional_target_payload(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    target_type = getattr(args, "target_type", None)
    if not target_type:
        return None
    return _build_target_payload(args)


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


def _build_plan_spec_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_id": args.task_id,
        "prompt": args.prompt,
    }
    target = _build_optional_target_payload(args)
    if target is not None:
        payload["target"] = target
    if args.webhook_url:
        payload["webhook_url"] = args.webhook_url
    return payload


def _load_json_file(path_str: str, *, label: str) -> Dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise RuntimeError(f"{label} 不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} 不是合法 JSON: {path}") from exc


def _build_region_bind_capture_ref(*, base_url: str, args: argparse.Namespace, plan: Dict[str, Any]) -> Dict[str, Any]:
    if args.capture_id and args.image_path and args.image_width is not None and args.image_height is not None:
        return {
            "capture_id": args.capture_id,
            "image_path": args.image_path,
            "image_width": args.image_width,
            "image_height": args.image_height,
        }
    task_id = str(plan.get("task_id") or "").strip() or None
    screenshot_path = _build_query_path("/api/screenshot", task_id=task_id)
    screenshot_payload = _request_json(base_url, screenshot_path)
    image_path = str(screenshot_payload.get("path") or "").strip()
    image_width = screenshot_payload.get("image_width")
    image_height = screenshot_payload.get("image_height")
    if not image_path or image_width is None or image_height is None:
        raise RuntimeError("缺少 region-bind 所需截图信息，请先执行 run-once/observe-live 生成最近截图，或显式提供 --capture-id --image-path --image-width --image-height")
    capture_id = str(args.capture_id or f"cap_{task_id or 'latest'}").strip()
    return {
        "capture_id": capture_id,
        "image_path": image_path,
        "image_width": int(image_width),
        "image_height": int(image_height),
    }


def _parse_optional_bool(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    normalized = str(raw).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise RuntimeError(f"无法识别布尔值: {raw}")


def _build_confirm_plan_payload(args: argparse.Namespace) -> Dict[str, Any]:
    plan_path = Path(args.plan_file)
    if not plan_path.exists():
        raise RuntimeError(f"plan_file 不存在: {plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"plan_file 不是合法 JSON: {plan_path}") from exc
    confirmations: Dict[str, Any] = {}
    if args.webhook_url:
        confirmations["webhook_url"] = args.webhook_url
    if args.alert_message_title:
        confirmations["alert_message_title"] = str(args.alert_message_title).strip()
    if args.alert_message_template:
        confirmations["alert_message_template"] = str(args.alert_message_template).strip()
    target = _build_optional_target_payload(args)
    if target is not None:
        confirmations["target"] = target
    if args.use_entire_target:
        confirmations["use_entire_target"] = True
    if args.region_intent:
        confirmations["region_intents"] = [_parse_region_intent(item) for item in args.region_intent]
    if args.region_binding:
        confirmations["region_bindings"] = [_parse_region_binding(item) for item in args.region_binding]
    if args.refresh_click_enabled:
        confirmations["refresh_click_enabled"] = True
    if args.refresh_click_interval_sec is not None:
        confirmations["refresh_click_interval_sec"] = args.refresh_click_interval_sec
    if args.refresh_click_coordinate_space is not None:
        confirmations["refresh_click_coordinate_space"] = args.refresh_click_coordinate_space
    if args.refresh_click_point:
        confirmations["refresh_click_point"] = _parse_point(args.refresh_click_point, field_name="refresh_click_point")
    return {"plan": plan, "confirmations": confirmations}


def _parse_region_intent(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise RuntimeError("region_intent 不能为空")
    if ":" in text:
        name, purpose = text.split(":", 1)
    elif "：" in text:
        name, purpose = text.split("：", 1)
    else:
        name, purpose = text, ""
    name = name.strip()
    purpose = purpose.strip()
    if not name:
        raise RuntimeError("region_intent 名称不能为空")
    return {"name": name, "purpose": purpose, "required": True, "status": "needs_binding"}


def _parse_region_binding(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    parts = text.split("|")
    if len(parts) != 9:
        raise RuntimeError("region_binding 必须是 region_intent_id|region_id|name|x|y|w|h|coordinate_space|source")
    region_intent_id, region_id, name, x, y, w, h, coordinate_space, source = [item.strip() for item in parts]
    if not region_intent_id or not region_id or not name:
        raise RuntimeError("region_binding 的 region_intent_id、region_id、name 不能为空")
    return {
        "region_intent_id": region_intent_id,
        "region_id": region_id,
        "name": name,
        "x": int(x),
        "y": int(y),
        "w": int(w),
        "h": int(h),
        "coordinate_space": coordinate_space or "target",
        "source": source or "manual_coordinates",
    }


def _parse_point(raw: str, *, field_name: str) -> Dict[str, int]:
    text = str(raw or "").strip()
    parts = [item.strip() for item in text.split(",")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RuntimeError(f"{field_name} 必须是 x,y 形式")
    try:
        x = int(parts[0])
        y = int(parts[1])
    except ValueError as exc:
        raise RuntimeError(f"{field_name} 必须是整数坐标") from exc
    return {"x": x, "y": y}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ayes-agent", description="Ayes 面向智能体的本地薄工具")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="本地 Ayes HTTP 服务地址")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ensure-service", help="确保本地 Ayes 服务可达")
    subparsers.add_parser("contracts", help="读取智能体接口契约")
    subparsers.add_parser("status", help="读取当前监控状态")
    subparsers.add_parser("targets", help="读取目标候选摘要")
    tasks_parser = subparsers.add_parser("tasks", help="读取已持久化任务列表")
    tasks_parser.add_argument("--limit", type=int, default=100)
    subparsers.add_parser("start", help="启动当前已装载的持续监控")
    subparsers.add_parser("run-once", help="执行一次即时采样")
    subparsers.add_parser("stop", help="停止当前持续监控")
    switch_task_parser = subparsers.add_parser("switch-task", help="切换并恢复指定历史任务")
    switch_task_parser.add_argument("--task-id", required=True)
    delete_task_parser = subparsers.add_parser("delete-task", help="删除指定任务及其长短期记忆")
    delete_task_parser.add_argument("--task-id", required=True)
    plan_parser = subparsers.add_parser("plan-spec", help="根据自然语言生成 watch spec 草案")
    plan_parser.add_argument("--task-id", required=True)
    plan_parser.add_argument("--prompt", required=True)
    plan_parser.add_argument("--target-type", choices=["screen", "window", "process"], default=None)
    plan_parser.add_argument("--screen-id", type=int, default=1)
    plan_parser.add_argument("--window-id", type=int, default=None)
    plan_parser.add_argument("--process-name", default=None)
    plan_parser.add_argument("--webhook-url", default=None)

    confirm_plan_parser = subparsers.add_parser("confirm-plan", help="确认任务草案并装载监控任务")
    confirm_plan_parser.add_argument("--plan-file", required=True)
    confirm_plan_parser.add_argument("--target-type", choices=["screen", "window", "process"], default=None)
    confirm_plan_parser.add_argument("--screen-id", type=int, default=1)
    confirm_plan_parser.add_argument("--window-id", type=int, default=None)
    confirm_plan_parser.add_argument("--process-name", default=None)
    confirm_plan_parser.add_argument("--webhook-url", default=None)
    confirm_plan_parser.add_argument("--alert-message-title", default=None)
    confirm_plan_parser.add_argument("--alert-message-template", default=None)
    confirm_plan_parser.add_argument("--use-entire-target", action="store_true")
    confirm_plan_parser.add_argument("--region-intent", action="append", default=[])
    confirm_plan_parser.add_argument("--region-binding", action="append", default=[])
    confirm_plan_parser.add_argument("--refresh-click-enabled", action="store_true")
    confirm_plan_parser.add_argument("--refresh-click-interval-sec", type=int, default=None)
    confirm_plan_parser.add_argument("--refresh-click-coordinate-space", choices=["window", "screen"], default=None)
    confirm_plan_parser.add_argument("--refresh-click-point", default=None, help="刷新点击点，格式 x,y")

    task_parser = subparsers.add_parser("task", help="读取指定任务快照")
    task_parser.add_argument("--task-id", required=True, help="任务 ID")

    recent_parser = subparsers.add_parser("recent", help="读取近期时间线事件")
    recent_parser.add_argument("--task-id", default=None)
    recent_parser.add_argument("--minutes", type=int, default=5)
    recent_parser.add_argument("--limit", type=int, default=20)

    observe_live_parser = subparsers.add_parser("observe-live", help="读取面向 agent 的实时屏幕观察上下文")
    observe_live_parser.add_argument("--task-id", default=None)
    observe_live_parser.add_argument("--minutes", type=int, default=5)
    observe_live_parser.add_argument("--limit", type=int, default=20)

    alerts_parser = subparsers.add_parser("alerts", help="读取最近告警审计结果")
    alerts_parser.add_argument("--task-id", default=None)
    alerts_parser.add_argument("--minutes", type=int, default=15)
    alerts_parser.add_argument("--limit", type=int, default=20)

    control_parser = subparsers.add_parser("control", help="读取或变更后台控制状态")
    control_subparsers = control_parser.add_subparsers(dest="control_command", required=True)
    control_subparsers.add_parser("status", help="读取后台控制状态")
    control_subparsers.add_parser("pause-all", help="暂停全部监控任务")
    control_subparsers.add_parser("resume-all", help="恢复全部监控任务")
    control_subparsers.add_parser("open-data-dir", help="读取运行数据目录信息")
    cleanup_reminder_parser = control_subparsers.add_parser("cleanup-reminder", help="更新清理提醒状态")
    cleanup_reminder_parser.add_argument("--suppress-forever", default=None)
    cleanup_reminder_parser.add_argument("--snoozed-until", type=float, default=None)
    cleanup_reminder_parser.add_argument("--last-prompt-at", type=float, default=None)
    cleanup_reminder_parser.add_argument("--next-check-after-days", type=int, default=None)
    cleanup_reminder_check_parser = control_subparsers.add_parser("cleanup-reminder-check", help="执行一次清理提醒到期检查")
    cleanup_reminder_check_parser.add_argument("--now", type=float, default=None)

    vision_parser = subparsers.add_parser("vision", help="读取或变更本地视觉增强状态")
    vision_subparsers = vision_parser.add_subparsers(dest="vision_command", required=True)
    vision_subparsers.add_parser("models", help="读取本地视觉模型与 Ollama 可达性")
    vision_prepare_parser = vision_subparsers.add_parser("prepare", help="仅在用户明确要求启用本地视觉增强时执行就绪检查")
    vision_prepare_parser.add_argument("--requested-by", default="agent_enable_local_vision")
    vision_subparsers.add_parser("status", help="读取本地视觉增强配置")
    vision_enable_parser = vision_subparsers.add_parser("enable", help="启用本地视觉增强")
    vision_enable_parser.add_argument("--provider", default="ollama")
    vision_enable_parser.add_argument("--model", required=True)
    vision_enable_parser.add_argument("--auto-use-when-available", default=None)
    vision_subparsers.add_parser("disable", help="关闭本地视觉增强")

    subparsers.add_parser("region-bind-contract", help="读取正式 region-bind 合同")

    region_bind_request_parser = subparsers.add_parser("region-bind-request", help="生成正式 region-bind request")
    region_bind_request_parser.add_argument("--plan-file", required=True)
    region_bind_request_parser.add_argument("--capture-id", default=None)
    region_bind_request_parser.add_argument("--image-path", default=None)
    region_bind_request_parser.add_argument("--image-width", type=int, default=None)
    region_bind_request_parser.add_argument("--image-height", type=int, default=None)

    region_bind_result_parser = subparsers.add_parser("region-bind-result", help="提交正式 region-bind result")
    region_bind_result_parser.add_argument("--result-file", required=True)

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
    if args.command == "tasks":
        path = _build_query_path("/api/tasks", limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "plan-spec":
        return _request_json(base_url, "/api/agent/plan-watch-spec", method="POST", payload=_build_plan_spec_payload(args))
    if args.command == "confirm-plan":
        return _request_json(base_url, "/api/watch/confirm-plan", method="POST", payload=_build_confirm_plan_payload(args))
    if args.command == "switch-task":
        return _request_json(base_url, "/api/watch/switch-task", method="POST", payload={"task_id": args.task_id})
    if args.command == "delete-task":
        return _request_json(base_url, f"/api/watch/task/{args.task_id}", method="DELETE")
    if args.command == "start":
        result = _request_json(base_url, "/api/watch/start", method="POST", payload={})
        if base_url == DEFAULT_BASE_URL:
            result = dict(result)
            result["menubar"] = ensure_local_menubar_started()
        return result
    if args.command == "run-once":
        return _request_json(base_url, "/api/watch/run-once", method="POST", payload={})
    if args.command == "stop":
        return _request_json(base_url, "/api/watch/stop", method="POST", payload={})
    if args.command == "task":
        return _request_json(base_url, f"/api/watch/task/{args.task_id}")
    if args.command == "recent":
        path = _build_query_path("/api/timeline/recent", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "observe-live":
        path = _build_query_path("/api/agent/observe-live", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "alerts":
        path = _build_query_path("/api/alerts/recent", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "control":
        if args.control_command == "status":
            return _request_json(base_url, "/api/control/status")
        if args.control_command == "pause-all":
            return _request_json(base_url, "/api/control/pause-all", method="POST", payload={})
        if args.control_command == "resume-all":
            return _request_json(base_url, "/api/control/resume-all", method="POST", payload={})
        if args.control_command == "open-data-dir":
            return _request_json(base_url, "/api/control/open-data-dir")
        if args.control_command == "cleanup-reminder":
            payload = {
                "suppress_forever": _parse_optional_bool(args.suppress_forever),
                "snoozed_until": args.snoozed_until,
                "last_prompt_at": args.last_prompt_at,
                "next_check_after_days": args.next_check_after_days,
            }
            payload = {key: value for key, value in payload.items() if value is not None}
            return _request_json(base_url, "/api/control/cleanup-reminder", method="POST", payload=payload)
        if args.control_command == "cleanup-reminder-check":
            payload = {"now": args.now} if args.now is not None else {}
            return _request_json(base_url, "/api/control/cleanup-reminder/check", method="POST", payload=payload)
        raise RuntimeError(f"未知 control 命令: {args.control_command}")
    if args.command == "vision":
        if args.vision_command == "models":
            return _request_json(base_url, "/api/vision/models")
        if args.vision_command == "prepare":
            return _request_json(
                base_url,
                "/api/vision/prepare",
                method="POST",
                payload={"requested_by": args.requested_by},
            )
        if args.vision_command == "status":
            return _request_json(base_url, "/api/vision/settings")
        if args.vision_command == "enable":
            payload = {
                "enabled": True,
                "provider": args.provider,
                "model": args.model,
            }
            auto_use_when_available = _parse_optional_bool(args.auto_use_when_available)
            if auto_use_when_available is not None:
                payload["auto_use_when_available"] = auto_use_when_available
            return _request_json(base_url, "/api/vision/settings", method="POST", payload=payload)
        if args.vision_command == "disable":
            return _request_json(base_url, "/api/vision/settings", method="POST", payload={"enabled": False})
        raise RuntimeError(f"未知 vision 命令: {args.vision_command}")
    if args.command == "region-bind-contract":
        return _request_json(base_url, "/api/agent/region-bind-contract")
    if args.command == "region-bind-request":
        plan = _load_json_file(args.plan_file, label="plan_file")
        payload = {
            "plan": plan,
            "capture_ref": _build_region_bind_capture_ref(base_url=base_url, args=args, plan=plan),
        }
        return _request_json(base_url, "/api/agent/region-bind-request", method="POST", payload=payload)
    if args.command == "region-bind-result":
        payload = _load_json_file(args.result_file, label="result_file")
        return _request_json(base_url, "/api/agent/region-bind-result", method="POST", payload=payload)
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
