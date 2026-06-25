import json

from ayes.events.factory import build_event
from ayes.events.models import EventTarget, Observability
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

    assert path == tmp_path / "memory" / "task_browser" / "short" / "2026-10-25-task_browser-details.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload["task_id"] == "task_browser"
    assert payload["summary"] == "Apifox 登录页"


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

    assert path == tmp_path / "memory" / "task_browser" / "long" / "2026-10-25-task_browser-summary.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["summary_id"] == "lts_1"
    assert payload["summary"] == "Chrome 中出现 Apifox 登录页"
