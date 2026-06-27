from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region, WatchMatch
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


def test_short_term_content_question_prefers_readable_earlier_fact_over_latest_thumbnail_noise() -> None:
    store = ShortTermMemoryStore(retain_seconds=4 * 60 * 60)
    watched = build_event(
        task_id="task_video",
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
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
    thumbnail_grid = build_event(
        task_id="task_video",
        spec_version="1.0",
        task_mode="observe",
        timestamp=200.0,
        source="tagger",
        event_type="visual_summary",
        priority="medium",
        confidence=0.68,
        target=EventTarget(type="process", process_name="哔哩哔哩"),
        observability=Observability(True, True, True, True, "ok"),
        summary="图中有多个视频缩略图展示，每个缩略图下方有播放次数和点赞数等信息。",
    )
    thumbnail_grid = thumbnail_grid.__class__(
        **{
            **thumbnail_grid.__dict__,
            "visual": EventVisual(summary="图中有多个视频缩略图展示，每个缩略图下方有播放次数和点赞数等信息。", provider="ollama"),
        }
    )
    store.append(watched)
    store.append(thumbnail_grid)

    result = store.query(now=220.0, minutes=240, question="最近看的视频是什么")

    assert "布欧怎么出现的" in result.answer
    assert "话说龙珠" in result.answer
    assert "多个视频缩略图" not in result.answer
    assert result.matched_events[0].event_id == watched.event_id


def test_short_term_generic_content_question_filters_low_quality_ocr_from_answer() -> None:
    store = ShortTermMemoryStore(retain_seconds=15 * 60)
    noisy = build_event(
        task_id="task_page",
        spec_version="1.0",
        task_mode="observe",
        timestamp=100.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.54,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="02-05 55 96\uffff rf18iO 03-16 A<S>J 6-14 PKI *# .WF%",
    )
    noisy = noisy.__class__(
        **{
            **noisy.__dict__,
            "text": EventText(ocr_text="02-05 55 96\uffff rf18iO 03-16 A<S>J 6-14 PKI *# .WF%", normalized_text=""),
        }
    )
    readable = build_event(
        task_id="task_page",
        spec_version="1.0",
        task_mode="observe",
        timestamp=120.0,
        source="tagger",
        event_type="visual_summary",
        priority="medium",
        confidence=0.82,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="当前主内容是 Apifox 登录页，页面中央有账号登录表单。",
    )
    store.append(noisy)
    store.append(readable)

    result = store.query(now=130.0, minutes=5, question="最近页面内容是什么")

    assert "Apifox 登录页" in result.answer
    assert "rf18iO" not in result.answer
    assert "PKI" not in result.answer
