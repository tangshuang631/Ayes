from pathlib import Path

from scripts import smoke_ayes_local_skill


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
        if command[:1] == ("load-spec",):
            return {"status": "loaded"}
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
    assert ("run-once",) in [command for command, _ in calls]
    assert any(command[:1] == ("alerts",) for command, _ in calls)
    assert summary["alert_count"] == 1
    assert summary["trigger_query"] == "商品有货"
    assert summary["ask_answer"] == "最近出现了监控命中"
    assert summary["screenshot_path"] == "/runtime/web-last-frame.png"
