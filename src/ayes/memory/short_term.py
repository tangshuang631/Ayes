"""Short-term in-memory event store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from ayes.events.models import TimelineEvent


@dataclass(frozen=True)
class QueryResult:
    answer: str
    confidence: float
    matched_events: List[TimelineEvent]
    memory_layers_used: List[str]


class ShortTermMemoryStore:
    def __init__(self, *, retain_seconds: int = 15 * 60) -> None:
        self.retain_seconds = retain_seconds
        self._events: List[TimelineEvent] = []

    def append(self, event: TimelineEvent) -> None:
        self._events.append(event)
        self.prune(now=event.timestamp)

    def prune(self, *, now: float) -> None:
        threshold = now - self.retain_seconds
        self._events = [event for event in self._events if event.timestamp >= threshold]

    def list_events(self) -> List[TimelineEvent]:
        return list(self._events)

    def query(self, *, now: float, minutes: int, keyword: Optional[str] = None) -> QueryResult:
        threshold = now - (minutes * 60)
        matched = [event for event in self._events if event.timestamp >= threshold]
        if keyword:
            lowered = keyword.lower()
            matched = [
                event for event in matched
                if lowered in event.summary.lower()
                or lowered in event.text.ocr_text.lower()
                or lowered in event.text.normalized_text.lower()
                or any(lowered in tag.lower() for tag in event.tags)
            ]
        if not matched:
            return QueryResult(
                answer=f"最近 {minutes} 分钟内未发现相关事件。",
                confidence=0.72,
                matched_events=[],
                memory_layers_used=["short_term"],
            )
        matched = sorted(matched, key=lambda item: item.timestamp)
        answer = "；".join(
            f"{event.summary or event.event_type}@{int(event.timestamp)}"
            for event in matched[-5:]
        )
        return QueryResult(
            answer=answer,
            confidence=0.86,
            matched_events=matched,
            memory_layers_used=["short_term"],
        )
