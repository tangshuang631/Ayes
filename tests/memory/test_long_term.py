from ayes.events.factory import build_event
from dataclasses import replace

from ayes.events.models import EventTarget, EventText, EventVisual, Observability
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


def test_build_long_term_summary_filters_noisy_ocr_when_readable_fact_exists() -> None:
    noisy = build_event(
        task_id="task_1",
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.55,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="02-05 55 96\uffff rf18iO 03-16 A<S>J 6-14 PKI *# .WF%",
    )
    noisy = replace(
        noisy,
        text=EventText(ocr_text="02-05 55 96\uffff rf18iO 03-16 A<S>J 6-14 PKI *# .WF%", normalized_text=""),
    )
    readable = build_event(
        task_id="task_1",
        spec_version="1.0",
        task_mode="observe",
        timestamp=120.0,
        source="capture",
        event_type="target_window_changed",
        priority="medium",
        confidence=0.96,
        target=EventTarget(type="process", process_name="哔哩哔哩", window_title="布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】"),
        observability=Observability(True, True, True, True, "ok"),
        summary="进程 哔哩哔哩 代表窗口切换: 哔哩哔哩 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
    )

    summary = build_long_term_summary(task_id="task_1", events=[noisy, readable])

    assert "布欧怎么出现的" in summary["summary"]
    assert "话说龙珠" in summary["summary"]
    assert "rf18iO" not in summary["summary"]
    assert "PKI" not in summary["summary"]
