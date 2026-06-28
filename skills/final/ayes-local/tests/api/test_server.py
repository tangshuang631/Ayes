from fastapi.testclient import TestClient

from ayes.api.server import app, state
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.config.models import WatchSpec
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region
from ayes.ocr.models import OCRResult, OCRTextBlock
from PIL import Image
from io import BytesIO
import json
import os
from pathlib import Path
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


class FakeCaptureBlue:
    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        image = Image.new("RGB", (4, 3), color="blue")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return CaptureResult(
            ok=True,
            status="ok",
            frame=CaptureFrame(
                frame_id="frame_blue",
                timestamp=timestamp,
                target_type="screen",
                target_id="main",
                width=4,
                height=3,
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


def test_load_configured_defaults_sampling_to_six_seconds() -> None:
    response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_default_sampling",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spec"]["sampling"]["screenshot_interval_ms"] == 6000
    assert payload["spec"]["sampling"]["ocr_interval_ms"] == 6000
    assert payload["spec"]["sampling"]["change_detection_interval_ms"] == 6000
    assert payload["spec"]["sampling"]["quality"] == "standard"
    assert payload["spec"]["sampling"]["save_ocr_screenshots"] is False


def test_control_sampling_updates_current_task_interval_with_bounds() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_sampling_control",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.post("/api/control/sampling", json={"interval_ms": 500})
    assert response.status_code == 200
    payload = response.json()
    assert payload["sampling"]["interval_ms"] == 500
    assert payload["sampling"]["screenshot_interval_ms"] == 500
    assert payload["sampling"]["ocr_interval_ms"] == 500
    assert payload["sampling"]["change_detection_interval_ms"] == 500

    too_fast = client.post("/api/control/sampling", json={"interval_ms": 499})
    assert too_fast.status_code == 400
    too_slow = client.post("/api/control/sampling", json={"interval_ms": 3600001})
    assert too_slow.status_code == 400


def test_control_sampling_updates_quality_and_screenshot_persistence() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_sampling_storage_control",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.post(
        "/api/control/sampling",
        json={"quality": "space_saver", "save_ocr_screenshots": False},
    )

    assert response.status_code == 200
    sampling = response.json()["sampling"]
    assert sampling["quality"] == "space_saver"
    assert sampling["quality_max_dimension"] == 1280
    assert sampling["save_ocr_screenshots"] is False

    invalid = client.post("/api/control/sampling", json={"quality": "huge"})
    assert invalid.status_code == 400


def test_control_sampling_log_stores_change_summary_not_full_sampling_payload() -> None:
    task_id = f"task_sampling_log_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.post(
        "/api/control/sampling",
        json={"task_id": task_id, "interval_ms": 9000, "quality": "space_saver", "save_ocr_screenshots": False},
    )

    assert response.status_code == 200
    logs = state.sqlite_store.list_logs(task_id=task_id, category="control", limit=10)
    sampling_log = next(item for item in logs if item["message"] == "任务采样策略已更新")
    metadata = sampling_log["metadata"]
    assert "sampling" not in metadata
    assert metadata["changed_keys"] == ["interval_ms", "quality"]
    assert metadata["changes"]["interval_ms"]["to"] == 9000
    assert metadata["changes"]["quality"]["to"] == "space_saver"
    assert metadata["config_path"].endswith("/config/task-settings.json")


def test_task_load_and_app_settings_logs_store_summaries_not_full_configs() -> None:
    task_id = f"task_slim_logs_{uuid4().hex}"
    load_response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
            "memory": {
                "short_term": {"retain_days": 8},
                "long_term": {"retain_days": 22},
                "disable_auto_cleanup": True,
            },
        },
    )
    current_settings = state.get_app_settings()
    next_cleanup_days = 10 if int(current_settings.get("cleanup_reminder_days") or 7) != 10 else 11
    settings_response = client.post(
        "/api/control/settings",
        json={"cleanup_reminder_days": next_cleanup_days, "monitor_context_prompt": "Ayes context mode"},
    )

    assert load_response.status_code == 200
    assert settings_response.status_code == 200
    logs = state.sqlite_store.list_logs(task_id=task_id, category="watch", limit=20)
    load_log = next(item for item in logs if item["message"] == "监控任务已装载")
    assert "memory_policy" not in load_log["metadata"]
    assert load_log["metadata"]["memory_policy_summary"]["short_term_retain_days"] == 8
    assert load_log["metadata"]["config_path"].endswith("/config/task-settings.json")

    control_logs = state.sqlite_store.list_logs(task_id=task_id, category="control", limit=20)
    app_log = next(item for item in control_logs if item["message"] == "应用设置已更新")
    assert "settings" not in app_log["metadata"]
    assert sorted(app_log["metadata"]["changed_keys"]) == ["cleanup_reminder_days"]


def test_control_sampling_updates_requested_task_without_switching_current() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_current_task",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-25_background_task",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/switch-task", json={"task_id": "2026-06-26_current_task"})

    response = client.post(
        "/api/control/sampling",
        json={"task_id": "2026-06-25_background_task", "interval_ms": 12000, "quality": "space_saver"},
    )

    assert response.status_code == 200
    assert response.json()["sampling"]["task_id"] == "2026-06-25_background_task"
    assert response.json()["sampling"]["interval_ms"] == 12000
    assert state.current_task_id == "2026-06-26_current_task"
    current_response = client.get("/api/control/sampling")
    assert current_response.json()["sampling"]["task_id"] == "2026-06-26_current_task"
    target_response = client.get("/api/control/sampling", params={"task_id": "2026-06-25_background_task"})
    assert target_response.json()["sampling"]["interval_ms"] == 12000


def test_task_specific_settings_are_persisted_to_config_snapshot() -> None:
    task_id = "2026-06-26_task_specific_settings"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.post(
        "/api/control/sampling",
        json={"task_id": task_id, "interval_ms": 9000, "quality": "ultra_saver", "save_ocr_screenshots": False},
    )

    assert response.status_code == 200
    settings_response = client.get("/api/control/task-settings", params={"task_id": task_id})
    assert settings_response.status_code == 200
    assert settings_response.json()["settings"]["sampling"]["interval_ms"] == 9000
    config_path = Path(settings_response.json()["settings"]["task_paths"]["config_dir"]) / "task-settings.json"
    assert config_path.exists()
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert config_payload["sampling"]["screenshot_interval_ms"] == 9000
    assert config_payload["sampling"]["quality"] == "ultra_saver"


def test_task_specific_sampling_update_does_not_overwrite_global_task_sampling() -> None:
    current_task_id = f"task_global_{uuid4().hex}"
    specific_task_id = f"task_specific_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": current_task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 6000,
                "ocr_interval_ms": 6000,
                "change_detection_interval_ms": 6000,
                "quality": "standard",
                "save_ocr_screenshots": False,
            },
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": specific_task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 6000,
                "ocr_interval_ms": 6000,
                "change_detection_interval_ms": 6000,
                "quality": "standard",
                "save_ocr_screenshots": False,
            },
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/switch-task", json={"task_id": current_task_id})

    response = client.post(
        "/api/control/sampling",
        json={"task_id": specific_task_id, "interval_ms": 15000, "quality": "space_saver", "save_ocr_screenshots": False},
    )

    assert response.status_code == 200
    assert response.json()["sampling"]["task_id"] == specific_task_id
    assert response.json()["sampling"]["interval_ms"] == 15000
    global_sampling = client.get("/api/control/sampling", params={"task_id": current_task_id}).json()["sampling"]
    specific_sampling = client.get("/api/control/sampling", params={"task_id": specific_task_id}).json()["sampling"]
    assert global_sampling["interval_ms"] == 6000
    assert global_sampling["quality"] == "standard"
    assert specific_sampling["interval_ms"] == 15000
    assert specific_sampling["quality"] == "space_saver"


def test_task_settings_snapshot_prefers_task_specific_sampling_and_vision() -> None:
    task_id = "2026-06-27_task_settings_override"
    client.post(
        "/api/vision/settings",
        json={
            "enabled": False,
            "provider": "ollama",
            "model": "qwen2.5vl:7b",
            "auto_use_when_available": True,
        },
    )
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 6000,
                "ocr_interval_ms": 6000,
                "change_detection_interval_ms": 6000,
                "quality": "standard",
                "save_ocr_screenshots": False,
            },
            "vision": {
                "enabled": False,
                "provider": "ollama",
                "model": "qwen2.5vl:7b",
            },
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/control/sampling",
        json={"task_id": task_id, "interval_ms": 9000, "quality": "ultra_saver", "save_ocr_screenshots": True},
    )
    client.post(
        f"/api/tasks/{task_id}/vision-policy",
        json={"enabled": True, "provider": "ollama", "model": "qwen2.5vl:7b"},
    )

    response = client.get("/api/control/task-settings", params={"task_id": task_id})

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["sampling"]["task_id"] == task_id


def test_task_settings_snapshot_includes_task_alert_for_specialized_settings() -> None:
    task_id = "2026-06-27_task_settings_alert"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        f"/api/tasks/{task_id}/alert",
        json={
            "enabled": True,
            "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=task",
            "message_template": "任务 {task_id} 命中：{summary}",
        },
    )

    response = client.get("/api/control/task-settings", params={"task_id": task_id})

    assert response.status_code == 200
    alert = response.json()["settings"]["alert"]
    assert alert["enabled"] is True
    assert alert["webhook_url"].endswith("key=task")
    assert alert["message_template"] == "任务 {task_id} 命中：{summary}"


def test_load_configured_task_persists_display_name() -> None:
    task_id = "2026-06-27_wechat_process_monitor_微信"
    response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "display_name": "微信",
            "mode": "observe",
            "target": {"type": "process", "process_name": "WeChat"},
            "watch_intent": {"enabled": False},
        },
    )

    assert response.status_code == 200
    tasks = client.get("/api/tasks").json()["items"]
    target = next(item for item in tasks if item["task_id"] == task_id)
    assert target["display_name"] == "微信"


def test_rename_task_updates_display_name_only() -> None:
    task_id = f"task_rename_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "display_name": "微信",
            "mode": "observe",
            "target": {"type": "process", "process_name": "WeChat"},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.post(f"/api/tasks/{task_id}/rename", json={"display_name": "我的微信"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["task_id"] == task_id
    assert payload["task"]["display_name"] == "我的微信"
    assert payload["task"]["target"]["process_name"] == "WeChat"


def test_process_candidates_endpoint_returns_ranked_preview_items(monkeypatch) -> None:
    from ayes.targets.models import Bounds, ObservabilityStatus, WindowCandidate

    task_id = f"task_process_candidates_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "display_name": "微信",
            "mode": "observe",
            "target": {"type": "process", "process_name": "WeChat"},
            "watch_intent": {"enabled": False},
        },
    )

    class FakeDiscovery:
        def list_windows_for_process(self, *, process_name=None, process_id=None, only_observable=False):
            return [
                WindowCandidate(
                    window_id=201,
                    process_id=1,
                    process_name="WeChat",
                    title="小窗",
                    bounds=Bounds(x=0, y=0, width=400, height=300),
                    layer=0,
                    is_onscreen=True,
                    observability=ObservabilityStatus(code="partial", label="部分可观测", has_pixels=True, is_recommended=False),
                    is_business_candidate=True,
                    metadata={},
                ),
                WindowCandidate(
                    window_id=202,
                    process_id=1,
                    process_name="WeChat",
                    title="微信主窗口",
                    bounds=Bounds(x=0, y=0, width=1280, height=820),
                    layer=0,
                    is_onscreen=True,
                    observability=ObservabilityStatus(code="observable", label="可观测", has_pixels=True, is_recommended=True),
                    is_business_candidate=True,
                    metadata={},
                ),
            ]

    monkeypatch.setattr(state, "window_discovery", FakeDiscovery())

    def fake_preview(candidate):
        return f"/runtime/window-preview-{candidate.window_id}.png"

    monkeypatch.setattr("ayes.api.server.target_preview_service.capture_window_preview", fake_preview)

    response = client.get(f"/api/tasks/{task_id}/process-candidates")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["capturable_count"] == 2
    assert payload["items"][0]["window_id"] == 202
    assert payload["items"][0]["preview_path"].endswith("202.png")
    assert payload["items"][0]["capturable"] is True


def test_process_candidates_can_refocus_and_retry_preview(monkeypatch) -> None:
    from ayes.targets.models import Bounds, ObservabilityStatus, WindowCandidate

    task_id = f"task_process_focus_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "display_name": "微信",
            "mode": "observe",
            "target": {"type": "process", "process_name": "WeChat"},
            "watch_intent": {"enabled": False},
        },
    )

    class FakeDiscovery:
        def __init__(self) -> None:
            self.focused = False

        def list_windows_for_process(self, *, process_name=None, process_id=None, only_observable=False):
            return [
                WindowCandidate(
                    window_id=201,
                    process_id=1,
                    process_name="WeChat",
                    title="微信主窗口",
                    bounds=Bounds(x=0, y=0, width=1280, height=820),
                    layer=0,
                    is_onscreen=self.focused,
                    observability=ObservabilityStatus(
                        code="observable" if self.focused else "partial",
                        label="可观测" if self.focused else "部分可观测",
                        has_pixels=True,
                        is_recommended=self.focused,
                    ),
                    is_business_candidate=True,
                    metadata={},
                )
            ]

        def activate_process(self, *, process_name=None, process_id=None):
            self.focused = True
            return True

    discovery = FakeDiscovery()
    monkeypatch.setattr(state, "window_discovery", discovery)

    def fake_preview(candidate):
        return f"/runtime/window-preview-{candidate.window_id}.png" if discovery.focused else None

    monkeypatch.setattr("ayes.api.server.target_preview_service.capture_window_preview", fake_preview)

    response = client.get(f"/api/tasks/{task_id}/process-candidates?auto_focus=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["focus_attempted"] is True
    assert payload["focus_succeeded"] is True
    assert payload["capturable_count"] == 1
    assert payload["items"][0]["capturable"] is True


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
    assert payload["draft_spec"]["memory"]["short_term"]["retain_days"] == 7
    assert payload["draft_spec"]["memory"]["long_term"]["retain_days"] == 14
    assert payload["draft_spec"]["memory"]["disable_auto_cleanup"] is False
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


def test_task_vision_policy_updates_current_task_spec(tmp_path: Path) -> None:
    task_id = "task_wechat_vision"
    task_spec = {
        "spec_version": "1.0",
        "mode": "observe",
        "target": {
            "type": "process",
            "process_name": "微信",
            "include_all_windows": True,
            "only_observable_windows": True,
            "regions": [],
        },
        "sampling": {
            "screenshot_interval_ms": 30000,
            "ocr_interval_ms": 30000,
            "change_detection_interval_ms": 30000,
            "max_fps": 2,
            "skip_ocr_when_no_change": True,
            "quality": "standard",
            "save_ocr_screenshots": False,
        },
        "vision": {
            "enabled": False,
            "provider": "ollama",
            "model": "qwen2.5vl:7b",
            "trigger_when_ocr_sparse": True,
            "ocr_sparse_min_chars": 12,
            "trigger_on_visual_regions": True,
            "trigger_on_watch_intent": True,
            "trigger_on_question_semantics": True,
            "disable_for_text_only_tasks": True,
            "disable_for_numeric_only_tasks": True,
            "disable_for_threshold_rules": True,
            "sampling_every_n_runs": 1,
            "sampling_min_interval_sec": 0,
            "max_calls_per_minute": 6,
        },
        "memory": {
            "short_term": {"enabled": True, "retain_days": 7, "retain_minutes": 10080, "detail_level": "high"},
            "long_term": {"enabled": True, "retain_days": 14, "retain_hours": 336, "max_retain_hours": 720, "summary_interval_minutes": 5, "detail_level": "summary"},
            "disable_auto_cleanup": False,
            "memory_compact_every_n_events": 500,
        },
        "watch_intent": {"enabled": False, "summary": "", "queries": [], "rules": [], "semantic_match": {"enabled": True, "threshold": 0.78}},
        "alert": {"enabled": False, "channel": "wecom_webhook", "webhook_url_env": "AYES_WECOM_WEBHOOK_URL", "webhook_url": "", "message_title": "", "message_template": "", "priority_threshold": "medium", "cooldown_sec": 120, "dedupe_window_sec": 300},
        "actions": {"refresh_click": {"enabled": False, "point": None, "coordinate_space": "window", "interval_sec": 30, "cooldown_sec": 30, "max_clicks_per_hour": 120, "pause_when_target_matched": True}},
        "roi": {},
    }
    state.set_runner(WatchSpec.from_dict(task_spec), task_id=task_id)

    response = client.post(
        f"/api/tasks/{task_id}/vision-policy",
        json={"enabled": True, "provider": "ollama", "model": "qwen2.5vl:7b"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["vision"]["enabled"] is True
    assert state.current_spec is not None
    assert state.current_spec.vision.enabled is True
    status_response = client.get("/api/status")
    assert status_response.json()["task_snapshot"]["vision_enabled"] is True
    assert status_response.json()["vision_effective"]["enabled"] is True
    assert status_response.json()["vision_effective"]["provider"] == "ollama"
    assert status_response.json()["vision_effective"]["model"] == "qwen2.5vl:7b"
    assert "开启" in status_response.json()["vision_effective"]["label"]


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


def test_screenshot_endpoint_keeps_latest_frame_when_evidence_persistence_disabled() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_screenshot_latest_without_evidence",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1000,
                "ocr_interval_ms": 1000,
                "change_detection_interval_ms": 1000,
                "save_ocr_screenshots": False,
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
    assert payload["path"]
    assert "/screenshots/latest/" in payload["path"]
    latest_path = state.runtime_dir / payload["path"].removeprefix("/runtime/")
    assert latest_path.exists()


def test_screenshot_endpoint_prunes_latest_frames_to_small_cache() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_screenshot_latest_prune",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1000,
                "ocr_interval_ms": 1000,
                "change_detection_interval_ms": 1000,
                "save_ocr_screenshots": False,
            },
            "watch_intent": {"enabled": False},
        },
    )
    assert state.current_runner is not None
    state.current_runner.capture = FakeCapture()

    latest_dir = Path(state.current_task_paths(task_id="task_screenshot_latest_prune")["latest_dir"])
    latest_dir.mkdir(parents=True, exist_ok=True)
    for index in range(8):
        path = latest_dir / f"latest-frame-old-{index}.png"
        path.write_bytes(b"old")
        ts = time.time() - 20 + index
        path.touch()
        path.chmod(0o644)
        os.utime(path, (ts, ts))

    client.post("/api/watch/run-once")
    client.get("/api/screenshot")

    assert len(list(latest_dir.glob("latest-frame-*.png"))) <= 5
    assert (latest_dir / "web-last-frame.png").exists()


def test_task_fresh_screenshot_captures_without_switching_current_task(monkeypatch) -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_roi_current_runner",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_roi_inactive_target",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/switch-task", json={"task_id": "task_roi_current_runner"})
    assert state.current_task_id == "task_roi_current_runner"

    monkeypatch.setattr("ayes.app.runner.create_screen_capture", lambda: FakeCaptureBlue())

    response = client.post("/api/tasks/task_roi_inactive_target/screenshot/fresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task_roi_inactive_target"
    assert payload["capture_status"] == "ok"
    assert payload["image_width"] == 4
    assert payload["image_height"] == 3
    assert "/runtime/tasks/" in payload["path"]
    assert "/task_roi_inactive_target/screenshots/latest/" in payload["path"]
    assert state.current_task_id == "task_roi_current_runner"
    assert state.last_screenshot_path is None or "task_roi_inactive_target" not in state.last_screenshot_path


def test_hotkey_snapshot_captures_fresh_current_running_task(monkeypatch) -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_hotkey_current",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/start")
    assert state.current_task_id == "task_hotkey_current"
    monkeypatch.setattr("ayes.app.runner.create_screen_capture", lambda: FakeCaptureBlue())

    response = client.post("/api/hotkey/latest-frame")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "task_hotkey_current"
    assert payload["capture_status"] == "ok"
    assert payload["image_width"] == 4
    assert payload["image_height"] == 3
    assert payload["hotkey_action"] == "fresh_sample"
    assert "/task_hotkey_current/screenshots/latest/" in payload["path"]
    client.post("/api/watch/stop")


def test_hotkey_snapshot_can_target_specific_running_task(monkeypatch) -> None:
    task_id = "task_hotkey_specific"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/start")
    monkeypatch.setattr("ayes.app.runner.create_screen_capture", lambda: FakeCaptureBlue())

    response = client.post("/api/hotkey/latest-frame", json={"task_id": task_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["hotkey_action"] == "fresh_sample"
    assert "/task_hotkey_specific/screenshots/latest/" in payload["path"]
    client.post("/api/watch/stop")


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


def test_activity_endpoint_returns_compact_recent_activity_without_heavy_fields() -> None:
    task_id = f"task_activity_{uuid4().hex}"
    now = time.time()
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 30,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.91,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="正在查看 Codex 中 Ayes 的 activity 轻量接口实现",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="main", name="主内容区", x_norm=0.2, y_norm=0.2, w_norm=0.6, h_norm=0.6),
            "text": EventText(
                ocr_text="Codex Ayes activity memory-items compact",
                normalized_text="codex ayes activity memory-items compact",
                blocks=[
                    EventTextBlock(
                        text="activity",
                        confidence=0.95,
                        bbox=[1, 2, 3, 4],
                        rect_norm={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                    )
                ],
            ),
            "visual": EventVisual(
                summary="代码编辑器",
                attributes={"structured_observation": {"screen": "code", "attention": {"primary": True}}},
                provider="ollama",
            ),
            "evidence_refs": ["/tmp/heavy-frame.png"],
            "tags": ["codex", "activity"],
        }
    )
    state.sqlite_store.insert_event(event)

    response = client.get("/api/activity", params={"task_id": task_id, "minutes": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task_id
    assert payload["time_scope"]["minutes"] == 5
    assert "Codex" in payload["primary_summary"]
    assert payload["has_screenshot_evidence"] in {True, False}
    assert payload["needs_detail_followup"] in {True, False}
    assert payload["timeline"]
    assert payload["keywords"]
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "blocks" not in encoded
    assert "bbox" not in encoded
    assert "evidence_refs" not in encoded
    assert "structured_observation" not in encoded
    assert "logs" not in encoded


def test_activity_primary_summary_prioritizes_main_content_and_filters_noisy_ocr() -> None:
    task_id = f"task_activity_quality_{uuid4().hex}"
    now = time.time()
    noisy = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.24,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="0OCg0, KIkIl\ufffd8YeSJX",
    )
    noisy = noisy.__class__(
        **{
            **noisy.__dict__,
            "region": Region(region_id="auto_bottom_bar", name="自动底部栏"),
            "text": EventText(ocr_text="0OCg0, KIkIl\ufffd8YeSJX", normalized_text="0ocg0 kikil\ufffd8yesjx"),
            "visual": EventVisual(
                summary="OCR vision | 字符 18 | 块 2 | 平均置信度 0.30",
                attributes={"text_quality_score": 0.12, "text_quality_noisy": True, "attention": {"primary": False, "weight": 0.28}},
            ),
        }
    )
    main = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 1,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="Codex 正在编辑 Ayes OCR 抗噪优化",
    )
    main = main.__class__(
        **{
            **main.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "text": EventText(ocr_text="Codex 正在编辑 Ayes OCR 抗噪优化", normalized_text="codex 正在编辑 ayes ocr 抗噪优化"),
            "visual": EventVisual(
                summary="OCR vision | 字符 24 | 块 3 | 平均置信度 0.91",
                attributes={"text_quality_score": 0.88, "text_quality_noisy": False, "attention": {"primary": True, "weight": 1.0}},
            ),
        }
    )
    edge_alert = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 2,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.82,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="右侧栏出现错误提示",
    )
    edge_alert = edge_alert.__class__(
        **{
            **edge_alert.__dict__,
            "region": Region(region_id="auto_right_panel", name="自动右侧栏"),
            "text": EventText(ocr_text="错误提示", normalized_text="错误提示"),
            "visual": EventVisual(attributes={"text_quality_score": 0.76, "text_quality_noisy": False, "attention": {"primary": False, "weight": 0.32}}),
        }
    )
    state.sqlite_store.insert_event(noisy)
    state.sqlite_store.insert_event(main)
    state.sqlite_store.insert_event(edge_alert)

    response = client.get("/api/activity", params={"task_id": task_id, "minutes": 5})

    assert response.status_code == 200
    payload = response.json()
    assert "Codex 正在编辑 Ayes OCR 抗噪优化" in payload["primary_summary"]
    assert "右侧栏出现错误提示" in payload["primary_summary"]
    assert "0OCg0" not in payload["primary_summary"]
    assert any("0OCg0" in item["summary"] for item in payload["timeline"])


def test_activity_primary_summary_prefers_visual_summary_over_low_quality_primary_ocr() -> None:
    task_id = f"task_activity_visual_quality_{uuid4().hex}"
    now = time.time()
    noisy_primary = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.49,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="KlklltsYeSJx O*¥$*¥LtM text_rwlltyJcor",
    )
    noisy_primary = noisy_primary.__class__(
        **{
            **noisy_primary.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "text": EventText(ocr_text="KlklltsYeSJx O*¥$*¥LtM text_rwlltyJcor", normalized_text="klklltsyesjx o*¥$*¥ltm text_rwlltyjcor"),
            "visual": EventVisual(attributes={"text_quality_score": 0.49, "text_quality_noisy": False, "attention": {"primary": True, "weight": 1.0}}),
        }
    )
    vision_decision = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now + 1,
        source="vision",
        event_type="vision_triggered",
        priority="medium",
        confidence=0.82,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="视觉增强已触发: ocr_low_quality",
    )
    vision_decision = vision_decision.__class__(
        **{
            **vision_decision.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"attention": {"primary": True, "weight": 1.0}}),
        }
    )
    visual_summary = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now + 2,
        source="tagger",
        event_type="visual_summary",
        priority="medium",
        confidence=0.68,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="图中显示 Codex 正在编辑 Ayes OCR 抗噪优化代码",
    )
    visual_summary = visual_summary.__class__(
        **{
            **visual_summary.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"attention": {"primary": True, "weight": 1.0}}),
            "tags": ["vision", "ollama"],
        }
    )
    state.sqlite_store.insert_event(noisy_primary)
    state.sqlite_store.insert_event(vision_decision)
    state.sqlite_store.insert_event(visual_summary)

    response = client.get("/api/activity", params={"task_id": task_id, "minutes": 5})

    assert response.status_code == 200
    primary = response.json()["primary_summary"]
    assert "图中显示 Codex 正在编辑 Ayes OCR 抗噪优化代码" in primary
    assert "KlklltsYeSJx" not in primary
    assert "视觉增强已触发" not in primary


def test_activity_primary_summary_demotes_medium_quality_ocr_when_primary_visual_exists() -> None:
    task_id = f"task_activity_visual_demote_{uuid4().hex}"
    now = time.time()
    medium_noise = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.58,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="Qwm*_SummaryffSf*A8 OCR vision | 字符 68 | 块 7",
    )
    medium_noise = medium_noise.__class__(
        **{
            **medium_noise.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "text": EventText(
                ocr_text="Qwm*_SummaryffSf*A8 OCR vision | 字符 68 | 块 7",
                normalized_text="qwm summaryffsfa8 ocr vision 字符 68 块 7",
            ),
            "visual": EventVisual(
                summary="OCR vision | 字符 68 | 块 7 | 平均置信度 0.58",
                attributes={"text_quality_score": 0.5827, "text_quality_noisy": False, "attention": {"primary": True, "weight": 1.0}},
            ),
        }
    )
    visual_summary = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now + 1,
        source="tagger",
        event_type="visual_summary",
        priority="medium",
        confidence=0.74,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="该区域显示 Codex 正在编辑 Ayes 设置和 OCR 摘要代码。",
    )
    visual_summary = visual_summary.__class__(
        **{
            **visual_summary.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"attention": {"primary": True, "weight": 1.0}, "vision_model": "qwen2.5vl:7b"}),
            "tags": ["vision", "ollama"],
        }
    )
    state.sqlite_store.insert_event(medium_noise)
    state.sqlite_store.insert_event(visual_summary)

    response = client.get("/api/activity", params={"task_id": task_id, "minutes": 5})

    assert response.status_code == 200
    payload = response.json()
    assert "该区域显示 Codex 正在编辑 Ayes 设置和 OCR 摘要代码" in payload["primary_summary"]
    assert "Qwm*_Summary" not in payload["primary_summary"]
    assert not any("Qwm" in keyword for keyword in payload["keywords"])
    assert any("Qwm*_Summary" in item["summary"] for item in payload["timeline"])


def test_activity_primary_summary_orders_main_then_top_then_side_by_spatial_priority() -> None:
    task_id = f"task_activity_spatial_{uuid4().hex}"
    now = time.time()
    side = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.86,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="右侧推荐卡片列表",
    )
    side = side.__class__(
        **{
            **side.__dict__,
            "region": Region(region_id="auto_right_panel", name="自动右侧栏"),
            "visual": EventVisual(attributes={"attention": {"primary": False, "weight": 0.32}}),
        }
    )
    top = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 1,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.87,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="顶部标签导航，当前选中设置页签",
    )
    top = top.__class__(
        **{
            **top.__dict__,
            "region": Region(region_id="auto_top_bar", name="自动顶部栏"),
            "visual": EventVisual(attributes={"attention": {"primary": False, "weight": 0.38}}),
        }
    )
    main = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 2,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容文档页面，标题为项目进展",
    )
    main = main.__class__(
        **{
            **main.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"attention": {"primary": True, "weight": 1.0}}),
        }
    )
    state.sqlite_store.insert_event(side)
    state.sqlite_store.insert_event(top)
    state.sqlite_store.insert_event(main)

    response = client.get("/api/activity", params={"task_id": task_id, "minutes": 5})

    assert response.status_code == 200
    payload = response.json()
    parts = payload["primary_summary"].split("；")
    assert "主内容文档页面" in parts[0]
    assert "顶部标签导航" in parts[1]


def test_activity_timeline_orders_same_region_by_real_rect_position() -> None:
    task_id = f"task_activity_rect_{uuid4().hex}"
    now = time.time()
    lower = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容下半区表格",
    )
    lower = lower.__class__(
        **{
            **lower.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "text": EventText(
                ocr_text="主内容下半区表格",
                normalized_text="主内容下半区表格",
                blocks=[EventTextBlock(text="下半区", confidence=0.9, rect_norm={"x": 0.2, "y": 0.72, "w": 0.2, "h": 0.08})],
            ),
            "visual": EventVisual(attributes={"attention": {"primary": True, "weight": 1.0}, "text_quality_score": 0.88, "text_quality_noisy": False}),
        }
    )
    upper = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 1,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容上半区标题",
    )
    upper = upper.__class__(
        **{
            **upper.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "text": EventText(
                ocr_text="主内容上半区标题",
                normalized_text="主内容上半区标题",
                blocks=[EventTextBlock(text="上半区", confidence=0.9, rect_norm={"x": 0.2, "y": 0.12, "w": 0.2, "h": 0.08})],
            ),
            "visual": EventVisual(attributes={"attention": {"primary": True, "weight": 1.0}, "text_quality_score": 0.88, "text_quality_noisy": False}),
        }
    )
    state.sqlite_store.insert_event(lower)
    state.sqlite_store.insert_event(upper)

    response = client.get("/api/activity", params={"task_id": task_id, "minutes": 5})

    assert response.status_code == 200
    timeline = response.json()["timeline"]
    assert "上半区" in timeline[0]["summary"]
    assert "下半区" in timeline[1]["summary"]


def test_activity_and_ask_do_not_query_raw_logs(monkeypatch) -> None:
    task_id = f"task_no_log_query_{uuid4().hex}"
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=time.time(),
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="普通回忆问题只查记忆事件",
    )
    state.sqlite_store.insert_event(event)

    def fail_list_logs(*args, **kwargs):
        raise AssertionError("normal recall must not query raw logs")

    monkeypatch.setattr(state.sqlite_store, "list_logs", fail_list_logs)

    activity_response = client.get("/api/activity", params={"task_id": task_id, "minutes": 5})
    ask_response = client.get("/api/ask", params={"task_id": task_id, "minutes": 5, "question": "最近发生了什么"})

    assert activity_response.status_code == 200
    assert ask_response.status_code == 200


def test_status_uses_log_summary_without_loading_raw_log_payloads(monkeypatch) -> None:
    client.post("/api/watch/load-screen")

    def fail_list_logs(*args, **kwargs):
        raise AssertionError("status must not load raw log payloads")

    monkeypatch.setattr(state.sqlite_store, "list_logs", fail_list_logs)

    response = client.get("/api/status")

    assert response.status_code == 200
    recent_logs = response.json()["health_summary"]["recent_logs"]
    assert "error_count" in recent_logs
    assert "warn_count" in recent_logs


def test_memory_items_compact_filters_heavy_event_fields() -> None:
    task_id = f"task_memory_compact_{uuid4().hex}"
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=time.time(),
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.88,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页与 Chrome 标签页",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="main", name="主内容区"),
            "text": EventText(
                ocr_text="Apifox Chrome 登录",
                normalized_text="apifox chrome login",
                blocks=[EventTextBlock(text="Apifox", confidence=0.92, bbox=[1, 2, 3, 4])],
            ),
            "visual": EventVisual(attributes={"structured_observation": {"main": "Apifox"}}),
            "evidence_refs": ["/tmp/frame.png"],
            "tags": ["Apifox", "Chrome"],
        }
    )
    state.sqlite_store.insert_event(event)

    response = client.get("/api/memory/items", params={"task_id": task_id, "minutes": 5, "limit": 5, "compact": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["compact"] is True
    assert payload["items"]
    item = payload["items"][0]
    assert item["summary"] == "Apifox 登录页与 Chrome 标签页"
    assert item["region_name"] == "主内容区"
    assert item["keywords"]
    encoded = json.dumps(item, ensure_ascii=False)
    assert "blocks" not in encoded
    assert "bbox" not in encoded
    assert "evidence_refs" not in encoded
    assert "structured_observation" not in encoded


def test_memory_items_compact_filters_keywords_from_low_quality_ocr() -> None:
    task_id = f"task_memory_compact_noise_{uuid4().hex}"
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=time.time(),
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.38,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="OCR 低质量文本已降权 (vision)",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "text": EventText(
                ocr_text="Qwm*_SummaryffSf*A8 KIkIl\ufffd8YeSJX",
                normalized_text="qwm summaryffsfa8 kikil\ufffd8yesjx",
                blocks=[EventTextBlock(text="KIkIl\ufffd8YeSJX", confidence=0.2, bbox=[1, 2, 3, 4])],
            ),
            "visual": EventVisual(attributes={"text_quality_score": 0.31, "text_quality_noisy": True}),
            "tags": ["ocr", "vision"],
        }
    )
    state.sqlite_store.insert_event(event)

    response = client.get("/api/memory/items", params={"task_id": task_id, "minutes": 5, "limit": 5, "compact": True})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["keywords"] == ["ocr", "vision", "低质量文本已降权"]
    assert not any("Qwm" in keyword or "KIkIl" in keyword for keyword in item["keywords"])


def test_memory_items_compact_filters_keywords_from_medium_quality_gibberish_summary() -> None:
    task_id = f"task_memory_compact_medium_noise_{uuid4().hex}"
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=time.time(),
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.5,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="10ffl 125 4Ert5E A*¢cRN¢\ufffdk5\ufffd\ufffd MY\ufffd",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "text": EventText(ocr_text="10ffl 125 4Ert5E A*¢cRN¢\ufffdk5\ufffd\ufffd MY\ufffd", normalized_text="10ffl 125 4ert5e acrn k5 my"),
            "visual": EventVisual(attributes={"text_quality_score": 0.5014, "text_quality_noisy": False}),
            "tags": ["ocr", "vision"],
        }
    )
    state.sqlite_store.insert_event(event)

    response = client.get("/api/memory/items", params={"task_id": task_id, "minutes": 5, "limit": 5, "compact": True})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["keywords"] == ["ocr", "vision"]


def test_task_memory_file_store_compact_short_event_omits_redundant_task_fields() -> None:
    task_id = f"task_memory_file_compact_{uuid4().hex}"
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=time.time(),
        source="vision",
        event_type="vision_skipped",
        priority="medium",
        confidence=0.76,
        target=EventTarget(type="process", process_name="哔哩哔哩"),
        observability=Observability(True, True, True, True, "ok"),
        summary="视觉增强已跳过: non_primary_attention_region",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_top_bar", name="自动顶部栏"),
            "visual": EventVisual(
                summary="视觉增强已跳过: non_primary_attention_region",
                attributes={"attention": {"primary": False, "weight": 0.38}},
            ),
            "tags": ["vision", "vision_skipped"],
        }
    )

    path = state.memory_file_store.append_short_event(event)

    assert not path.exists()


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
    state.update_vision_enhancement_settings(enabled=False, provider="ollama", model="qwen2.5vl:7b")

    class FakeOllamaService:
        def status_report(self, *, default_model="qwen2.5vl:7b", selected_model=None):
            return {
                "provider": "ollama",
                "binary_available": True,
                "service_reachable": True,
                "available": True,
                "default_model": default_model,
                "default_model_installed": True,
                "default_selected_model": selected_model or "qwen2.5vl:7b",
                "items": [
                    {"name": "qwen2.5vl:7b", "is_vision_model": True},
                    {"name": "qwen2.5:7b", "is_vision_model": False},
                ],
                "recommended_action": "ready",
            }

    original = server.ollama_service
    server.ollama_service = FakeOllamaService()
    try:
        response = client.get("/api/vision/models")
    finally:
        server.ollama_service = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["binary_available"] is True
    assert payload["service_reachable"] is True
    assert payload["default_model"] == "qwen2.5vl:7b"
    assert payload["default_model_installed"] is True
    assert payload["recommended_action"] == "ready"
    assert "items" in payload
    assert payload["items"][0]["is_vision_model"] is True
    assert payload["items"][1]["is_vision_model"] is False
    assert payload["default_selected_model"] == "qwen2.5vl:7b"


def test_vision_settings_disables_non_vision_model_with_warning() -> None:
    from ayes.api import server

    class FakeOllamaService:
        def status_report(self, *, default_model="qwen2.5vl:7b", selected_model=None):
            return {
                "provider": "ollama",
                "binary_available": True,
                "service_reachable": True,
                "available": True,
                "default_model": default_model,
                "default_model_installed": True,
                "default_selected_model": "qwen2.5vl:7b",
                "items": [
                    {"name": "qwen2.5vl:7b", "is_vision_model": True},
                    {"name": "qwen2.5:7b", "is_vision_model": False},
                ],
                "recommended_action": "ready",
            }

    original = server.ollama_service
    server.ollama_service = FakeOllamaService()
    try:
        response = client.post(
            "/api/vision/settings",
            json={
                "enabled": True,
                "provider": "ollama",
                "model": "qwen2.5:7b",
                "auto_use_when_available": True,
            },
        )
    finally:
        server.ollama_service = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["vision_settings"]["enabled"] is False
    assert payload["vision_settings"]["model"] == "qwen2.5:7b"
    assert "非视觉模型" in payload["warning"]


def test_vision_settings_disables_unknown_non_vision_model_with_warning() -> None:
    from ayes.api import server

    class FakeOllamaService:
        def status_report(self, *, default_model="qwen2.5vl:7b", selected_model=None):
            return {
                "provider": "ollama",
                "binary_available": True,
                "service_reachable": True,
                "available": True,
                "default_model": default_model,
                "default_model_installed": False,
                "default_selected_model": "qwen2.5vl:7b",
                "items": [
                    {"name": "qwen2.5vl:7b", "is_vision_model": True},
                ],
                "recommended_action": "ready",
            }

    original = server.ollama_service
    server.ollama_service = FakeOllamaService()
    try:
        response = client.post(
            "/api/vision/settings",
            json={
                "enabled": True,
                "provider": "ollama",
                "model": "llama3.1:8b",
                "auto_use_when_available": True,
            },
        )
    finally:
        server.ollama_service = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["vision_settings"]["enabled"] is False
    assert payload["vision_settings"]["model"] == "llama3.1:8b"
    assert "非视觉模型" in payload["warning"]


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


def test_query_includes_effective_vision_summary() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_query_vision",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "qwen2.5vl:7b",
            },
        },
    )

    response = client.get(
        "/api/query",
        params={
            "task_id": "task_query_vision",
            "question": "最近页面内容是什么",
            "minutes": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["vision_effective"]["enabled"] is True
    assert payload["vision_effective"]["provider"] == "ollama"
    assert payload["vision_effective"]["model"] == "qwen2.5vl:7b"
    assert "开启" in payload["vision_effective"]["label"]


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


def test_storage_status_reports_task_category_sizes() -> None:
    task_id = f"2026-06-26_storage_status_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "target": {"type": "screen", "screen_id": 1},
        },
    )
    task_dir = Path(state.current_task_paths(task_id=task_id)["task_dir"])
    (task_dir / "screenshots" / "latest").mkdir(parents=True, exist_ok=True)
    (task_dir / "memory" / "short").mkdir(parents=True, exist_ok=True)
    (task_dir / "logs").mkdir(parents=True, exist_ok=True)
    (task_dir / "index" / "chunks").mkdir(parents=True, exist_ok=True)
    (task_dir / "screenshots" / "latest" / "frame.png").write_bytes(b"abc")
    (task_dir / "memory" / "short" / "items.jsonl").write_text("memory", encoding="utf-8")
    (task_dir / "logs" / "task.log").write_text("log", encoding="utf-8")
    (task_dir / "index" / "chunks" / "chunks.jsonl").write_text("index", encoding="utf-8")

    response = client.get("/api/storage/status")

    assert response.status_code == 200
    payload = response.json()
    task_payload = next(item for item in payload["tasks"] if item["task_id"] == task_id)
    assert task_payload["screenshots_bytes"] == 3
    assert task_payload["memory_bytes"] == 6
    assert task_payload["logs_bytes"] >= 3
    assert task_payload["index_bytes"] == 5


def test_storage_cleanup_removes_selected_categories_and_rebuilds_index() -> None:
    task_id = f"2026-06-26_storage_cleanup_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "target": {"type": "screen", "screen_id": 1},
        },
    )
    task_dir = Path(state.current_task_paths(task_id=task_id)["task_dir"])
    (task_dir / "screenshots" / "evidence").mkdir(parents=True, exist_ok=True)
    (task_dir / "logs").mkdir(parents=True, exist_ok=True)
    (task_dir / "memory" / "compact").mkdir(parents=True, exist_ok=True)
    (task_dir / "index" / "chunks").mkdir(parents=True, exist_ok=True)
    (task_dir / "screenshots" / "evidence" / "old.png").write_bytes(b"abc")
    (task_dir / "logs" / "task.log").write_text("log", encoding="utf-8")
    (task_dir / "memory" / "compact" / "segments.jsonl").write_text(
        '{"from":"2026-10-25T16:00:00Z","to":"2026-10-25T16:01:00Z","info":"有效摘要","repeat_count":2}\n',
        encoding="utf-8",
    )
    (task_dir / "index" / "chunks" / "stale.jsonl").write_text('{"info":"旧索引"}\n', encoding="utf-8")

    response = client.post(
        "/api/storage/cleanup",
        json={"task_id": task_id, "screenshots": True, "logs": True, "index": True, "rebuild_index": True, "vacuum": True},
    )

    assert response.status_code == 200
    payload = response.json()
    cleanup = payload["cleanup"]
    assert cleanup["screenshots"]["deleted_bytes"] == 3
    assert cleanup["logs"]["deleted_bytes"] >= 3
    assert cleanup["index"]["deleted_bytes"] >= len('{"info":"旧索引"}\n')
    assert cleanup["memory"]["deleted_bytes"] == 0
    assert cleanup["index_rebuild"]["indexed_chunks"] == 1
    assert cleanup["sqlite_vacuum"]["before_bytes"] >= cleanup["sqlite_vacuum"]["after_bytes"]
    assert not (task_dir / "screenshots" / "evidence" / "old.png").exists()
    assert not (task_dir / "logs" / "task.log").exists()
    assert (task_dir / "memory" / "compact" / "segments.jsonl").exists()


def test_storage_cleanup_can_remove_empty_evidence_dir_without_deleting_screenshots() -> None:
    task_id = f"2026-06-26_empty_evidence_cleanup_{uuid4().hex}"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "target": {"type": "screen", "screen_id": 1},
        },
    )
    task_dir = Path(state.current_task_paths(task_id=task_id)["task_dir"])
    evidence_dir = task_dir / "screenshots" / "evidence"
    latest_dir = task_dir / "screenshots" / "latest"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "latest-frame-test.png").write_bytes(b"latest")

    response = client.post("/api/storage/cleanup", json={"task_id": task_id, "empty_evidence": True})

    assert response.status_code == 200
    cleanup = response.json()["cleanup"]
    assert cleanup["empty_evidence"]["deleted_paths"] == 1
    assert not evidence_dir.exists()
    assert (latest_dir / "latest-frame-test.png").exists()
