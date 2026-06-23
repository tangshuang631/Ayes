from ayes.events.factory import build_event
from ayes.events.models import EventTarget, Observability, WatchMatch


def test_build_event_sets_defaults_and_ids() -> None:
    event = build_event(
        task_id="task_1",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=1719123456.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.91,
        target=EventTarget(type="window", process_name="TargetApp", window_id=12),
        observability=Observability(
            has_metadata=True,
            has_pixels=True,
            is_onscreen=True,
            is_observable_candidate=True,
            capture_status="ok",
        ),
        summary="检测到价格变化",
        watch_match=WatchMatch(matched=True, score=0.88, matched_rule="price_lt_299"),
    )
    assert event.event_id.startswith("evt_")
    assert event.watch_match.matched_rule == "price_lt_299"
    assert event.summary == "检测到价格变化"
