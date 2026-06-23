from fastapi.testclient import TestClient

from ayes.api.server import app


client = TestClient(app)


def test_status_endpoint_returns_basic_state() -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert "has_runner" in payload


def test_windows_endpoint_returns_items_key() -> None:
    response = client.get("/api/windows")
    assert response.status_code == 200
    assert "items" in response.json()
