from fastapi.testclient import TestClient

from ayes.api.server import app


client = TestClient(app)


def test_agent_contracts_endpoint_exposes_expected_routes() -> None:
    response = client.get("/api/agent/contracts")
    assert response.status_code == 200
    payload = response.json()
    assert "watch.status" in payload
    assert "agent.observe_live" in payload
    assert payload["agent.observe_live"]["path"] == "/api/agent/observe-live"
    assert "evidence_status" in payload["agent.observe_live"]["response_keys"]
    assert "agent_hints" in payload["agent.observe_live"]["response_keys"]
    assert "vision_status" in payload["agent.observe_live"]["response_keys"]
    assert payload["agent.activity"]["path"] == "/api/activity"
    assert "primary_summary" in payload["agent.activity"]["response_keys"]
    assert "compact" in payload["memory.items"]["query"]
    assert payload["control.status"]["path"] == "/api/control/status"
    assert payload["control.pause_all"]["path"] == "/api/control/pause-all"
    assert payload["control.resume_all"]["path"] == "/api/control/resume-all"
    assert payload["control.cleanup_reminder"]["path"] == "/api/control/cleanup-reminder"
    assert payload["control.sampling"]["path"] == "/api/control/sampling"
    assert "task_id" in payload["control.sampling"]["request"]
    assert payload["control.settings"]["path"] == "/api/control/settings"
    assert "latest_frame_hotkey" in payload["control.settings"]["request"]
    assert payload["tasks.list"]["path"] == "/api/tasks"
    assert payload["tasks.switch"]["path"] == "/api/watch/switch-task"
    assert payload["tasks.delete"]["path"] == "/api/watch/task/{task_id}"
    assert payload["tasks.roi.list"]["path"] == "/api/tasks/{task_id}/roi"
    assert payload["tasks.roi.create"]["path"] == "/api/tasks/{task_id}/roi"
    assert payload["tasks.roi.update"]["path"] == "/api/tasks/{task_id}/roi/{roi_task_id}"
    assert payload["tasks.alert"]["path"] == "/api/tasks/{task_id}/alert"
    assert "roi_name" in payload["tasks.roi.create"]["request"]
    assert "webhook_url" in payload["tasks.alert"]["request"]
    assert payload["region_bind.contract"]["path"] == "/api/agent/region-bind-contract"
    assert payload["vision.models"]["path"] == "/api/vision/models"
    assert payload["vision.settings"]["path"] == "/api/vision/settings"
    assert "watch.start" in payload
    assert "watch.plan" in payload
    assert "watch.confirm_plan" in payload
    assert "questions" in payload["watch.plan"]["response_keys"]
    assert "region_intents" in payload["watch.plan"]["response_keys"]
    assert "action_intents" in payload["watch.plan"]["response_keys"]
    assert "setup_guidance" in payload["watch.plan"]["response_keys"]
    assert "region_bindings" in payload["watch.confirm_plan"]["request"]
    assert "alert_message_template" in payload["watch.confirm_plan"]["request"]
    assert "snapshot.inspect" in payload
    assert "timeline.recent" in payload
    assert payload["timeline.query"]["path"] == "/api/ask"
    assert "structured_matches" in payload["timeline.query"]["response_keys"]
    assert "structured_observations" in payload["timeline.query"]["response_keys"]
    assert "query" in payload["logs.recent"]
    assert payload["alerts.recent"]["path"] == "/api/alerts/recent"
    assert payload["watch.run_once"]["path"] == "/api/watch/run-once"
