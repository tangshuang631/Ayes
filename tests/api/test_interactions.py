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
                "model": "Molmo-7B-D-0924",
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
