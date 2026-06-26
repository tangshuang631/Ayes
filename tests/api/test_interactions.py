from fastapi.testclient import TestClient
from pathlib import Path

from ayes.api.server import app, state
from ayes.capture.models import CaptureFrame
import time


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


def test_recent_timeline_supports_minutes_and_task_filter() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/run-once")
    response = client.get("/api/timeline/recent", params={"task_id": "task_web", "minutes": 5, "limit": 20})
    assert response.status_code == 200
    assert "items" in response.json()


def test_start_watch_endpoint_marks_background_running() -> None:
    client.post("/api/watch/load-screen")
    response = client.post("/api/watch/start")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"]["is_running"] is True
    stop_response = client.post("/api/watch/stop")
    assert stop_response.status_code == 200


def test_stop_watch_endpoint_clears_background_running() -> None:
    client.post("/api/watch/load-screen")
    client.post("/api/watch/start")
    response = client.post("/api/watch/stop")
    assert response.status_code == 200
    assert response.json()["status"]["is_running"] is False


def test_control_status_pause_and_resume_flow() -> None:
    client.post("/api/watch/load-screen")

    status_response = client.get("/api/control/status")
    assert status_response.status_code == 200
    assert status_response.json()["is_paused"] is False

    pause_response = client.post("/api/control/pause-all")
    assert pause_response.status_code == 200
    pause_payload = pause_response.json()
    assert pause_payload["status"]["is_paused"] is True
    assert pause_payload["status"]["pause_reason"] == "manual"

    resume_response = client.post("/api/control/resume-all")
    assert resume_response.status_code == 200
    resume_payload = resume_response.json()
    assert resume_payload["status"]["is_paused"] is False
    assert resume_payload["status"]["pause_reason"] is None


def test_control_open_data_dir_returns_current_task_paths() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_screen_monitor",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    response = client.get("/api/control/open-data-dir")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data_dir"].endswith("/runtime/tasks/2026-06-26/2026-06-26_screen_monitor")
    assert payload["screenshots_dir"].endswith("/screenshots")
    assert payload["memory_dir"].endswith("/memory")
    assert payload["config_dir"].endswith("/config")
    assert payload["archive_dir"].endswith("/runtime/archive")


def test_control_open_data_dir_accepts_task_id() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_screen_monitor",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-25_other_monitor",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.get("/api/control/open-data-dir", params={"task_id": "2026-06-26_screen_monitor"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "2026-06-26_screen_monitor"
    assert payload["task_dir"].endswith("/runtime/tasks/2026-06-26/2026-06-26_screen_monitor")


def test_control_open_data_dir_exposes_roi_task_directory() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_process_monitor_Chrome__roi_price",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "roi": {"parent_task_id": "2026-06-26_process_monitor_Chrome", "roi_name": "价格监控"},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.get("/api/control/open-data-dir", params={"task_id": "2026-06-26_process_monitor_Chrome__roi_price"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_dir"].endswith("/runtime/tasks/2026-06-26/2026-06-26_process_monitor_Chrome/roi/2026-06-26_process_monitor_Chrome__roi_price")
    assert payload["roi_dir"].endswith("/runtime/tasks/2026-06-26/2026-06-26_process_monitor_Chrome/roi/2026-06-26_process_monitor_Chrome__roi_price")


def test_task_logs_are_written_to_task_directory() -> None:
    task_id = "2026-06-26_task_log_files"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": task_id,
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.get("/api/control/open-data-dir", params={"task_id": task_id})

    assert response.status_code == 200
    logs_dir = response.json()["logs_dir"]
    log_files = list(Path(logs_dir).glob("*.log.jsonl"))
    assert log_files
    assert "监控任务已装载" in log_files[-1].read_text(encoding="utf-8")


def test_task_list_includes_roi_child_tasks_when_present() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_process_monitor_Chrome",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_process_monitor_Chrome__roi_price",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "roi": {
                "parent_task_id": "2026-06-26_process_monitor_Chrome",
                "roi_name": "价格监控",
            },
            "watch_intent": {"enabled": False},
        },
    )

    response = client.get("/api/tasks")

    assert response.status_code == 200
    payload = response.json()
    roi_task = next(item for item in payload["items"] if item["task_id"] == "2026-06-26_process_monitor_Chrome__roi_price")
    assert roi_task["spec"]["roi"]["parent_task_id"] == "2026-06-26_process_monitor_Chrome"
    assert roi_task["spec"]["roi"]["roi_name"] == "价格监控"


def test_status_exposes_task_tree_with_roi_children() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_process_monitor_Chrome",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "watch_intent": {"enabled": False},
        },
    )
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-26_process_monitor_Chrome__roi_price",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "roi": {
                "parent_task_id": "2026-06-26_process_monitor_Chrome",
                "roi_name": "价格监控",
            },
            "watch_intent": {"enabled": False},
        },
    )

    response = client.get("/api/status")

    assert response.status_code == 200
    tree = response.json()["task_context"]["task_tree"]
    parent = next(item for item in tree if item["task_id"] == "2026-06-26_process_monitor_Chrome")
    assert any(child["task_id"] == "2026-06-26_process_monitor_Chrome__roi_price" for child in parent["children"])


def test_task_roi_api_creates_named_roi_child_task_with_independent_directory() -> None:
    parent_task_id = "2026-06-26_process_monitor_Chrome_roi_api"
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": parent_task_id,
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "watch_intent": {"enabled": False},
        },
    )

    response = client.post(
        f"/api/tasks/{parent_task_id}/roi",
        json={
            "roi_name": "价格监控",
            "region": {
                "region_id": "roi_price",
                "name": "价格监控",
                "x": 10,
                "y": 20,
                "w": 300,
                "h": 120,
                "coordinate_space": "target",
            },
            "enabled": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["roi"]["parent_task_id"] == parent_task_id
    assert payload["roi"]["roi_name"] == "价格监控"
    assert payload["roi"]["enabled"] is True
    assert payload["task"]["task_id"].startswith(f"{parent_task_id}__roi_")
    assert payload["task_paths"]["task_dir"].endswith(f"/runtime/tasks/2026-06-26/{parent_task_id}/roi/{payload['task']['task_id']}")

    list_response = client.get(f"/api/tasks/{parent_task_id}/roi")
    assert list_response.status_code == 200
    assert any(item["roi_task_id"] == payload["task"]["task_id"] for item in list_response.json()["items"])


def test_task_roi_api_patches_enabled_and_name_without_losing_task_spec() -> None:
    parent_task_id = "2026-06-26_process_monitor_Chrome_roi_patch"
    create_response = client.post(
        "/api/watch/load-configured",
        json={
            "task_id": parent_task_id,
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "watch_intent": {"enabled": False},
        },
    )
    assert create_response.status_code == 200
    roi_response = client.post(
        f"/api/tasks/{parent_task_id}/roi",
        json={
            "roi_name": "价格监控",
            "region": {"region_id": "roi_price", "name": "价格监控", "x": 1, "y": 2, "w": 30, "h": 40},
        },
    )
    roi_task_id = roi_response.json()["task"]["task_id"]

    patch_response = client.patch(
        f"/api/tasks/{parent_task_id}/roi/{roi_task_id}",
        json={"roi_name": "主价格区", "enabled": False},
    )

    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["roi"]["roi_name"] == "主价格区"
    assert payload["roi"]["enabled"] is False
    task_response = client.get(f"/api/watch/task/{roi_task_id}")
    assert task_response.json()["spec"]["roi"]["roi_name"] == "主价格区"
    assert task_response.json()["spec"]["roi"]["enabled"] is False


def test_task_alert_api_updates_task_webhook_settings() -> None:
    task_id = "2026-06-26_alert_task"
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
        f"/api/tasks/{task_id}/alert",
        json={
            "enabled": True,
            "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            "message_title": "价格提醒",
            "message_template": "任务 {task_id} 命中：{summary}",
            "cooldown_sec": 30,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["alert"]["enabled"] is True
    assert payload["alert"]["webhook_url"].endswith("key=test")
    assert payload["alert"]["message_title"] == "价格提醒"
    task_response = client.get(f"/api/watch/task/{task_id}")
    assert task_response.json()["spec"]["alert"]["enabled"] is True
    assert task_response.json()["spec"]["alert"]["cooldown_sec"] == 30


def test_control_status_exposes_cleanup_reminder_state() -> None:
    client.post(
        "/api/control/cleanup-reminder",
        json={"suppress_forever": True, "next_check_after_days": 7},
    )

    response = client.get("/api/control/status")
    assert response.status_code == 200
    payload = response.json()
    assert "cleanup_reminder" in payload
    assert payload["cleanup_reminder"]["suppress_forever"] is True
    assert payload["cleanup_reminder"]["next_check_after_days"] == 7


def test_control_settings_round_trip_virtual_display_capture_preference() -> None:
    response = client.post(
        "/api/control/settings",
        json={"capture_screen_when_display_sleep": True, "cleanup_reminder_days": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["capture_screen_when_display_sleep"] is True
    assert payload["settings"]["cleanup_reminder_days"] == 5
    assert payload["settings"]["capture_sleep_note"]


def test_control_settings_round_trip_latest_frame_hotkey() -> None:
    response = client.post(
        "/api/control/settings",
        json={"latest_frame_hotkey": "cmd+shift+9"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["latest_frame_hotkey"] == "cmd+shift+9"

    disabled = client.post(
        "/api/control/settings",
        json={"latest_frame_hotkey": ""},
    )
    assert disabled.status_code == 200
    assert disabled.json()["settings"]["latest_frame_hotkey"] == ""


def test_control_settings_rejects_dangerous_latest_frame_hotkey() -> None:
    response = client.post(
        "/api/control/settings",
        json={"latest_frame_hotkey": "cmd+v"},
    )

    assert response.status_code == 400


def test_current_task_regions_can_be_added_and_deleted_interactively() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_interactive_roi",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    add_response = client.post(
        "/api/watch/current/regions",
        json={
            "region": {
                "region_id": "roi_price",
                "name": "价格区",
                "x": 10,
                "y": 20,
                "w": 120,
                "h": 60,
                "coordinate_space": "target",
                "enabled": True,
            }
        },
    )

    assert add_response.status_code == 200
    assert add_response.json()["target"]["regions"][0]["region_id"] == "roi_price"
    assert state.current_spec is not None
    assert state.current_spec.target.regions[0].name == "价格区"

    delete_response = client.delete("/api/watch/current/regions/roi_price")

    assert delete_response.status_code == 200
    assert delete_response.json()["target"]["regions"] == []
    assert state.current_spec.target.regions == []


def test_control_cleanup_reminder_check_writes_audit_log_when_due() -> None:
    now = time.time()
    client.post(
        "/api/control/cleanup-reminder",
        json={"suppress_forever": False, "last_prompt_at": now - (8 * 24 * 60 * 60)},
    )
    response = client.post("/api/control/cleanup-reminder/check", json={"now": now})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "prompt_due"
    logs_response = client.get("/api/logs", params={"category": "control", "minutes": 60})
    assert logs_response.status_code == 200
    assert any(item["message"] == "数据清理提醒已到期" for item in logs_response.json()["items"])


def test_background_watch_triggers_cleanup_reminder_check_automatically() -> None:
    now = time.time()
    client.post(
        "/api/control/cleanup-reminder",
        json={"suppress_forever": False, "last_prompt_at": now - (8 * 24 * 60 * 60)},
    )
    client.post("/api/watch/load-screen")
    start_response = client.post("/api/watch/start")
    assert start_response.status_code == 200
    time.sleep(0.4)
    client.post("/api/watch/stop")

    logs_response = client.get("/api/logs", params={"category": "control", "minutes": 60})
    assert logs_response.status_code == 200
    assert any(item["message"] == "数据清理提醒已到期" for item in logs_response.json()["items"])


def test_cleanup_reminder_interval_can_be_configured() -> None:
    response = client.post(
        "/api/control/cleanup-reminder",
        json={"suppress_forever": False, "next_check_after_days": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cleanup_reminder"]["next_check_after_days"] == 3


def test_background_watch_persists_latest_captured_frame_to_fresh_screenshot() -> None:
    client.post("/api/watch/load-screen")
    assert state.current_runner is not None
    state.remember_screenshot(path="runtime/web-last-frame.png", width=1, height=1)
    state.current_runner._last_captured_frame = CaptureFrame(
        frame_id="frame_background_fresh",
        timestamp=time.time(),
        target_type="screen",
        target_id="main",
        width=3,
        height=2,
        image_bytes=b"fresh-png-bytes",
    )

    state.persist_latest_screenshot()

    response = client.get("/api/screenshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["image_width"] == 3
    assert payload["image_height"] == 2
    assert "latest-frame-" in payload["path"]
    assert not payload["path"].endswith("runtime/web-last-frame.png")


def test_background_watch_skips_evidence_screenshot_when_persistence_disabled() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_no_screenshot_persistence",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {"save_ocr_screenshots": False},
            "watch_intent": {"enabled": False},
        },
    )
    assert state.current_runner is not None
    state.remember_screenshot(path="runtime/previous.png", width=1, height=1)
    state.current_runner._last_captured_frame = CaptureFrame(
        frame_id="frame_background_no_persist",
        timestamp=time.time(),
        target_type="screen",
        target_id="main",
        width=3,
        height=2,
        image_bytes=b"fresh-png-bytes",
    )

    payload = state.persist_latest_screenshot()

    assert payload is not None
    assert state.last_screenshot_path is not None
    assert "latest-frame-" in payload["path"]


def test_status_endpoint_marks_when_frontend_exit_can_stop_service() -> None:
    client.post("/api/watch/load-screen")
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert "can_shutdown_service" in payload
    assert payload["can_shutdown_service"] is True

    client.post("/api/watch/start")
    running_response = client.get("/api/status")
    running_payload = running_response.json()
    client.post("/api/watch/stop")
    assert running_payload["can_shutdown_service"] is False


def test_app_session_open_and_close_exposes_frontend_connection_state() -> None:
    open_response = client.post("/api/app/session-open", json={"session_id": "web_test_1"})
    assert open_response.status_code == 200
    assert open_response.json()["connected_frontends"] >= 1

    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    assert status_response.json()["connected_frontends"] >= 1

    close_response = client.post("/api/app/session-close", json={"session_id": "web_test_1"})
    assert close_response.status_code == 200
    assert close_response.json()["connected_frontends"] == 0


def test_app_session_heartbeat_keeps_session_alive() -> None:
    open_response = client.post("/api/app/session-open", json={"session_id": "web_test_hb"})
    assert open_response.status_code == 200

    heartbeat_response = client.post("/api/app/session-heartbeat", json={"session_id": "web_test_hb"})
    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json()["connected_frontends"] >= 1

    close_response = client.post("/api/app/session-close", json={"session_id": "web_test_hb"})
    assert close_response.status_code == 200


def test_frontend_connection_blocks_shutdown_when_idle() -> None:
    client.post("/api/app/session-open", json={"session_id": "web_test_idle_guard"})
    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    assert status_response.json()["can_shutdown_service"] is False

    gate_response = client.get("/api/app/can-shutdown")
    assert gate_response.status_code == 200
    assert gate_response.json()["can_shutdown_service"] is False

    client.post("/api/app/session-close", json={"session_id": "web_test_idle_guard"})
    after_close = client.get("/api/app/can-shutdown")
    assert after_close.status_code == 200
    assert "can_shutdown_service" in after_close.json()


def test_background_watch_writes_action_logs_when_refresh_click_enabled() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_action_logs",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
            "actions": {
                "refresh_click": {
                    "enabled": True,
                    "point": {"x": 10, "y": 20},
                    "coordinate_space": "screen",
                    "interval_sec": 1,
                    "cooldown_sec": 1,
                }
            },
        },
    )
    client.post("/api/watch/start")
    response = client.get("/api/logs", params={"task_id": "task_action_logs", "category": "action"})
    client.post("/api/watch/stop")
    assert response.status_code == 200
    assert "items" in response.json()


def test_events_endpoint_supports_action_source_filter() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_action_events",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
            "actions": {
                "refresh_click": {
                    "enabled": True,
                    "point": {"x": 10, "y": 20},
                    "coordinate_space": "screen",
                    "interval_sec": 1,
                    "cooldown_sec": 1,
                }
            },
        },
    )
    client.post("/api/watch/start")
    response = client.get("/api/events", params={"task_id": "task_action_events", "source": "action", "minutes": 15})
    client.post("/api/watch/stop")
    assert response.status_code == 200
    assert "items" in response.json()


def test_events_endpoint_supports_match_source_filter() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_match_events",
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
                "summary": "库存恢复提醒",
                "queries": ["库存恢复"],
            },
        },
    )
    client.post("/api/watch/run-once")
    response = client.get("/api/events", params={"task_id": "task_match_events", "source": "semantic_match", "minutes": 15})
    client.post("/api/watch/stop")
    assert response.status_code == 200
    assert "items" in response.json()


def test_task_lifecycle_list_switch_and_delete_flow() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-25__price_watch",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/run-once")
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "2026-06-25__stock_watch",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        },
    )
    client.post("/api/watch/run-once")

    list_response = client.get("/api/tasks", params={"limit": 500})
    assert list_response.status_code == 200
    tasks_payload = list_response.json()
    assert tasks_payload["count"] >= 2
    assert any(item["task_id"] == "2026-06-25__price_watch" for item in tasks_payload["items"])

    switch_response = client.post("/api/watch/switch-task", json={"task_id": "2026-06-25__price_watch"})
    assert switch_response.status_code == 200
    switch_payload = switch_response.json()
    assert switch_payload["status"] == "switched"
    assert switch_payload["task"]["task_id"] == "2026-06-25__price_watch"

    ask_response = client.get("/api/ask", params={"question": "最近发生了什么", "minutes": 5})
    assert ask_response.status_code == 200
    assert ask_response.json()["task_id"] == "2026-06-25__price_watch"

    delete_response = client.delete("/api/watch/task/2026-06-25__stock_watch")
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["status"] == "deleted"
    assert delete_payload["deleted"]["tasks"] == 1

    missing_task_response = client.get("/api/watch/task/2026-06-25__stock_watch")
    assert missing_task_response.status_code == 404


def test_events_endpoint_supports_vision_source_filter() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_vision_events",
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
    client.post("/api/watch/run-once")
    response = client.get("/api/events", params={"task_id": "task_vision_events", "source": "vision", "minutes": 15})
    client.post("/api/watch/stop")
    assert response.status_code == 200
    assert "items" in response.json()


def test_minimal_human_verifiable_monitoring_flow() -> None:
    client.post(
        "/api/watch/load-configured",
        json={
            "task_id": "task_human_flow",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_flow",
                        "name": "价格区",
                        "x": 0,
                        "y": 0,
                        "w": 200,
                        "h": 120,
                        "coordinate_space": "target",
                        "enabled": True,
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
    run_once = client.post("/api/watch/run-once")
    assert run_once.status_code == 200

    status = client.get("/api/status")
    timeline = client.get("/api/timeline/recent", params={"task_id": "task_human_flow", "minutes": 5, "limit": 20})
    snippets = client.get("/api/ocr/snippets", params={"task_id": "task_human_flow", "minutes": 5, "limit": 20})
    logs = client.get("/api/logs", params={"task_id": "task_human_flow", "minutes": 15})
    ask = client.get("/api/ask", params={"task_id": "task_human_flow", "question": "最近发生了什么", "minutes": 5})
    memory_items = client.get("/api/memory/items", params={"task_id": "task_human_flow", "minutes": 5, "limit": 20})

    assert status.status_code == 200
    status_payload = status.json()
    assert "health_summary" in status_payload
    assert "recent_memory" in status_payload["health_summary"]
    assert "recent_logs" in status_payload["health_summary"]
    assert timeline.status_code == 200
    assert snippets.status_code == 200
    assert logs.status_code == 200
    assert ask.status_code == 200
    assert memory_items.status_code == 200

    timeline_items = timeline.json()["items"]
    assert isinstance(timeline_items, list)
    if timeline_items:
        assert "preview_overlay" in timeline_items[0]

    snippet_items = snippets.json()["items"]
    assert isinstance(snippet_items, list)
    if snippet_items:
        assert "preview_overlay" in snippet_items[0]

    ask_payload = ask.json()
    assert "answer" in ask_payload
    assert "matched_events" in ask_payload
    assert "time_range" in ask_payload
    memory_items_payload = memory_items.json()
    assert "items" in memory_items_payload
