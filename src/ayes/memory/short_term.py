"""Short-term in-memory event store."""

from __future__ import annotations

from dataclasses import dataclass
import re
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

    def query(self, *, now: float, minutes: int, keyword: Optional[str] = None, question: Optional[str] = None) -> QueryResult:
        threshold = now - (minutes * 60)
        matched = [event for event in self._events if event.timestamp >= threshold]
        if question:
            structured = self._query_structured_numeric_question(matched, minutes=minutes, question=question)
            if structured is not None:
                return structured
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

    def _query_structured_numeric_question(
        self,
        events: List[TimelineEvent],
        *,
        minutes: int,
        question: str,
    ) -> Optional[QueryResult]:
        lowered = question.lower().strip()
        if "最低" in lowered or "最高" in lowered:
            return self._query_numeric_extreme(events, minutes=minutes, question=lowered)
        operator = None
        if "低于" in lowered or "小于" in lowered:
            operator = "lt"
        elif "高于" in lowered or "大于" in lowered:
            operator = "gt"
        if operator is None:
            return None
        threshold_match = re.search(rf"{operator_label(operator)}\s*(\d+(?:\.\d+)?)", lowered)
        if threshold_match is None:
            threshold_match = re.search(r"(\d+(?:\.\d+)?)", lowered)
        if threshold_match is None:
            return None
        threshold = float(threshold_match.group(1))
        field = ""
        if "价格" in lowered or "price" in lowered:
            field = "price"
        elif "库存" in lowered or "stock" in lowered:
            field = "stock"
        operator_token = f"{operator_label(operator)}{threshold:g}"
        operator_token_spaced = f"{operator_label(operator)} {threshold:g}"
        matched = [
            event
            for event in events
            if event.watch_match.matched
            and event.watch_match.matched_rule.startswith("numeric_threshold:")
            and (not field or event.watch_match.matched_field == field)
            and event.watch_match.matched_value is not None
            and (
                (operator == "lt" and event.watch_match.matched_value < threshold)
                or (operator == "gt" and event.watch_match.matched_value > threshold)
                or operator_token in (event.summary or "")
                or operator_token_spaced in (event.summary or "")
            )
        ]
        if not matched:
            return QueryResult(
                answer=f"最近 {minutes} 分钟内未发现满足该数值条件的事件。",
                confidence=0.78,
                matched_events=[],
                memory_layers_used=["short_term"],
            )
        matched = sorted(matched, key=lambda item: item.timestamp)
        latest = matched[-1]
        field_label = latest.watch_match.matched_field or "目标字段"
        answer = (
            f"最近 {minutes} 分钟内，{field_label} 有命中数值条件；"
            f"识别值为 {latest.watch_match.matched_value}，"
            f"满足“{operator_label(operator)} {threshold:g}”。"
        )
        return QueryResult(
            answer=answer,
            confidence=0.9,
            matched_events=matched,
            memory_layers_used=["short_term"],
        )

    def _query_numeric_extreme(
        self,
        events: List[TimelineEvent],
        *,
        minutes: int,
        question: str,
    ) -> QueryResult:
        field = ""
        if "价格" in question or "price" in question:
            field = "price"
        elif "库存" in question or "stock" in question:
            field = "stock"
        matched = [
            event
            for event in events
            if event.watch_match.matched
            and event.watch_match.matched_rule.startswith("numeric_threshold:")
            and event.watch_match.matched_value is not None
            and (not field or event.watch_match.matched_field == field)
        ]
        if not matched:
            return QueryResult(
                answer=f"最近 {minutes} 分钟内未发现相关数值命中事件。",
                confidence=0.76,
                matched_events=[],
                memory_layers_used=["short_term"],
            )
        field_label = self._field_label(field or matched[0].watch_match.matched_field)
        if "最低" in question:
            target = min(matched, key=lambda item: item.watch_match.matched_value or 0.0)
            adjective = "最低"
        else:
            target = max(matched, key=lambda item: item.watch_match.matched_value or 0.0)
            adjective = "最高"
        answer = (
            f"最近 {minutes} 分钟内，{field_label}{adjective}值大约是 {target.watch_match.matched_value}；"
            f"对应时间约为 {int(target.timestamp)}。"
        )
        return QueryResult(
            answer=answer,
            confidence=0.9,
            matched_events=sorted(matched, key=lambda item: item.timestamp),
            memory_layers_used=["short_term"],
        )

    def _field_label(self, field: str) -> str:
        lowered = (field or "").lower()
        if lowered == "price":
            return "价格"
        if lowered == "stock":
            return "库存"
        return field or "目标字段"


def operator_label(operator: str) -> str:
    if operator == "lt":
        return "低于"
    if operator == "gt":
        return "高于"
    return operator
