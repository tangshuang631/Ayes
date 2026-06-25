from fastapi.testclient import TestClient

from ayes.api.server import app


client = TestClient(app)


def test_agent_contracts_endpoint_exposes_expected_routes() -> None:
    response = client.get("/api/agent/contracts")
    assert response.status_code == 200
    payload = response.json()
    assert "watch.status" in payload
    assert "agent.observe_live" in payload
    assert payload["agent.observe_live"]["path"] == "/api/agent/observe-live"
    assert "evidence_status" in payload["agent.observe_live"]["response_keys"]
    assert "agent_hints" in payload["agent.observe_live"]["response_keys"]
    assert "watch.start" in payload
    assert "watch.plan" in payload
    assert "watch.confirm_plan" in payload
    assert "questions" in payload["watch.plan"]["response_keys"]
    assert "region_intents" in payload["watch.plan"]["response_keys"]
    assert "action_intents" in payload["watch.plan"]["response_keys"]
    assert "region_bindings" in payload["watch.confirm_plan"]["request"]
    assert "snapshot.inspect" in payload
    assert "timeline.recent" in payload
    assert payload["timeline.query"]["path"] == "/api/ask"
    assert "structured_matches" in payload["timeline.query"]["response_keys"]
    assert "structured_observations" in payload["timeline.query"]["response_keys"]
    assert "query" in payload["logs.recent"]
    assert payload["alerts.recent"]["path"] == "/api/alerts/recent"
    assert payload["watch.run_once"]["path"] == "/api/watch/run-once"
