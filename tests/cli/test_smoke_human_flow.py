from urllib.error import URLError

from scripts import smoke_human_flow


def test_wait_for_service_ready_retries_until_status_available() -> None:
    calls = {"count": 0}

    def fake_request_json(base_url: str, path: str, payload=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise URLError("not ready")
        return {"ok": True}

    ready = smoke_human_flow.wait_for_service_ready(
        "http://127.0.0.1:8770",
        attempts=3,
        sleep_sec=0,
        request_json_fn=fake_request_json,
    )

    assert ready is True
    assert calls["count"] == 3


def test_wait_for_service_ready_returns_false_when_service_never_comes_up() -> None:
    def fake_request_json(base_url: str, path: str, payload=None):
        raise URLError("not ready")

    ready = smoke_human_flow.wait_for_service_ready(
        "http://127.0.0.1:8770",
        attempts=2,
        sleep_sec=0,
        request_json_fn=fake_request_json,
    )

    assert ready is False
