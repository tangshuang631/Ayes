import time
from uuid import uuid4

from fastapi.testclient import TestClient

from ayes.api.server import app, state
from ayes.config.models import WatchSpec
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, Observability


client = TestClient(app)


def test_load_configured_persists_task_memory_policy_and_exposes_directory() -> None:
    task_id = f"task_policy_api_{uuid4().hex}"

    response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
            "memory": {
                "short_term": {"retain_days": 8},
                "long_term": {"retain_days": 22},
                "disable_auto_cleanup": True,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memory_policy"]["short_term_retain_days"] == 8
    assert payload["memory_policy"]["long_term_retain_days"] == 22
    assert payload["memory_policy"]["disable_auto_cleanup"] is True
    assert payload["memory_policy"]["memory_dir"].endswith(f"/{task_id}/memory")


def test_task_memory_policy_endpoint_updates_per_task_policy() -> None:
    task_id = f"task_policy_update_{uuid4().hex}"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    state.set_runner(spec, task_id=task_id)

    response = client.post(
        f"/api/tasks/{task_id}/memory-policy",
        json={
            "short_term_retain_days": 12,
            "long_term_retain_days": 28,
            "disable_auto_cleanup": True,
        },
    )

    assert response.status_code == 200
    policy = response.json()["memory_policy"]
    assert policy["task_id"] == task_id
    assert policy["short_term_retain_days"] == 12
    assert policy["long_term_retain_days"] == 28
    assert policy["disable_auto_cleanup"] is True


def test_apply_memory_cleanup_deletes_expired_short_and_long_memory() -> None:
    task_id = f"task_memory_cleanup_{uuid4().hex}"
    state.sqlite_store.upsert_task_memory_policy(
        task_id=task_id,
        short_term_retain_days=7,
        long_term_retain_days=14,
        disable_auto_cleanup=False,
        updated_at=100.0,
    )
    old_event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="旧短期记忆",
    )
    new_event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=(8 * 24 * 60 * 60),
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="新短期记忆",
    )
    state.sqlite_store.insert_event(old_event)
    state.sqlite_store.insert_event(new_event)
    state.sqlite_store.insert_long_term_summary(
        summary_id="lts_old_cleanup",
        task_id=task_id,
        window_start=100.0,
        window_end=100.0,
        summary="旧长期摘要",
        payload={"summary_id": "lts_old_cleanup", "task_id": task_id, "window_start": 100.0, "window_end": 100.0, "summary": "旧长期摘要", "event_count": 1, "event_ids": ["evt_old"]},
    )
    old_short_file = state.memory_file_store.short_event_path(task_id=task_id, timestamp=100.0)
    old_long_file = state.memory_file_store.long_summary_path(task_id=task_id, timestamp=100.0)
    for path in [old_short_file, old_long_file]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    result = state.apply_memory_cleanup(task_id=task_id, now=31 * 24 * 60 * 60)

    assert result["skipped"] is False
    assert result["deleted_events"] >= 1
    assert result["deleted_long_term_summaries"] >= 1
    assert result["deleted_short_files"] >= 1
    assert result["deleted_long_files"] >= 1
    assert not old_short_file.exists()
    assert not old_long_file.exists()
    assert all(item["summary"] != "旧短期记忆" for item in state.sqlite_store.list_events(task_id=task_id, limit=20))


def test_apply_memory_cleanup_skips_when_auto_cleanup_disabled() -> None:
    task_id = f"task_memory_keep_{uuid4().hex}"
    state.sqlite_store.upsert_task_memory_policy(
        task_id=task_id,
        short_term_retain_days=7,
        long_term_retain_days=14,
        disable_auto_cleanup=True,
        updated_at=100.0,
    )
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="永久保留",
    )
    state.sqlite_store.insert_event(event)

    result = state.apply_memory_cleanup(task_id=task_id, now=31 * 24 * 60 * 60)

    assert result["skipped"] is True
    assert state.sqlite_store.list_events(task_id=task_id, limit=20)[0]["summary"] == "永久保留"


def test_ask_uses_long_term_when_requested_window_exceeds_short_retention() -> None:
    task_id = f"task_memory_ask_{uuid4().hex}"
    now = time.time()
    state.sqlite_store.upsert_task_memory_policy(
        task_id=task_id,
        short_term_retain_days=7,
        long_term_retain_days=14,
        disable_auto_cleanup=False,
    )
    state.sqlite_store.insert_long_term_summary(
        summary_id="lts_yesterday_apifox",
        task_id=task_id,
        window_start=now - (24 * 60 * 60),
        window_end=now - (24 * 60 * 60) + 60,
        summary="昨天 Chrome 显示了 Apifox 登录页",
        payload={"summary_id": "lts_yesterday_apifox", "task_id": task_id, "window_start": now - (24 * 60 * 60), "window_end": now - (24 * 60 * 60) + 60, "summary": "昨天 Chrome 显示了 Apifox 登录页", "event_count": 2, "event_ids": ["evt_1"]},
    )

    response = client.get(
        "/api/ask",
        params={"task_id": task_id, "question": "昨天 Chrome 里是什么", "hours": 24 * 8},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Apifox" in payload["answer"]
    assert "long_term_persisted" in payload["memory_layers_used"]
