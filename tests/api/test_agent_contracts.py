from fastapi.testclient import TestClient

from ayes.api.server import app


client = TestClient(app)


def test_agent_contracts_endpoint_exposes_expected_routes() -> None:
    response = client.get("/api/agent/contracts")
    assert response.status_code == 200
    payload = response.json()
    assert "watch.status" in payload
    assert "watch.start" in payload
    assert "timeline.recent" in payload
    assert payload["timeline.query"]["path"] == "/api/ask"
    assert "query" in payload["logs.recent"]
