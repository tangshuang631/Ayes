from ayes.events.factory import build_event
from dataclasses import replace

from ayes.events.models import EventTarget, EventVisual, Observability
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


def test_build_long_term_summary_extracts_primary_attention_snapshot() -> None:
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
        summary="Apifox 登录页",
    )
    event = replace(
        event,
        visual=EventVisual(
            summary="OCR fake | 字符 9 | 块 1",
            attributes={
                "structured_observation": {
                    "source": "ocr",
                    "region": {"region_id": "auto_center_main", "name": "自动主内容区"},
                    "text": {"full_text": "Apifox 登录页"},
                    "visual": {"summary": ""},
                    "attention": {
                        "region_id": "auto_center_main",
                        "role": "main_content",
                        "weight": 1.0,
                        "primary": True,
                    },
                }
            },
        ),
    )

    summary = build_long_term_summary(task_id="task_1", events=[event])

    snapshot = summary["main_content_snapshot"]
    assert snapshot["text"] == "Apifox 登录页"
    assert snapshot["region_id"] == "auto_center_main"
    assert snapshot["attention_role"] == "main_content"
