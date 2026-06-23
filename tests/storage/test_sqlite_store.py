from ayes.events.factory import build_event
from ayes.events.models import EventTarget, Observability
from ayes.logs.models import LogEntry
from ayes.storage.sqlite_store import SQLiteStore


def test_sqlite_store_persists_events_and_logs(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))
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
        summary="测试事件",
    )
    store.insert_event(event)
    store.insert_log(
        LogEntry(
            log_id="log_1",
            timestamp=100.0,
            category="watch",
            level="info",
            message="测试日志",
            task_id="task_1",
        )
    )
    assert store.list_events(task_id="task_1", limit=10)[0]["event_id"] == event.event_id
    assert store.list_logs(task_id="task_1", limit=10)[0]["message"] == "测试日志"
