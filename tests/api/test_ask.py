from fastapi.testclient import TestClient
import time

from ayes.api.server import app, state
from ayes.config.models import WatchSpec
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, Observability, Region, WatchMatch


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
    assert "lead_evidence" in payload
    assert "time_scope_respected" in payload
    assert payload["time_scope_respected"] is True
    assert "memory_layers_used" in payload
    assert isinstance(payload["evidence_refs"], list)
    assert isinstance(payload["evidence_previews"], list)
    if payload["evidence_refs"]:
        assert all(str(ref).startswith("runtime/evidence/") for ref in payload["evidence_refs"])
    if payload["evidence_previews"]:
        assert all(str(item.get("src", "")).startswith("/runtime/evidence/") for item in payload["evidence_previews"])
    assert set(payload["lead_evidence"].keys()) >= {"event_id", "timestamp", "summary", "location_summary"}


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
    event = event.__class__(
        **{
            **event.__dict__,
            "text": EventText(ocr_text="当前价格 ¥199", normalized_text="当前价格 199"),
            "region": Region(region_id="roi_price", name="价格区域", x=10, y=20, w=30, h=40),
        }
    )
    runner.memory.append(event)
    response = client.get("/api/ask", params={"question": "最近5分钟价格有没有低于299", "minutes": 5, "task_id": "task_numeric_ask"})
    assert response.status_code == 200
    payload = response.json()
    assert "低于 299" in payload["answer"]
    assert "199.0" in payload["answer"]
    assert payload["matched_events"]
    assert payload["structured_matches"]
    assert payload["structured_matches"][0]["field"] == "price"
    assert payload["structured_matches"][0]["value"] == 199.0
    assert payload["structured_matches"][0]["unit"] == "cny"
    assert payload["structured_matches"][0]["region_name"] == "价格区域"
    assert payload["structured_matches"][0]["rule"] == "numeric_threshold:price:lt:299.0"
    assert payload["structured_matches"][0]["time_text"]
    assert payload["structured_matches"][0]["location_summary"] == "价格区域"


def test_ask_endpoint_answers_numeric_lowest_question_with_time() -> None:
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
    runner = state.set_runner(spec, task_id="task_numeric_lowest_ask")
    first = build_event(
        task_id="task_numeric_lowest_ask",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=now - 30,
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
    second = build_event(
        task_id="task_numeric_lowest_ask",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=now - 10,
        source="semantic_match",
        event_type="semantic_match",
        priority="high",
        confidence=1.0,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="命中数值阈值规则: price lt 299.0，当前识别值 159",
        watch_match=WatchMatch(
            matched=True,
            score=1.0,
            matched_rule="numeric_threshold:price:lt:299.0",
            matched_value=159.0,
            matched_unit="cny",
            matched_field="price",
        ),
    )
    runner.memory.append(first)
    runner.memory.append(second)
    response = client.get("/api/ask", params={"question": "最近5分钟最低大概是什么时候", "minutes": 5, "task_id": "task_numeric_lowest_ask"})
    assert response.status_code == 200


def test_ask_endpoint_answers_position_question_with_region_and_direction() -> None:
    now = time.time()
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id="task_position_ask")
    event = build_event(
        task_id="task_position_ask",
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.95,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="价格 199",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="roi_price", name="价格区域", x=0, y=0, w=100, h=100),
            "text": EventText(
                ocr_text="价格 199",
                normalized_text="价格 199",
                blocks=[
                    EventTextBlock(
                        text="价格 199",
                        confidence=0.98,
                        bbox=[0.1, 0.1, 0.3, 0.1, 0.3, 0.2, 0.1, 0.2],
                        rect={"x": 10.0, "y": 10.0, "w": 20.0, "h": 10.0},
                        rect_norm={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1},
                        coordinate_space="image_pixels",
                        line_index=0,
                    )
                ],
            ),
        }
    )
    runner.memory.append(event)
    response = client.get("/api/ask", params={"question": "最近5分钟价格大概在什么位置", "minutes": 5, "task_id": "task_position_ask"})
    assert response.status_code == 200
    payload = response.json()
    assert "价格区域" in payload["answer"]
    assert "左上" in payload["answer"]
    assert payload["matched_events"]
    assert payload["matched_events"][0]["location_summary"]
    assert payload["matched_events"][0]["text"]["blocks"][0]["rect_norm"]
    if payload["evidence_previews"]:
        assert payload["evidence_previews"][0]["overlay"]["kind"] in {"block", "region", "none"}


def test_ask_payload_exposes_structured_vision_matches() -> None:
    now = time.time()
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id="task_vision_ask")
    event = build_event(
        task_id="task_vision_ask",
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="vision",
        event_type="vision_triggered",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="视觉增强已触发: ocr_sparse",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="roi_chart", name="图表区", x=0, y=0, w=100, h=100),
            "visual": __import__("ayes.events.models", fromlist=["EventVisual"]).EventVisual(
                summary="检测到下降图表和红色按钮",
                labels=["vision_triggered", "ocr_sparse"],
                attributes={
                    "vision_reasons": ["ocr_sparse"],
                    "vision_blocked_reason": "",
                    "vision_model": "Molmo-7B-D-0924",
                    "vision_provider": "ollama",
                    "detail_lines": ["下降图表位于中间", "右上有红色按钮"],
                },
                provider="ollama",
            ),
        }
    )
    runner.memory.append(event)
    response = client.get("/api/ask", params={"question": "最近发生了什么", "minutes": 5, "task_id": "task_vision_ask"})
    assert response.status_code == 200
    payload = response.json()
    assert "structured_vision_matches" in payload
    assert payload["structured_vision_matches"]
    first = payload["structured_vision_matches"][0]
    assert first["provider"] == "ollama"
    assert first["model"] == "Molmo-7B-D-0924"
    assert first["region_name"] == "图表区"
    assert first["detail_lines"] == ["下降图表位于中间", "右上有红色按钮"]


def test_ask_endpoint_supports_long_term_hours_scope() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id="task_long_term_ask")
    runner.run_once()
    state.clear_runner()
    response = client.get("/api/ask", params={"question": "最近24小时发生了什么", "hours": 24, "task_id": "task_long_term_ask"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["memory_layers_used"] == ["long_term_persisted"]
    assert payload["time_scope_respected"] is True
