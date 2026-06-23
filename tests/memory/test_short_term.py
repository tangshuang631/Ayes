from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, Observability
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
