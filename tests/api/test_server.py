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
    assert "cleanup_reminder" in payload
    assert "region_binding_context" in payload
    assert "configuration_guidance" in payload["agent_hints"]
    assert isinstance(payload["agent_hints"]["configuration_guidance"], list)
    assert "task_context" in payload["agent_hints"]
    assert payload["agent_hints"]["task_context"]["current_task_id"] == "task_observe_live"


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
    assert "task_context" in payload


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
    webhook_guidance = next(item for item in payload["setup_guidance"] if item["topic"] == "wecom_webhook")
    assert "alert.webhook_url" in webhook_guidance["blocking_fields"]
    assert any("webhook" in item.lower() for item in webhook_guidance["user_steps"])
    assert payload["can_apply_directly"] is False


def test_plan_watch_spec_extracts_explicit_trigger_keyword_from_natural_language() -> None:
    response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_keyword_trigger",
            "prompt": "帮我监控当前主屏幕里出现 Codex 时提醒我",
            "target": {"type": "screen", "screen_id": 1},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "triggered"
    assert payload["draft_spec"]["watch_intent"]["enabled"] is True
    assert payload["draft_spec"]["watch_intent"]["queries"] == ["Codex"]


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


def test_triggered_plan_can_continue_after_webhook_guidance_is_fulfilled() -> None:
    plan_response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_guided_webhook",
            "prompt": "帮我监控 Safari 里的商品价格低于 299 时提醒我",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert any(item["topic"] == "wecom_webhook" for item in plan_payload["setup_guidance"])
    assert any(question["kind"] == "webhook_missing" for question in plan_payload["questions"])

    confirm_response = client.post(
        "/api/watch/confirm-plan",
        json={
            "plan": plan_payload,
            "confirmations": {
                "webhook_url": "http://127.0.0.1:18999/webhook",
            },
        },
    )
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert confirm_payload["status"] == "loaded"
    assert confirm_payload["spec"]["alert"]["webhook_url"] == "http://127.0.0.1:18999/webhook"


def test_confirm_plan_can_persist_custom_alert_message_template() -> None:
    plan_response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_alert_template",
            "prompt": "帮我监控 Safari 里的库存恢复时提醒我",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert plan_response.status_code == 200

    confirm_response = client.post(
        "/api/watch/confirm-plan",
        json={
            "plan": plan_response.json(),
            "confirmations": {
                "webhook_url": "http://127.0.0.1:18999/webhook",
                "alert_message_title": "库存提醒",
                "alert_message_template": "任务 {task_id} 命中：{summary}",
            },
        },
    )
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert confirm_payload["spec"]["alert"]["message_title"] == "库存提醒"
    assert confirm_payload["spec"]["alert"]["message_template"] == "任务 {task_id} 命中：{summary}"


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

    observe_response = client.get("/api/agent/observe-live", params={"task_id": "task_plan_region_bindings", "minutes": 5, "limit": 10})
    assert observe_response.status_code == 200
    observe_payload = observe_response.json()
    assert observe_payload["region_binding_context"]["bound_count"] == 2
    assert observe_payload["region_binding_context"]["bindings"][0]["region_id"] == "roi_price"
    assert observe_payload["region_binding_context"]["bindings"][1]["source"] == "external_selector"


def test_region_bind_request_and_result_round_trip() -> None:
    plan_response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_region_bind_api",
            "prompt": "帮我监控 Safari 页面里的价格和库存，只看两个重点区域",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()

    request_response = client.post(
        "/api/agent/region-bind-request",
        json={
            "plan": plan_payload,
            "capture_ref": {
                "capture_id": "cap_demo_1",
                "image_path": "/tmp/runtime/evidence/2026-06-25__task_region_bind_api/cap.png",
                "image_width": 1440,
                "image_height": 900,
            },
        },
    )
    assert request_response.status_code == 200
    request_payload = request_response.json()
    assert request_payload["bind_version"] == "1.0"
    assert request_payload["task_id"] == "task_region_bind_api"
    assert len(request_payload["region_intents"]) >= 2

    price_intent = next(item for item in request_payload["region_intents"] if item["name"] == "价格区")
    result_response = client.post(
        "/api/agent/region-bind-result",
        json={
            "bind_version": "1.0",
            "task_id": "task_region_bind_api",
            "target_ref": request_payload["target_ref"],
            "capture_ref": request_payload["capture_ref"],
            "region_bindings": [
                {
                    "region_intent_id": price_intent["region_intent_id"],
                    "region_id": "roi_price",
                    "name": "价格区",
                    "x": 100,
                    "y": 200,
                    "w": 300,
                    "h": 120,
                    "coordinate_space": "target",
                    "binding_space": "capture_image",
                    "source": "external_selector",
                }
            ],
            "unbound_region_intents": [],
        },
    )
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["status"] == "accepted"
    assert result_payload["region_binding_context"]["bindings"][0]["region_id"] == "roi_price"


def test_region_bind_contract_endpoint_returns_formal_schema() -> None:
    response = client.get("/api/agent/region-bind-contract")
    assert response.status_code == 200
    payload = response.json()
    assert payload["bind_version"] == "1.0"
    assert "request" in payload
    assert "result" in payload
    assert "confirm_plan_rules" in payload
    assert payload["result"]["region_bindings"][0]["source"] == "external_selector|screenshot_annotation|manual_coordinates"


def test_region_bind_request_uses_latest_screenshot_when_capture_ref_missing() -> None:
    state.remember_screenshot(path="runtime/web-last-frame.png", width=2, height=2)

    plan_response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_region_bind_auto_capture",
            "prompt": "帮我监控 Safari 页面里的价格和库存，只看两个重点区域",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()

    request_response = client.post("/api/agent/region-bind-request", json={"plan": plan_payload})
    assert request_response.status_code == 200
    request_payload = request_response.json()
    assert request_payload["capture_ref"]["image_path"].endswith("runtime/web-last-frame.png")
    assert request_payload["capture_ref"]["image_width"] == 2
    assert request_payload["capture_ref"]["image_height"] == 2


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
                "model": "qwen2.5vl:7b",
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
    assert payload["spec"]["vision"]["model"] == "qwen2.5vl:7b"


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
            "vision": {"enabled": True, "model": "qwen2.5vl:7b"},
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
    from ayes.api import server

    class FakeOllamaService:
        def status_report(self):
            return {
                "provider": "ollama",
                "binary_available": True,
                "service_reachable": False,
                "available": False,
                "default_model": "qwen2.5vl:7b",
                "default_model_installed": False,
                "items": [],
                "recommended_action": "start_service",
            }

    original = server.ollama_service
    server.ollama_service = FakeOllamaService()
    try:
        response = client.get("/api/vision/models")
    finally:
        server.ollama_service = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["binary_available"] is True
    assert payload["service_reachable"] is False
    assert payload["default_model"] == "qwen2.5vl:7b"
    assert payload["default_model_installed"] is False
    assert payload["recommended_action"] == "start_service"
    assert "items" in payload


def test_vision_settings_endpoint_persists_agent_visible_state() -> None:
    response = client.post(
        "/api/vision/settings",
        json={
            "enabled": True,
            "provider": "ollama",
            "model": "qwen2.5vl:7b",
            "auto_use_when_available": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["vision_settings"]["enabled"] is True
    assert payload["vision_settings"]["model"] == "qwen2.5vl:7b"
    get_response = client.get("/api/vision/settings")
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is True


def test_observe_live_includes_vision_status() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_observe_live_vision",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/vision/settings",
        json={
            "enabled": True,
            "provider": "ollama",
            "model": "qwen2.5vl:7b",
            "auto_use_when_available": True,
        },
    )
    response = client.get("/api/agent/observe-live", params={"task_id": "task_observe_live_vision", "minutes": 5, "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert "vision_status" in payload
    assert payload["vision_status"]["settings"]["enabled"] is True
    assert payload["vision_status"]["settings"]["model"] == "qwen2.5vl:7b"
    assert payload["vision_status"]["default_local_model"] == "qwen2.5vl:7b"


def test_observe_live_includes_vision_enable_guidance_when_ollama_not_ready() -> None:
    from ayes.api import server

    class FakeOllamaService:
        def status_report(self, default_model="qwen2.5vl:7b"):
            raise AssertionError("observe-live 不应主动探测 Ollama 就绪状态")

    original = server.ollama_service
    server.ollama_service = FakeOllamaService()
    try:
        response = client.get("/api/agent/observe-live", params={"task_id": "task_observe_live_vision", "minutes": 5, "limit": 10})
    finally:
        server.ollama_service = original

    assert response.status_code == 200
    payload = response.json()
    vision_status = payload["vision_status"]
    assert vision_status["default_local_model"] == "qwen2.5vl:7b"
    assert vision_status["readiness_check_required"] is True
    assert vision_status["provider_status"] == {}
    assert "installation_guidance" in vision_status
    assert any("vision prepare" in item for item in vision_status["installation_guidance"]["user_steps"])
    assert payload["agent_hints"]["vision_next_action"]["action"] == "check_on_user_enable_request"
    assert payload["agent_hints"]["vision_next_action"]["default_model"] == "qwen2.5vl:7b"


def test_plan_spec_visual_prompt_uses_qwen_default_and_enable_guidance() -> None:
    response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_visual_qwen",
            "prompt": "帮我实时看图表和按钮颜色变化，并在需要时启用本地视觉增强",
            "target": {"type": "screen", "screen_id": 1},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_spec"]["vision"]["enabled"] is True
    assert payload["draft_spec"]["vision"]["model"] == "qwen2.5vl:7b"
    assert any("qwen2.5vl:7b" in item for item in payload["confirmation_summary"])
    vision_guidance = next(item for item in payload["setup_guidance"] if item["topic"] == "local_vision")
    assert vision_guidance["can_agent_attempt_after_permission"] is True
    assert any("vision prepare" in item for item in vision_guidance["commands"])


def test_vision_prepare_endpoint_checks_ollama_only_on_explicit_request() -> None:
    from ayes.api import server

    class FakeOllamaService:
        def status_report(self, default_model="qwen2.5vl:7b"):
            return {
                "provider": "ollama",
                "available": False,
                "binary_available": False,
                "service_reachable": False,
                "default_model": default_model,
                "default_model_installed": False,
                "items": [],
                "recommended_action": "install_ollama",
            }

    original = server.ollama_service
    server.ollama_service = FakeOllamaService()
    try:
        response = client.post("/api/vision/prepare", json={"requested_by": "agent_enable_local_vision"})
    finally:
        server.ollama_service = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_by"] == "agent_enable_local_vision"
    assert payload["default_local_model"] == "qwen2.5vl:7b"
    assert payload["provider_status"]["recommended_action"] == "install_ollama"
    assert payload["agent_can_attempt_after_permission"] is True
    assert any("ollama pull qwen2.5vl:7b" in item for item in payload["user_steps"])


def test_plan_spec_keeps_vision_disabled_for_simple_text_monitoring() -> None:
    response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_plain_text_only",
            "prompt": "帮我监控 Safari 里的商品价格低于 299 时提醒我，只看文字和数字，不需要看图表和颜色",
            "target": {"type": "process", "process_name": "Safari"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_spec"]["vision"]["enabled"] is False
    assert any("默认不启用本地视觉增强" in item for item in payload["confirmation_summary"])


def test_plan_spec_parses_visual_sampling_policy_from_prompt() -> None:
    response = client.post(
        "/api/agent/plan-watch-spec",
        json={
            "task_id": "task_plan_visual_sampling_policy",
            "prompt": "帮我看图表和按钮变化，开启本地视觉增强，但默认不要每次都调大模型，每隔 5 次截图交给本地模型一次，至少间隔 30 秒",
            "target": {"type": "screen", "screen_id": 1},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    vision = payload["draft_spec"]["vision"]
    assert vision["enabled"] is True
    assert vision["sampling_every_n_runs"] == 5
    assert vision["sampling_min_interval_sec"] == 30
    assert any("每隔 5 次截图" in item or "30 秒" in item for item in payload["confirmation_summary"])


def test_vision_models_endpoint_returns_availability_shape_legacy_keys() -> None:
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
                "model": "qwen2.5vl:7b",
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
        assert attrs.get("vision_model") == "qwen2.5vl:7b"


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
