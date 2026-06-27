import json

from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region
from ayes.memory.file_store import TaskMemoryFileStore


def test_task_memory_file_store_writes_short_events_by_task_and_date(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页",
    )

    path = store.append_short_event(event)

    assert path == tmp_path / "tasks" / "2026-10-25" / "task_browser" / "memory" / "short" / "2026-10-25-task_browser-details.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload == {"time": "2026-10-25T16:00:00Z", "info": "Apifox 登录页"}


def test_task_memory_file_store_writes_compact_short_events_without_heavy_ocr_fields(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "text": EventText(
                ocr_text="Apifox 登录页",
                normalized_text="apifox 登录页",
                blocks=[
                        EventTextBlock(
                            text="Apifox",
                            confidence=0.9,
                            bbox=[1, 2, 3, 4],
                            rect={"x": 1, "y": 2, "w": 3, "h": 4},
                            rect_norm={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                    )
                ],
            ),
            "region": Region(region_id="auto_center_main", name="自动主内容区", x=0, y=0, w=100, h=100),
            "visual": EventVisual(attributes={"structured_observation": {"heavy": "payload"}, "text_quality_score": 0.88}),
            "evidence_refs": ["/tmp/heavy.png"],
        }
    )

    path = store.append_short_event(event)

    encoded = path.read_text(encoding="utf-8")
    payload = json.loads(encoded.splitlines()[0])
    assert payload == {"time": "2026-10-25T16:00:00Z", "region": "自动主内容区", "info": "Apifox 登录页"}
    assert "blocks" not in encoded
    assert "bbox" not in encoded
    assert "rect_norm" not in encoded
    assert "evidence_refs" not in encoded
    assert "structured_observation" not in encoded
    assert "confidence" not in encoded
    assert "task_id" not in encoded


def test_task_memory_file_store_suppresses_consecutive_duplicate_short_events(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    first = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页",
    )
    duplicate = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944006.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页",
    )

    path = store.append_short_event(first)
    duplicate_path = store.append_short_event(duplicate)

    assert duplicate_path == path
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"time": "2026-10-25T16:00:00Z", "info": "Apifox 登录页"}


def test_task_memory_file_store_filters_gibberish_short_events(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="-.2,*.Yt.]E;-IHA iJ->AIJIfiEtJ L,I,L'l'",
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_omits_low_confidence_marker_from_short_memory(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.31,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="OCR 低质量文本已降权 (vision)",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区", x=0, y=0, w=100, h=100),
            "text": EventText(ocr_text="KIkIl\ufffd8YeSJX 0OCg0,", normalized_text="kikil 8yesjx 0ocg0"),
            "visual": EventVisual(attributes={"text_quality_score": 0.12, "text_quality_noisy": True}),
        }
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_omits_medium_quality_gibberish_fragments_from_short_memory(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_video",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.58,
        target=EventTarget(type="process", process_name="哔哩哔哩", window_title="视频播放页"),
        observability=Observability(True, True, True, True, "ok"),
        summary="%sSE7 A&IEF4B (111) Executive Producer David G.fX.Fit] %oD",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区", x=0, y=0, w=100, h=100),
            "text": EventText(
                ocr_text="%sSE7 A&IEF4B (111) Executive Producer David G.fX.Fit] %oD",
                normalized_text="sse7 aief4b 111 executive producer david gfx fit od",
            ),
            "visual": EventVisual(attributes={"text_quality_score": 0.51, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_omits_low_information_time_or_single_word_fragments(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_video",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.74,
        target=EventTarget(type="process", process_name="哔哩哔哩", window_title="视频播放页"),
        observability=Observability(True, True, True, True, "ok"),
        summary="04:33",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区", x=0, y=0, w=100, h=100),
            "text": EventText(ocr_text="04:33", normalized_text="04:33"),
            "visual": EventVisual(attributes={"text_quality_score": 0.74, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_omits_no_change_events_from_short_memory(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="diff",
        event_type="visual_change",
        priority="low",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="未检测到显著变化",
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_omits_repeated_capture_status_failures_from_short_memory(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_wechat",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="capture",
        event_type="capture_status",
        priority="medium",
        confidence=1.0,
        target=EventTarget(type="process", process_name="微信"),
        observability=Observability(True, False, True, True, "process_window_not_found"),
        summary="进程 微信 当前未找到可采集业务窗口",
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_compacts_wechat_conversation_list(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_wechat",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.86,
        target=EventTarget(type="process", process_name="微信"),
        observability=Observability(True, True, True, True, "ok"),
        summary=(
            "鲜可时斋区二群 10:45 [@所有人][303条] 服务号 10:40 才储·写给正在报志愿的学弟 "
            "接单群 10:39 [288条] luck:[动画表情] 美团深圳吃喝特... 10:36 [221条] 吃喝玩... "
            "SZU校集9群 10:34 番：乔木阁毕业出闲 麦当劳深圳高新... 10:31 麦麦种草官：[图片]"
        ),
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区", x=0, y=0, w=100, h=100),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload == {
        "time": "2026-10-25T16:00:00Z",
        "region": "自动主内容区",
        "info": "微信会话列表：鲜可时斋区二群 10:45；服务号 10:40；接单群 10:39；美团深圳吃喝特 10:36；SZU校集9群 10:34；麦当劳深圳高新 10:31",
    }


def test_task_memory_file_store_compacts_wechat_list_when_target_name_missing(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="2026-06-27_wechat_process_monitor_微信",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.86,
        target=EventTarget(type="process"),
        observability=Observability(True, True, True, True, "ok"),
        summary="福利小... 10:56 君小二-B391: 8 vIP大... 10:55 置顶本群，每天领. 10:40 圳吃喝特... 10:39",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区", x=0, y=0, w=100, h=100),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"].startswith("微信会话列表：")
    assert "福利小 10:56" in payload["info"]


def test_task_memory_file_store_compacts_generic_time_labeled_lists(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_inbox",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.86,
        target=EventTarget(type="process", process_name="Mail"),
        observability=Observability(True, True, True, True, "ok"),
        summary="订单提醒 10:56 付款成功 10:55 售后消息 10:40 系统通知 10:39",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_left_panel", name="自动左侧栏"),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "时间列表：订单提醒 10:56；付款成功 10:55；售后消息 10:40；系统通知 10:39"


def test_task_memory_file_store_prefers_window_title_fact_for_high_value_page_context(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="target_window_changed",
        priority="medium",
        confidence=0.92,
        target=EventTarget(type="process", process_name="Chrome", window_title="Apifox 登录页"),
        observability=Observability(True, True, True, True, "ok"),
        summary="窗口切换到 Apifox 登录页",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区", x=0, y=0, w=100, h=100),
            "visual": EventVisual(attributes={"text_quality_score": 0.91, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["region"] == "自动主内容区"
    assert payload["info"] == "页面：Apifox 登录页"


def test_task_memory_file_store_prefers_dialog_fact_for_visual_summary(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.88,
        target=EventTarget(type="process", process_name="Chrome", window_title="登录页面"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容是一张网页，中央出现登录弹窗，包含手机号输入框和确认按钮",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(
                summary="中央出现登录弹窗，包含手机号输入框和确认按钮",
                attributes={"text_quality_score": 0.9, "structured_observation": {"detail_lines": ["中央登录弹窗", "手机号输入框", "确认按钮"]}},
            ),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "弹窗：中央登录弹窗，手机号输入框，确认按钮"


def test_task_memory_file_store_prefers_chart_fact_for_visual_summary(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_dashboard",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome", window_title="运营看板"),
        observability=Observability(True, True, True, True, "ok"),
        summary="中部是一张折线图，走势下降，右上有红色告警标记",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(
                summary="中部是一张折线图，走势下降，右上有红色告警标记",
                attributes={"text_quality_score": 0.92, "structured_observation": {"labels": ["chart_like"], "detail_lines": ["中部折线图", "走势下降", "右上红色告警"]}},
            ),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "图表：中部折线图，走势下降，右上红色告警"


def test_task_memory_file_store_prefers_table_fact_for_visual_summary(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_sheet",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.88,
        target=EventTarget(type="process", process_name="Numbers", window_title="库存表"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容是一张价格和库存表格",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(
                summary="主内容是一张价格和库存表格",
                attributes={"text_quality_score": 0.91, "structured_observation": {"detail_lines": ["价格列", "库存列", "多行商品数据"]}},
            ),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "表格：价格列，库存列，多行商品数据"


def test_task_memory_file_store_prefers_spatial_list_fact_for_sidebar_lists(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_chat",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.89,
        target=EventTarget(type="process", process_name="Slack"),
        observability=Observability(True, True, True, True, "ok"),
        summary="项目群 10:56 设计评审 10:55 付款确认 10:40 系统通知 10:39",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_left_panel", name="自动左侧栏"),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "左侧列表：项目群 10:56；设计评审 10:55；付款确认 10:40；系统通知 10:39"


def test_task_memory_file_store_omits_low_confidence_region_noise_messages(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_wechat",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="low",
        confidence=0.2,
        target=EventTarget(type="process", process_name="微信"),
        observability=Observability(True, True, True, True, "ok"),
        summary="低置信 OCR：自动右侧栏文本质量低，已忽略原文",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_right_panel", name="自动右侧栏"),
            "visual": EventVisual(attributes={"text_quality_score": 0.2, "text_quality_noisy": True}),
        }
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_extracts_content_fact_for_document_like_scene(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_doc",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="WPS", window_title="项目进展汇报"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容是一页文档，标题为项目进展汇报，中部有三条要点说明",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(
                summary="主内容是一页文档，标题为项目进展汇报，中部有三条要点说明",
                attributes={"structured_observation": {"detail_lines": ["文档页面", "标题：项目进展汇报", "三条要点说明"]}},
            ),
        }
    )

    path = store.append_short_event(event)
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "内容：文档页面，标题：项目进展汇报，三条要点说明"


def test_task_memory_file_store_extracts_visual_scene_fact_for_video_like_scene(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_video",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome", window_title="Bilibili"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主画面是视频帧，人物近景，底部有字幕",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(
                summary="主画面是视频帧，人物近景，底部有字幕",
                attributes={"structured_observation": {"detail_lines": ["视频主画面", "人物近景", "底部字幕"]}},
            ),
        }
    )

    path = store.append_short_event(event)
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "画面：视频主画面，人物近景，底部字幕"


def test_task_memory_file_store_omits_classified_scene_with_only_subtitle_fragments(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_video_noise",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.72,
        target=EventTarget(type="process", process_name="Chrome", window_title="视频播放页"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主画面是视频帧，底部是字幕碎片和无意义字符",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(
                summary="主画面是视频帧，底部是字幕碎片和无意义字符",
                attributes={"structured_observation": {"detail_lines": ["04:33", "SSS172R AA0", "Lil\\“Lil' JE ig??*jIt"]}},
            ),
        }
    )

    path = store.append_short_event(event)

    assert not path.exists()


def test_task_memory_file_store_keeps_classified_scene_with_meaningful_primary_details(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_video_fact",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.88,
        target=EventTarget(type="process", process_name="Chrome", window_title="视频播放页"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主画面是视频帧，人物近景，底部有少量字幕",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(
                summary="主画面是视频帧，人物近景，底部有少量字幕",
                attributes={"structured_observation": {"detail_lines": ["视频主画面", "人物近景", "04:33"]}},
            ),
        }
    )

    path = store.append_short_event(event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "画面：视频主画面，人物近景"


def test_task_memory_file_store_extracts_card_fact_for_recommendation_cards(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_shop",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.88,
        target=EventTarget(type="process", process_name="Chrome", window_title="商品推荐"),
        observability=Observability(True, True, True, True, "ok"),
        summary="右侧是一列商品推荐卡片，包含缩略图、标题和价格",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_right_panel", name="自动右侧栏"),
            "visual": EventVisual(
                summary="右侧是一列商品推荐卡片，包含缩略图、标题和价格",
                attributes={"structured_observation": {"detail_lines": ["推荐卡片列表", "商品缩略图", "标题和价格"]}},
            ),
        }
    )

    path = store.append_short_event(event)
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "卡片：推荐卡片列表，商品缩略图，标题和价格"


def test_task_memory_file_store_extracts_status_fact_for_error_banner(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_console",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="high",
        confidence=0.93,
        target=EventTarget(type="process", process_name="Chrome", window_title="控制台"),
        observability=Observability(True, True, True, True, "ok"),
        summary="右上出现错误提示，显示请重新登录",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_right_panel", name="自动右侧栏"),
            "visual": EventVisual(
                summary="右上出现错误提示，显示请重新登录",
                attributes={"structured_observation": {"detail_lines": ["右上错误提示", "请重新登录"]}},
            ),
        }
    )

    path = store.append_short_event(event)
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "状态：右上错误提示，请重新登录"


def test_task_memory_file_store_extracts_form_fact_for_login_area(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_login",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.91,
        target=EventTarget(type="process", process_name="Chrome", window_title="登录"),
        observability=Observability(True, True, True, True, "ok"),
        summary="中部是登录表单，包含手机号输入框和获取验证码按钮",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": ["登录表单", "手机号输入框", "获取验证码按钮"]}}),
        }
    )

    payload = json.loads(store.append_short_event(event).read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "表单：登录表单，手机号输入框，获取验证码按钮"


def test_task_memory_file_store_extracts_navigation_fact_for_tab_area(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_nav",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.88,
        target=EventTarget(type="process", process_name="Chrome", window_title="工作台"),
        observability=Observability(True, True, True, True, "ok"),
        summary="顶部有标签导航，当前选中设置页签",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_top_bar", name="自动顶部栏"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": ["标签导航", "当前选中设置页签"]}}),
        }
    )

    payload = json.loads(store.append_short_event(event).read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "导航：标签导航，当前选中设置页签"


def test_task_memory_file_store_extracts_control_fact_for_button_group(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_controls",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome", window_title="设置"),
        observability=Observability(True, True, True, True, "ok"),
        summary="右下有保存按钮和取消按钮",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_bottom_bar", name="自动底部栏"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": ["保存按钮", "取消按钮"]}}),
        }
    )

    payload = json.loads(store.append_short_event(event).read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "控件：保存按钮，取消按钮"


def test_task_memory_file_store_extracts_slide_fact_for_ppt_page(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_ppt",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.92,
        target=EventTarget(type="process", process_name="WPS", window_title="答辩PPT"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容是一页 PPT，标题为系统架构，左侧有缩略图列表",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": ["PPT 页面", "标题：系统架构", "左侧缩略图列表"]}}),
        }
    )

    payload = json.loads(store.append_short_event(event).read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "PPT：PPT 页面，标题：系统架构，左侧缩略图列表"


def test_task_memory_file_store_extracts_chat_fact_for_chat_page(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_chat_page",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.89,
        target=EventTarget(type="process", process_name="微信", window_title="聊天窗口"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容是聊天页，上方联系人名，下方输入框",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": ["聊天页面", "上方联系人名", "下方输入框"]}}),
        }
    )

    payload = json.loads(store.append_short_event(event).read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "聊天：聊天页面，上方联系人名，下方输入框"


def test_task_memory_file_store_extracts_subject_fact_for_image_subject(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_image",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Preview", window_title="图片查看"),
        observability=Observability(True, True, True, True, "ok"),
        summary="画面主体是一只猫，近景，浅色背景",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": ["图像主体", "猫的近景", "浅色背景"]}}),
        }
    )

    payload = json.loads(store.append_short_event(event).read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "主体：图像主体，猫的近景，浅色背景"


def test_task_memory_file_store_compact_short_event_writes_ai_friendly_code(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_compact_code",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="WPS", window_title="答辩PPT"),
        observability=Observability(True, True, True, True, "ok"),
        summary="主内容是一页 PPT，标题为系统架构，左侧有缩略图列表",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": ["PPT 页面", "标题：系统架构", "左侧缩略图列表"]}}),
        }
    )

    payload = json.loads(store.append_short_event(event).read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "PPT：PPT 页面，标题：系统架构，左侧缩略图列表"
    assert payload["code"] == "scn=ppt|reg=main|k1=PPT 页面|k2=标题：系统架构|k3=左侧缩略图列表"


def test_task_memory_file_store_compacts_adjacent_duplicate_segments(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    for index, summary in enumerate(["Apifox 登录页", "Apifox 登录页", "价格页面", "价格页面", "Apifox 登录页"]):
        store.append_short_event(
            build_event(
                task_id="task_browser",
                spec_version="1.0",
                task_mode="observe",
                timestamp=1792944000.0 + index * 60,
                source="ocr",
                event_type="text_change",
                priority="medium",
                confidence=0.9,
                target=EventTarget(type="process", process_name="Chrome"),
                observability=Observability(True, True, True, True, "ok"),
                summary=summary,
            )
        )

    result = store.compact_short_memory(task_id="task_browser", timestamp=1792944300.0)

    assert result["segment_count"] == 3
    compact_path = tmp_path / "tasks" / "2026-10-25" / "task_browser" / "memory" / "compact" / "2026-10-25-task_browser-segments.jsonl"
    lines = [json.loads(line) for line in compact_path.read_text(encoding="utf-8").splitlines()]
    assert lines == [
        {
            "from": "2026-10-25T16:00:00Z",
            "to": "2026-10-25T16:01:00Z",
            "info": "Apifox 登录页",
            "repeat_count": 2,
        },
        {
            "from": "2026-10-25T16:02:00Z",
            "to": "2026-10-25T16:03:00Z",
            "info": "价格页面",
            "repeat_count": 2,
        },
        {
            "from": "2026-10-25T16:04:00Z",
            "to": "2026-10-25T16:04:00Z",
            "info": "Apifox 登录页",
            "repeat_count": 1,
        },
    ]


def test_task_memory_file_store_deletes_expired_memory_files(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    old_short = store.short_event_path(task_id="task_browser", timestamp=100.0)
    new_short = store.short_event_path(task_id="task_browser", timestamp=86400.0)
    old_long = store.long_summary_path(task_id="task_browser", timestamp=100.0)
    new_long = store.long_summary_path(task_id="task_browser", timestamp=86400.0)
    for path in [old_short, new_short, old_long, new_long]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    result = store.delete_expired_files(task_id="task_browser", short_cutoff=43200.0, long_cutoff=43200.0)

    assert result["deleted_short_files"] == 1
    assert result["deleted_long_files"] == 1
    assert not old_short.exists()
    assert new_short.exists()
    assert not old_long.exists()
    assert new_long.exists()


def test_task_memory_file_store_writes_long_summaries_by_task_and_date(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)

    path = store.append_long_summary(
        {
            "summary_id": "lts_1",
            "task_id": "task_browser",
            "window_start": 1792944000.0,
            "window_end": 1792944300.0,
            "summary": "Chrome 中出现 Apifox 登录页",
            "event_count": 3,
            "event_ids": ["evt_1"],
        }
    )

    assert path == tmp_path / "tasks" / "2026-10-25" / "task_browser" / "memory" / "long" / "2026-10-25-task_browser-summary.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload == {
        "from": "2026-10-25T16:00:00Z",
        "to": "2026-10-25T16:05:00Z",
        "info": "Chrome 中出现 Apifox 登录页",
    }


def test_task_memory_file_store_filters_internal_long_summary_parts(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)

    path = store.append_long_summary(
        {
            "summary_id": "lts_1",
            "task_id": "task_browser",
            "window_start": 1792944000.0,
            "window_end": 1792944300.0,
            "summary": "视觉增强已触发: ocr_sparse；Chrome 中出现 Apifox 登录页；视觉增强已跳过: non_primary_attention_region",
        }
    )

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "Chrome 中出现 Apifox 登录页"


def test_task_memory_file_store_skips_empty_long_summary_placeholder(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)

    path = store.append_long_summary(
        {
            "summary_id": "lts_empty",
            "task_id": "task_browser",
            "window_start": 1792944000.0,
            "window_end": 1792944300.0,
            "summary": "视觉增强已跳过: non_primary_attention_region",
        }
    )

    assert not path.exists()


def test_task_memory_file_store_suppresses_same_region_duplicate_for_longer_window(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    first = build_event(
        task_id="task_chat",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chat"),
        observability=Observability(True, True, True, True, "ok"),
        summary="左侧列表显示新的会话",
    )
    first = first.__class__(
        **{
            **first.__dict__,
            "region": Region(region_id="auto_left_panel", name="自动左侧栏"),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )
    duplicate = first.__class__(**{**first.__dict__, "timestamp": 1792944300.0})

    path = store.append_short_event(first)
    store.append_short_event(duplicate)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "time": "2026-10-25T16:00:00Z",
        "region": "自动左侧栏",
        "info": "左侧列表显示新的会话",
    }


def test_task_memory_file_store_keeps_long_running_duplicate_heartbeat(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    first = build_event(
        task_id="task_chat",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chat"),
        observability=Observability(True, True, True, True, "ok"),
        summary="左侧列表显示新的会话",
    )
    first = first.__class__(
        **{
            **first.__dict__,
            "region": Region(region_id="auto_left_panel", name="自动左侧栏"),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )
    suppressed = first.__class__(**{**first.__dict__, "timestamp": 1792944300.0})
    heartbeat = first.__class__(**{**first.__dict__, "timestamp": 1792944610.0})

    path = store.append_short_event(first)
    store.append_short_event(suppressed)
    store.append_short_event(heartbeat)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["time"] == "2026-10-25T16:00:00Z"
    assert rows[1]["time"] == "2026-10-25T16:10:10Z"


def test_task_memory_file_store_keeps_same_text_when_region_changes(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    base = build_event(
        task_id="task_dashboard",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Dashboard"),
        observability=Observability(True, True, True, True, "ok"),
        summary="登录失败",
    )
    left = base.__class__(
        **{
            **base.__dict__,
            "region": Region(region_id="auto_left_panel", name="自动左侧栏"),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )
    main = base.__class__(
        **{
            **base.__dict__,
            "timestamp": 1792944300.0,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )

    path = store.append_short_event(left)
    store.append_short_event(main)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["region"] for row in rows] == ["自动左侧栏", "自动主内容区"]


def test_task_memory_file_store_compact_segments_preserve_region(tmp_path) -> None:
    store = TaskMemoryFileStore(runtime_dir=tmp_path)
    for index, region in enumerate(["自动左侧栏", "自动左侧栏", "自动主内容区"]):
        event = build_event(
            task_id="task_spatial",
            spec_version="1.0",
            task_mode="observe",
            timestamp=1792944000.0 + index * 900,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=0.9,
            target=EventTarget(type="process", process_name="Chat"),
            observability=Observability(True, True, True, True, "ok"),
            summary="列表显示订单提醒" if region == "自动左侧栏" else "主内容区显示订单详情",
        )
        store.append_short_event(
            event.__class__(
                **{
                    **event.__dict__,
                    "region": Region(region_id=f"region_{index}", name=region),
                    "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
                }
            )
        )

    result = store.compact_short_memory(task_id="task_spatial", timestamp=1792945800.0)

    compact_path = tmp_path / "tasks" / "2026-10-25" / "task_spatial" / "memory" / "compact" / "2026-10-25-task_spatial-segments.jsonl"
    rows = [json.loads(line) for line in compact_path.read_text(encoding="utf-8").splitlines()]
    assert result["segment_count"] == 2
    assert rows[0]["region"] == "自动左侧栏"
    assert rows[0]["repeat_count"] == 2
    assert rows[1]["region"] == "自动主内容区"
