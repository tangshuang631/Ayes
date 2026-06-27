from fastapi.testclient import TestClient
from uuid import uuid4

from ayes.api.server import app, state
from ayes.config.models import WatchSpec
from ayes.storage.sqlite_store import SQLiteStore


client = TestClient(app)


def test_long_term_timeline_endpoint_returns_items_key() -> None:
    task_id = f"task_long_term_test_{uuid4().hex}"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id=task_id)
    runner.run_once()
    state.clear_runner()
    response = client.get("/api/timeline/long-term", params={"task_id": task_id})
    assert response.status_code == 200
    assert "items" in response.json()


def test_long_term_timeline_endpoint_supports_hours_scope() -> None:
    task_id = f"task_long_term_hours_{uuid4().hex}"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id=task_id)
    runner.run_once()
    state.clear_runner()
    response = client.get("/api/timeline/long-term", params={"task_id": task_id, "hours": 24})
    assert response.status_code == 200
    payload = response.json()
    assert payload["hours"] == 24
    assert "items" in payload


def test_clear_runner_flushes_only_pending_long_term_events() -> None:
    task_id = f"task_long_term_flush_{uuid4().hex}"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
            "memory": {
                "long_term": {
                    "enabled": True,
                    "retain_hours": 24,
                    "max_retain_hours": 72,
                    "summary_interval_minutes": 5,
                }
            },
        }
    )
    runner = state.set_runner(spec, task_id=task_id)
    runner.run_once(now=100.0)
    state._flush_long_term_summary(force=False)
    first_items = state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20)
    assert len(first_items) == 1
    state.clear_runner()
    second_items = state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20)
    assert len(second_items) == 1


def test_periodic_long_term_summary_uses_summary_interval_minutes() -> None:
    task_id = f"task_long_term_periodic_{uuid4().hex}"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
            "memory": {
                "long_term": {
                    "enabled": True,
                    "retain_hours": 24,
                    "max_retain_hours": 72,
                    "summary_interval_minutes": 1,
                }
            },
        }
    )
    runner = state.set_runner(spec, task_id=task_id)
    runner.run_once(now=100.0)
    state._flush_long_term_summary(force=False)
    runner.run_once(now=170.0)
    state._flush_long_term_summary(force=False)
    items = state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20)
    assert len(items) >= 2
    state.clear_runner()


def test_sqlite_store_deletes_expired_long_term_summaries(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "ayes.db"))
    store.insert_long_term_summary(
        summary_id="lts_old",
        task_id="task_cleanup",
        window_start=100.0,
        window_end=120.0,
        summary="old",
        payload={"summary_id": "lts_old", "task_id": "task_cleanup", "window_start": 100.0, "window_end": 120.0, "summary": "old", "event_count": 1, "event_ids": ["evt_old"]},
    )
    store.insert_long_term_summary(
        summary_id="lts_new",
        task_id="task_cleanup",
        window_start=7000.0,
        window_end=7200.0,
        summary="new",
        payload={"summary_id": "lts_new", "task_id": "task_cleanup", "window_start": 7000.0, "window_end": 7200.0, "summary": "new", "event_count": 1, "event_ids": ["evt_new"]},
    )

    removed = store.delete_long_term_summaries_before(task_id="task_cleanup", cutoff_timestamp=3600.0)

    assert removed == 1
    items = store.list_long_term_summaries(task_id="task_cleanup", limit=20)
    assert [item["summary_id"] for item in items] == ["lts_new"]


def test_clear_runner_prunes_expired_long_term_summaries_by_task_policy_and_logs_it() -> None:
    task_id = f"task_long_term_prune_{uuid4().hex}"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
            "memory": {
                "long_term": {
                    "enabled": True,
                    "retain_days": 1,
                    "max_retain_hours": 720,
                    "summary_interval_minutes": 5,
                }
            },
        }
    )
    state.sqlite_store.insert_long_term_summary(
        summary_id=f"lts_expired_{uuid4().hex}",
        task_id=task_id,
        window_start=10.0,
        window_end=20.0,
        summary="expired",
        payload={"summary_id": "expired", "task_id": task_id, "window_start": 10.0, "window_end": 20.0, "summary": "expired", "event_count": 1, "event_ids": ["evt_expired"]},
    )
    runner = state.set_runner(spec, task_id=task_id)
    runner.run_once(now=2 * 24 * 60 * 60)

    state.clear_runner()

    items = state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20)
    assert all(item["window_end"] >= 24 * 60 * 60 for item in items)
    logs = state.sqlite_store.list_logs(task_id=task_id, category="watch", limit=50)
    assert any("已清理过期长期摘要" in item["message"] for item in logs)
