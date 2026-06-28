from fastapi.testclient import TestClient
import time
from uuid import uuid4

from ayes.api.server import app, state
from ayes.app.state import AppState
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


def test_clear_runner_does_not_flush_recent_short_memory_to_long_term() -> None:
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
    assert first_items == []
    state.clear_runner()
    second_items = state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20)
    assert second_items == []


def test_long_term_summary_waits_until_short_facts_are_at_least_three_days_old() -> None:
    task_id = f"task_long_term_periodic_{uuid4().hex}"
    local_state = AppState()
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
    runner = local_state.set_runner(spec, task_id=task_id)
    now = time.time()
    short_path = local_state.memory_file_store.short_event_path(task_id=task_id, timestamp=now)
    short_path.parent.mkdir(parents=True, exist_ok=True)
    short_path.write_text(
        f'{{"time":"{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60))}","info":"页面：今天的新内容","code":"scn=pg|reg=main|k1=今天的新内容"}}\n',
        encoding="utf-8",
    )
    runner.run_once(now=now)
    local_state._flush_long_term_summary(force=True)
    assert local_state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20) == []

    old_time = now - (3 * 24 * 60 * 60) - 60
    old_path = local_state.memory_file_store.short_event_path(task_id=task_id, timestamp=old_time)
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(
        f'{{"time":"{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(old_time))}","info":"页面：三天前可沉淀内容","code":"scn=pg|reg=main|k1=三天前可沉淀内容"}}\n',
        encoding="utf-8",
    )
    local_state._flush_long_term_summary(force=True)
    items = local_state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20)
    assert len(items) == 1
    assert "三天前可沉淀内容" in items[0]["summary"]
    assert "今天的新内容" not in items[0]["summary"]
    local_state.clear_runner()


def test_flush_long_term_summary_prefers_short_fact_rows_over_raw_event_noise() -> None:
    local_state = AppState()
    task_id = f"task_long_term_from_short_{uuid4().hex}"
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
    runner = local_state.set_runner(spec, task_id=task_id)
    now = time.time()
    old_time = now - (3 * 24 * 60 * 60) - 60
    short_path = local_state.memory_file_store.short_event_path(task_id=task_id, timestamp=now)
    short_path.parent.mkdir(parents=True, exist_ok=True)
    short_path.write_text(
        f'{{"time":"{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(old_time - 30))}","info":"页面：Apifox 登录页","code":"scn=pg|reg=main|k1=Apifox|k2=登录页"}}\n'
        f'{{"time":"{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(old_time - 10))}","info":"表单：手机号输入框，确认按钮","code":"scn=frm|reg=main|k1=手机号输入框|k2=确认按钮"}}\n',
        encoding="utf-8",
    )
    runner.run_once(now=now)
    local_state._flush_long_term_summary(force=True)
    items = local_state.sqlite_store.list_long_term_summaries(task_id=task_id, limit=20)
    assert items
    assert "Apifox 登录页" in items[-1]["summary"]
    assert "手机号输入框" in items[-1]["summary"]
    local_state.clear_runner()


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
