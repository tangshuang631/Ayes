from ayes.cli import agent_tool


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
    assert '"status": "loaded"' in capsys.readouterr().out
