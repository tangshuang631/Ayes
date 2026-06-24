from ayes.cli import agent_tool


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
