from fastapi.testclient import TestClient

from ayes.api.server import app


client = TestClient(app)


def test_load_screen_and_status_flow() -> None:
    load_response = client.post("/api/watch/load-screen")
    assert load_response.status_code == 200
    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    assert status_response.json()["has_runner"] is True


def test_stop_watch_endpoint() -> None:
    client.post("/api/watch/load-screen")
    response = client.post("/api/watch/stop")
    assert response.status_code == 200
    assert response.json()["status"]["has_runner"] is False
