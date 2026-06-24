from fastapi.testclient import TestClient

from ayes.api.server import app


client = TestClient(app)


def test_agent_contracts_endpoint_exposes_expected_routes() -> None:
    response = client.get("/api/agent/contracts")
    assert response.status_code == 200
    payload = response.json()
    assert "watch.status" in payload
    assert "watch.start" in payload
    assert "snapshot.inspect" in payload
    assert "timeline.recent" in payload
    assert payload["timeline.query"]["path"] == "/api/ask"
    assert "structured_matches" in payload["timeline.query"]["response_keys"]
    assert "query" in payload["logs.recent"]
