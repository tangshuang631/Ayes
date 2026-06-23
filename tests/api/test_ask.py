from fastapi.testclient import TestClient
import time

from ayes.api.server import app, state
from ayes.config.models import WatchSpec
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, Observability, WatchMatch


client = TestClient(app)


def test_ask_endpoint_uses_recent_summary_for_generic_question() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id="task_api_test")
    runner.run_once()
    response = client.get("/api/ask", params={"question": "最近发生了什么", "minutes": 5})
    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert "matched_events" in payload
    assert payload["task_id"] == "task_api_test"
    assert payload["minutes"] == 5
    assert "time_range" in payload
    assert "evidence_refs" in payload
    assert "evidence_previews" in payload
    assert "time_scope_respected" in payload
    assert payload["time_scope_respected"] is True
    assert "memory_layers_used" in payload
    assert isinstance(payload["evidence_refs"], list)
    assert any(str(ref).startswith("runtime/evidence/") for ref in payload["evidence_refs"])
    assert isinstance(payload["evidence_previews"], list)
    assert any(str(item.get("src", "")).startswith("/runtime/evidence/") for item in payload["evidence_previews"])


def test_ask_endpoint_answers_numeric_threshold_question_from_structured_match() -> None:
    now = time.time()
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
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
        }
    )
    runner = state.set_runner(spec, task_id="task_numeric_ask")
    event = build_event(
        task_id="task_numeric_ask",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=now,
        source="semantic_match",
        event_type="semantic_match",
        priority="high",
        confidence=1.0,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="命中数值阈值规则: price lt 299.0，当前识别值 199",
        watch_match=WatchMatch(
            matched=True,
            score=1.0,
            matched_rule="numeric_threshold:price:lt:299.0",
            matched_value=199.0,
            matched_unit="cny",
            matched_field="price",
        ),
    )
    event = event.__class__(**{**event.__dict__, "text": EventText(ocr_text="当前价格 ¥199", normalized_text="当前价格 199")})
    runner.memory.append(event)
    response = client.get("/api/ask", params={"question": "最近5分钟价格有没有低于299", "minutes": 5, "task_id": "task_numeric_ask"})
    assert response.status_code == 200
    payload = response.json()
    assert "低于 299" in payload["answer"]
    assert "199.0" in payload["answer"]
    assert payload["matched_events"]
