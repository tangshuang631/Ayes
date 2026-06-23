from fastapi.testclient import TestClient

from ayes.api.server import app, state
from ayes.config.models import WatchSpec


client = TestClient(app)


def test_ask_endpoint_uses_recent_summary_for_generic_question() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id="task_api_test")
    runner.run_once()
    response = client.get("/api/ask", params={"question": "最近发生了什么", "minutes": 5})
    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert "matched_events" in payload
    assert payload["task_id"] == "task_api_test"
    assert payload["minutes"] == 5
    assert "time_range" in payload
    assert "evidence_refs" in payload
    assert "time_scope_respected" in payload
    assert payload["time_scope_respected"] is True
    assert "memory_layers_used" in payload
