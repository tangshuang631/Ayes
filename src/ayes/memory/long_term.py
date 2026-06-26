"""Long-term summary generation."""

from __future__ import annotations

from typing import Iterable, List
from uuid import uuid4

from ayes.events.models import TimelineEvent


def build_long_term_summary(*, task_id: str, events: Iterable[TimelineEvent]) -> dict:
    collected: List[TimelineEvent] = list(events)
    if not collected:
        raise ValueError("无法对空事件列表生成长期摘要")
    collected = sorted(collected, key=lambda item: item.timestamp)
    texts = [event.summary for event in collected if event.summary][:5]
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
