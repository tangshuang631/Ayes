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


def test_sqlite_store_filters_events_and_logs_by_timestamp_and_keyword(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))
    early = build_event(
        task_id="task_2",
        spec_version="1.0",
        task_mode="observe",
        timestamp=10.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="普通变化",
    )
    later = build_event(
        task_id="task_2",
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
    store.insert_event(early)
    store.insert_event(later)
    store.insert_log(LogEntry(log_id="log_early", timestamp=10.0, category="system", level="info", message="旧日志", task_id="task_2"))
    store.insert_log(LogEntry(log_id="log_later", timestamp=100.0, category="api", level="info", message="新日志", task_id="task_2"))

    assert len(store.list_events(task_id="task_2", since_timestamp=50.0, limit=10)) == 1
    matched = store.query_events(task_id="task_2", minutes=1, keyword="299", now=120.0, limit=10)
    assert len(matched) == 1
    assert "299" in matched[0]["summary"]
    logs = store.list_logs(task_id="task_2", since_timestamp=50.0, category="api", limit=10)
    assert len(logs) == 1
    assert logs[0]["message"] == "新日志"
