from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, Observability, Region, WatchMatch
from ayes.memory.short_term import ShortTermMemoryStore


def test_short_term_query_filters_by_time_and_keyword() -> None:
    store = ShortTermMemoryStore(retain_seconds=900)
    event = build_event(
        task_id="task_1",
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="价格低于 299",
    )
    event = event.__class__(**{**event.__dict__, "text": EventText(ocr_text="价格低于 299", normalized_text="价格低于 299")})
    store.append(event)
    result = store.query(now=200.0, minutes=5, keyword="299")
    assert len(result.matched_events) == 1
    assert "299" in result.answer


def test_short_term_query_answers_numeric_threshold_question_from_structured_match() -> None:
    store = ShortTermMemoryStore(retain_seconds=900)
    event = build_event(
        task_id="task_numeric",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=100.0,
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
    store.append(event)
    result = store.query(now=200.0, minutes=5, question="最近5分钟价格有没有低于299")
    assert len(result.matched_events) == 1
    assert "低于 299" in result.answer
    assert "199.0" in result.answer


def test_short_term_query_answers_numeric_lowest_question_with_time() -> None:
    store = ShortTermMemoryStore(retain_seconds=900)
    first = build_event(
        task_id="task_numeric",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=100.0,
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
        task_id="task_numeric",
        spec_version="1.0",
        task_mode="triggered",
        timestamp=180.0,
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
    store.append(first)
    store.append(second)
    result = store.query(now=200.0, minutes=5, question="最近5分钟最低大概是什么时候")
    assert len(result.matched_events) == 2
    assert "最低" in result.answer
    assert "159.0" in result.answer
    assert "00:03:00" in result.answer


def test_short_term_query_answers_position_question_from_region_and_block() -> None:
    store = ShortTermMemoryStore(retain_seconds=900)
    event = build_event(
        task_id="task_position",
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
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
    store.append(event)
    result = store.query(now=200.0, minutes=5, question="最近5分钟价格大概在什么位置")
    assert len(result.matched_events) == 1
    assert "价格区域" in result.answer
    assert "左上" in result.answer
