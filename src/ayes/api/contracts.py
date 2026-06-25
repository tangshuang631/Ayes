"""API-level task, timeline, and agent contract helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from dataclasses import asdict
from typing import Any, Dict, List

from ayes.config.models import WatchSpec
from ayes.memory.short_term import QueryResult


def extract_structured_observation(event: Dict[str, Any]) -> Dict[str, Any]:
    visual = event.get("visual") or {}
    attrs = visual.get("attributes") or {}
    observation = attrs.get("structured_observation")
    if isinstance(observation, dict):
        return observation
    return {}


def describe_location_summary(event: Dict[str, Any]) -> str:
    region = event.get("region") or {}
    region_label = region.get("name") or region.get("region_id") or ""
    blocks = ((event.get("text") or {}).get("blocks") or [])
    direction = ""
    if blocks:
        rect_norm = blocks[0].get("rect_norm") or {}
        direction = _describe_direction(rect_norm)
    if region_label and direction:
        return f"{region_label} / {direction}"
    if region_label:
        return str(region_label)
    return direction


def build_preview_overlay(event: Dict[str, Any]) -> Dict[str, Any]:
    blocks = ((event.get("text") or {}).get("blocks") or [])
    if blocks:
        first = blocks[0]
        rect_norm = first.get("rect_norm") or {}
        if rect_norm:
            return {
                "kind": "block",
                "label": first.get("text") or describe_location_summary(event) or "OCR block",
                "rect_norm": rect_norm,
            }
    region = event.get("region") or {}
    region_rect = {
        "x": region.get("x_norm"),
        "y": region.get("y_norm"),
        "w": region.get("w_norm"),
        "h": region.get("h_norm"),
    }
    if all(value is not None for value in region_rect.values()):
        return {
            "kind": "region",
            "label": region.get("name") or region.get("region_id") or "ROI",
            "rect_norm": region_rect,
        }
    return {"kind": "none", "label": "", "rect_norm": {}}


def build_task_payload(*, task_id: str, spec: WatchSpec) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "mode": spec.mode,
        "target": asdict(spec.target),
        "spec": asdict(spec),
        "created_at": time.time(),
    }


def build_query_result_payload(*, result: QueryResult, minutes: int, task_id: str, question: str) -> Dict[str, Any]:
    matched_events = [asdict(event) for event in result.matched_events]
    structured_observations: List[Dict[str, Any]] = []
    for event in matched_events:
        event["location_summary"] = describe_location_summary(event)
        event["preview_overlay"] = build_preview_overlay(event)
        observation = extract_structured_observation(event)
        event["structured_observation"] = observation
        if observation:
            structured_observations.append(observation)
    timestamps = [event["timestamp"] for event in matched_events if "timestamp" in event]
    evidence_refs: List[str] = []
    for event in matched_events:
        for ref in event.get("evidence_refs", []):
            if ref not in evidence_refs:
                evidence_refs.append(ref)
    structured_matches: List[Dict[str, Any]] = []
    structured_vision_matches: List[Dict[str, Any]] = []
    seen_structured_keys: set[str] = set()
    for event in matched_events:
        watch_match = event.get("watch_match") or {}
        if not watch_match.get("matched"):
            continue
        key = "|".join(
            [
                str(event.get("event_id") or ""),
                str(watch_match.get("matched_rule") or ""),
                str(watch_match.get("matched_field") or ""),
                str(watch_match.get("matched_value")),
            ]
        )
        if key in seen_structured_keys:
            continue
        seen_structured_keys.add(key)
        region = event.get("region") or {}
        timestamp = event.get("timestamp")
        blocks = ((event.get("text") or {}).get("blocks") or [])
        first_block = blocks[0] if blocks else {}
        first_block_rect_norm = first_block.get("rect_norm") or {}
        structured_matches.append(
            {
                "event_id": event.get("event_id"),
                "field": watch_match.get("matched_field") or "",
                "value": watch_match.get("matched_value"),
                "unit": watch_match.get("matched_unit") or "",
                "rule": watch_match.get("matched_rule") or "",
                "query": watch_match.get("matched_query") or "",
                "region_name": region.get("name") or region.get("region_id") or "",
                "location_summary": event.get("location_summary") or describe_location_summary(event),
                "first_block_text": first_block.get("text") or "",
                "first_block_rect_norm": first_block_rect_norm,
                "first_block_direction": _describe_direction(first_block_rect_norm),
                "time_text": _format_time_text(timestamp),
            }
        )
    for event in matched_events:
        if event.get("source") != "vision":
            continue
        visual = event.get("visual") or {}
        attrs = visual.get("attributes") or {}
        region = event.get("region") or {}
        structured_vision_matches.append(
            {
                "event_id": event.get("event_id"),
                "summary": visual.get("summary") or event.get("summary") or "",
                "detail_lines": attrs.get("detail_lines") or [],
                "reasons": attrs.get("vision_reasons") or [],
                "blocked_reason": attrs.get("vision_blocked_reason") or "",
                "model": attrs.get("vision_model") or visual.get("provider") or "",
                "provider": attrs.get("vision_provider") or visual.get("provider") or "",
                "region_name": region.get("name") or region.get("region_id") or "",
                "time_text": _format_time_text(event.get("timestamp")),
            }
        )
    evidence_previews = [
        {
            "ref": ref,
            "src": ref if ref.startswith("/") else f"/{ref}",
            "label": ref.split("/")[-1],
            "overlay": build_preview_overlay(matched_events[0]) if matched_events else {"kind": "none", "label": "", "rect_norm": {}},
        }
        for ref in evidence_refs
    ]
    lead_event = matched_events[0] if matched_events else {}
    return {
        "task_id": task_id,
        "question": question,
        "minutes": minutes,
        "answer": result.answer,
        "confidence": result.confidence,
        "memory_layers_used": result.memory_layers_used,
        "matched_events": matched_events,
        "time_range": {
            "from": min(timestamps) if timestamps else None,
            "to": max(timestamps) if timestamps else None,
        },
        "structured_matches": structured_matches,
        "structured_vision_matches": structured_vision_matches,
        "structured_observations": structured_observations,
        "evidence_refs": evidence_refs,
        "evidence_previews": evidence_previews,
        "lead_evidence": {
            "event_id": lead_event.get("event_id"),
            "timestamp": lead_event.get("timestamp"),
            "summary": lead_event.get("summary") or lead_event.get("event_type") or "",
            "location_summary": lead_event.get("location_summary") or "",
        },
        "time_scope_respected": True,
    }


def build_memory_items_payload(*, items: List[Dict[str, Any]], task_id: str, minutes: int, limit: int) -> Dict[str, Any]:
    normalized: List[Dict[str, Any]] = []
    for item in items:
        event = dict(item)
        event["location_summary"] = describe_location_summary(event)
        event["preview_overlay"] = build_preview_overlay(event)
        event["structured_observation"] = extract_structured_observation(event)
        normalized.append(event)
    return {
        "task_id": task_id,
        "minutes": minutes,
        "limit": limit,
        "count": len(normalized),
        "items": normalized,
    }


def build_observe_live_payload(
    *,
    task_id: str,
    minutes: int,
    limit: int,
    status: Dict[str, Any],
    screenshot: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
    memory_items: List[Dict[str, Any]],
    alerts: List[Dict[str, Any]],
    logs: List[Dict[str, Any]],
    cleanup_reminder: Dict[str, Any],
    region_binding_context: Dict[str, Any],
    vision_status: Dict[str, Any],
    observed_at: float,
) -> Dict[str, Any]:
    decorated_recent_events = [_decorate_live_event(item) for item in recent_events[:limit]]
    decorated_memory_items = [_decorate_live_event(item) for item in memory_items[:limit]]
    decorated_alerts = [_decorate_live_event(item) for item in alerts[:limit]]
    trimmed_logs = logs[:limit]
    latest_event_at = _latest_timestamp(decorated_recent_events)
    latest_memory_at = _latest_timestamp(decorated_memory_items)
    latest_alert_at = _latest_timestamp(decorated_alerts)
    latest_log_at = _latest_timestamp(trimmed_logs)
    screenshot_path = screenshot.get("path")
    evidence_status = _build_live_evidence_status(
        status=status,
        screenshot=screenshot,
        recent_events=decorated_recent_events,
        memory_items=decorated_memory_items,
        observed_at=observed_at,
    )
    vision_next_action = _build_vision_next_action(vision_status)
    configuration_guidance = _build_configuration_guidance(status=status, vision_status=vision_status)
    task_context = _build_task_context_hint(status=status, task_id=task_id)
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "observed_at": observed_at,
        "time_scope": {
            "minutes": minutes,
            "from": observed_at - (minutes * 60),
            "to": observed_at,
        },
        "status": status,
        "screenshot": {
            **screenshot,
            "available": bool(screenshot_path),
        },
        "recent_events": {
            "items": decorated_recent_events,
            "count": len(decorated_recent_events),
            "limit": limit,
            "latest_timestamp": latest_event_at,
        },
        "memory_items": {
            "items": decorated_memory_items,
            "count": len(decorated_memory_items),
            "limit": limit,
            "latest_timestamp": latest_memory_at,
        },
        "alerts": {
            "items": decorated_alerts,
            "count": len(decorated_alerts),
            "limit": limit,
            "latest_timestamp": latest_alert_at,
        },
        "logs": {
            "items": trimmed_logs,
            "count": len(trimmed_logs),
            "limit": limit,
            "latest_timestamp": latest_log_at,
            "error_count": sum(1 for item in trimmed_logs if str(item.get("level") or "").lower() == "error"),
            "warn_count": sum(1 for item in trimmed_logs if str(item.get("level") or "").lower() in {"warn", "warning"}),
        },
        "cleanup_reminder": cleanup_reminder,
        "region_binding_context": _build_region_binding_context(region_binding_context),
        "vision_status": vision_status,
        "evidence_status": evidence_status,
        "agent_hints": {
            "summary": evidence_status["summary"],
            "suggested_next_steps": _build_live_next_steps(status=status, evidence_status=evidence_status),
            "vision_next_action": vision_next_action,
            "configuration_guidance": configuration_guidance,
            "task_context": task_context,
        },
    }


def _decorate_live_event(item: Dict[str, Any]) -> Dict[str, Any]:
    event = dict(item)
    event["location_summary"] = describe_location_summary(event)
    event["preview_overlay"] = build_preview_overlay(event)
    event["structured_observation"] = extract_structured_observation(event)
    return event


def _latest_timestamp(items: List[Dict[str, Any]]) -> Any:
    timestamps = [item.get("timestamp") for item in items if item.get("timestamp") is not None]
    if not timestamps:
        return None
    return max(timestamps)


def _build_live_evidence_status(
    *,
    status: Dict[str, Any],
    screenshot: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
    memory_items: List[Dict[str, Any]],
    observed_at: float,
) -> Dict[str, Any]:
    has_runner = bool(status.get("has_runner"))
    screenshot_available = bool(screenshot.get("path"))
    recent_count = len(recent_events)
    memory_count = len(memory_items)
    last_run_at = status.get("last_run_at")
    seconds_since_run = None
    if last_run_at is not None:
        try:
            seconds_since_run = round(observed_at - float(last_run_at), 2)
        except (TypeError, ValueError):
            seconds_since_run = None
    if not has_runner:
        quality = "no_task"
        summary = "当前没有已装载监控任务。"
    elif not screenshot_available and recent_count == 0:
        quality = "no_evidence"
        summary = "当前还没有可用截图或近期事件。"
    elif recent_count == 0 and memory_count == 0:
        quality = "sparse"
        summary = "当前有监控任务，但最近时间窗内证据较少。"
    else:
        quality = "ready"
        summary = "当前已有可供 agent 回读的截图、事件或记忆证据。"
    return {
        "quality": quality,
        "summary": summary,
        "has_runner": has_runner,
        "is_running": bool(status.get("is_running")),
        "screenshot_available": screenshot_available,
        "recent_event_count": recent_count,
        "memory_item_count": memory_count,
        "seconds_since_run": seconds_since_run,
        "activity_status": status.get("activity_status"),
    }


def _build_live_next_steps(*, status: Dict[str, Any], evidence_status: Dict[str, Any]) -> List[str]:
    if not evidence_status["has_runner"]:
        recent_tasks = ((status.get("task_context") or {}).get("recent_tasks") or [])
        if recent_tasks:
            return ["当前没有装载中的任务；可先从 tasks 里恢复历史任务，或重新通过 plan-spec/confirm-plan 创建新任务。"]
        return ["先通过 plan-spec/confirm-plan 或工作台装载监控任务。"]
    if not evidence_status["is_running"]:
        return ["如需持续监控，调用 start 恢复后台采样。"]
    if evidence_status["quality"] in {"no_evidence", "sparse"}:
        return ["执行 run-once 或检查目标预览、ROI、OCR 可观测性。"]
    if status.get("last_error"):
        return ["读取 logs 排查最近一次后台错误。"]
    return ["可以结合 ask/recent/memory-items 对最近时间窗继续追问。"]


def _build_vision_next_action(vision_status: Dict[str, Any]) -> Dict[str, Any]:
    provider_status = vision_status.get("provider_status") or {}
    installation_guidance = vision_status.get("installation_guidance") or {}
    action = str(provider_status.get("recommended_action") or "")
    if not action and vision_status.get("readiness_check_required"):
        action = "check_on_user_enable_request"
    if not action:
        action = "ready"
    return {
        "action": action,
        "provider": "ollama",
        "default_model": vision_status.get("default_local_model") or provider_status.get("default_model") or "qwen2.5vl:7b",
        "message": installation_guidance.get("agent_message") or "当前本地视觉增强已可用。",
        "user_steps": installation_guidance.get("user_steps") or [],
        "agent_can_attempt_after_permission": bool(installation_guidance.get("agent_can_attempt_after_permission", False)),
        "expected_effect": installation_guidance.get("expected_effect") or "",
    }


def _build_configuration_guidance(*, status: Dict[str, Any], vision_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    guidance: List[Dict[str, Any]] = []
    current_spec = status.get("spec") or {}
    alert = current_spec.get("alert") or {}
    mode = str(status.get("mode") or current_spec.get("mode") or "")
    if mode == "triggered" and not str(alert.get("webhook_url") or "").strip():
        guidance.append(
            {
                "topic": "wecom_webhook",
                "status": "needs_user_setup",
                "summary": "当前 triggered 任务缺少企业微信 webhook，提醒暂时无法真正发出。",
                "user_steps": [
                    "去企业微信群机器人配置页获取 webhook URL。",
                    "把完整 webhook URL 发给 agent，由 agent 写入 confirm-plan 或重新确认任务。",
                    "若暂时不想通知，可改成 observe 模式继续观察。",
                ],
                "agent_steps": [
                    "继续通过对话指导用户获取并填写 webhook，而不是只报缺失字段。",
                    "拿到 webhook 后继续执行 confirm-plan 或重建任务，不要让流程停在中间态。",
                ],
            }
        )
    installation_guidance = vision_status.get("installation_guidance") or {}
    guidance.append(
        {
            "topic": "local_vision",
            "status": "on_demand_only",
            "summary": installation_guidance.get("agent_message")
            or "默认不主动检查 Ollama；只有用户明确要求开启本地大模型增强时才继续准备流程。",
            "user_steps": installation_guidance.get("user_steps") or [],
            "agent_steps": [
                "仅当用户明确希望开启本地视觉增强时，才继续执行 vision prepare。",
                "如果用户不会操作，就继续按返回步骤指导或在获权后代为执行。",
            ],
        }
    )
    return guidance


def _build_task_context_hint(*, status: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    context = status.get("task_context") or {}
    current_task_id = context.get("current_task_id")
    last_task_id = context.get("last_task_id")
    recent_tasks = context.get("recent_tasks") or []
    message = ""
    if task_id and task_id == current_task_id:
        message = f"当前正在查看任务 {task_id}。"
    elif task_id and task_id == last_task_id:
        message = f"当前未装载该任务，但最近活动任务是 {task_id}，可直接 switch-task 恢复。"
    elif task_id:
        message = f"当前正在按 task_id={task_id} 回读持久化证据。"
    elif current_task_id:
        message = f"当前已装载任务 {current_task_id}。"
    elif recent_tasks:
        message = "当前没有装载中的任务，但存在可恢复的历史任务。"
    else:
        message = "当前没有装载任务，也没有可恢复的历史任务。"
    return {
        "current_task_id": current_task_id,
        "last_task_id": last_task_id,
        "requested_task_id": task_id or None,
        "recent_tasks": recent_tasks[:5],
        "message": message,
    }


def _build_region_binding_context(context: Dict[str, Any]) -> Dict[str, Any]:
    bindings = list(context.get("bindings") or [])
    unbound = list(context.get("unbound_region_intents") or [])
    return {
        "task_id": context.get("task_id"),
        "target_ref": context.get("target_ref") or {},
        "capture_ref": context.get("capture_ref") or {},
        "bindings": bindings,
        "bound_count": len(bindings),
        "unbound_region_intents": unbound,
        "unbound_count": len(unbound),
    }


def _format_time_text(timestamp: Any) -> str:
    if timestamp in {None, ""}:
        return ""
    try:
        numeric = float(timestamp)
    except (TypeError, ValueError):
        return str(timestamp)
    return datetime.fromtimestamp(numeric, tz=timezone.utc).strftime("%H:%M:%S")


def _describe_direction(rect_norm: Dict[str, Any]) -> str:
    if not rect_norm:
        return ""
    center_x = float(rect_norm.get("x", 0.0)) + (float(rect_norm.get("w", 0.0)) / 2.0)
    center_y = float(rect_norm.get("y", 0.0)) + (float(rect_norm.get("h", 0.0)) / 2.0)
    horizontal = "左"
    vertical = "上"
    if center_x >= 0.66:
        horizontal = "右"
    elif center_x >= 0.33:
        horizontal = ""
    if center_y >= 0.66:
        vertical = "下"
    elif center_y >= 0.33:
        vertical = ""
    if horizontal and vertical:
        return f"{horizontal}{vertical}"
    if vertical:
        return f"{vertical}方"
    if horizontal:
        return f"{horizontal}侧"
    return "中间"


def build_region_bind_contract_payload() -> Dict[str, Any]:
    return {
        "bind_version": "1.0",
        "request": {
            "task_id": "必填，必须关联当前草案或待确认任务",
            "target_ref": {
                "type": "process|window|screen",
                "process_name": "可选",
                "window_id": "可选",
                "screen_id": "可选",
            },
            "capture_ref": {
                "capture_id": "必填",
                "image_path": "建议提供最近截图绝对路径",
                "image_width": "必填",
                "image_height": "必填",
            },
            "region_intents": [
                {
                    "region_intent_id": "必填",
                    "name": "必填",
                    "purpose": "可选但建议提供",
                    "required": "可选，默认 true",
                }
            ],
        },
        "result": {
            "task_id": "必填",
            "target_ref": "需与 request 对应",
            "capture_ref": "需与 request 对应",
            "region_bindings": [
                {
                    "region_intent_id": "必填",
                    "region_id": "必填",
                    "name": "必填",
                    "x": "必填",
                    "y": "必填",
                    "w": "必填",
                    "h": "必填",
                    "coordinate_space": "v1 建议固定为 target",
                    "binding_space": "建议为 capture_image",
                    "source": "external_selector|screenshot_annotation|manual_coordinates",
                    "confidence": "可选",
                    "notes": "可选",
                }
            ],
            "unbound_region_intents": [
                {
                    "region_intent_id": "必填",
                    "name": "建议提供",
                    "reason": "建议提供未绑定原因",
                }
            ],
        },
        "confirm_plan_rules": [
            "region_bindings[] 必须可直接转成 watch spec.target.regions[]",
            "required=true 且未绑定的区域不得静默丢失",
            "必要时可退回整目标监控，但仅限非 required 区域",
        ],
        "action_binding_extension": {
            "refresh_click": {
                "action_type": "refresh_click",
                "point_id": "refresh_main",
                "x": "必填",
                "y": "必填",
                "coordinate_space": "target|screen|window",
                "binding_space": "capture_image",
                "source": "external_selector|screenshot_annotation|manual_coordinates",
                "confidence": "可选",
            }
        },
    }


def build_agent_contract_payload() -> Dict[str, Dict[str, Any]]:
    return {
        "watch.create": {
            "method": "POST",
            "path": "/api/watch/load-screen",
            "alternative_paths": ["/api/watch/load-window/{window_id}"],
            "request": {"window_id": "可选，窗口监控时通过路径参数提供"},
            "response_keys": ["status", "mode"],
        },
        "watch.plan": {
            "method": "POST",
            "path": "/api/agent/plan-watch-spec",
            "request": {"task_id": "必填", "prompt": "必填", "target": "可选"},
            "response_keys": ["task_id", "mode", "draft_spec", "missing_fields", "questions", "region_intents", "action_intents", "setup_guidance", "ambiguities", "confirmation_summary", "can_apply_directly"],
        },
        "region_bind.request": {
            "method": "POST",
            "path": "/api/agent/region-bind-request",
            "request": {"plan": "必填", "capture_ref": "必填"},
            "response_keys": ["bind_version", "task_id", "target_ref", "capture_ref", "region_intents"],
        },
        "region_bind.result": {
            "method": "POST",
            "path": "/api/agent/region-bind-result",
            "request": {"bind_version": "必填", "task_id": "必填", "target_ref": "必填", "capture_ref": "必填", "region_bindings": "必填"},
            "response_keys": ["status", "region_binding_context"],
        },
        "region_bind.contract": {
            "method": "GET",
            "path": "/api/agent/region-bind-contract",
            "response_keys": ["bind_version", "request", "result", "confirm_plan_rules", "action_binding_extension"],
        },
        "watch.confirm_plan": {
            "method": "POST",
            "path": "/api/watch/confirm-plan",
            "request": {
                "plan": "必填",
                "confirmations": "可选",
                "region_bindings": "推荐放在 confirmations 下",
                "alert_message_title": "可放在 confirmations 下",
                "alert_message_template": "可放在 confirmations 下",
            },
            "response_keys": ["status", "task_id", "mode", "spec", "target"],
        },
        "watch.status": {
            "method": "GET",
            "path": "/api/watch/status",
            "response_keys": ["has_runner", "is_running", "task_id", "last_task_id", "target", "mode", "event_count"],
        },
        "tasks.list": {
            "method": "GET",
            "path": "/api/tasks",
            "query": {"limit": "1-500"},
            "response_keys": ["items", "count"],
        },
        "tasks.switch": {
            "method": "POST",
            "path": "/api/watch/switch-task",
            "request": {"task_id": "必填"},
            "response_keys": ["status", "task", "watch_status"],
        },
        "tasks.delete": {
            "method": "DELETE",
            "path": "/api/watch/task/{task_id}",
            "response_keys": ["status", "task_id", "deleted"],
        },
        "tasks.memory_policy": {
            "method": "GET/POST",
            "path": "/api/tasks/{task_id}/memory-policy",
            "request": {"short_term_retain_days": "1-14", "long_term_retain_days": "1-30", "disable_auto_cleanup": "可选，true 表示永久保留不自动清理"},
            "response_keys": ["status", "memory_policy"],
        },
        "tasks.memory_cleanup": {
            "method": "POST",
            "path": "/api/tasks/{task_id}/memory-cleanup",
            "request": {"now": "可选"},
            "response_keys": ["status", "cleanup"],
        },
        "agent.observe_live": {
            "method": "GET",
            "path": "/api/agent/observe-live",
            "query": {"task_id": "可选", "minutes": "1-20160", "limit": "1-100"},
            "response_keys": ["schema_version", "task_id", "observed_at", "time_scope", "status", "screenshot", "recent_events", "memory_items", "alerts", "logs", "cleanup_reminder", "region_binding_context", "vision_status", "evidence_status", "agent_hints"],
        },
        "control.status": {
            "method": "GET",
            "path": "/api/control/status",
            "response_keys": ["is_paused", "paused_at", "pause_reason", "has_runner", "is_running", "task_id", "data_dir", "archive_dir"],
        },
        "control.pause_all": {
            "method": "POST",
            "path": "/api/control/pause-all",
            "response_keys": ["status"],
        },
        "control.resume_all": {
            "method": "POST",
            "path": "/api/control/resume-all",
            "response_keys": ["status"],
        },
        "control.open_data_dir": {
            "method": "GET",
            "path": "/api/control/open-data-dir",
            "response_keys": ["status", "data_dir", "archive_dir"],
        },
        "control.cleanup_reminder": {
            "method": "POST",
            "path": "/api/control/cleanup-reminder",
            "request": {"suppress_forever": "可选", "snoozed_until": "可选", "last_prompt_at": "可选"},
            "response_keys": ["status", "cleanup_reminder"],
        },
        "control.cleanup_reminder_check": {
            "method": "POST",
            "path": "/api/control/cleanup-reminder/check",
            "request": {"now": "可选"},
            "response_keys": ["status", "cleanup_reminder"],
        },
        "watch.start": {
            "method": "POST",
            "path": "/api/watch/start",
            "response_keys": ["status"],
        },
        "watch.run_once": {
            "method": "POST",
            "path": "/api/watch/run-once",
            "response_keys": ["events", "status"],
        },
        "watch.stop": {
            "method": "POST",
            "path": "/api/watch/stop",
            "response_keys": ["status"],
        },
        "timeline.recent": {
            "method": "GET",
            "path": "/api/timeline/recent",
            "query": {"task_id": "可选", "minutes": "1-20160", "limit": "1-200"},
            "response_keys": ["items"],
        },
        "timeline.long_term": {
            "method": "GET",
            "path": "/api/timeline/long-term",
            "query": {"task_id": "可选", "hours": "1-720", "limit": "1-100"},
            "response_keys": ["items"],
        },
        "timeline.query": {
            "method": "GET",
            "path": "/api/ask",
            "query": {"task_id": "可选", "question": "必填", "minutes": "1-20160", "hours": "1-720"},
            "response_keys": ["task_id", "question", "minutes", "answer", "matched_events", "structured_matches", "structured_observations", "memory_layers_used", "time_range", "evidence_refs", "evidence_previews", "time_scope_respected"],
        },
        "snapshot.inspect": {
            "method": "GET",
            "path": "/api/screenshot",
            "query": {"task_id": "可选"},
            "response_keys": ["path", "regions", "target", "capture_target", "capture_status", "capture_timestamp"],
        },
        "memory.recent": {
            "method": "GET",
            "path": "/api/memory/recent",
            "query": {"task_id": "可选", "minutes": "1-20160", "keyword": "可选"},
            "response_keys": ["task_id", "minutes", "answer", "matched_events", "structured_matches", "memory_layers_used", "time_range", "evidence_refs", "evidence_previews", "time_scope_respected"],
        },
        "memory.items": {
            "method": "GET",
            "path": "/api/memory/items",
            "query": {"task_id": "可选", "minutes": "1-20160", "limit": "1-100", "keyword": "可选"},
            "response_keys": ["task_id", "minutes", "limit", "count", "items"],
        },
        "logs.recent": {
            "method": "GET",
            "path": "/api/logs",
            "query": {"task_id": "可选", "category": "可选", "minutes": "可选"},
            "response_keys": ["items"],
        },
        "alerts.recent": {
            "method": "GET",
            "path": "/api/alerts/recent",
            "query": {"task_id": "可选", "minutes": "1-60", "limit": "1-100"},
            "response_keys": ["task_id", "minutes", "limit", "count", "items"],
        },
        "vision.models": {
            "method": "GET",
            "path": "/api/vision/models",
            "response_keys": ["available", "binary_available", "service_reachable", "default_model", "default_model_installed", "items", "recommended_action"],
        },
        "vision.prepare": {
            "method": "POST",
            "path": "/api/vision/prepare",
            "request": {"requested_by": "建议填写 agent_enable_local_vision 或 user_enable_local_vision"},
            "response_keys": ["requested_by", "default_local_model", "provider", "provider_status", "agent_can_attempt_after_permission", "user_steps", "expected_effect"],
        },
        "vision.settings": {
            "method": "POST",
            "path": "/api/vision/settings",
            "request": {"enabled": "可选", "provider": "可选", "model": "可选", "auto_use_when_available": "可选"},
            "response_keys": ["status", "vision_settings"],
        },
    }
