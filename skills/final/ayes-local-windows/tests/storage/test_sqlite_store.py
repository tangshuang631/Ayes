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


def test_sqlite_store_vacuum_returns_reclaimed_size_payload(tmp_path) -> None:
    db_path = tmp_path / "ayes.db"
    store = SQLiteStore(db_path=str(db_path))
    store.insert_log(
        LogEntry(
            log_id="log_large",
            timestamp=100.0,
            category="system",
            level="info",
            message="x" * 10000,
            task_id="task_vacuum",
        )
    )
    store.delete_task_data("task_vacuum")

    payload = store.vacuum()

    assert payload["db_path"] == str(db_path)
    assert payload["before_bytes"] >= payload["after_bytes"]
    assert payload["reclaimed_bytes"] == payload["before_bytes"] - payload["after_bytes"]


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


def test_sqlite_store_persists_task_memory_policy(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))

    payload = store.upsert_task_memory_policy(
        task_id="task_policy",
        short_term_retain_days=9,
        long_term_retain_days=21,
        disable_auto_cleanup=True,
    )

    assert payload["task_id"] == "task_policy"
    assert payload["short_term_retain_days"] == 9
    assert payload["long_term_retain_days"] == 21
    assert payload["disable_auto_cleanup"] is True
    assert payload["memory_compact_every_n_events"] == 500
    assert "/runtime/tasks/" in payload["memory_dir"]
    assert payload["memory_dir"].endswith("/task_policy/memory")
    assert store.get_task_memory_policy("task_policy") == payload


def test_sqlite_store_persists_memory_compaction_threshold(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))

    payload = store.upsert_task_memory_policy(
        task_id="task_policy",
        short_term_retain_days=9,
        long_term_retain_days=21,
        disable_auto_cleanup=False,
        memory_compact_every_n_events=750,
    )

    assert payload["memory_compact_every_n_events"] == 750
    assert store.get_task_memory_policy("task_policy")["memory_compact_every_n_events"] == 750


def test_sqlite_store_persists_roi_task_metadata(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))

    store.upsert_task(
        task_id="2026-06-26_process_monitor_Chrome",
        mode="observe",
        target={"type": "process", "process_name": "Chrome"},
        spec={
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "roi": {
                "parent_task_id": "2026-06-26_process_monitor_Chrome",
                "roi_name": "价格监控",
            },
        },
        created_at=100.0,
    )

    task = store.get_task("2026-06-26_process_monitor_Chrome")
    assert task is not None
    assert task["spec"]["roi"]["parent_task_id"] == "2026-06-26_process_monitor_Chrome"
    assert task["spec"]["roi"]["roi_name"] == "价格监控"


def test_sqlite_store_rejects_task_memory_policy_over_caps(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))

    try:
        store.upsert_task_memory_policy(
            task_id="task_policy",
            short_term_retain_days=15,
            long_term_retain_days=14,
            disable_auto_cleanup=False,
        )
    except ValueError as exc:
        assert "short_term_retain_days" in str(exc)
    else:
        raise AssertionError("expected short_term_retain_days cap failure")

    try:
        store.upsert_task_memory_policy(
            task_id="task_policy",
            short_term_retain_days=7,
            long_term_retain_days=31,
            disable_auto_cleanup=False,
        )
    except ValueError as exc:
        assert "long_term_retain_days" in str(exc)
    else:
        raise AssertionError("expected long_term_retain_days cap failure")


def test_sqlite_store_deletes_expired_events_by_task(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "ayes.db"))
    old_event = build_event(
        task_id="task_cleanup_events",
        spec_version="1.0",
        task_mode="observe",
        timestamp=10.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="旧事件",
    )
    new_event = build_event(
        task_id="task_cleanup_events",
        spec_version="1.0",
        task_mode="observe",
        timestamp=200.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="新事件",
    )
    store.insert_event(old_event)
    store.insert_event(new_event)

    removed = store.delete_events_before(task_id="task_cleanup_events", cutoff_timestamp=100.0)

    assert removed == 1
    items = store.list_events(task_id="task_cleanup_events", limit=10)
    assert [item["summary"] for item in items] == ["新事件"]
