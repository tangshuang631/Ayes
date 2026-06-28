import inspect

from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventVisual, Observability, Region
from ayes.memory.facts import MemoryFactExtractor


def _vision_event(*, summary, details, region=None):
    event = build_event(
        task_id="task_fact",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="vision",
        event_type="visual_summary",
        priority="medium",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome", window_title="测试窗口"),
        observability=Observability(True, True, True, True, "ok"),
        summary=summary,
    )
    return event.__class__(
        **{
            **event.__dict__,
            "region": region or Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"structured_observation": {"detail_lines": details}}),
        }
    )


def test_memory_fact_extractor_outputs_stable_slots_for_core_visual_scenes() -> None:
    extractor = MemoryFactExtractor()
    cases = [
        ("主画面是视频帧，人物近景，底部有字幕", ["视频主画面", "人物近景", "底部字幕"], "vis", "画面：视频主画面"),
        ("主内容是聊天页，上方联系人名，下方输入框", ["聊天页面", "上方联系人名", "下方输入框"], "chat", "聊天：聊天页面"),
        ("主内容是一张价格和库存表格", ["价格列", "库存列", "多行商品数据"], "tbl", "表格：价格列"),
        ("主内容是一页 PPT，标题为系统架构，左侧有缩略图列表", ["PPT 页面", "标题：系统架构", "左侧缩略图列表"], "ppt", "PPT：PPT 页面"),
        ("中部是登录表单，包含手机号输入框和获取验证码按钮", ["登录表单", "手机号输入框", "获取验证码按钮"], "frm", "表单：登录表单"),
        ("右上出现错误提示，显示请重新登录", ["右上错误提示", "请重新登录"], "sts", "状态：右上错误提示"),
        ("画面主体是一只猫，近景，浅色背景", ["图像主体", "猫的近景", "浅色背景"], "subj", "主体：图像主体"),
    ]

    for summary, details, expected_scene, expected_info in cases:
        fact = extractor.extract(_vision_event(summary=summary, details=details))
        assert fact is not None
        assert fact.info == expected_info
        assert fact.scene == expected_scene
        assert fact.region_slot == "main"
        assert fact.to_short_payload()["info"] == expected_info
        assert f"scene={expected_scene}" in fact.code


def test_memory_fact_extractor_drops_low_quality_ocr_noise() -> None:
    extractor = MemoryFactExtractor()
    event = build_event(
        task_id="task_noise",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="low",
        confidence=0.2,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="OCR 低质量文本已降权 (vision)",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_bottom_bar", name="自动底部栏"),
            "visual": EventVisual(attributes={"text_quality_score": 0.2, "text_quality_noisy": True}),
        }
    )

    assert extractor.extract(event) is None


def test_memory_fact_extractor_is_not_coupled_to_file_store() -> None:
    source = inspect.getsource(MemoryFactExtractor)

    assert "TaskMemoryFileStore" not in source
    assert "_compact_short_event" not in source


def test_memory_fact_extractor_outputs_page_fact_from_window_title_change() -> None:
    extractor = MemoryFactExtractor()
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
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"text_quality_score": 0.91, "text_quality_noisy": False}),
        }
    )

    fact = extractor.extract(event)

    assert fact is not None
    assert fact.info == "页面：Apifox 登录页"
    assert fact.code == "scene=pg|reg=main|pos=center|subj=Apifox 登录页"
    assert fact.to_short_payload(time_text="2026-10-25T16:00:00Z") == {
        "time": "2026-10-25T16:00:00Z",
        "info": "页面：Apifox 登录页",
        "code": "scene=pg|reg=main|pos=center|subj=Apifox 登录页",
        "region": "自动主内容区",
    }


def test_memory_fact_extractor_compacts_time_labeled_chat_lists() -> None:
    extractor = MemoryFactExtractor()
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
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"text_quality_score": 0.82, "text_quality_noisy": False}),
        }
    )

    fact = extractor.extract(event)

    assert fact is not None
    assert fact.info.startswith("微信会话列表：")
    assert "福利小 10:56" in fact.info
    assert fact.code == ""


def test_memory_fact_extractor_does_not_code_unclassified_natural_language_colon_text() -> None:
    extractor = MemoryFactExtractor()
    event = build_event(
        task_id="task_article",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.88,
        target=EventTarget(type="screen", screen_id=1),
        observability=Observability(True, True, True, True, "ok"),
        summary="所以更准确的判断是：如果你说的是融合两个闭源模型，难度极高。",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "region": Region(region_id="auto_center_main", name="自动主内容区"),
            "visual": EventVisual(attributes={"text_quality_score": 0.84, "text_quality_noisy": False}),
        }
    )

    fact = extractor.extract(event)

    assert fact is not None
    assert fact.info == "所以更准确的判断是：如果你说的是融合两个闭源模型，难度极高。"
    assert fact.code == ""
    assert fact.scene == ""
