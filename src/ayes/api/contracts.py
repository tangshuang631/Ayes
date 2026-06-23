"""API-level task, timeline, and agent contract helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from dataclasses import asdict
from typing import Any, Dict, List

from ayes.config.models import WatchSpec
from ayes.memory.short_term import QueryResult


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
    for event in matched_events:
        event["location_summary"] = describe_location_summary(event)
        event["preview_overlay"] = build_preview_overlay(event)
    timestamps = [event["timestamp"] for event in matched_events if "timestamp" in event]
    evidence_refs: List[str] = []
    for event in matched_events:
        for ref in event.get("evidence_refs", []):
            if ref not in evidence_refs:
                evidence_refs.append(ref)
    structured_matches: List[Dict[str, Any]] = []
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
        structured_matches.append(
            {
                "event_id": event.get("event_id"),
                "field": watch_match.get("matched_field") or "",
                "value": watch_match.get("matched_value"),
                "unit": watch_match.get("matched_unit") or "",
                "rule": watch_match.get("matched_rule") or "",
                "query": watch_match.get("matched_query") or "",
                "region_name": region.get("name") or region.get("region_id") or "",
                "time_text": _format_time_text(timestamp),
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
        "evidence_refs": evidence_refs,
        "evidence_previews": evidence_previews,
        "time_scope_respected": True,
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
            "response_keys": ["task_id", "question", "minutes", "answer", "matched_events", "structured_matches", "memory_layers_used", "time_range", "evidence_refs", "evidence_previews", "time_scope_respected"],
        },
        "memory.recent": {
            "method": "GET",
            "path": "/api/memory/recent",
            "query": {"task_id": "可选", "minutes": "1-15", "keyword": "可选"},
            "response_keys": ["task_id", "minutes", "answer", "matched_events", "structured_matches", "memory_layers_used", "time_range", "evidence_refs", "evidence_previews", "time_scope_respected"],
        },
        "logs.recent": {
            "method": "GET",
            "path": "/api/logs",
            "query": {"task_id": "可选", "category": "可选", "minutes": "可选"},
            "response_keys": ["items"],
        },
        "vision.models": {
            "method": "GET",
            "path": "/api/vision/models",
            "response_keys": ["available", "items"],
        },
    }
