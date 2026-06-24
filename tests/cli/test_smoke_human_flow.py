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


def test_collect_smoke_summary_includes_screenshot_and_ask_evidence_fields() -> None:
    calls: list[tuple[str, object | None]] = []

    responses = {
        "/api/status": {
            "has_runner": True,
            "last_ocr_quality": {"summary": "ok"},
            "last_vision_decision": None,
            "last_vision_summary": None,
            "latest_key_event": {"summary": "最新事件"},
            "recent_ocr_read": {"summary": "最近 OCR"},
            "activity_status": {"summary": "活跃"},
        },
        "/api/timeline/recent?task_id=task_demo&minutes=5&limit=20": {
            "items": [{"preview_overlay": {"kind": "block"}}]
        },
        "/api/ocr/snippets?task_id=task_demo&minutes=5&limit=20": {
            "items": [{"preview_overlay": {"kind": "block"}, "evidence_ref": "runtime/evidence/demo.png"}]
        },
        "/api/logs?task_id=task_demo&minutes=15": {"items": [{"message": "ok"}]},
        "/api/ask?task_id=task_demo&question=%E6%9C%80%E8%BF%91%E5%8F%91%E7%94%9F%E4%BA%86%E4%BB%80%E4%B9%88&minutes=5": {
            "answer": "最近发生了什么",
            "matched_events": [{"event_id": "evt_1"}],
            "time_range": {"from": 1, "to": 2},
            "structured_vision_matches": [],
            "lead_evidence": {"event_id": "evt_1", "timestamp": 123.0, "summary": "证据摘要", "location_summary": "左上"},
            "evidence_previews": [{"src": "/runtime/evidence/demo.png"}],
        },
        "/api/memory/items?task_id=task_demo&minutes=5&limit=20": {
            "items": [{"preview_overlay": {"kind": "region"}}]
        },
        "/api/screenshot?task_id=task_demo": {
            "path": "/runtime/web-last-frame.png",
            "capture_timestamp": 456.0,
            "capture_status": "ok",
            "capture_target": {"type": "screen", "screen_id": 1},
            "regions": [],
        },
    }

    def fake_request_json(base_url: str, path: str, payload=None):
        calls.append((path, payload))
        if path == "/api/watch/load-configured":
            return {"status": "loaded"}
        if path == "/api/watch/run-once":
            return {"status": "ok"}
        return responses[path]

    summary = smoke_human_flow.collect_smoke_summary(
        "http://127.0.0.1:8770",
        "task_demo",
        request_json_fn=fake_request_json,
        sleep_sec=0,
    )

    assert "/api/screenshot?task_id=task_demo" in [path for path, _ in calls]
    assert summary["screenshot_path"] == "/runtime/web-last-frame.png"
    assert summary["screenshot_capture_timestamp"] == 456.0
    assert summary["screenshot_capture_status"] == "ok"
    assert summary["ask_lead_evidence"]["event_id"] == "evt_1"
    assert summary["ask_evidence_preview_count"] == 1
