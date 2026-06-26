import json

from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability
from ayes.memory.file_store import TaskMemoryFileStore


def test_task_memory_file_store_writes_short_events_by_task_and_date(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页",
    )

    path = store.append_short_event(event)

    assert path == tmp_path / "tasks" / "2026-10-25" / "task_browser" / "memory" / "short" / "2026-10-25-task_browser-details.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload == {"time": "2026-10-25T16:00:00Z", "info": "Apifox 登录页"}


def test_task_memory_file_store_writes_compact_short_events_without_heavy_ocr_fields(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "text": EventText(
                ocr_text="Apifox 登录页",
                normalized_text="apifox 登录页",
                blocks=[
                        EventTextBlock(
                            text="Apifox",
                            confidence=0.9,
                            bbox=[1, 2, 3, 4],
                            rect={"x": 1, "y": 2, "w": 3, "h": 4},
                            rect_norm={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                    )
                ],
            ),
            "visual": EventVisual(attributes={"structured_observation": {"heavy": "payload"}, "text_quality_score": 0.88}),
            "evidence_refs": ["/tmp/heavy.png"],
        }
    )

    path = store.append_short_event(event)

    encoded = path.read_text(encoding="utf-8")
    payload = json.loads(encoded.splitlines()[0])
    assert payload == {"time": "2026-10-25T16:00:00Z", "info": "Apifox 登录页"}
    assert "blocks" not in encoded
    assert "bbox" not in encoded
    assert "rect_norm" not in encoded
    assert "evidence_refs" not in encoded
    assert "structured_observation" not in encoded
    assert "confidence" not in encoded
    assert "task_id" not in encoded


def test_task_memory_file_store_deletes_expired_memory_files(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    old_short = store.short_event_path(task_id="task_browser", timestamp=100.0)
    new_short = store.short_event_path(task_id="task_browser", timestamp=86400.0)
    old_long = store.long_summary_path(task_id="task_browser", timestamp=100.0)
    new_long = store.long_summary_path(task_id="task_browser", timestamp=86400.0)
    for path in [old_short, new_short, old_long, new_long]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    result = store.delete_expired_files(task_id="task_browser", short_cutoff=43200.0, long_cutoff=43200.0)

    assert result["deleted_short_files"] == 1
    assert result["deleted_long_files"] == 1
    assert not old_short.exists()
    assert new_short.exists()
    assert not old_long.exists()
    assert new_long.exists()


def test_task_memory_file_store_writes_long_summaries_by_task_and_date(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)

    path = store.append_long_summary(
        {
            "summary_id": "lts_1",
            "task_id": "task_browser",
            "window_start": 1792944000.0,
            "window_end": 1792944300.0,
            "summary": "Chrome 中出现 Apifox 登录页",
            "event_count": 3,
            "event_ids": ["evt_1"],
        }
    )

    assert path == tmp_path / "tasks" / "2026-10-25" / "task_browser" / "memory" / "long" / "2026-10-25-task_browser-summary.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload == {
        "from": "2026-10-25T16:00:00Z",
        "to": "2026-10-25T16:05:00Z",
        "info": "Chrome 中出现 Apifox 登录页",
    }


def test_task_memory_file_store_filters_internal_long_summary_parts(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)

    path = store.append_long_summary(
        {
            "summary_id": "lts_1",
            "task_id": "task_browser",
            "window_start": 1792944000.0,
            "window_end": 1792944300.0,
            "summary": "视觉增强已触发: ocr_sparse；Chrome 中出现 Apifox 登录页；视觉增强已跳过: non_primary_attention_region",
        }
    )

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "Chrome 中出现 Apifox 登录页"
