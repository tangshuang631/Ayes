from ayes.cli import agent_tool
import json
import os
from pathlib import Path


def test_agent_tool_ensure_service_uses_local_helper(monkeypatch, capsys) -> None:
    calls = []

    monkeypatch.setattr(agent_tool, "ensure_local_service_started", lambda base_url: calls.append(base_url))
    exit_code = agent_tool.main(["ensure-service"])

    assert exit_code == 0
    assert calls == ["http://127.0.0.1:8770"]
    assert '"status": "service_ready"' in capsys.readouterr().out


def test_agent_tool_targets_reads_targets_endpoint(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        return {"screens": [], "processes": []}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["targets"])

    assert exit_code == 0
    assert recorded["path"] == "/api/targets"
    assert recorded["method"] == "GET"
    assert '"screens": []' in capsys.readouterr().out


def test_agent_tool_task_reads_watch_task_endpoint(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        return {"task_id": "task_demo"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["task", "--task-id", "task_demo"])

    assert exit_code == 0
    assert recorded["path"] == "/api/watch/task/task_demo"
    assert recorded["method"] == "GET"
    assert '"task_id": "task_demo"' in capsys.readouterr().out


def test_agent_tool_tasks_reads_task_list_endpoint(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        return {"items": [{"task_id": "2026-06-25__price_watch"}], "count": 1}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["tasks"])

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks?limit=100"
    assert recorded["method"] == "GET"
    assert '"2026-06-25__price_watch"' in capsys.readouterr().out


def test_agent_tool_memory_policy_reads_task_policy(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"memory_policy": {"task_id": "task_demo", "short_term_retain_days": 7}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["memory-policy", "--task-id", "task_demo"])

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_demo/memory-policy"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"short_term_retain_days": 7' in capsys.readouterr().out


def test_agent_tool_memory_policy_updates_task_policy(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "memory_policy": {"task_id": "task_demo", "disable_auto_cleanup": True}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "memory-policy",
            "--task-id",
            "task_demo",
            "--short-term-days",
            "10",
            "--long-term-days",
            "25",
            "--disable-auto-cleanup",
            "true",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_demo/memory-policy"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {
        "short_term_retain_days": 10,
        "long_term_retain_days": 25,
        "disable_auto_cleanup": True,
    }
    assert '"disable_auto_cleanup": true' in capsys.readouterr().out


def test_agent_tool_memory_cleanup_posts_task_cleanup(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "cleanup": {"deleted_events": 2}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["memory-cleanup", "--task-id", "task_demo"])

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_demo/memory-cleanup"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {}
    assert '"deleted_events": 2' in capsys.readouterr().out


def test_agent_tool_roi_list_reads_parent_roi_endpoint(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"items": [{"roi_task_id": "task_parent__roi_price", "roi_name": "价格监控"}]}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["roi", "list", "--task-id", "task_parent"])

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_parent/roi"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"价格监控"' in capsys.readouterr().out


def test_agent_tool_roi_paths_url_encode_non_ascii_task_ids(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        return {"items": []}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["roi", "list", "--task-id", "2026-06-26_process_monitor_哔哩哔哩"])

    assert exit_code == 0
    assert "%E5%93%94%E5%93%A9%E5%93%94%E5%93%A9" in recorded["path"]
    assert recorded["path"].startswith("/api/tasks/2026-06-26_process_monitor_")
    assert '"items": []' in capsys.readouterr().out


def test_agent_tool_roi_create_posts_named_region_payload(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "roi": {"roi_name": "价格监控"}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "roi",
            "create",
            "--task-id",
            "task_parent",
            "--roi-name",
            "价格监控",
            "--region",
            "roi_price|价格监控|10|20|300|120|target",
            "--enabled",
            "true",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_parent/roi"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["roi_name"] == "价格监控"
    assert recorded["payload"]["enabled"] is True
    assert recorded["payload"]["region"]["region_id"] == "roi_price"
    assert recorded["payload"]["region"]["w"] == 300
    assert '"status": "ok"' in capsys.readouterr().out


def test_agent_tool_roi_update_patches_child_roi(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "roi": payload}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "roi",
            "update",
            "--task-id",
            "task_parent",
            "--roi-task-id",
            "task_parent__roi_price",
            "--roi-name",
            "主价格区",
            "--enabled",
            "false",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_parent/roi/task_parent__roi_price"
    assert recorded["method"] == "PATCH"
    assert recorded["payload"] == {"roi_name": "主价格区", "enabled": False}
    assert '"enabled": false' in capsys.readouterr().out


def test_agent_tool_roi_delete_calls_child_roi_delete_endpoint(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "deleted", "task_id": "task_parent__roi_price"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "roi",
            "delete",
            "--task-id",
            "task_parent",
            "--roi-task-id",
            "task_parent__roi_price",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_parent/roi/task_parent__roi_price"
    assert recorded["method"] == "DELETE"
    assert recorded["payload"] is None
    assert '"status": "deleted"' in capsys.readouterr().out


def test_agent_tool_task_alert_posts_webhook_settings(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "alert": payload}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "task-alert",
            "--task-id",
            "task_parent__roi_price",
            "--enabled",
            "true",
            "--webhook-url",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            "--message-title",
            "价格提醒",
            "--message-template",
            "任务 {task_id} 命中：{summary}",
            "--cooldown-sec",
            "30",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/tasks/task_parent__roi_price/alert"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["enabled"] is True
    assert recorded["payload"]["message_title"] == "价格提醒"
    assert recorded["payload"]["cooldown_sec"] == 30
    assert '"价格提醒"' in capsys.readouterr().out


def test_agent_tool_switch_task_posts_expected_payload(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "switched", "task": {"task_id": "2026-06-25__price_watch"}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["switch-task", "--task-id", "2026-06-25__price_watch"])

    assert exit_code == 0
    assert recorded["path"] == "/api/watch/switch-task"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {"task_id": "2026-06-25__price_watch"}
    assert '"status": "switched"' in capsys.readouterr().out


def test_agent_tool_delete_task_calls_expected_endpoint(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        return {"status": "deleted", "deleted": {"tasks": 1}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["delete-task", "--task-id", "2026-06-25__stock_watch"])

    assert exit_code == 0
    assert recorded["path"] == "/api/watch/task/2026-06-25__stock_watch"
    assert recorded["method"] == "DELETE"
    assert '"status": "deleted"' in capsys.readouterr().out


def test_agent_tool_recent_builds_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"items": [], "ok": True}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["recent", "--task-id", "task_demo", "--minutes", "7", "--limit", "9"])

    assert exit_code == 0
    assert recorded["base_url"] == "http://127.0.0.1:8770"
    assert recorded["path"] == "/api/timeline/recent?task_id=task_demo&minutes=7&limit=9"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"ok": true' in capsys.readouterr().out


def test_agent_tool_observe_live_builds_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"schema_version": "1.0", "task_id": "task_demo", "agent_hints": {"suggested_next_steps": []}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["observe-live", "--task-id", "task_demo", "--minutes", "7", "--limit", "9"])

    assert exit_code == 0
    assert recorded["base_url"] == "http://127.0.0.1:8770"
    assert recorded["path"] == "/api/agent/observe-live?task_id=task_demo&minutes=7&limit=9"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"schema_version": "1.0"' in capsys.readouterr().out


def test_agent_tool_activity_builds_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"task_id": "task_demo", "primary_summary": "最近在写 activity"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["activity", "--task-id", "task_demo", "--minutes", "7"])

    assert exit_code == 0
    assert recorded["base_url"] == "http://127.0.0.1:8770"
    assert recorded["path"] == "/api/activity?task_id=task_demo&minutes=7"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"primary_summary": "最近在写 activity"' in capsys.readouterr().out


def test_agent_tool_alerts_builds_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"items": [], "count": 0}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["alerts", "--task-id", "task_demo", "--minutes", "15", "--limit", "5"])

    assert exit_code == 0
    assert recorded["path"] == "/api/alerts/recent?task_id=task_demo&minutes=15&limit=5"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"count": 0' in capsys.readouterr().out


def test_agent_tool_memory_items_compact_builds_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"task_id": "task_demo", "compact": True, "items": []}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["memory-items", "--task-id", "task_demo", "--minutes", "5", "--limit", "5", "--compact"])

    assert exit_code == 0
    assert recorded["base_url"] == "http://127.0.0.1:8770"
    assert recorded["path"] == "/api/memory/items?task_id=task_demo&minutes=5&limit=5&compact=True"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"compact": true' in capsys.readouterr().out


def test_agent_tool_memory_items_defaults_to_compact(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        return {"task_id": "task_demo", "compact": True, "items": []}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["memory-items", "--task-id", "task_demo", "--minutes", "5", "--limit", "5"])

    assert exit_code == 0
    assert recorded["path"] == "/api/memory/items?task_id=task_demo&minutes=5&limit=5&compact=True"
    assert '"compact": true' in capsys.readouterr().out


def test_agent_tool_memory_items_raw_disables_compact(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        return {"task_id": "task_demo", "compact": False, "items": []}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["memory-items", "--task-id", "task_demo", "--minutes", "5", "--limit", "5", "--raw"])

    assert exit_code == 0
    assert recorded["path"] == "/api/memory/items?task_id=task_demo&minutes=5&limit=5&compact=False"
    assert '"compact": false' in capsys.readouterr().out


def test_agent_tool_control_pause_all_posts_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": {"is_paused": True}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["control", "pause-all"])

    assert exit_code == 0
    assert recorded["path"] == "/api/control/pause-all"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {}
    assert '"is_paused": true' in capsys.readouterr().out


def test_agent_tool_control_status_reads_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"is_paused": False, "data_dir": "/tmp/runtime"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["control", "status"])

    assert exit_code == 0
    assert recorded["path"] == "/api/control/status"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"is_paused": false' in capsys.readouterr().out


def test_agent_tool_control_cleanup_reminder_posts_expected_payload(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "cleanup_reminder": {"suppress_forever": True}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["control", "cleanup-reminder", "--suppress-forever", "true"])

    assert exit_code == 0
    assert recorded["path"] == "/api/control/cleanup-reminder"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["suppress_forever"] is True
    assert '"suppress_forever": true' in capsys.readouterr().out


def test_agent_tool_control_cleanup_reminder_posts_next_check_after_days(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "cleanup_reminder": {"next_check_after_days": 3}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["control", "cleanup-reminder", "--next-check-after-days", "3"])

    assert exit_code == 0
    assert recorded["path"] == "/api/control/cleanup-reminder"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["next_check_after_days"] == 3
    assert '"next_check_after_days": 3' in capsys.readouterr().out


def test_agent_tool_vision_models_reads_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"available": False, "binary_available": True, "service_reachable": False}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["vision", "models"])

    assert exit_code == 0
    assert recorded["path"] == "/api/vision/models"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"binary_available": true' in capsys.readouterr().out


def test_agent_tool_vision_prepare_posts_expected_payload(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"requested_by": "agent_enable_local_vision", "default_local_model": "qwen2.5vl:7b"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["vision", "prepare", "--requested-by", "agent_enable_local_vision"])

    assert exit_code == 0
    assert recorded["path"] == "/api/vision/prepare"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {"requested_by": "agent_enable_local_vision"}
    assert '"default_local_model": "qwen2.5vl:7b"' in capsys.readouterr().out


def test_agent_tool_vision_enable_posts_expected_payload(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "vision_settings": payload}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "vision",
            "enable",
            "--provider",
            "ollama",
            "--model",
            "qwen2.5vl:7b",
            "--auto-use-when-available",
            "true",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/vision/settings"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["enabled"] is True
    assert recorded["payload"]["provider"] == "ollama"
    assert recorded["payload"]["model"] == "qwen2.5vl:7b"
    assert recorded["payload"]["auto_use_when_available"] is True
    assert '"enabled": true' in capsys.readouterr().out


def test_agent_tool_vision_disable_posts_expected_payload(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "ok", "vision_settings": payload}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["vision", "disable"])

    assert exit_code == 0
    assert recorded["path"] == "/api/vision/settings"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {"enabled": False}
    assert '"enabled": false' in capsys.readouterr().out


def test_agent_tool_region_bind_contract_reads_expected_path(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"bind_version": "1.0", "request": {}, "result": {}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["region-bind-contract"])

    assert exit_code == 0
    assert recorded["path"] == "/api/agent/region-bind-contract"
    assert recorded["method"] == "GET"
    assert recorded["payload"] is None
    assert '"bind_version": "1.0"' in capsys.readouterr().out


def test_agent_tool_run_once_posts_to_watch_run_once(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"events": [], "status": {"has_runner": True}}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["run-once"])

    assert exit_code == 0
    assert recorded["path"] == "/api/watch/run-once"
    assert recorded["method"] == "POST"
    assert recorded["payload"] == {}
    assert '"has_runner": true' in capsys.readouterr().out


def test_agent_tool_start_ensures_menubar_by_default(monkeypatch, capsys) -> None:
    calls = []

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        calls.append({"kind": "request", "path": path, "method": method, "payload": payload})
        return {"status": {"has_runner": True, "is_running": True}}

    def fake_ensure_menubar():
        calls.append({"kind": "menubar"})
        return {"status": "started"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    monkeypatch.setattr(agent_tool, "ensure_local_menubar_started", fake_ensure_menubar)
    exit_code = agent_tool.main(["start"])

    assert exit_code == 0
    assert calls == [
        {"kind": "request", "path": "/api/watch/start", "method": "POST", "payload": {}},
        {"kind": "menubar"},
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["menubar"]["status"] == "started"


def test_build_menubar_app_bundle_uses_openable_app_layout(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    executable = app_path / "Contents" / "MacOS" / "AyesMenubar"
    source = app_path / "Contents" / "MacOS" / "AyesMenubar.m"
    plist = app_path / "Contents" / "Info.plist"
    assert app_path.name == "Ayes 菜单栏.app"
    assert executable.exists()
    assert os.access(executable, os.X_OK)
    assert source.exists()
    assert "LSUIElement" in plist.read_text(encoding="utf-8")
    assert "NSStatusBar" in source.read_text(encoding="utf-8")
    assert "/api/control/pause-all" in source.read_text(encoding="utf-8")
    assert "设置..." in source.read_text(encoding="utf-8")
    assert "openSettings:" in source.read_text(encoding="utf-8")
    assert "/api/control/sampling" in source.read_text(encoding="utf-8")
    assert "postJsonSync" in source.read_text(encoding="utf-8")
    assert "addTaskSubmenuWithTask:" in source.read_text(encoding="utf-8")
    assert "/api/control/task-settings" in source.read_text(encoding="utf-8")


def test_build_menubar_settings_uses_ollama_model_dropdown(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert "/api/vision/models" in source
    assert "NSPopUpButton *visionPopup" in source
    assert "is_vision_model" in source
    assert "当前选择增强模型为非视觉模型，已关闭本地模型增强。" in source
    assert "visionField" not in source


def test_build_menubar_settings_does_not_overwrite_popup_model_metadata(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert "[[visionPopup lastItem] setRepresentedObject:model];" in source
    assert "[visionPopup setRepresentedObject:visionCheckbox];" not in source
    assert "[visionCheckbox setRepresentedObject:visionPopup];" not in source


def test_build_menubar_settings_posts_explicit_json_booleans(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert '@"save_ocr_screenshots": saveCheckbox.state == NSControlStateValueOn ? @YES : @NO' in source
    assert '@"save_ocr_screenshots": @(saveCheckbox.state == NSControlStateValueOn)' not in source


def test_build_menubar_native_host_prioritizes_paused_state(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert 'BOOL paused = [self statusBoolForKey:@"is_paused"];' in source
    assert 'paused ? @"Ayes 已暂停" : (running ? @"Ayes 监控中" : @"Ayes 未监控")' in source
    assert 'paused ? @"继续上次的监控" : (running ? @"暂停监控" : @"继续上次的监控")' in source
    assert 'paused ? @selector(resume:) : (running ? @selector(pause:) : @selector(resume:))' in source
    assert 'paused ? @"Ayes ◐" : (running ? @"Ayes ◉" : @"Ayes ○")' in source


def test_build_menubar_native_host_formats_task_target_titles(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert "- (NSString *)titleForTask:(NSDictionary *)task" in source
    assert "- (NSArray *)titleBitsForTarget:(NSDictionary *)target" in source
    assert '@"全屏监控"' in source
    assert '@"进程监控"' in source
    assert '@"窗口监控"' in source
    assert 'NSString *taskTitle = [self titleForTask:task];' in source
    assert "[self addTaskSubmenuWithTask:currentTask toMenu:self.menu allTasks:tasks];" in source
    assert "[self addTaskSubmenuWithTask:task toMenu:self.menu allTasks:tasks];" in source
    assert "addTaskSubmenuWithTaskId:taskId" not in source


def test_build_menubar_roi_editor_uses_screenshot_selection_and_preview(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert "RoiSelectionView" in source
    assert "RoiPreviewView" in source
    assert "/api/screenshot" in source
    assert "imagePixelRectFromDisplayedSelection" in source
    assert "displayScaleX" in source
    assert "displayScaleY" in source
    assert '"coordinate_space": @"target"' in source
    assert "ROI 预览确认" in source
    assert "请拖拽框选 ROI 区域" in source
    assert "toPath:roiPath" in source
    assert "当前任务 ROI 子任务数" not in source


def test_build_menubar_global_settings_does_not_target_current_task_sampling(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert 'BOOL isTaskSpecificSettings = taskId != nil && [taskId length] > 0;' in source
    assert "当前为全局设置；不会覆盖任务专属采样和记忆配置。" in source
    task_specific_block = source[source.index("if (isTaskSpecificSettings) {") : source.index('NSDictionary *settingsResult = [self postJsonSync:@{')]
    assert '[next setObject:resolvedTaskId forKey:@"task_id"];' in task_specific_block
    assert 'toPath:@"/api/control/sampling"' in task_specific_block


def test_build_menubar_global_settings_title_never_uses_current_task_id(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert 'NSString *resolvedTaskId = isTaskSpecificSettings ? taskId : @"";' in source
    assert 'alert.messageText = isTaskSpecificSettings ? [@"Ayes 设置 · " stringByAppendingString:resolvedTaskId] : @"Ayes 设置";' in source
    assert 'NSString *resolvedTaskId = taskId ?: [settings objectForKey:@"task_id"] ?: [sampling objectForKey:@"task_id"];' not in source


def test_build_menubar_pause_resume_refresh_after_sync_post(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert '- (NSDictionary *)postPathSync:(NSString *)path {' in source
    assert '[self postPathSync:@"/api/control/pause-all"];' in source
    assert '[self postPathSync:@"/api/control/resume-all"];' in source
    assert '[self postPath:@"/api/control/pause-all"]; self.statusItem.button.title = @"◐"; [self refreshStatus:nil];' not in source
    assert '[self postPath:@"/api/control/resume-all"]; self.statusItem.button.title = @"◉"; [self refreshStatus:nil];' not in source


def test_menubar_pid_reuse_rejects_python_fallback(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "/usr/bin/python3 -m ayes.cli.menubar\n"

    monkeypatch.setattr(agent_tool.subprocess, "run", lambda *args, **kwargs: Result())

    assert agent_tool._is_native_menubar_pid(12345) is False


def test_build_menubar_settings_activates_app_before_modal(tmp_path: Path) -> None:
    app_path = agent_tool.build_menubar_app_bundle(
        root_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        python_bin="/usr/bin/python3",
        base_url="http://127.0.0.1:8770",
    )

    source = (app_path / "Contents" / "MacOS" / "AyesMenubar.m").read_text(encoding="utf-8")
    assert "[NSApp activateIgnoringOtherApps:YES];" in source


def test_agent_tool_load_spec_posts_minimal_payload(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["base_url"] = base_url
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "loaded"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "load-spec",
            "--task-id",
            "task_demo",
            "--mode",
            "triggered",
            "--target-type",
            "process",
            "--process-name",
            "Google Chrome",
            "--query",
            "价格低于 299",
            "--webhook-url",
            "http://127.0.0.1:18999/webhook",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/watch/load-configured"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["task_id"] == "task_demo"
    assert recorded["payload"]["mode"] == "triggered"
    assert recorded["payload"]["target"] == {"type": "process", "process_name": "Google Chrome"}
    assert recorded["payload"]["watch_intent"]["enabled"] is True
    assert recorded["payload"]["watch_intent"]["queries"] == ["价格低于 299"]
    assert recorded["payload"]["alert"]["webhook_url"] == "http://127.0.0.1:18999/webhook"
    assert '"status": "loaded"' in capsys.readouterr().out


def test_agent_tool_plan_spec_posts_prompt_and_target(monkeypatch, capsys) -> None:
    recorded = {}

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"mode": "triggered", "can_apply_directly": False}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "plan-spec",
            "--task-id",
            "task_plan",
            "--prompt",
            "帮我监控 Safari 里的商品价格低于 299 时提醒我",
            "--target-type",
            "process",
            "--process-name",
            "Safari",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/agent/plan-watch-spec"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["task_id"] == "task_plan"
    assert recorded["payload"]["prompt"].startswith("帮我监控 Safari")
    assert recorded["payload"]["target"]["process_name"] == "Safari"
    assert '"mode": "triggered"' in capsys.readouterr().out


def test_agent_tool_confirm_plan_posts_region_and_refresh_confirmations(monkeypatch, tmp_path, capsys) -> None:
    recorded = {}
    plan_path = tmp_path / "plan_regions.json"
    plan_path.write_text(
        json.dumps(
            {
                "task_id": "task_plan_regions",
                "draft_spec": {
                    "spec_version": "1.0",
                    "mode": "observe",
                    "target": {"type": "process", "process_name": "Safari"},
                    "watch_intent": {"enabled": False, "summary": "", "queries": []},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "loaded", "task_id": "task_plan_regions"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "confirm-plan",
            "--plan-file",
            str(plan_path),
            "--use-entire-target",
            "--region-intent",
            "价格区:读取价格",
            "--region-intent",
            "库存区:读取库存",
            "--refresh-click-enabled",
            "--refresh-click-interval-sec",
            "45",
            "--refresh-click-coordinate-space",
            "screen",
        ]
    )

    assert exit_code == 0
    confirmations = recorded["payload"]["confirmations"]
    assert confirmations["use_entire_target"] is True
    assert len(confirmations["region_intents"]) == 2
    assert confirmations["region_intents"][0]["name"] == "价格区"
    assert confirmations["refresh_click_enabled"] is True
    assert confirmations["refresh_click_interval_sec"] == 45
    assert confirmations["refresh_click_coordinate_space"] == "screen"
    assert '"status": "loaded"' in capsys.readouterr().out


def test_agent_tool_confirm_plan_posts_refresh_click_point(monkeypatch, tmp_path, capsys) -> None:
    recorded = {}
    plan_path = tmp_path / "plan_refresh_click_point.json"
    plan_path.write_text(
        json.dumps(
            {
                "task_id": "task_plan_refresh_click_point",
                "draft_spec": {
                    "spec_version": "1.0",
                    "mode": "observe",
                    "target": {"type": "process", "process_name": "Safari"},
                    "watch_intent": {"enabled": False, "summary": "", "queries": []},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "loaded", "task_id": "task_plan_refresh_click_point"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "confirm-plan",
            "--plan-file",
            str(plan_path),
            "--refresh-click-enabled",
            "--refresh-click-point",
            "100,120",
            "--refresh-click-coordinate-space",
            "screen",
        ]
    )

    assert exit_code == 0
    confirmations = recorded["payload"]["confirmations"]
    assert confirmations["refresh_click_enabled"] is True
    assert confirmations["refresh_click_coordinate_space"] == "screen"
    assert confirmations["refresh_click_point"] == {"x": 100, "y": 120}
    assert '"status": "loaded"' in capsys.readouterr().out


def test_agent_tool_confirm_plan_posts_region_bindings(monkeypatch, tmp_path, capsys) -> None:
    recorded = {}
    plan_path = tmp_path / "plan_bindings.json"
    plan_path.write_text(
        json.dumps(
            {
                "task_id": "task_plan_bindings",
                "draft_spec": {
                    "spec_version": "1.0",
                    "mode": "observe",
                    "target": {"type": "process", "process_name": "Safari"},
                    "watch_intent": {"enabled": False, "summary": "", "queries": []},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "loaded", "task_id": "task_plan_bindings"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "confirm-plan",
            "--plan-file",
            str(plan_path),
            "--region-binding",
            "ri_price|roi_price|价格区|120|240|360|160|target|screenshot_annotation",
            "--region-binding",
            "ri_stock|roi_stock|库存区|120|420|360|120|target|external_selector",
        ]
    )

    assert exit_code == 0
    bindings = recorded["payload"]["confirmations"]["region_bindings"]
    assert len(bindings) == 2
    assert bindings[0]["region_intent_id"] == "ri_price"
    assert bindings[0]["region_id"] == "roi_price"
    assert bindings[0]["source"] == "screenshot_annotation"
    assert bindings[1]["source"] == "external_selector"
    assert '"status": "loaded"' in capsys.readouterr().out


def test_agent_tool_confirm_plan_posts_plan_file(monkeypatch, tmp_path, capsys) -> None:
    recorded = {}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "task_id": "task_plan_confirm",
                "draft_spec": {
                    "spec_version": "1.0",
                    "mode": "triggered",
                    "target": {"type": "process", "process_name": "Safari"},
                    "watch_intent": {"enabled": True, "summary": "价格低于 299 时提醒我", "queries": ["价格低于 299"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "loaded", "task_id": "task_plan_confirm"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "confirm-plan",
            "--plan-file",
            str(plan_path),
            "--webhook-url",
            "http://127.0.0.1:18999/webhook",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/watch/confirm-plan"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["plan"]["task_id"] == "task_plan_confirm"
    assert recorded["payload"]["confirmations"]["webhook_url"] == "http://127.0.0.1:18999/webhook"
    assert '"status": "loaded"' in capsys.readouterr().out


def test_agent_tool_confirm_plan_posts_custom_alert_message(monkeypatch, tmp_path, capsys) -> None:
    recorded = {}
    plan_path = tmp_path / "plan_alert_message.json"
    plan_path.write_text(
        json.dumps(
            {
                "task_id": "task_plan_alert_message",
                "draft_spec": {
                    "spec_version": "1.0",
                    "mode": "triggered",
                    "target": {"type": "process", "process_name": "Safari"},
                    "watch_intent": {"enabled": True, "summary": "库存恢复提醒", "queries": ["库存恢复"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "loaded", "task_id": "task_plan_alert_message"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "confirm-plan",
            "--plan-file",
            str(plan_path),
            "--webhook-url",
            "http://127.0.0.1:18999/webhook",
            "--alert-message-title",
            "库存提醒",
            "--alert-message-template",
            "任务 {task_id} 命中：{summary}",
        ]
    )

    assert exit_code == 0
    confirmations = recorded["payload"]["confirmations"]
    assert confirmations["webhook_url"] == "http://127.0.0.1:18999/webhook"
    assert confirmations["alert_message_title"] == "库存提醒"
    assert confirmations["alert_message_template"] == "任务 {task_id} 命中：{summary}"
    assert '"status": "loaded"' in capsys.readouterr().out


def test_agent_tool_region_bind_request_posts_expected_payload(monkeypatch, tmp_path, capsys) -> None:
    recorded = {}
    plan_path = tmp_path / "plan_region_bind_request.json"
    plan_path.write_text(
        json.dumps(
            {
                "task_id": "task_region_bind_request",
                "resolved_target": {"type": "process", "process_name": "Safari"},
                "region_intents": [{"region_intent_id": "ri_price", "name": "价格区", "purpose": "读取价格", "required": True}],
                "draft_spec": {
                    "spec_version": "1.0",
                    "mode": "observe",
                    "target": {"type": "process", "process_name": "Safari"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"bind_version": "1.0", "task_id": "task_region_bind_request"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "region-bind-request",
            "--plan-file",
            str(plan_path),
            "--capture-id",
            "cap_demo_2",
            "--image-path",
            "/tmp/cap.png",
            "--image-width",
            "1440",
            "--image-height",
            "900",
        ]
    )

    assert exit_code == 0
    assert recorded["path"] == "/api/agent/region-bind-request"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["capture_ref"]["capture_id"] == "cap_demo_2"
    assert '"bind_version": "1.0"' in capsys.readouterr().out


def test_agent_tool_region_bind_request_can_use_latest_screenshot(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    plan_path = tmp_path / "plan_region_bind_request_latest.json"
    plan_path.write_text(
        json.dumps(
            {
                "task_id": "task_region_bind_request_latest",
                "resolved_target": {"type": "process", "process_name": "Safari"},
                "region_intents": [{"region_intent_id": "ri_price", "name": "价格区", "purpose": "读取价格", "required": True}],
                "draft_spec": {
                    "spec_version": "1.0",
                    "mode": "observe",
                    "target": {"type": "process", "process_name": "Safari"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        calls.append({"path": path, "method": method, "payload": payload})
        if path == "/api/screenshot?task_id=task_region_bind_request_latest":
            return {
                "path": "/tmp/runtime/evidence/latest-cap.png",
                "image_width": 1728,
                "image_height": 1117,
            }
        if path == "/api/agent/region-bind-request":
            return {"bind_version": "1.0", "task_id": "task_region_bind_request_latest"}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(
        [
            "region-bind-request",
            "--plan-file",
            str(plan_path),
        ]
    )

    assert exit_code == 0
    assert calls[0]["path"] == "/api/screenshot?task_id=task_region_bind_request_latest"
    assert calls[1]["path"] == "/api/agent/region-bind-request"
    assert calls[1]["payload"]["capture_ref"]["capture_id"] == "cap_task_region_bind_request_latest"
    assert calls[1]["payload"]["capture_ref"]["image_path"] == "/tmp/runtime/evidence/latest-cap.png"
    assert calls[1]["payload"]["capture_ref"]["image_width"] == 1728
    assert calls[1]["payload"]["capture_ref"]["image_height"] == 1117
    assert '"bind_version": "1.0"' in capsys.readouterr().out


def test_agent_tool_region_bind_result_posts_expected_payload(monkeypatch, tmp_path, capsys) -> None:
    recorded = {}
    result_path = tmp_path / "region_bind_result.json"
    result_path.write_text(
        json.dumps(
            {
                "bind_version": "1.0",
                "task_id": "task_region_bind_result",
                "target_ref": {"type": "process", "process_name": "Safari"},
                "capture_ref": {"capture_id": "cap_demo_3"},
                "region_bindings": [
                    {
                        "region_intent_id": "ri_price",
                        "region_id": "roi_price",
                        "name": "价格区",
                        "x": 100,
                        "y": 200,
                        "w": 300,
                        "h": 120,
                        "coordinate_space": "target",
                        "source": "external_selector",
                    }
                ],
                "unbound_region_intents": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_request_json(base_url, path, *, method="GET", payload=None):
        recorded["path"] = path
        recorded["method"] = method
        recorded["payload"] = payload
        return {"status": "accepted"}

    monkeypatch.setattr(agent_tool, "_request_json", fake_request_json)
    exit_code = agent_tool.main(["region-bind-result", "--result-file", str(result_path)])

    assert exit_code == 0
    assert recorded["path"] == "/api/agent/region-bind-result"
    assert recorded["method"] == "POST"
    assert recorded["payload"]["task_id"] == "task_region_bind_result"
    assert recorded["payload"]["region_bindings"][0]["region_id"] == "roi_price"
    assert '"status": "accepted"' in capsys.readouterr().out
