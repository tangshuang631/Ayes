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
