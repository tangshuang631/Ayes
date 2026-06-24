from fastapi.testclient import TestClient

from ayes.api.server import app, state
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.ocr.models import OCRResult
from PIL import Image
from io import BytesIO


client = TestClient(app)


class FakeCapture:
    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        image = Image.new("RGB", (2, 2), color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
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
                image_bytes=buffer.getvalue(),
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
    assert "health_summary" in payload


def test_status_endpoint_includes_health_summary_diagnostics() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    health = payload["health_summary"]
    assert "last_match" in health
    assert "last_alert" in health
    assert "recent_memory" in health
    assert "recent_logs" in health
    assert "count" in health["recent_memory"]
    assert "error_count" in health["recent_logs"]
    assert "warn_count" in health["recent_logs"]


def test_windows_endpoint_returns_items_key() -> None:
    response = client.get("/api/windows")
    assert response.status_code == 200
    assert "items" in response.json()


def test_logs_endpoint_supports_task_and_category_filters() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/logs", params={"task_id": "task_web", "category": "watch", "minutes": 15})
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert payload["task_id"] == "task_web"
    assert payload["category"] == "watch"
    assert payload["minutes"] == 15
    assert "count" in payload


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
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_status",
                        "name": "价格区",
                        "x": 10,
                        "y": 20,
                        "w": 30,
                        "h": 40,
                        "coordinate_space": "target",
                        "enabled": True,
                    }
                ],
            },
            "sampling": {"screenshot_interval_ms": 3000, "ocr_interval_ms": 1200},
            "vision": {"enabled": True, "model": "Molmo-7B-D-0924"},
            "alert": {"enabled": True},
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
    assert "last_ocr_quality" in payload
    assert "last_vision_summary" in payload
    assert "last_vision_decision" in payload
    assert "last_capture_target" in payload
    assert "last_capture_status" in payload
    assert "task_snapshot" in payload
    assert payload["task_snapshot"]["mode"] == "observe"
    assert payload["task_snapshot"]["target_type"] == "screen"
    assert payload["task_snapshot"]["region_count"] == 1
    assert payload["task_snapshot"]["region_names"] == ["价格区"]
    assert payload["task_snapshot"]["sampling"]["screenshot_interval_ms"] == 3000
    assert payload["task_snapshot"]["sampling"]["ocr_interval_ms"] == 1200
    assert payload["task_snapshot"]["vision_enabled"] is True
    assert payload["task_snapshot"]["alert_enabled"] is True
    assert "latest_key_event" in payload


def test_status_endpoint_exposes_latest_key_event_summary() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_status_latest_event",
            "mode": "triggered",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_price",
                        "name": "价格区",
                        "x": 10,
                        "y": 20,
                        "w": 80,
                        "h": 60,
                        "coordinate_space": "target",
                        "enabled": True,
                    }
                ],
            },
            "sampling": {"screenshot_interval_ms": 1000, "ocr_interval_ms": 1000},
            "watch_intent": {
                "enabled": True,
                "summary": "价格低于 299 时提醒",
                "queries": ["价格低于 299"],
            },
            "alert": {"enabled": True},
        },
    )
    assert state.current_runner is not None
    state.current_runner.capture = FakeCapture()
    state.current_runner.ocr = FakeNumericOCR()
    client.post("/api/watch/run-once")

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    latest = payload["latest_key_event"]
    assert latest is not None
    assert "source" in latest
    assert "event_type" in latest
    assert "summary" in latest
    assert "timestamp" in latest
    assert "location_summary" in latest
    assert "text_preview" in latest


def test_ocr_snippets_endpoint_returns_recent_text_fragments() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/ocr/snippets", params={"task_id": "task_web", "minutes": 5})
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert payload["task_id"] == "task_web"
    assert payload["minutes"] == 5
    assert "count" in payload
    if payload["items"]:
        assert "location_summary" in payload["items"][0]
        assert "preview_overlay" in payload["items"][0]


def test_ask_endpoint_returns_time_range_and_evidence_fields() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/ask", params={"question": "最近发生了什么", "minutes": 5, "task_id": "task_web"})
    assert response.status_code == 200
    payload = response.json()
    assert "time_range" in payload
    assert "evidence_refs" in payload
    assert payload["time_scope_respected"] is True


def test_screenshot_endpoint_returns_active_regions_overlay() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_screenshot_regions",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_main",
                        "name": "价格区",
                        "x": 10,
                        "y": 20,
                        "w": 30,
                        "h": 40,
                        "coordinate_space": "target",
                        "enabled": True,
                    },
                    {
                        "region_id": "roi_secondary",
                        "name": "库存区",
                        "x": 50,
                        "y": 60,
                        "w": 20,
                        "h": 10,
                        "coordinate_space": "target",
                        "enabled": False,
                    },
                ],
            },
            "watch_intent": {"enabled": False},
        },
    )
    assert state.current_runner is not None
    state.current_runner.capture = FakeCapture()
    client.post("/api/watch/run-once")

    response = client.get("/api/screenshot")

    assert response.status_code == 200
    payload = response.json()
    assert "path" in payload
    assert "regions" in payload
    assert len(payload["regions"]) == 1
    assert payload["regions"][0]["region_id"] == "roi_main"


def test_memory_items_endpoint_returns_recent_event_items() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/memory/items", params={"task_id": "task_web", "minutes": 5, "limit": 20})
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task_web"
    assert payload["minutes"] == 5
    assert payload["limit"] == 20
    assert "count" in payload
    assert isinstance(payload["items"], list)
    if payload["items"]:
        assert "location_summary" in payload["items"][0]
        assert "preview_overlay" in payload["items"][0]


def test_targets_endpoint_exposes_preview_and_collapse_metadata() -> None:
    response = client.get("/api/targets")
    assert response.status_code == 200
    payload = response.json()
    assert "collapse_rule" in payload
    assert payload["collapse_rule"]["max_width"] == 500
    assert payload["collapse_rule"]["max_height"] == 500
    assert "preview_path" in payload["screens"][0]
    assert payload["screens"][0]["observability"]["has_pixels"] == bool(payload["screens"][0]["preview_path"])


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
    payload = response.json()
    assert payload["task_id"] == "task_timeline_shape"
    assert payload["minutes"] == 5
    assert payload["limit"] == 20
    assert "count" in payload
    items = payload["items"]
    assert isinstance(items, list)
    if items:
        item = items[0]
        assert "region" in item
        assert "visual" in item
        assert "text" in item
        assert "blocks" in (item.get("text") or {})
        assert "location_summary" in item
        assert "preview_overlay" in item
        ocr_item = next((entry for entry in items if entry.get("source") == "ocr"), item)
        visual = ocr_item.get("visual") or {}
        attrs = visual.get("attributes") or {}
        if ocr_item.get("source") == "ocr":
            assert "ocr_provider" in attrs
            assert "ocr_char_count" in attrs
            assert "ocr_block_count" in attrs
            assert "ocr_avg_confidence" in attrs
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
    payload = timeline_response.json()
    assert payload["task_id"] == "task_numeric_watch_match"
    items = payload["items"]
    match_item = next((item for item in items if item.get("event_type") == "semantic_match"), None)
    if match_item is not None:
        watch_match = match_item.get("watch_match") or {}
        assert watch_match.get("matched") is True
        assert watch_match.get("matched_field") == "price"
        assert watch_match.get("matched_value") == 199.0
        assert watch_match.get("matched_unit") == "cny"


def test_timeline_recent_exposes_vision_trigger_reason_event() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_vision_reason",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_chart",
                        "name": "图表区",
                        "x": 0,
                        "y": 0,
                        "w": 120,
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
                "ocr_sparse_min_chars": 999,
                "trigger_on_visual_regions": True,
                "trigger_on_watch_intent": False,
            },
            "watch_intent": {"enabled": False},
        },
    )
    response = client.post("/api/watch/run-once")
    assert response.status_code == 200
    timeline_response = client.get("/api/timeline/recent", params={"task_id": "task_vision_reason", "minutes": 5, "limit": 50})
    assert timeline_response.status_code == 200
    items = timeline_response.json()["items"]
    vision_reason_event = next((item for item in items if item.get("event_type") == "vision_triggered"), None)
    if vision_reason_event is not None:
        attrs = ((vision_reason_event.get("visual") or {}).get("attributes") or {})
        assert attrs.get("vision_triggered") is True
        assert isinstance(attrs.get("vision_reasons"), list)
        assert attrs.get("vision_model") == "Molmo-7B-D-0924"


def test_ollama_vision_result_splits_detail_lines() -> None:
    from ayes.vision.ollama import OllamaService

    service = OllamaService()
    raw_text = "主摘要\n- 红色按钮在右上\n- 图表趋势向下\n- 有一个弹窗"
    lines = [line.strip(" -•\t") for line in raw_text.splitlines() if line.strip()]
    assert lines[0] == "主摘要"
    assert lines[1:] == ["红色按钮在右上", "图表趋势向下", "有一个弹窗"]


def test_events_endpoint_returns_query_scope_metadata() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/events", params={"task_id": "task_web", "source": "ocr", "minutes": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task_web"
    assert payload["source"] == "ocr"
    assert payload["minutes"] == 5
    assert "count" in payload
