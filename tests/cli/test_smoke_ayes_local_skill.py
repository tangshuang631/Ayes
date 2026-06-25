from pathlib import Path

from scripts import smoke_ayes_local_skill
from scripts.install_ayes_local_skill import InstallPaths


def test_choose_trigger_query_prefers_ocr_tokens() -> None:
    query = smoke_ayes_local_skill.choose_trigger_query(
        {
            "items": [
                {
                    "summary": "变化",
                    "text": {
                        "ocr_text": "商品有货 立即购买",
                        "normalized_text": "商品有货 立即购买",
                    },
                }
            ]
        }
    )

    assert query == "商品有货"


def test_collect_skill_smoke_summary_uses_wrapper_commands_and_includes_alerts() -> None:
    calls: list[tuple[tuple[str, ...], dict | None]] = []

    def fake_run_wrapper_json(wrapper_path: Path, args: list[str], *, env=None):
        calls.append((tuple(args), env))
        command = tuple(args)
        if command == ("ensure-service",):
            return {"status": "service_ready"}
        if command[:1] == ("plan-spec",):
            prompt = command[4] if len(command) > 4 else ""
            mode = "triggered" if "提醒我" in prompt else "observe"
            payload = {
                "task_id": "task_skill_smoke",
                "draft_spec": {"mode": mode},
                "missing_fields": [],
                "questions": [],
                "setup_guidance": [],
            }
            if mode == "triggered":
                payload["missing_fields"] = [{"field": "alert.webhook_url", "reason": "triggered 模式需要可用通知出口"}]
                payload["questions"] = [{"kind": "webhook_missing"}]
                payload["setup_guidance"] = [{"topic": "wecom_webhook"}]
            return payload
        if command[:1] == ("confirm-plan",):
            return {"status": "loaded", "task_id": "task_skill_smoke"}
        if command == ("start",):
            return {"status": {"is_running": True}}
        if command == ("run-once",):
            return {"events": [{"event_id": "evt_run"}], "status": {"has_runner": True}}
        if command == ("status",):
            return {"has_runner": True, "is_running": True}
        if command[:1] == ("recent",):
            return {
                "items": [
                    {
                        "event_id": "evt_recent",
                        "summary": "商品有货 立即购买",
                        "text": {"ocr_text": "商品有货 立即购买", "normalized_text": "商品有货 立即购买"},
                    }
                ],
                "count": 1,
            }
        if command[:1] == ("alerts",):
            return {"items": [{"event_id": "evt_alert", "event_type": "alert_sent"}], "count": 1}
        if command[:1] == ("screenshot",):
            return {"path": "/runtime/web-last-frame.png", "capture_status": "ok"}
        if command[:1] == ("memory-items",):
            return {"items": [{"event_id": "evt_mem"}], "count": 1}
        if command[:1] == ("logs",):
            return {"items": [{"message": "ok"}], "count": 1}
        if command[:1] == ("ask",):
            return {"answer": "最近出现了监控命中", "matched_events": [{"event_id": "evt_alert"}]}
        if command == ("stop",):
            return {"status": {"is_running": False}}
        raise AssertionError(f"unexpected command: {command}")

    summary = smoke_ayes_local_skill.collect_skill_smoke_summary(
        wrapper_path=Path("/tmp/ayes-agent-local"),
        task_id="task_skill_smoke",
        webhook_url="http://127.0.0.1:18999/webhook",
        run_wrapper_json_fn=fake_run_wrapper_json,
        sleep_sec=0,
    )

    assert ("ensure-service",) in [command for command, _ in calls]
    assert any(command[:1] == ("plan-spec",) for command, _ in calls)
    assert any(command[:1] == ("confirm-plan",) for command, _ in calls)
    assert ("run-once",) in [command for command, _ in calls]
    assert any(command[:1] == ("alerts",) for command, _ in calls)
    assert summary["alert_count"] == 1
    assert summary["trigger_query"] == "商品有货"
    assert summary["ask_answer"] == "最近出现了监控命中"
    assert summary["screenshot_path"] == "/runtime/web-last-frame.png"


def test_collect_skill_smoke_summary_uses_plan_confirm_and_setup_guidance() -> None:
    calls: list[tuple[tuple[str, ...], dict | None]] = []

    def fake_run_wrapper_json(wrapper_path: Path, args: list[str], *, env=None):
        calls.append((tuple(args), env))
        command = tuple(args)
        if command == ("ensure-service",):
            return {"status": "service_ready"}
        if command[:1] == ("plan-spec",):
            return {
                "task_id": "task_skill_smoke",
                "draft_spec": {"mode": "triggered"},
                "missing_fields": [{"field": "alert.webhook_url", "reason": "triggered 模式需要可用通知出口"}],
                "questions": [{"kind": "webhook_missing"}],
                "setup_guidance": [
                    {
                        "topic": "wecom_webhook",
                        "user_steps": ["获取 webhook", "发给 agent"],
                        "agent_steps": ["继续指导用户补 webhook", "补完后继续 confirm-plan"],
                    }
                ],
            }
        if command[:1] == ("confirm-plan",):
            return {"status": "loaded", "task_id": "task_skill_smoke"}
        if command == ("start",):
            return {"status": {"is_running": True}}
        if command == ("run-once",):
            return {"events": [{"event_id": "evt_run"}], "status": {"has_runner": True}}
        if command == ("status",):
            return {"has_runner": True, "is_running": True}
        if command[:1] == ("recent",):
            return {
                "items": [
                    {
                        "event_id": "evt_recent",
                        "summary": "商品有货 立即购买",
                        "text": {"ocr_text": "商品有货 立即购买", "normalized_text": "商品有货 立即购买"},
                    }
                ],
                "count": 1,
            }
        if command[:1] == ("alerts",):
            return {"items": [{"event_id": "evt_alert", "event_type": "alert_sent"}], "count": 1}
        if command[:1] == ("screenshot",):
            return {"path": "/runtime/web-last-frame.png", "capture_status": "ok"}
        if command[:1] == ("memory-items",):
            return {"items": [{"event_id": "evt_mem"}], "count": 1}
        if command[:1] == ("logs",):
            return {"items": [{"message": "ok"}], "count": 1}
        if command[:1] == ("ask",):
            return {"answer": "最近出现了监控命中", "matched_events": [{"event_id": "evt_alert"}]}
        if command == ("stop",):
            return {"status": {"is_running": False}}
        raise AssertionError(f"unexpected command: {command}")

    summary = smoke_ayes_local_skill.collect_skill_smoke_summary(
        wrapper_path=Path("/tmp/ayes-agent-local"),
        task_id="task_skill_smoke",
        webhook_url="http://127.0.0.1:18999/webhook",
        run_wrapper_json_fn=fake_run_wrapper_json,
        sleep_sec=0,
    )

    commands = [command for command, _ in calls]
    assert any(command[:1] == ("plan-spec",) for command in commands)
    assert any(command[:1] == ("confirm-plan",) for command in commands)
    assert summary["alert_count"] == 1


def test_collect_skill_smoke_summary_passes_custom_alert_message_to_confirm_plan() -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run_wrapper_json(wrapper_path: Path, args: list[str], *, env=None):
        command = tuple(args)
        calls.append(command)
        if command == ("ensure-service",):
            return {"status": "service_ready"}
        if command[:1] == ("plan-spec",):
            return {
                "task_id": "task_skill_smoke",
                "draft_spec": {"mode": "triggered"},
                "missing_fields": [],
                "questions": [],
                "setup_guidance": [],
            }
        if command[:1] == ("confirm-plan",):
            return {"status": "loaded", "task_id": "task_skill_smoke"}
        if command in {("run-once",), ("start",)}:
            return {"status": {"is_running": True}, "events": [{"event_id": "evt_run"}]}
        if command == ("status",):
            return {"has_runner": True, "is_running": True}
        if command[:1] == ("recent",):
            return {"items": [{"summary": "Codex", "text": {"ocr_text": "Codex", "normalized_text": "Codex"}}], "count": 1}
        if command[:1] == ("alerts",):
            return {"items": [{"event_type": "alert_sent"}], "count": 1}
        if command[:1] == ("screenshot",):
            return {"path": "/runtime/web-last-frame.png", "capture_status": "ok"}
        if command[:1] == ("memory-items",):
            return {"items": [], "count": 0}
        if command[:1] == ("logs",):
            return {"items": [], "count": 0}
        if command[:1] == ("ask",):
            return {"answer": "最近出现了监控命中", "matched_events": []}
        if command == ("stop",):
            return {"status": {"is_running": False}}
        raise AssertionError(f"unexpected command: {command}")

    smoke_ayes_local_skill.collect_skill_smoke_summary(
        wrapper_path=Path("/tmp/ayes-agent-local"),
        task_id="task_skill_smoke",
        webhook_url="http://127.0.0.1:18999/webhook",
        alert_message_title="库存提醒",
        alert_message_template="任务 {task_id} 命中：{summary}",
        run_wrapper_json_fn=fake_run_wrapper_json,
        sleep_sec=0,
    )

    confirm_commands = [command for command in calls if command[:1] == ("confirm-plan",)]
    triggered_confirm = confirm_commands[-1]
    assert "--alert-message-title" in triggered_confirm
    assert "库存提醒" in triggered_confirm
    assert "--alert-message-template" in triggered_confirm
    assert "任务 {task_id} 命中：{summary}" in triggered_confirm


def test_collect_skill_smoke_with_local_webhook_embeds_webhook_round_trip(monkeypatch) -> None:
    recorded = {}

    def fake_collect_skill_smoke_summary(*, wrapper_path, task_id, webhook_url, alert_message_title=None, alert_message_template=None, run_wrapper_json_fn=None, sleep_sec=0, env=None):
        recorded["wrapper_path"] = wrapper_path
        recorded["task_id"] = task_id
        recorded["webhook_url"] = webhook_url
        return {"task_id": task_id, "alert_count": 1}

    def fake_capture_single_webhook_request(*, trigger_fn, timeout_sec):
        webhook_url = "http://127.0.0.1:19999/webhook"
        trigger_fn(webhook_url)
        return {
            "webhook_url": webhook_url,
            "received": True,
            "request_count": 1,
            "last_path": "/webhook",
            "response_status": 200,
            "response_body": '{"ok":true}',
        }

    monkeypatch.setattr(smoke_ayes_local_skill, "collect_skill_smoke_summary", fake_collect_skill_smoke_summary)
    monkeypatch.setattr(smoke_ayes_local_skill, "capture_single_webhook_request", fake_capture_single_webhook_request)

    summary = smoke_ayes_local_skill.collect_skill_smoke_with_local_webhook(
        wrapper_path=Path("/tmp/ayes-agent-local"),
        task_id="task_skill_smoke",
        sleep_sec=0,
    )

    assert recorded["wrapper_path"] == Path("/tmp/ayes-agent-local")
    assert recorded["task_id"] == "task_skill_smoke"
    assert recorded["webhook_url"] == "http://127.0.0.1:19999/webhook"
    assert summary["alert_count"] == 1
    assert summary["webhook_smoke"]["received"] is True


def test_collect_skill_smoke_with_local_webhook_preserves_custom_message_in_request(monkeypatch) -> None:
    def fake_collect_skill_smoke_summary(*, wrapper_path, task_id, webhook_url, alert_message_title=None, alert_message_template=None, run_wrapper_json_fn=None, sleep_sec=0, env=None):
        return {
            "task_id": task_id,
            "alert_count": 1,
            "alert_message_title": alert_message_title,
            "alert_message_template": alert_message_template,
        }

    def fake_capture_single_webhook_request(*, trigger_fn, timeout_sec):
        webhook_url = "http://127.0.0.1:19999/webhook"
        trigger_fn(webhook_url)
        return {
            "webhook_url": webhook_url,
            "received": True,
            "request_count": 1,
            "last_path": "/webhook",
            "body": {
                "msgtype": "text",
                "text": {
                    "content": "[Ayes] 库存提醒\n\n任务 task_skill_smoke 命中：命中监控关键词: Codex",
                },
            },
            "response_status": 200,
            "response_body": '{"ok":true}',
        }

    monkeypatch.setattr(smoke_ayes_local_skill, "collect_skill_smoke_summary", fake_collect_skill_smoke_summary)
    monkeypatch.setattr(smoke_ayes_local_skill, "capture_single_webhook_request", fake_capture_single_webhook_request)

    summary = smoke_ayes_local_skill.collect_skill_smoke_with_local_webhook(
        wrapper_path=Path("/tmp/ayes-agent-local"),
        task_id="task_skill_smoke",
        sleep_sec=0,
        alert_message_title="库存提醒",
        alert_message_template="任务 {task_id} 命中：{summary}",
    )

    assert summary["alert_message_title"] == "库存提醒"
    assert summary["alert_message_template"] == "任务 {task_id} 命中：{summary}"
    assert summary["webhook_smoke"]["received"] is True
    assert "库存提醒" in summary["webhook_smoke"]["body"]["text"]["content"]
    assert "任务 task_skill_smoke 命中" in summary["webhook_smoke"]["body"]["text"]["content"]


def test_smoke_main_uses_agent_wrapper_path_from_install_result(monkeypatch, tmp_path, capsys) -> None:
    installed_dir = tmp_path / "skills" / "ayes-local"
    scripts_dir = installed_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    agent_wrapper = scripts_dir / "ayes-agent-local"
    menubar_wrapper = scripts_dir / "ayes-menubar-local"
    agent_wrapper.write_text("", encoding="utf-8")
    menubar_wrapper.write_text("", encoding="utf-8")

    install_paths = InstallPaths(
        repo_root=tmp_path / "repo",
        skill_root=tmp_path / "skills",
        source_skill_dir=tmp_path / "repo" / "skills" / "final" / "ayes-local",
        target_skill_dir=installed_dir,
        target_scripts_dir=scripts_dir,
        agent_wrapper_path=agent_wrapper,
        menubar_wrapper_path=menubar_wrapper,
    )

    recorded = {}

    monkeypatch.setattr(smoke_ayes_local_skill, "install_skill", lambda **kwargs: install_paths)

    def fake_collect_skill_smoke_summary(*, wrapper_path, task_id, webhook_url, alert_message_title=None, alert_message_template=None, sleep_sec=0, env=None):
        recorded["wrapper_path"] = wrapper_path
        recorded["task_id"] = task_id
        recorded["webhook_url"] = webhook_url
        return {"task_id": task_id, "alert_count": 1}

    monkeypatch.setattr(smoke_ayes_local_skill, "collect_skill_smoke_summary", fake_collect_skill_smoke_summary)

    exit_code = smoke_ayes_local_skill.main(
        [
            "--repo-root",
            str(tmp_path / "repo"),
            "--skill-root",
            str(tmp_path / "skills"),
            "--task-id",
            "task_skill_smoke",
            "--webhook-url",
            "http://127.0.0.1:18999/webhook",
            "--sleep-sec",
            "0",
        ]
    )

    assert exit_code == 0
    assert recorded["wrapper_path"] == agent_wrapper
    assert recorded["task_id"] == "task_skill_smoke"
    assert recorded["webhook_url"] == "http://127.0.0.1:18999/webhook"
    output = capsys.readouterr().out
    assert str(installed_dir) in output
    assert str(agent_wrapper) in output


def test_smoke_main_recycles_reusable_local_service_before_collecting_summary(monkeypatch, tmp_path) -> None:
    installed_dir = tmp_path / "skills" / "ayes-local"
    scripts_dir = installed_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    agent_wrapper = scripts_dir / "ayes-agent-local"
    menubar_wrapper = scripts_dir / "ayes-menubar-local"
    agent_wrapper.write_text("", encoding="utf-8")
    menubar_wrapper.write_text("", encoding="utf-8")

    install_paths = InstallPaths(
        repo_root=tmp_path / "repo",
        skill_root=tmp_path / "skills",
        source_skill_dir=tmp_path / "repo" / "skills" / "final" / "ayes-local",
        target_skill_dir=installed_dir,
        target_scripts_dir=scripts_dir,
        agent_wrapper_path=agent_wrapper,
        menubar_wrapper_path=menubar_wrapper,
    )

    call_order: list[str] = []

    monkeypatch.setattr(smoke_ayes_local_skill, "install_skill", lambda **kwargs: install_paths)

    def fake_recycle() -> None:
        call_order.append("recycle")

    def fake_collect_skill_smoke_summary(*, wrapper_path, task_id, webhook_url, alert_message_title=None, alert_message_template=None, sleep_sec=0, env=None):
        assert wrapper_path == agent_wrapper
        call_order.append("collect")
        return {"task_id": task_id, "alert_count": 1}

    monkeypatch.setattr(smoke_ayes_local_skill, "recycle_reusable_local_service", fake_recycle)
    monkeypatch.setattr(smoke_ayes_local_skill, "collect_skill_smoke_summary", fake_collect_skill_smoke_summary)

    exit_code = smoke_ayes_local_skill.main(
        [
            "--repo-root",
            str(tmp_path / "repo"),
            "--skill-root",
            str(tmp_path / "skills"),
            "--task-id",
            "task_skill_smoke",
            "--webhook-url",
            "http://127.0.0.1:18999/webhook",
            "--sleep-sec",
            "0",
        ]
    )

    assert exit_code == 0
    assert call_order == ["recycle", "collect"]


def test_smoke_main_defaults_to_local_webhook_round_trip_when_no_webhook_arg(monkeypatch, tmp_path) -> None:
    installed_dir = tmp_path / "skills" / "ayes-local"
    scripts_dir = installed_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    agent_wrapper = scripts_dir / "ayes-agent-local"
    menubar_wrapper = scripts_dir / "ayes-menubar-local"
    agent_wrapper.write_text("", encoding="utf-8")
    menubar_wrapper.write_text("", encoding="utf-8")

    install_paths = InstallPaths(
        repo_root=tmp_path / "repo",
        skill_root=tmp_path / "skills",
        source_skill_dir=tmp_path / "repo" / "skills" / "final" / "ayes-local",
        target_skill_dir=installed_dir,
        target_scripts_dir=scripts_dir,
        agent_wrapper_path=agent_wrapper,
        menubar_wrapper_path=menubar_wrapper,
    )

    recorded = {}

    monkeypatch.setattr(smoke_ayes_local_skill, "install_skill", lambda **kwargs: install_paths)
    monkeypatch.setattr(smoke_ayes_local_skill, "recycle_reusable_local_service", lambda: None)

    def fake_collect_skill_smoke_with_local_webhook(*, wrapper_path, task_id, sleep_sec, alert_message_title=None, alert_message_template=None, run_wrapper_json_fn=None, env=None):
        recorded["wrapper_path"] = wrapper_path
        recorded["task_id"] = task_id
        return {"task_id": task_id, "alert_count": 1, "webhook_smoke": {"received": True}}

    monkeypatch.setattr(smoke_ayes_local_skill, "collect_skill_smoke_with_local_webhook", fake_collect_skill_smoke_with_local_webhook)

    exit_code = smoke_ayes_local_skill.main(
        [
            "--repo-root",
            str(tmp_path / "repo"),
            "--skill-root",
            str(tmp_path / "skills"),
            "--task-id",
            "task_skill_smoke",
            "--sleep-sec",
            "0",
        ]
    )

    assert exit_code == 0
    assert recorded["wrapper_path"] == agent_wrapper
    assert recorded["task_id"] == "task_skill_smoke"


def test_smoke_main_forwards_custom_alert_message_options(monkeypatch, tmp_path) -> None:
    installed_dir = tmp_path / "skills" / "ayes-local"
    scripts_dir = installed_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    agent_wrapper = scripts_dir / "ayes-agent-local"
    menubar_wrapper = scripts_dir / "ayes-menubar-local"
    agent_wrapper.write_text("", encoding="utf-8")
    menubar_wrapper.write_text("", encoding="utf-8")

    install_paths = InstallPaths(
        repo_root=tmp_path / "repo",
        skill_root=tmp_path / "skills",
        source_skill_dir=tmp_path / "repo" / "skills" / "final" / "ayes-local",
        target_skill_dir=installed_dir,
        target_scripts_dir=scripts_dir,
        agent_wrapper_path=agent_wrapper,
        menubar_wrapper_path=menubar_wrapper,
    )

    recorded = {}

    monkeypatch.setattr(smoke_ayes_local_skill, "install_skill", lambda **kwargs: install_paths)
    monkeypatch.setattr(smoke_ayes_local_skill, "recycle_reusable_local_service", lambda: None)

    def fake_collect_skill_smoke_with_local_webhook(*, wrapper_path, task_id, sleep_sec, alert_message_title=None, alert_message_template=None, run_wrapper_json_fn=None, env=None):
        recorded["wrapper_path"] = wrapper_path
        recorded["task_id"] = task_id
        recorded["alert_message_title"] = alert_message_title
        recorded["alert_message_template"] = alert_message_template
        return {"task_id": task_id, "alert_count": 1, "webhook_smoke": {"received": True}}

    monkeypatch.setattr(smoke_ayes_local_skill, "collect_skill_smoke_with_local_webhook", fake_collect_skill_smoke_with_local_webhook)

    exit_code = smoke_ayes_local_skill.main(
        [
            "--repo-root",
            str(tmp_path / "repo"),
            "--skill-root",
            str(tmp_path / "skills"),
            "--task-id",
            "task_skill_smoke",
            "--alert-message-title",
            "库存提醒",
            "--alert-message-template",
            "任务 {task_id} 命中：{summary}",
            "--sleep-sec",
            "0",
        ]
    )

    assert exit_code == 0
    assert recorded["wrapper_path"] == agent_wrapper
    assert recorded["task_id"] == "task_skill_smoke"
    assert recorded["alert_message_title"] == "库存提醒"
    assert recorded["alert_message_template"] == "任务 {task_id} 命中：{summary}"
