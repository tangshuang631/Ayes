"""Event creation helpers."""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from ayes.events.models import EventTarget, Observability, TimelineEvent, WatchMatch


def build_event(
    *,
    task_id: str,
    spec_version: str,
    task_mode: str,
    timestamp: float,
    source: str,
    event_type: str,
    priority: str,
    confidence: float,
    target: EventTarget,
    observability: Observability,
    summary: str = "",
    event_id: Optional[str] = None,
    watch_match: Optional[WatchMatch] = None,
) -> TimelineEvent:
    return TimelineEvent(
        event_id=event_id or f"evt_{uuid4().hex}",
        task_id=task_id,
        spec_version=spec_version,
        task_mode=task_mode,
        timestamp=timestamp,
        source=source,
        event_type=event_type,
        priority=priority,
        confidence=confidence,
        target=target,
        observability=observability,
        summary=summary,
        watch_match=watch_match or WatchMatch(),
    )
