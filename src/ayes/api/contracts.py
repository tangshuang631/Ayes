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
            "response_keys": ["task_id", "mode", "draft_spec", "missing_fields", "questions", "region_intents", "action_intents", "ambiguities", "confirmation_summary", "can_apply_directly"],
        },
        "watch.confirm_plan": {
            "method": "POST",
            "path": "/api/watch/confirm-plan",
            "request": {"plan": "必填", "confirmations": "可选", "region_bindings": "推荐放在 confirmations 下"},
            "response_keys": ["status", "task_id", "mode", "spec", "target"],
        },
        "watch.status": {
            "method": "GET",
            "path": "/api/watch/status",
            "response_keys": ["has_runner", "is_running", "task_id", "last_task_id", "target", "mode", "event_count"],
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
            "query": {"task_id": "可选", "minutes": "1-15", "limit": "1-200"},
            "response_keys": ["items"],
        },
        "timeline.long_term": {
            "method": "GET",
            "path": "/api/timeline/long-term",
            "query": {"task_id": "可选", "limit": "1-100"},
            "response_keys": ["items"],
        },
        "timeline.query": {
            "method": "GET",
            "path": "/api/ask",
            "query": {"task_id": "可选", "question": "必填", "minutes": "1-15"},
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
            "query": {"task_id": "可选", "minutes": "1-15", "keyword": "可选"},
            "response_keys": ["task_id", "minutes", "answer", "matched_events", "structured_matches", "memory_layers_used", "time_range", "evidence_refs", "evidence_previews", "time_scope_respected"],
        },
        "memory.items": {
            "method": "GET",
            "path": "/api/memory/items",
            "query": {"task_id": "可选", "minutes": "1-15", "limit": "1-100", "keyword": "可选"},
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
            "response_keys": ["available", "items"],
        },
    }
