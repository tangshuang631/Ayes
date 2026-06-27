"""API-level task, timeline, and agent contract helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from dataclasses import asdict
from typing import Any, Dict, List

from ayes.config.models import WatchSpec
from ayes.memory.short_term import QueryResult
from ayes.observation.text_quality import score_ocr_text


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


def build_task_payload(*, task_id: str, spec: WatchSpec, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = {
        "task_id": task_id,
        "mode": spec.mode,
        "target": asdict(spec.target),
        "spec": asdict(spec),
        "created_at": time.time(),
    }
    roi = getattr(spec, "roi", None)
    if isinstance(roi, dict) and roi:
        payload["roi"] = dict(roi)
    if extra:
        payload.update(extra)
    return payload


def build_query_result_payload(*, result: QueryResult, minutes: int, task_id: str, question: str) -> Dict[str, Any]:
    raw_matched_events = [asdict(event) for event in result.matched_events]
    matched_events = [_compact_query_event(event) for event in raw_matched_events]
    structured_observations: List[Dict[str, Any]] = []
    for event, raw_event in zip(matched_events, raw_matched_events):
        event["location_summary"] = describe_location_summary(event)
        event["preview_overlay"] = build_preview_overlay(event)
        observation = _compact_structured_observation(extract_structured_observation(raw_event))
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


def _compact_query_event(event: Dict[str, Any]) -> Dict[str, Any]:
    visual = event.get("visual") or {}
    attrs = visual.get("attributes") or {}
    safe_attrs = {
        key: attrs.get(key)
        for key in ["raw_text", "detail_lines", "detail_count", "vision_reasons", "vision_blocked_reason", "vision_model", "vision_provider", "attention"]
        if key in attrs
    }
    if "structured_observation" in attrs:
        safe_attrs["structured_observation"] = _compact_structured_observation(attrs.get("structured_observation") or {})
    text_payload = event.get("text") or {}
    compact_text = {
        "ocr_text": text_payload.get("ocr_text") or "",
        "normalized_text": text_payload.get("normalized_text") or "",
        "blocks": [_compact_text_block(block) for block in (text_payload.get("blocks") or [])[:3] if isinstance(block, dict)],
    }
    return {
        "event_id": event.get("event_id"),
        "task_id": event.get("task_id"),
        "spec_version": event.get("spec_version"),
        "task_mode": event.get("task_mode"),
        "timestamp": event.get("timestamp"),
        "source": event.get("source"),
        "event_type": event.get("event_type"),
        "priority": event.get("priority"),
        "confidence": event.get("confidence"),
        "target": event.get("target") or {},
        "observability": event.get("observability") or {},
        "region": event.get("region") or {},
        "text": compact_text,
        "visual": {
            "summary": visual.get("summary") or "",
            "labels": visual.get("labels") or [],
            "attributes": safe_attrs,
            "provider": visual.get("provider") or "",
        },
        "summary": event.get("summary") or "",
        "tags": event.get("tags") or [],
        "watch_match": event.get("watch_match") or {},
        "evidence_refs": event.get("evidence_refs") or [],
        "related_event_ids": event.get("related_event_ids") or [],
    }


def _compact_structured_observation(observation: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(observation, dict) or not observation:
        return {}
    compact = {
        key: observation.get(key)
        for key in ["observation_version", "source", "region", "layout", "visual", "entities", "warnings", "fusion_notes", "attention"]
        if key in observation
    }
    text = observation.get("text")
    if isinstance(text, dict):
        compact["text"] = {
            "full_text": text.get("full_text") or "",
            "char_count": text.get("char_count") or 0,
            "provider": text.get("provider") or "",
            "confidence": text.get("confidence") or 0.0,
        }
    return compact


def _compact_text_block(block: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "text": block.get("text") or "",
        "confidence": block.get("confidence"),
        "rect_norm": block.get("rect_norm") or {},
        "coordinate_space": block.get("coordinate_space") or "",
        "line_index": block.get("line_index"),
        "block_type": block.get("block_type"),
    }


def build_memory_items_payload(*, items: List[Dict[str, Any]], task_id: str, minutes: int, limit: int, compact: bool = False) -> Dict[str, Any]:
    if compact:
        normalized = [_compact_event_payload(item) for item in items]
        return {
            "task_id": task_id,
            "minutes": minutes,
            "limit": limit,
            "compact": True,
            "count": len(normalized),
            "items": normalized,
        }
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
        "compact": False,
        "count": len(normalized),
        "items": normalized,
    }


def build_activity_payload(
    *,
    items: List[Dict[str, Any]],
    task_id: str,
    minutes: int,
    observed_at: float,
    has_screenshot_evidence: bool,
) -> Dict[str, Any]:
    compact_items = [_compact_event_payload(item) for item in items]
    timestamps = [item.get("timestamp") for item in compact_items if item.get("timestamp") is not None]
    keyword_items = [item for item in compact_items if not _is_activity_audit_summary(item) and not _is_low_quality_ocr_summary(item)]
    keywords = _dedupe_keywords(keyword for item in keyword_items for keyword in item.get("keywords", []))[:12]
    primary_summary = _build_primary_activity_summary(compact_items)
    confidence = _average_confidence(compact_items)
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "observed_at": observed_at,
        "time_scope": {
            "minutes": minutes,
            "from": observed_at - (minutes * 60),
            "to": observed_at,
            "evidence_from": min(timestamps) if timestamps else None,
            "evidence_to": max(timestamps) if timestamps else None,
        },
        "primary_summary": primary_summary,
        "timeline": compact_items[:8],
        "keywords": keywords,
        "confidence": confidence,
        "has_screenshot_evidence": has_screenshot_evidence,
        "needs_detail_followup": len(compact_items) > 8 or confidence < 0.65,
    }


def _compact_event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    region = event.get("region") or {}
    summary = str(event.get("summary") or event.get("event_type") or "").strip()
    visual = event.get("visual") or {}
    visual_summary = str(visual.get("summary") or "").strip()
    if visual_summary and visual_summary not in summary and not _is_internal_visual_diagnostic(visual_summary):
        summary = f"{summary}；{visual_summary}" if summary else visual_summary
    text_payload = event.get("text") or {}
    text = str(text_payload.get("normalized_text") or text_payload.get("ocr_text") or "").strip()
    attributes = visual.get("attributes") or {}
    attention = attributes.get("attention") or (attributes.get("structured_observation") or {}).get("attention") or {}
    text_quality = None
    if event.get("source") == "ocr" and attributes.get("text_quality_score") is None:
        block_confidences = [block.get("confidence") for block in (text_payload.get("blocks") or []) if isinstance(block, dict)]
        text_quality = score_ocr_text(text or summary, avg_confidence=float(attributes.get("ocr_avg_confidence") or event.get("confidence") or 0.0), block_confidences=block_confidences)
    text_quality_score = attributes.get("text_quality_score") if text_quality is None else text_quality.score
    text_quality_noisy = attributes.get("text_quality_noisy") if text_quality is None else text_quality.is_noisy
    quality_probe = None
    if event.get("source") == "ocr":
        try:
            quality_probe = score_ocr_text(f"{summary} {text}", avg_confidence=float(event.get("confidence") or 0.0))
        except (TypeError, ValueError):
            quality_probe = None
    low_quality_ocr = (
        event.get("source") == "ocr"
        and (
            bool(text_quality_noisy)
            or (text_quality_score is not None and float(text_quality_score or 0.0) < 0.55)
            or (quality_probe is not None and (quality_probe.is_noisy or quality_probe.score < 0.62))
        )
    )
    keyword_source = list(event.get("tags") or [])
    if not low_quality_ocr:
        keyword_source += _extract_keywords(summary)
        keyword_source += _extract_keywords(text)
    elif any(keyword in summary for keyword in ["错误", "异常", "弹窗", "登录", "价格", "按钮", "告警", "低质量文本已降权"]):
        keyword_source += _extract_keywords(summary)
    keywords = _dedupe_keywords(keyword_source)
    return {
        "event_id": event.get("event_id"),
        "timestamp": event.get("timestamp"),
        "time_text": _format_time_text(event.get("timestamp")),
        "source": event.get("source"),
        "event_type": event.get("event_type"),
        "summary": summary,
        "region_name": region.get("name") or region.get("region_id") or "",
        "location_summary": describe_location_summary(event),
        "keywords": keywords[:8],
        "confidence": event.get("confidence"),
        "text_quality_score": text_quality_score,
        "text_quality_noisy": text_quality_noisy,
        "attention_primary": attention.get("primary"),
        "attention_weight": attention.get("weight"),
        "priority": event.get("priority"),
    }


def _build_primary_activity_summary(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "最近时间窗内未发现可摘要的监控事件。"
    has_primary_visual = any(_is_primary_visual_summary(item) for item in items)
    ranked_items = sorted(items, key=_activity_summary_rank, reverse=True)
    summaries = [
        summary
        for item in ranked_items
        for summary in [str(item.get("summary") or "").strip()]
        if summary and not _is_low_quality_ocr_summary(item, has_primary_visual=has_primary_visual) and not _is_activity_audit_summary(item)
    ]
    if not summaries:
        return "最近有监控事件，但摘要信息较少。"
    return "；".join(summaries[:3])


def _activity_summary_rank(item: Dict[str, Any]) -> float:
    score = 0.0
    region = str(item.get("region_name") or item.get("location_summary") or "")
    event_type = str(item.get("event_type") or "")
    summary = str(item.get("summary") or "")
    if "主内容" in region:
        score += 5.0
    elif "全目标" in region:
        score += 3.0
    elif any(label in region for label in ["顶部", "底部", "侧栏"]):
        score += 1.0
    if event_type == "vision_skipped" or "已跳过" in summary:
        score -= 4.0
    if _is_activity_audit_summary(item):
        score -= 6.0
    if _is_low_quality_ocr_summary(item):
        score -= 8.0
    if _is_primary_visual_summary(item):
        score += 5.5
    if item.get("attention_primary") is True:
        score += 3.0
    try:
        score += float(item.get("attention_weight") or 0.0)
    except (TypeError, ValueError):
        pass
    try:
        score += float(item.get("text_quality_score") or 0.0) * 3.0
    except (TypeError, ValueError):
        pass
    if any(keyword in summary for keyword in ["错误", "异常", "弹窗", "登录", "价格", "按钮", "告警"]):
        score += 2.0
    try:
        score += float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        pass
    try:
        score += float(item.get("timestamp") or 0.0) / 1_000_000_000
    except (TypeError, ValueError):
        pass
    return score


def _is_low_quality_ocr_summary(item: Dict[str, Any], *, has_primary_visual: bool = False) -> bool:
    if item.get("source") != "ocr":
        return False
    summary = str(item.get("summary") or "")
    if _is_internal_visual_diagnostic(summary):
        return True
    if bool(item.get("text_quality_noisy")):
        return True
    if item.get("text_quality_score") is None:
        return False
    try:
        threshold = 0.62 if has_primary_visual else 0.55
        return float(item.get("text_quality_score") or 0.0) < threshold
    except (TypeError, ValueError):
        return False


def _is_primary_visual_summary(item: Dict[str, Any]) -> bool:
    event_type = str(item.get("event_type") or "")
    if event_type != "visual_summary":
        return False
    if _is_activity_audit_summary(item):
        return False
    if item.get("attention_primary") is True:
        return True
    region = str(item.get("region_name") or item.get("location_summary") or "")
    return "主内容" in region


def _is_activity_audit_summary(item: Dict[str, Any]) -> bool:
    event_type = str(item.get("event_type") or "")
    summary = str(item.get("summary") or "")
    return event_type in {"vision_triggered", "vision_skipped"} or "视觉增强已触发" in summary or "视觉增强已跳过" in summary


def _is_internal_visual_diagnostic(summary: str) -> bool:
    value = str(summary or "").strip()
    return value.startswith("OCR vision |") or "OCR vision | 字符" in value


def _average_confidence(items: List[Dict[str, Any]]) -> float:
    values = []
    for item in items:
        try:
            values.append(float(item.get("confidence")))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0.0 if not items else 0.6
    return round(sum(values) / len(values), 3)


def _extract_keywords(text: str) -> List[str]:
    tokens: List[str] = []
    for raw in str(text or "").replace("，", " ").replace("。", " ").replace("；", " ").replace("/", " ").split():
        token = raw.strip(" ,.;:!?()[]{}<>\"'`")
        if len(token) >= 2:
            tokens.append(token[:32])
    return tokens


def _dedupe_keywords(values) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


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
        "storage.status": {
            "method": "GET",
            "path": "/api/storage/status",
            "response_keys": ["runtime_dir", "total_bytes", "sqlite_db_bytes", "tasks", "root_legacy"],
        },
        "storage.cleanup": {
            "method": "POST",
            "path": "/api/storage/cleanup",
            "request": {
                "task_id": "可选，不传则作用于全部任务",
                "screenshots": "可选，清理任务截图目录",
                "logs": "可选，清理任务日志目录",
                "memory": "可选，显式清理任务记忆；不会被 --all 隐式启用",
                "index": "可选，清理任务检索索引",
                "legacy": "可选，清理 runtime 根目录旧遗留文件",
                "vacuum": "可选，执行 SQLite VACUUM",
                "rebuild_index": "可选，从 compact/short/long 记忆重建索引",
            },
            "response_keys": ["status", "cleanup"],
        },
        "tasks.roi.list": {
            "method": "GET",
            "path": "/api/tasks/{task_id}/roi",
            "response_keys": ["task_id", "items", "count"],
        },
        "tasks.roi.create": {
            "method": "POST",
            "path": "/api/tasks/{task_id}/roi",
            "request": {
                "roi_name": "必填，用户可用自然语言命名，例如 价格监控",
                "region": "必填，region_id/name/x/y/w/h/coordinate_space",
                "enabled": "可选，默认 true",
                "roi_task_id": "可选，不传则按父任务和 ROI 名称生成",
            },
            "response_keys": ["status", "roi", "task", "task_paths"],
        },
        "tasks.roi.update": {
            "method": "PATCH",
            "path": "/api/tasks/{task_id}/roi/{roi_task_id}",
            "request": {"roi_name": "可选", "region": "可选", "enabled": "可选"},
            "response_keys": ["status", "roi", "task", "task_paths"],
        },
        "tasks.roi.delete": {
            "method": "DELETE",
            "path": "/api/tasks/{task_id}/roi/{roi_task_id}",
            "response_keys": ["status", "task_id", "parent_task_id", "deleted"],
        },
        "tasks.alert": {
            "method": "GET/POST",
            "path": "/api/tasks/{task_id}/alert",
            "request": {
                "enabled": "可选",
                "webhook_url": "可选，企业微信机器人 webhook",
                "message_title": "可选",
                "message_template": "可选，可用 {task_id}/{summary}",
                "cooldown_sec": "可选",
                "dedupe_window_sec": "可选",
            },
            "response_keys": ["status", "alert", "task", "task_paths"],
        },
        "agent.observe_live": {
            "method": "GET",
            "path": "/api/agent/observe-live",
            "query": {"task_id": "可选", "minutes": "1-20160", "limit": "1-100"},
            "response_keys": ["schema_version", "task_id", "observed_at", "time_scope", "status", "screenshot", "recent_events", "memory_items", "alerts", "logs", "cleanup_reminder", "region_binding_context", "vision_status", "evidence_status", "agent_hints"],
        },
        "agent.activity": {
            "method": "GET",
            "path": "/api/activity",
            "query": {"task_id": "可选", "minutes": "1-20160"},
            "response_keys": ["schema_version", "task_id", "observed_at", "time_scope", "primary_summary", "timeline", "keywords", "confidence", "has_screenshot_evidence", "needs_detail_followup"],
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
        "snapshot.fresh": {
            "method": "POST",
            "path": "/api/tasks/{task_id}/screenshot/fresh",
            "request": {"task_id": "必填；按指定任务目标即时采一张最新截图，不要求任务正在运行，也不切换当前任务"},
            "response_keys": ["task_id", "path", "image_width", "image_height", "regions", "target", "capture_target", "capture_status", "capture_message", "capture_timestamp"],
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
            "query": {"task_id": "可选", "minutes": "1-20160", "limit": "1-100", "keyword": "可选", "compact": "可选，true 时过滤 OCR blocks/bbox/evidence_refs 等重字段"},
            "response_keys": ["task_id", "minutes", "limit", "compact", "count", "items"],
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
        "control.sampling": {
            "method": "POST",
            "path": "/api/control/sampling",
            "request": {"task_id": "可选；不传则当前任务", "interval_ms": "500-3600000，任务截图/OCR/变化检测统一采样间隔", "quality": "可选", "save_ocr_screenshots": "可选"},
            "response_keys": ["status", "sampling"],
        },
        "control.settings": {
            "method": "POST",
            "path": "/api/control/settings",
            "request": {
                "capture_screen_when_display_sleep": "可选",
                "cleanup_reminder_days": "可选",
                "latest_frame_hotkey": "可选，例如 cmd+shift+9；留空关闭",
                "monitor_context_hotkey": "可选，例如 cmd+shift+8；留空关闭",
                "monitor_context_prompt": "可选，默认 Ayes context mode，最多 64 字符",
            },
            "response_keys": ["status", "settings"],
        },
        "vision.models": {
            "method": "GET",
            "path": "/api/vision/models",
            "response_keys": ["available", "binary_available", "service_reachable", "default_model", "default_model_installed", "default_selected_model", "items[].is_vision_model", "recommended_action"],
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
