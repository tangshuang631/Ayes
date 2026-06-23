"""Long-term summary generation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, List
from uuid import uuid4

from ayes.events.models import TimelineEvent


def build_long_term_summary(*, task_id: str, events: Iterable[TimelineEvent]) -> dict:
    collected: List[TimelineEvent] = list(events)
    if not collected:
        raise ValueError("无法对空事件列表生成长期摘要")
    collected = sorted(collected, key=lambda item: item.timestamp)
    texts = [event.summary for event in collected if event.summary][:5]
    return {
        "summary_id": f"lts_{uuid4().hex}",
        "task_id": task_id,
        "window_start": collected[0].timestamp,
        "window_end": collected[-1].timestamp,
        "summary": "；".join(texts) if texts else "该时间段内无高价值摘要",
        "event_count": len(collected),
        "event_ids": [event.event_id for event in collected],
    }
