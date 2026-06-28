"""Long-term summary generation."""

from __future__ import annotations

from typing import Iterable, List
from uuid import uuid4

from ayes.events.models import TimelineEvent
from ayes.memory.content_signal import is_memory_worthy_event, rank_memory_events, summarize_memory_event
from ayes.memory.search_index import _parse_code_fields


def build_long_term_summary(*, task_id: str, events: Iterable[TimelineEvent]) -> dict:
    collected: List[TimelineEvent] = list(events)
    if not collected:
        raise ValueError("无法对空事件列表生成长期摘要")
    collected = sorted(collected, key=lambda item: item.timestamp)
    ranked = rank_memory_events([event for event in collected if _is_user_memory_event(event) and is_memory_worthy_event(event)], limit=5)
    texts = [_trim_summary(summarize_memory_event(event)) for event in ranked if _trim_summary(summarize_memory_event(event))]
    snapshot = _build_main_content_snapshot(collected)
    return {
        "summary_id": f"lts_{uuid4().hex}",
        "task_id": task_id,
        "window_start": collected[0].timestamp,
        "window_end": collected[-1].timestamp,
        "summary": "；".join(texts) if texts else "该时间段内无高价值摘要",
        "event_count": len(collected),
        "event_ids": [event.event_id for event in collected],
        "main_content_snapshot": snapshot,
    }


def build_long_term_summary_from_short_rows(*, task_id: str, rows: List[dict], window_start: float, window_end: float) -> dict:
    normalized_rows = [row for row in rows if str(row.get("info") or "").strip()]
    if not normalized_rows:
        raise ValueError("无法对空短期事实列表生成长期摘要")
    unique_texts: list[str] = []
    for row in normalized_rows:
        info = " ".join(str(row.get("info") or "").split())
        if not info or info in unique_texts:
            continue
        unique_texts.append(info)
    snapshot = _build_snapshot_from_short_rows(normalized_rows)
    return {
        "summary_id": f"lts_{uuid4().hex}",
        "task_id": task_id,
        "window_start": window_start,
        "window_end": window_end,
        "summary": "；".join(unique_texts[:5]) if unique_texts else "该时间段内无高价值摘要",
        "event_count": len(normalized_rows),
        "event_ids": [],
        "main_content_snapshot": snapshot,
    }


def _is_user_memory_event(event: TimelineEvent) -> bool:
    summary = str(event.summary or "").strip()
    if event.event_type in {"vision_skipped", "vision_triggered"}:
        return False
    if summary.startswith("视觉增强已跳过") or summary.startswith("视觉增强已触发"):
        return False
    if summary.startswith("OCR vision |"):
        return False
    return True


def _trim_summary(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > 180:
        return text[:177] + "..."
    return text


def _build_main_content_snapshot(events: List[TimelineEvent]) -> dict:
    observations = []
    for event in events:
        observation = (event.visual.attributes or {}).get("structured_observation") or {}
        if not observation:
            continue
        attention = observation.get("attention") or {}
        observations.append((event, observation, attention))
    primary = [item for item in observations if bool(item[2].get("primary"))]
    candidates = primary or observations
    if not candidates:
        latest = events[-1]
        return {
            "timestamp": latest.timestamp,
            "event_id": latest.event_id,
            "text": latest.text.ocr_text or latest.summary or "",
            "visual_summary": latest.visual.summary or "",
            "region_id": latest.region.region_id,
            "region_name": latest.region.name,
            "attention_role": "",
            "source": latest.source,
        }
    event, observation, attention = candidates[-1]
    text = ((observation.get("text") or {}).get("full_text") or event.text.ocr_text or "").strip()
    visual = observation.get("visual") or {}
    region = observation.get("region") or {}
    return {
        "timestamp": event.timestamp,
        "event_id": event.event_id,
        "text": text,
        "visual_summary": str(visual.get("summary") or event.visual.summary or "").strip(),
        "region_id": str(region.get("region_id") or event.region.region_id or ""),
        "region_name": str(region.get("name") or event.region.name or ""),
        "attention_role": str(attention.get("role") or ""),
        "attention_weight": attention.get("weight"),
        "source": str(observation.get("source") or event.source or ""),
    }


def _build_snapshot_from_short_rows(rows: List[dict]) -> dict:
    latest = rows[-1]
    code_fields = _parse_code_fields(str(latest.get("code") or ""))
    return {
        "timestamp": latest.get("timestamp"),
        "event_id": "",
        "text": str(latest.get("info") or ""),
        "visual_summary": "",
        "region_id": str(latest.get("region") or ""),
        "region_name": str(latest.get("region") or ""),
        "attention_role": "main_content" if str(code_fields.get("region_slot") or "") == "main" else "",
        "attention_weight": 1.0 if str(code_fields.get("region_slot") or "") == "main" else 0.0,
        "source": "short_term_file",
    }
