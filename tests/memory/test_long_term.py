from ayes.events.factory import build_event
from ayes.events.models import EventTarget, Observability
from ayes.memory.long_term import build_long_term_summary


def test_build_long_term_summary_aggregates_event_summaries() -> None:
    events = [
        build_event(
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
            summary="第一条",
        ),
        build_event(
            task_id="task_1",
            spec_version="1.0",
            task_mode="observe",
            timestamp=120.0,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=0.9,
            target=EventTarget(type="screen", screen_id=1),
            observability=Observability(True, True, True, True, "ok"),
            summary="第二条",
        ),
    ]
    summary = build_long_term_summary(task_id="task_1", events=events)
    assert summary["task_id"] == "task_1"
    assert "第一条" in summary["summary"]
    assert summary["event_count"] == 2
