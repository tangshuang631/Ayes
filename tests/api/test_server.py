from fastapi.testclient import TestClient

from ayes.api.server import app, state
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, Observability
from ayes.ocr.models import OCRResult, OCRTextBlock
from PIL import Image
from io import BytesIO
import time
from uuid import uuid4


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


class FakeCaptureLarge:
    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        image = Image.new("RGB", (120, 80), color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return CaptureResult(
            ok=True,
            status="ok",
            frame=CaptureFrame(
                frame_id="frame_api_large",
                timestamp=timestamp,
                target_type="screen",
                target_id="main",
                width=120,
                height=80,
                image_bytes=buffer.getvalue(),
            ),
        )


class FakeNumericOCR:
    def recognize(self, image, options=None) -> OCRResult:
        return OCRResult(provider="fake", elapsed_ms=1, full_text="当前价格 ¥199，立即购买")


class FakeStructuredOCR:
    def recognize(self, image, options=None) -> OCRResult:
        return OCRResult(
            provider="fake",
            elapsed_ms=1,
            full_text="库存恢复 价格 ¥199",
            blocks=[
                OCRTextBlock(
                    text="库存恢复",
                    confidence=0.98,
                    bbox=[0, 0, 40, 0, 40, 10, 0, 10],
                ),
                OCRTextBlock(
                    text="价格 ¥199",
                    confidence=0.95,
                    bbox=[0, 12, 60, 12, 60, 24, 0, 24],
                ),
            ],
            char_count=len("库存恢复 价格 ¥199"),
        )


def test_status_endpoint_returns_basic_state() -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert "has_runner" in payload
    assert "is_running" in payload
    assert "health_summary" in payload


def test_observe_live_endpoint_returns_agent_ready_context() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_observe_live",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1000,
                "ocr_interval_ms": 1000,
                "change_detection_interval_ms": 1000,
                "max_fps": 2,
                "skip_ocr_when_no_change": True,
            },
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/run-once")

    response = client.get("/api/agent/observe-live", params={"task_id": "task_observe_live", "minutes": 5, "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["task_id"] == "task_observe_live"
    assert payload["time_scope"]["minutes"] == 5
    assert "observed_at" in payload
    assert "status" in payload
    assert "screenshot" in payload
    assert "recent_events" in payload
    assert "memory_items" in payload
    assert "alerts" in payload
    assert "logs" in payload
    assert "evidence_status" in payload
    assert "agent_hints" in payload
    assert isinstance(payload["agent_hints"]["suggested_next_steps"], list)
    assert payload["recent_events"]["limit"] == 10
    assert payload["memory_items"]["limit"] == 10
    assert payload["status"]["task_id"] == "task_observe_live"


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


def test_alerts_endpoint_returns_only_alert_source_events() -> None:
    task_id = f"task_alert_api_{uuid4().hex}"
    now = time.time()
    state.sqlite_store.insert_event(
        build_event(
            task_id=task_id,
            spec_version="1.0",
            task_mode="triggered",
            timestamp=now,
            source="alert",
            event_type="alert_sent",
            priority="medium",
            confidence=1.0,
            target=EventTarget(type="screen", screen_id=1),
            observability=Observability(True, True, True, True, "ok"),
            summary="告警发送成功",
        )
    )
    state.sqlite_store.insert_event(
        build_event(
            task_id=task_id,
            spec_version="1.0",
            task_mode="triggered",
            timestamp=now + 0.1,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=1.0,
            target=EventTarget(type="screen", screen_id=1),
            observability=Observability(True, True, True, True, "ok"),
            summary="OCR 变化",
        )
    )

    response = client.get("/api/alerts/recent", params={"task_id": task_id, "minutes": 15, "limit": 20})
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["count"] == 1
    assert payload["items"][0]["source"] == "alert"
    assert payload["items"][0]["event_type"] == "alert_sent"


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


def test_plan_watch_spec_endpoint_returns_draft_and_missing_confirmation() -> None:
    response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_price",
            "prompt": "帮我监控 Safari 里的商品价格低于 299 时提醒我",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task_plan_price"
    assert payload["mode"] == "triggered"
    assert payload["resolved_target"]["process_name"] == "Safari"
    assert payload["draft_spec"]["watch_intent"]["enabled"] is True
    assert payload["draft_spec"]["watch_intent"]["rules"][0]["field"] == "price"
    assert any(item["field"] == "alert.webhook_url" for item in payload["missing_fields"])
    assert any(question["kind"] == "webhook_missing" for question in payload["questions"])
    assert payload["can_apply_directly"] is False


def test_plan_watch_spec_endpoint_emits_region_and_refresh_questions() -> None:
    response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_regions",
            "prompt": "帮我监控 Safari 页面里的价格和库存，只看两个重点区域，并且每 30 秒自动刷新一次",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task_plan_regions"
    assert len(payload["region_intents"]) >= 2
    assert payload["region_intents"][0]["status"] == "needs_binding"
    kinds = [item["kind"] for item in payload["questions"]]
    assert "region_scope" in kinds
    assert "region_definition" in kinds
    assert "region_binding" in kinds
    assert "refresh_click_enable" in kinds
    refresh_intent = next(item for item in payload["action_intents"] if item["action_type"] == "refresh_click")
    assert "actions.refresh_click.point" in refresh_intent["missing_fields"]


def test_confirm_plan_endpoint_loads_runner_after_confirmation() -> None:
    plan_response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_apply",
            "prompt": "帮我监控 Safari 里的商品价格低于 299 时提醒我",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert plan_response.status_code == 200
    response = client.post(
        "/api/watch/confirm-plan",
        json={
            "plan": plan_response.json(),
            "confirmations": {
                "webhook_url": "http://127.0.0.1:18999/webhook",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "loaded"
    assert payload["task_id"] == "task_plan_apply"
    assert payload["spec"]["alert"]["enabled"] is True
    assert payload["spec"]["alert"]["webhook_url"] == "http://127.0.0.1:18999/webhook"


def test_confirm_plan_endpoint_merges_region_and_refresh_confirmations() -> None:
    plan_response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_confirm_regions",
            "prompt": "帮我监控 Safari 页面里的价格和库存，并自动刷新",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert plan_response.status_code == 200
    response = client.post(
        "/api/watch/confirm-plan",
        json={
            "plan": plan_response.json(),
            "confirmations": {
                "use_entire_target": False,
                "region_intents": [
                    {"name": "价格区", "purpose": "读取价格"},
                    {"name": "库存区", "purpose": "读取库存"},
                ],
                "regions": [
                    {"region_id": "roi_price", "name": "价格区", "x": 0, "y": 0, "w": 60, "h": 40},
                    {"region_id": "roi_stock", "name": "库存区", "x": 60, "y": 0, "w": 60, "h": 40},
                ],
                "refresh_click_enabled": True,
                "refresh_click_interval_sec": 45,
                "refresh_click_coordinate_space": "screen",
                "refresh_click_point": {"x": 100, "y": 120},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    refresh_click = payload["spec"]["actions"]["refresh_click"]
    assert refresh_click["enabled"] is True
    assert refresh_click["interval_sec"] == 45
    assert refresh_click["coordinate_space"] == "screen"
    assert refresh_click["point"] == {"x": 100, "y": 120}
    assert len(payload["spec"]["target"]["regions"]) == 2
    assert payload["plan"]["region_intents"][0]["name"] == "价格区"


def test_confirm_plan_endpoint_prefers_region_bindings_for_final_regions() -> None:
    plan_response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_region_bindings",
            "prompt": "帮我监控 Safari 页面里的价格和库存，只看两个重点区域",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    price_intent = next(item for item in plan_payload["region_intents"] if item["name"] == "价格区")
    stock_intent = next(item for item in plan_payload["region_intents"] if item["name"] == "库存区")
    response = client.post(
        "/api/watch/confirm-plan",
        json={
            "plan": plan_payload,
            "confirmations": {
                "region_bindings": [
                    {
                        "region_intent_id": price_intent["region_intent_id"],
                        "region_id": "roi_price",
                        "name": "价格区",
                        "x": 120,
                        "y": 240,
                        "w": 360,
                        "h": 160,
                        "coordinate_space": "target",
                        "source": "screenshot_annotation",
                    },
                    {
                        "region_intent_id": stock_intent["region_intent_id"],
                        "region_id": "roi_stock",
                        "name": "库存区",
                        "x": 120,
                        "y": 420,
                        "w": 360,
                        "h": 120,
                        "coordinate_space": "target",
                        "source": "external_selector",
                    },
                ]
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    regions = payload["spec"]["target"]["regions"]
    assert len(regions) == 2
    assert regions[0]["region_id"] == "roi_price"
    assert regions[1]["region_id"] == "roi_stock"
    assert payload["plan"]["region_bindings"][0]["source"] == "screenshot_annotation"


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
    state.current_runner.capture = FakeCaptureLarge()
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


def test_status_endpoint_exposes_recent_ocr_blocks_preview() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_status_ocr_blocks",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_status_blocks",
                        "name": "库存价格区",
                        "x": 0,
                        "y": 0,
                        "w": 120,
                        "h": 80,
                        "coordinate_space": "target",
                        "enabled": True,
                    }
                ],
            },
            "watch_intent": {"enabled": False},
        },
    )
    assert state.current_runner is not None
    state.current_runner.capture = FakeCaptureLarge()
    state.current_runner.ocr = FakeStructuredOCR()
    client.post("/api/watch/run-once")

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    recent_ocr = payload["recent_ocr_read"]
    assert recent_ocr is not None
    assert recent_ocr["full_text"] == "库存恢复 价格 ¥199"
    assert recent_ocr["location_summary"] == "库存价格区 / 左上"
    assert len(recent_ocr["blocks_preview"]) == 2
    assert recent_ocr["blocks_preview"][0]["text"] == "库存恢复"
    assert "direction" in recent_ocr["blocks_preview"][0]


def test_status_endpoint_exposes_activity_status_summary() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_status_activity",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    assert state.current_runner is not None
    state.current_runner.capture = FakeCapture()
    state.current_runner.ocr = FakeNumericOCR()
    client.post("/api/watch/run-once")

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    activity = payload["activity_status"]
    assert activity is not None
    assert activity["state"] in {"fresh", "idle", "stale"}
    assert "summary" in activity
    assert "seconds_since_run" in activity
    assert "seconds_since_event" in activity


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
    assert "capture_timestamp" in payload
    assert len(payload["regions"]) == 1
    assert payload["regions"][0]["region_id"] == "roi_main"
    assert payload["capture_timestamp"] is not None


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


def test_ask_endpoint_exposes_structured_observations() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_ask_observation",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_price",
                        "name": "价格区",
                        "x": 0,
                        "y": 0,
                        "w": 120,
                        "h": 80,
                    }
                ],
            },
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        },
    )
    state.current_runner.capture = FakeCaptureLarge()
    state.current_runner.ocr = FakeStructuredOCR()
    client.post("/api/watch/run-once")

    response = client.get("/api/ask", params={"question": "最近价格区读到了什么", "minutes": 5, "task_id": "task_ask_observation"})

    assert response.status_code == 200
    payload = response.json()
    assert "structured_observations" in payload
    assert payload["structured_observations"]
    observation = payload["structured_observations"][0]
    assert observation["text"]["full_text"] == "库存恢复 价格 ¥199"
    assert observation["layout"]["block_count"] == 2
    assert any(entity["field"] == "price" for entity in observation["entities"])


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
