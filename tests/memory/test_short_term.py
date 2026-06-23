from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, Observability, WatchMatch
from ayes.memory.short_term import ShortTermMemoryStore


def test_short_term_query_filters_by_time_and_keyword() -> None:
    store = ShortTermMemoryStore(retain_seconds=900)
    event = build_event(
        task_id="task_1",
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="价格低于 299",
    )
    event = event.__class__(**{**event.__dict__, "text": EventText(ocr_text="价格低于 299", normalized_text="价格低于 299")})
    store.append(event)
    result = store.query(now=200.0, minutes=5, keyword="299")
    assert len(result.matched_events) == 1
    assert "299" in result.answer


def test_short_term_query_answers_numeric_threshold_question_from_structured_match() -> None:
    store = ShortTermMemoryStore(retain_seconds=900)
    event = build_event(
        task_id="task_numeric",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=100.0,
        source="semantic_match",
        event_type="semantic_match",
        priority="high",
        confidence=1.0,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="命中数值阈值规则: price lt 299.0，当前识别值 199",
        watch_match=WatchMatch(
            matched=True,
            score=1.0,
            matched_rule="numeric_threshold:price:lt:299.0",
            matched_value=199.0,
            matched_unit="cny",
            matched_field="price",
        ),
    )
    event = event.__class__(**{**event.__dict__, "text": EventText(ocr_text="当前价格 ¥199", normalized_text="当前价格 199")})
    store.append(event)
    result = store.query(now=200.0, minutes=5, question="最近5分钟价格有没有低于299")
    assert len(result.matched_events) == 1
    assert "低于 299" in result.answer
    assert "199.0" in result.answer
