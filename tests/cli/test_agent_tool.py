from ayes.cli import agent_tool
import json


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
