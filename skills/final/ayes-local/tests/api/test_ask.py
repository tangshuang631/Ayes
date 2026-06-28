from fastapi.testclient import TestClient
import time
from dataclasses import replace
from datetime import datetime, timezone

from ayes.api.server import app, state
from ayes.config.models import WatchSpec
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region, WatchMatch


client = TestClient(app)


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
                    "vision_model": "qwen2.5vl:7b",
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
    assert first["model"] == "qwen2.5vl:7b"
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


def test_ask_content_question_uses_wide_memory_without_exact_question_keyword() -> None:
    task_id = "task_content_question"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "哔哩哔哩"},
            "watch_intent": {"enabled": False},
        }
    )
    state.set_runner(spec, task_id=task_id)
    state.clear_runner()
    now = time.time()
    watched = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 120,
        source="capture",
        event_type="target_window_changed",
        priority="medium",
        confidence=0.96,
        target=EventTarget(
            type="process",
            process_name="哔哩哔哩",
            window_title="布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
        ),
        observability=Observability(True, True, True, True, "ok"),
        summary="进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
    )
    latest_grid = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 10,
        source="tagger",
        event_type="visual_summary",
        priority="medium",
        confidence=0.68,
        target=EventTarget(type="process", process_name="哔哩哔哩"),
        observability=Observability(True, True, True, True, "ok"),
        summary="图中有多个视频缩略图展示，每个缩略图下方有播放次数和点赞数等信息。",
    )
    latest_grid = replace(
        latest_grid,
        visual=EventVisual(summary="图中有多个视频缩略图展示，每个缩略图下方有播放次数和点赞数等信息。", provider="ollama"),
    )
    state.sqlite_store.insert_event(watched)
    for index in range(1200):
        noisy = build_event(
            task_id=task_id,
            spec_version="1.0",
            task_mode="observe",
            timestamp=now - 119 + index,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=0.35,
            target=EventTarget(type="process", process_name="哔哩哔哩", window_title="哔哩哔哩 (゜-゜)つロ 干杯~-bilibili"),
            observability=Observability(True, True, True, True, "ok"),
            summary="OCR 未识别到文本 (vision)",
        )
        state.sqlite_store.insert_event(noisy)
    state.sqlite_store.insert_event(latest_grid)

    response = client.get("/api/ask", params={"task_id": task_id, "minutes": 240, "question": "最近看的视频是什么"})

    assert response.status_code == 200
    payload = response.json()
    assert "布欧怎么出现的" in payload["answer"]
    assert "话说龙珠" in payload["answer"]
    assert "多个视频缩略图" not in payload["answer"]


def test_ask_content_question_uses_compact_file_memory_when_sqlite_is_noisy() -> None:
    task_id = "task_content_file_memory"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "哔哩哔哩"},
            "watch_intent": {"enabled": False},
        }
    )
    state.set_runner(spec, task_id=task_id)
    state.clear_runner()
    now = time.time()
    memory_path = state.memory_file_store.short_event_path(task_id=task_id, timestamp=now - 120)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        '{"time":"2026-06-26T14:23:03Z","info":"进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】"}\n',
        encoding="utf-8",
    )
    for index in range(30):
        noisy = build_event(
            task_id=task_id,
            spec_version="1.0",
            task_mode="observe",
            timestamp=now - 30 + index,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=0.35,
            target=EventTarget(type="process", process_name="哔哩哔哩", window_title="哔哩哔哩 (゜-゜)つロ 干杯~-bilibili"),
            observability=Observability(True, True, True, True, "ok"),
            summary="OCR 未识别到文本 (vision)",
        )
        state.sqlite_store.insert_event(noisy)

    response = client.get("/api/ask", params={"task_id": task_id, "minutes": 240, "question": "最近看的视频是什么"})

    assert response.status_code == 200
    payload = response.json()
    assert "布欧怎么出现的" in payload["answer"]
    assert "话说龙珠" in payload["answer"]
    assert payload["memory_layers_used"] == ["short_term_file"]


def test_ask_content_identity_question_prefers_file_title_over_later_visual_scenes() -> None:
    task_id = "task_content_title_over_visual"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "哔哩哔哩"},
            "watch_intent": {"enabled": False},
        }
    )
    state.set_runner(spec, task_id=task_id)
    state.clear_runner()
    now = time.time()
    memory_path = state.memory_file_store.short_event_path(task_id=task_id, timestamp=now - 180)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        '{"time":"2026-06-26T14:23:03Z","info":"进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】"}\n',
        encoding="utf-8",
    )
    for index, summary in enumerate(
        [
            "这张图片展示了两个卡通人物坐在沙发上对话的场景。",
            "图中有两个穿着军装的卡通人物站在储物柜前。",
            "一个男孩坐在书桌前，背景墙上挂着哥斯拉海报。",
        ]
    ):
        event = build_event(
                task_id=task_id,
                spec_version="1.0",
                task_mode="observe",
                timestamp=now - 60 + index,
                source="tagger",
                event_type="visual_summary",
                priority="medium",
                confidence=0.88,
                target=EventTarget(type="process", process_name="哔哩哔哩", window_title="皮特替子从军高兴的都哭了"),
                observability=Observability(True, True, True, True, "ok"),
                summary=summary,
            )
        state.sqlite_store.insert_event(replace(event, visual=EventVisual(summary=summary)))

    response = client.get("/api/ask", params={"task_id": task_id, "minutes": 240, "question": "最近看的视频是什么"})

    assert response.status_code == 200
    payload = response.json()
    assert "布欧怎么出现的" in payload["answer"]
    assert "卡通人物坐在沙发" not in payload["answer"]
    assert payload["memory_layers_used"] == ["short_term_file"]


def test_ask_payload_strips_heavy_vision_request_payload() -> None:
    task_id = "task_ask_compact_payload"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id=task_id)
    event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=time.time(),
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容是一页包含错误弹窗的网页",
    )
    event = replace(
        event,
        visual=EventVisual(
            summary="主内容是一页包含错误弹窗的网页",
            attributes={
                "request_payload": {"images": ["x" * 1000], "prompt": "heavy"},
                "raw_text": "主内容是一页包含错误弹窗的网页",
                "structured_observation": {"visual": {"summary": "主内容是一页包含错误弹窗的网页"}},
            },
        ),
    )
    runner.memory.append(event)

    response = client.get("/api/ask", params={"task_id": task_id, "minutes": 5, "question": "页面内容是什么"})

    assert response.status_code == 200
    encoded = response.text
    assert "request_payload" not in encoded
    assert "xxxxxxxxxx" not in encoded
    assert "structured_observations" in encoded


def test_query_endpoint_returns_compact_reranked_answer_without_raw_payload() -> None:
    task_id = "task_query_compact"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "哔哩哔哩"},
            "watch_intent": {"enabled": False},
        }
    )
    runner = state.set_runner(spec, task_id=task_id)
    now = time.time()
    title_event = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 90,
        source="file_memory",
        event_type="compact_short_memory",
        priority="medium",
        confidence=0.86,
        target=EventTarget(type="process", process_name="哔哩哔哩", window_title="布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】"),
        observability=Observability(True, False, False, True, "summary"),
        summary="进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
    )
    heavy_visual = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now - 30,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="哔哩哔哩"),
        observability=Observability(True, True, True, True, "ok"),
        summary="这张图片展示了两个卡通人物坐在沙发上对话的场景。",
    )
    heavy_visual = replace(
        heavy_visual,
        text=EventText(ocr_text="noise", blocks=[EventTextBlock(text="noise", confidence=0.2, bbox=[1, 2, 3, 4])]),
        visual=EventVisual(attributes={"request_payload": {"images": ["x" * 1000]}}),
    )
    runner.event_sink(title_event)
    runner.event_sink(heavy_visual)

    response = client.get("/api/query", params={"task_id": task_id, "minutes": 240, "question": "最近看的视频是什么"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "memory_index"
    assert "布欧怎么出现的" in payload["answer"]
    encoded = response.text
    assert "request_payload" not in encoded
    assert "bbox" not in encoded
    assert payload["logs_used"] is False
    assert '"items":' in encoded
    assert '"logs":' not in encoded
    assert len(encoded) < 8000


def test_memory_items_prefers_short_fact_files_over_raw_sqlite_events() -> None:
    task_id = "task_memory_items_short_fact"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "Chrome"},
            "watch_intent": {"enabled": False},
        }
    )
    state.set_runner(spec, task_id=task_id)
    state.clear_runner()
    now = time.time()
    memory_path = state.memory_file_store.short_event_path(task_id=task_id, timestamp=now)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        f'{{"time":"{_iso_utc(now - 30)}","info":"页面：Apifox 登录页","code":"scn=pg|reg=main|k1=Apifox|k2=登录页"}}\n',
        encoding="utf-8",
    )
    noisy = build_event(
        task_id=task_id,
        spec_version="1.0",
        task_mode="observe",
        timestamp=now,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.31,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="0OCg0,、KIkIl￿8YeSJX",
    )
    state.sqlite_store.insert_event(noisy)

    response = client.get("/api/memory/items", params={"task_id": task_id, "minutes": 60, "limit": 5, "compact": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert payload["items"][0]["summary"] == "页面：Apifox 登录页"
    assert "KIkIl" not in response.text


def test_activity_prefers_short_fact_files_before_raw_sqlite_activity() -> None:
    task_id = "task_activity_short_fact"
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "watch_intent": {"enabled": False},
        }
    )
    state.set_runner(spec, task_id=task_id)
    state.clear_runner()
    now = time.time()
    memory_path = state.memory_file_store.short_event_path(task_id=task_id, timestamp=now)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        f'{{"time":"{_iso_utc(now - 30)}","info":"表单：手机号输入框，确认按钮","code":"scn=frm|reg=main|k1=手机号输入框|k2=确认按钮"}}\n',
        encoding="utf-8",
    )
    for index in range(3):
        noisy = build_event(
            task_id=task_id,
            spec_version="1.0",
            task_mode="observe",
            timestamp=now - index,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=0.28,
            target=EventTarget(type="screen", screen_id=1),
            observability=Observability(True, True, True, True, "ok"),
            summary="OCR 未识别到文本 (vision)",
        )
        state.sqlite_store.insert_event(noisy)

    response = client.get("/api/activity", params={"task_id": task_id, "minutes": 60})

    assert response.status_code == 200
    payload = response.json()
    assert "手机号输入框" in payload["primary_summary"]
    assert "OCR 未识别到文本" not in payload["primary_summary"]


def test_long_term_summary_is_built_from_short_fact_rows_not_raw_event_noise() -> None:
    task_id = "task_long_term_from_short_rows"
    now = time.time()
    short_rows = [
        {"time": "2026-06-27T10:20:03Z", "info": "页面：Apifox 登录页", "code": "scn=pg|reg=main|k1=Apifox|k2=登录页"},
        {"time": "2026-06-27T10:21:03Z", "info": "表单：手机号输入框，确认按钮", "code": "scn=frm|reg=main|k1=手机号输入框|k2=确认按钮"},
        {"time": "2026-06-27T10:22:03Z", "info": "状态：登录弹窗", "code": "scn=sts|reg=main|k1=登录弹窗"},
    ]

    summary = __import__("ayes.memory.long_term", fromlist=["build_long_term_summary_from_short_rows"]).build_long_term_summary_from_short_rows(
        task_id=task_id,
        rows=short_rows,
        window_start=now - 180,
        window_end=now,
    )

    assert "Apifox 登录页" in summary["summary"]
    assert "手机号输入框" in summary["summary"]
    assert "KIkIl" not in summary["summary"]
    assert summary["event_count"] == 3
