from fastapi.testclient import TestClient

from ayes.api.server import app, state
from ayes.config.models import WatchSpec


client = TestClient(app)


def test_long_term_timeline_endpoint_returns_items_key() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id="task_long_term_test")
    runner.run_once()
    state.clear_runner()
    response = client.get("/api/timeline/long-term", params={"task_id": "task_long_term_test"})
    assert response.status_code == 200
    assert "items" in response.json()


def test_long_term_timeline_endpoint_supports_hours_scope() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id="task_long_term_hours")
    runner.run_once()
    state.clear_runner()
    response = client.get("/api/timeline/long-term", params={"task_id": "task_long_term_hours", "hours": 24})
    assert response.status_code == 200
    payload = response.json()
    assert payload["hours"] == 24
    assert "items" in payload


def test_clear_runner_flushes_only_pending_long_term_events() -> None:
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
    runner = state.set_runner(spec, task_id="task_long_term_flush")
    runner.run_once(now=100.0)
    state._flush_long_term_summary(force=False)
    first_items = state.sqlite_store.list_long_term_summaries(task_id="task_long_term_flush", limit=20)
    assert len(first_items) == 1
    state.clear_runner()
    second_items = state.sqlite_store.list_long_term_summaries(task_id="task_long_term_flush", limit=20)
    assert len(second_items) == 1


def test_periodic_long_term_summary_uses_summary_interval_minutes() -> None:
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
    runner = state.set_runner(spec, task_id="task_long_term_periodic")
    runner.run_once(now=100.0)
    state._flush_long_term_summary(force=False)
    runner.run_once(now=170.0)
    state._flush_long_term_summary(force=False)
    items = state.sqlite_store.list_long_term_summaries(task_id="task_long_term_periodic", limit=20)
    assert len(items) >= 2
    state.clear_runner()
