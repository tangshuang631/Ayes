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


def test_sqlite_store_persists_cleanup_reminder_state(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))

    store.upsert_cleanup_reminder(
        enabled=True,
        last_prompt_at=100.0,
        snoozed_until=200.0,
        suppress_forever=False,
        data_dir="/tmp/runtime/archive",
        next_check_after_days=7,
    )

    payload = store.get_cleanup_reminder()
    assert payload is not None
    assert payload["enabled"] is True
    assert payload["last_prompt_at"] == 100.0
    assert payload["snoozed_until"] == 200.0
    assert payload["suppress_forever"] is False
    assert payload["data_dir"] == "/tmp/runtime/archive"
    assert payload["next_check_after_days"] == 7


def test_sqlite_store_persists_vision_enhancement_state(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))

    store.upsert_vision_enhancement_settings(
        enabled=True,
        provider="ollama",
        model="qwen2.5vl:7b",
        auto_use_when_available=True,
    )

    payload = store.get_vision_enhancement_settings()
    assert payload is not None
    assert payload["enabled"] is True
    assert payload["provider"] == "ollama"
    assert payload["model"] == "qwen2.5vl:7b"
    assert payload["auto_use_when_available"] is True


def test_sqlite_store_lists_and_deletes_task_data_by_task_id(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))
    store.upsert_task(
        task_id="2026-06-25__price_watch",
        mode="observe",
        target={"type": "screen", "screen_id": 1},
        spec={"spec_version": "1.0", "mode": "observe", "target": {"type": "screen", "screen_id": 1}},
        created_at=100.0,
    )
    store.upsert_task(
        task_id="2026-06-25__stock_watch",
        mode="triggered",
        target={"type": "process", "process_name": "Safari"},
        spec={"spec_version": "1.0", "mode": "triggered", "target": {"type": "process", "process_name": "Safari"}},
        created_at=200.0,
    )
    event = build_event(
        task_id="2026-06-25__price_watch",
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="价格 299",
    )
    store.insert_event(event)
    store.insert_log(LogEntry(log_id="log_price", timestamp=100.0, category="watch", level="info", message="price", task_id="2026-06-25__price_watch"))
    store.insert_long_term_summary(
        summary_id="sum_price",
        task_id="2026-06-25__price_watch",
        window_start=90.0,
        window_end=100.0,
        summary="价格观察摘要",
        payload={"summary_id": "sum_price", "task_id": "2026-06-25__price_watch", "summary": "价格观察摘要", "window_start": 90.0, "window_end": 100.0, "event_ids": [event.event_id]},
    )

    tasks = store.list_tasks(limit=10)
    assert tasks[0]["task_id"] == "2026-06-25__stock_watch"
    assert tasks[1]["task_id"] == "2026-06-25__price_watch"

    deleted = store.delete_task_data("2026-06-25__price_watch")
    assert deleted["tasks"] == 1
    assert deleted["events"] == 1
    assert deleted["logs"] == 1
    assert deleted["long_term_summaries"] == 1
    assert store.get_task("2026-06-25__price_watch") is None
