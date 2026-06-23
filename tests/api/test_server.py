from fastapi.testclient import TestClient

from ayes.api.server import app, state
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.ocr.models import OCRResult


client = TestClient(app)


class FakeCapture:
    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        return CaptureResult(
            ok=True,
            status="ok",
            frame=CaptureFrame(
                frame_id="frame_api",
                timestamp=timestamp,
                target_type="screen",
                target_id="main",
                width=2,
                height=2,
                image_bytes=b"api-frame",
            ),
        )


class FakeNumericOCR:
    def recognize(self, image, options=None) -> OCRResult:
        return OCRResult(provider="fake", elapsed_ms=1, full_text="当前价格 ¥199，立即购买")


def test_status_endpoint_returns_basic_state() -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert "has_runner" in payload
    assert "is_running" in payload


def test_windows_endpoint_returns_items_key() -> None:
    response = client.get("/api/windows")
    assert response.status_code == 200
    assert "items" in response.json()


def test_logs_endpoint_supports_task_and_category_filters() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/logs", params={"task_id": "task_web", "category": "watch", "minutes": 15})
    assert response.status_code == 200
    assert "items" in response.json()


def test_targets_endpoint_returns_screen_and_window_sections() -> None:
    response = client.get("/api/targets")
    assert response.status_code == 200
    payload = response.json()
    assert "screens" in payload
    assert "windows" in payload
    assert "collapsed_windows" in payload
    assert "processes" in payload


def test_favicon_endpoint_does_not_404() -> None:
    response = client.get("/favicon.ico")
    assert response.status_code in {200, 204}


def test_watch_config_endpoint_loads_spec_from_form_payload() -> None:
    response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_config_form",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1000,
                "ocr_interval_ms": 1000,
                "change_detection_interval_ms": 1000,
                "max_fps": 2,
                "skip_ocr_when_no_change": True,
            },
            "watch_intent": {
                "enabled": True,
                "summary": "价格低于阈值提醒我",
                "queries": ["价格低于 299"],
            },
            "alert": {"enabled": True},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task_config_form"
    assert payload["mode"] == "triggered"


def test_watch_config_endpoint_supports_process_target_and_refresh_click() -> None:
    response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_process_form",
            "mode": "triggered",
            "target": {"type": "process", "process_name": "Safari"},
            "sampling": {
                "screenshot_interval_ms": 500,
                "ocr_interval_ms": 1000,
                "change_detection_interval_ms": 500,
                "max_fps": 2,
                "skip_ocr_when_no_change": True,
            },
            "watch_intent": {
                "enabled": True,
                "summary": "商品有货提醒我",
                "queries": ["有货"],
            },
            "alert": {"enabled": True},
            "actions": {
                "refresh_click": {
                    "enabled": True,
                    "point": {"x": 100, "y": 200},
                    "coordinate_space": "screen",
                }
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["target"]["type"] == "process"
    assert payload["target"]["process_name"] == "Safari"


def test_watch_config_endpoint_supports_multi_regions_and_vision_config() -> None:
    response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_regions_vision",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_main",
                        "name": "价格区",
                        "x": 120,
                        "y": 240,
                        "w": 300,
                        "h": 120,
                        "coordinate_space": "target",
                        "enabled": True,
                    }
                ],
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "Molmo-7B-D-0924",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 12,
            },
            "watch_intent": {"enabled": False},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["target"]["regions"][0]["region_id"] == "roi_main"
    assert payload["spec"]["vision"]["enabled"] is True
    assert payload["spec"]["vision"]["model"] == "Molmo-7B-D-0924"


def test_status_endpoint_exposes_current_spec_payload() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_status_spec",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {"screenshot_interval_ms": 3000},
            "watch_intent": {"enabled": False},
        },
    )
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert "spec" in payload
    assert payload["spec"]["sampling"]["screenshot_interval_ms"] == 3000
    assert "last_run_at" in payload
    assert "last_event_at" in payload
    assert "action_count" in payload
    assert "match_count" in payload
    assert "alert_count" in payload
    assert "last_match_at" in payload


def test_ocr_snippets_endpoint_returns_recent_text_fragments() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/ocr/snippets", params={"task_id": "task_web", "minutes": 5})
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    if payload["items"]:
        assert "location_summary" in payload["items"][0]


def test_ask_endpoint_returns_time_range_and_evidence_fields() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/ask", params={"question": "最近发生了什么", "minutes": 5, "task_id": "task_web"})
    assert response.status_code == 200
    payload = response.json()
    assert "time_range" in payload
    assert "evidence_refs" in payload
    assert payload["time_scope_respected"] is True


def test_targets_endpoint_exposes_preview_and_collapse_metadata() -> None:
    response = client.get("/api/targets")
    assert response.status_code == 200
    payload = response.json()
    assert "collapse_rule" in payload
    assert payload["collapse_rule"]["max_width"] == 500
    assert payload["collapse_rule"]["max_height"] == 500
    assert payload["screens"][0]["preview_path"] is not None


def test_vision_models_endpoint_returns_availability_shape() -> None:
    response = client.get("/api/vision/models")
    assert response.status_code == 200
    payload = response.json()
    assert "available" in payload
    assert "items" in payload


def test_timeline_recent_exposes_region_visual_and_text_blocks() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_timeline_shape",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_demo",
                        "name": "价格区",
                        "x": 10,
                        "y": 20,
                        "w": 50,
                        "h": 60,
                        "coordinate_space": "target",
                        "enabled": True,
                    }
                ],
            },
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/run-once")
    response = client.get("/api/timeline/recent", params={"task_id": "task_timeline_shape", "minutes": 5, "limit": 20})
    assert response.status_code == 200
    items = response.json()["items"]
    assert isinstance(items, list)
    if items:
        item = items[0]
        assert "region" in item
        assert "visual" in item
        assert "text" in item
        assert "blocks" in (item.get("text") or {})
        assert "location_summary" in item
        blocks = (item.get("text") or {}).get("blocks") or []
        if blocks:
            assert "rect" in blocks[0]
            assert "rect_norm" in blocks[0]
            assert "coordinate_space" in blocks[0]


def test_timeline_recent_exposes_structured_watch_match_fields() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_numeric_watch_match",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {
                "enabled": True,
                "summary": "价格低于 299 时提醒",
                "queries": [],
                "rules": [
                    {
                        "type": "numeric_threshold",
                        "field": "price",
                        "operator": "lt",
                        "value": 299.0,
                        "unit": "cny",
                    }
                ],
            },
        },
    )
    assert state.current_runner is not None
    state.current_runner.capture = FakeCapture()
    state.current_runner.ocr = FakeNumericOCR()
    response = client.post("/api/watch/run-once")
    assert response.status_code == 200
    timeline_response = client.get("/api/timeline/recent", params={"task_id": "task_numeric_watch_match", "minutes": 5, "limit": 20})
    assert timeline_response.status_code == 200
    items = timeline_response.json()["items"]
    match_item = next((item for item in items if item.get("event_type") == "semantic_match"), None)
    if match_item is not None:
        watch_match = match_item.get("watch_match") or {}
        assert watch_match.get("matched") is True
        assert watch_match.get("matched_field") == "price"
        assert watch_match.get("matched_value") == 199.0
        assert watch_match.get("matched_unit") == "cny"
