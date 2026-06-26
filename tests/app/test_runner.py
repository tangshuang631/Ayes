from ayes.app.runner import WatchRunner
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.config.models import WatchSpec
from ayes.ocr.models import OCRResult, OCRTextBlock
from ayes.targets.models import Bounds, ObservabilityStatus, WindowCandidate
from ayes.vision.models import VisionResult
from PIL import Image
from io import BytesIO
from pathlib import Path
import os


def make_png_bytes(color: str) -> bytes:
    image = Image.new("RGB", (2, 2), color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeCapture:
    def __init__(self) -> None:
        self.calls = 0
        self.main_display_calls = 0
        self.window_calls = []

    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        self.calls += 1
        self.main_display_calls += 1
        payload = make_png_bytes("white") if self.calls == 1 else make_png_bytes("black")
        return CaptureResult(
            ok=True,
            status="ok",
            frame=CaptureFrame(
                frame_id=f"frame_{self.calls}",
                timestamp=timestamp,
                target_type="screen",
                target_id="main",
                width=2,
                height=2,
                image_bytes=payload,
            ),
        )

    def capture_window(self, candidate: WindowCandidate, *, timestamp: float) -> CaptureResult:
        self.calls += 1
        self.window_calls.append(candidate.window_id)
        return CaptureResult(
            ok=True,
            status="ok",
            frame=CaptureFrame(
                frame_id=f"window_{candidate.window_id}_{self.calls}",
                timestamp=timestamp,
                target_type="window",
                target_id=str(candidate.window_id),
                width=max(candidate.bounds.width, 2),
                height=max(candidate.bounds.height, 2),
                image_bytes=make_png_bytes("blue"),
            ),
        )


class LargeFakeCapture:
    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        return CaptureResult(
            ok=True,
            status="ok",
            frame=CaptureFrame(
                frame_id="large_frame_1",
                timestamp=timestamp,
                target_type="screen",
                target_id="main",
                width=100,
                height=80,
                image_bytes=make_png_bytes("white"),
            ),
        )


class FakeDiscovery:
    def __init__(self, *, window_by_id=None, process_window=None) -> None:
        self.window_by_id = window_by_id
        self.process_window = process_window

    def get_window_by_id(self, window_id: int):
        if self.window_by_id is not None and self.window_by_id.window_id == window_id:
            return self.window_by_id
        return None

    def get_primary_window_for_process(self, *, process_name=None, process_id=None, only_observable=True):
        return self.process_window


class SequenceDiscovery:
    def __init__(self, windows) -> None:
        self.windows = list(windows)
        self.index = 0

    def get_primary_window_for_process(self, *, process_name=None, process_id=None, only_observable=True):
        if not self.windows:
            return None
        candidate = self.windows[min(self.index, len(self.windows) - 1)]
        self.index += 1
        return candidate


def make_window_candidate(*, window_id: int, process_id: int = 100, process_name: str = "TargetApp") -> WindowCandidate:
    return WindowCandidate(
        window_id=window_id,
        process_id=process_id,
        process_name=process_name,
        title="商品页",
        bounds=Bounds(x=10, y=10, width=1280, height=720),
        layer=0,
        is_onscreen=True,
        observability=ObservabilityStatus(code="observable", label="可观测", has_pixels=True, is_recommended=True),
        is_business_candidate=True,
        metadata={},
    )


class FakeOCR:
    def recognize(self, image, options=None) -> OCRResult:
        return OCRResult(provider="fake", elapsed_ms=1, full_text="库存恢复", char_count=len("库存恢复"))


class SparseOCR:
    def recognize(self, image, options=None) -> OCRResult:
        return OCRResult(provider="fake", elapsed_ms=1, full_text="", char_count=0)


class FakeVision:
    def generate_vision_summary(self, *, model: str, image_bytes: bytes, prompt: str) -> VisionResult:
        return VisionResult(
            provider="ollama",
            model=model,
            summary="图表区域呈下降趋势，右侧有一个可点击按钮",
            labels=["chart_like", "button_like"],
            attributes={"trend": "down"},
        )


class FakeOCRWithBlocks:
    def recognize(self, image, options=None) -> OCRResult:
        return OCRResult(
            provider="fake",
            elapsed_ms=1,
            full_text="价格 199\n立即购买",
            char_count=len("价格199立即购买"),
            blocks=[
                OCRTextBlock(text="价格 199", confidence=0.98, bbox=[10, 20, 110, 20, 110, 48, 10, 48], line_index=0),
                OCRTextBlock(text="立即购买", confidence=0.97, bbox=[12, 70, 90, 70, 90, 98, 12, 98], line_index=1),
            ],
        )


class FakeLayoutAwareOCR:
    def recognize(self, image, options=None) -> OCRResult:
        width = int(getattr(image, "width", 0) or 0)
        height = int(getattr(image, "height", 0) or 0)
        if width <= 2 and height <= 2:
            return OCRResult(
                provider="fake",
                elapsed_ms=1,
                full_text="角落状态 1",
                char_count=len("角落状态 1"),
                blocks=[
                    OCRTextBlock(
                        text="角落状态 1",
                        confidence=0.9,
                        bbox=[0.05, 0.05, 0.25, 0.05, 0.25, 0.18, 0.05, 0.18],
                        line_index=0,
                    )
                ],
            )
        return OCRResult(
            provider="fake",
            elapsed_ms=1,
            full_text="Apifox 登录页",
            char_count=len("Apifox 登录页"),
            blocks=[
                OCRTextBlock(
                    text="Apifox 登录页",
                    confidence=0.98,
                    bbox=[0.25, 0.28, 0.78, 0.28, 0.78, 0.62, 0.25, 0.62],
                    line_index=0,
                )
            ],
        )


class FailingVision:
    def generate_vision_summary(self, *, model: str, image_bytes: bytes, prompt: str) -> VisionResult:
        raise RuntimeError("mock vision failure")


def test_runner_writes_ocr_event_and_supports_recent_query() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = FakeOCR()
    first = runner.run_once(now=100.0)
    second = runner.run_once(now=101.0)
    assert any(event.event_type == "text_change" for event in first)
    assert any(event.event_type == "text_change" for event in second)
    result = runner.ask_recent(minutes=5, keyword="库存", now=102.0)
    assert len(result.matched_events) >= 1
    assert "库存" in result.answer


def test_runner_process_target_captures_primary_process_window() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "TargetApp"},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.discovery = FakeDiscovery(process_window=make_window_candidate(window_id=42))
    runner.ocr = FakeOCR()

    events = runner.run_once(now=100.0)

    text_event = next(event for event in events if event.event_type == "text_change")
    assert text_event.target.type == "process"
    assert text_event.target.process_name == "TargetApp"
    assert text_event.target.window_id == 42
    assert text_event.target.window_title == "商品页"
    assert runner.capture.window_calls == [42]
    assert runner.capture.main_display_calls == 0


def test_runner_process_target_emits_capture_status_when_process_window_missing() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "TargetApp"},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.discovery = FakeDiscovery(process_window=None)
    runner.ocr = FakeOCR()

    events = runner.run_once(now=100.0)

    assert len(events) == 1
    assert events[0].event_type == "capture_status"
    assert events[0].observability.capture_status == "process_window_not_found"
    assert runner.capture.main_display_calls == 0


def test_runner_process_target_writes_warning_log_when_process_window_missing() -> None:
    logs = []
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "TargetApp"},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec, log_sink=logs.append)
    runner.capture = FakeCapture()
    runner.discovery = FakeDiscovery(process_window=None)
    runner.ocr = FakeOCR()

    runner.run_once(now=100.0)

    assert logs
    assert logs[-1]["category"] == "capture"
    assert logs[-1]["level"] == "warning"
    assert "未找到可采集业务窗口" in logs[-1]["message"]


def test_runner_ocr_event_contains_structured_observation() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_price",
                        "name": "价格区",
                        "x": 0,
                        "y": 0,
                        "w": 2,
                        "h": 2,
                    }
                ],
            },
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = FakeOCRWithBlocks()

    events = runner.run_once(now=100.0)

    observation = events[0].visual.attributes["structured_observation"]
    assert observation["text"]["full_text"] == "价格 199\n立即购买"
    assert observation["layout"]["block_count"] == 2
    assert any(entity["field"] == "price" for entity in observation["entities"])
    assert observation["region"]["region_id"] == "roi_price"


def test_runner_vision_event_contains_structured_observation() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_chart",
                        "name": "图表区",
                        "x": 0,
                        "y": 0,
                        "w": 2,
                        "h": 2,
                    }
                ],
            },
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "qwen2.5vl:7b",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 999,
                "trigger_on_visual_regions": True,
                "trigger_on_watch_intent": False,
                "trigger_on_question_semantics": False,
                "max_calls_per_minute": 6,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = SparseOCR()
    runner.vision = FakeVision()

    events = runner.run_once(now=100.0)

    vision_event = next(event for event in events if event.event_type == "visual_summary")
    observation = vision_event.visual.attributes["structured_observation"]
    assert observation["source"] == "ocr+vision"
    assert observation["visual"]["summary"] == "图表区域呈下降趋势，右侧有一个可点击按钮"
    assert "OCR 文本较稀疏" in observation["fusion_notes"][0]


def test_runner_without_roi_generates_attention_regions_for_full_target() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    regions = runner._effective_regions(
        CaptureFrame(
            frame_id="frame_attention",
            timestamp=100.0,
            target_type="screen",
            target_id="main",
            width=100,
            height=80,
            image_bytes=make_png_bytes("white"),
        )
    )

    region_ids = [region.region_id for region in regions if region is not None]
    assert "auto_full" in region_ids
    assert "auto_center_main" in region_ids
    assert any(region_id.startswith("auto_") for region_id in region_ids)


def test_runner_without_roi_prioritizes_center_attention_over_corner_text() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = LargeFakeCapture()
    runner.ocr = FakeLayoutAwareOCR()

    events = runner.run_once(now=100.0)

    primary_event = next(event for event in events if event.event_type == "text_change")
    observation = primary_event.visual.attributes["structured_observation"]
    assert observation["text"]["full_text"] == "Apifox 登录页"
    assert observation["region"]["region_id"] == "auto_center_main"


def test_runner_without_roi_still_records_lower_weight_context_regions() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = LargeFakeCapture()
    runner.ocr = SparseOCR()

    events = runner.run_once(now=100.0)

    region_ids = {event.region.region_id for event in events if event.event_type == "text_change"}
    assert "auto_center_main" in region_ids
    assert "auto_top_bar" in region_ids
    assert "auto_left_panel" in region_ids
    assert "auto_right_panel" in region_ids
    assert "auto_bottom_bar" in region_ids
    assert "auto_full" in region_ids


def test_runner_without_roi_triggers_vision_on_primary_attention_region_only() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "qwen2.5vl:7b",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 999,
                "trigger_on_visual_regions": True,
                "trigger_on_watch_intent": False,
                "trigger_on_question_semantics": False,
                "max_calls_per_minute": 6,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = LargeFakeCapture()
    runner.ocr = SparseOCR()
    runner.vision = FakeVision()

    events = runner.run_once(now=100.0)

    vision_events = [event for event in events if event.event_type == "visual_summary"]
    assert len(vision_events) == 1
    assert vision_events[0].region.region_id == "auto_center_main"


def test_runner_process_target_emits_target_switched_event_when_representative_window_changes() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "process", "process_name": "TargetApp"},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.discovery = SequenceDiscovery(
        [
            make_window_candidate(window_id=42, process_name="TargetApp"),
            make_window_candidate(window_id=43, process_name="TargetApp"),
        ]
    )
    runner.ocr = FakeOCR()

    first_events = runner.run_once(now=100.0)
    second_events = runner.run_once(now=101.0)

    assert all(event.event_type != "target_switched" for event in first_events)
    switch_events = [event for event in second_events if event.event_type == "target_switched"]
    assert len(switch_events) == 1
    assert switch_events[0].target.window_id == 43
    assert "42" in switch_events[0].summary
    assert "43" in switch_events[0].summary


def test_runner_emits_refresh_click_events_when_action_enabled() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
            "actions": {
                "refresh_click": {
                    "enabled": True,
                    "point": {"x": 10, "y": 20},
                    "coordinate_space": "screen",
                    "interval_sec": 1,
                    "cooldown_sec": 1,
                }
            },
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = FakeOCR()
    first = runner.run_once(now=100.0)
    second = runner.run_once(now=100.2)
    assert any(event.event_type == "refresh_click" for event in first)
    assert any(event.event_type == "refresh_click_skipped" for event in second)


def test_runner_emits_alert_sent_event_when_triggered_alert_matches() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {
                "enabled": True,
                "summary": "库存恢复提醒",
                "queries": ["库存恢复"],
            },
            "alert": {
                "enabled": True,
                "channel": "wecom_webhook",
                "webhook_url_env": "AYES_TEST_WEBHOOK_URL",
                "priority_threshold": "medium",
                "cooldown_sec": 0,
                "dedupe_window_sec": 0,
            },
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = FakeOCR()
    runner._send_alert = lambda event: (True, "sent")
    events = runner.run_once(now=100.0)
    assert any(event.event_type == "semantic_match" for event in events)
    assert any(event.event_type == "alert_sent" for event in events)


def test_runner_emits_visual_summary_when_vision_enabled_and_ocr_sparse() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_chart",
                        "name": "图表区域",
                        "x": 0,
                        "y": 0,
                        "w": 1,
                        "h": 1,
                        "coordinate_space": "target",
                        "enabled": True,
                    }
                ],
            },
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "fake-vision-model",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 12,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = SparseOCR()
    runner.vision = FakeVision()
    events = runner.run_once(now=100.0)
    assert any(event.event_type == "text_change" for event in events)
    assert any(event.event_type == "visual_summary" for event in events)


def test_runner_preserves_ocr_blocks_and_region_coordinates_in_event() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [
                    {
                        "region_id": "roi_price",
                        "name": "价格区域",
                        "x": 0,
                        "y": 0,
                        "w": 1,
                        "h": 1,
                        "coordinate_space": "target",
                        "enabled": True,
                    }
                ],
            },
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = FakeOCRWithBlocks()
    events = runner.run_once(now=100.0)
    text_event = next(event for event in events if event.event_type == "text_change")
    assert text_event.region.region_id == "roi_price"
    assert text_event.region.name == "价格区域"
    assert len(text_event.text.blocks) == 2
    assert text_event.text.blocks[0].text == "价格 199"
    assert text_event.text.blocks[0].bbox == [10, 20, 110, 20, 110, 48, 10, 48]
    assert text_event.text.blocks[0].rect == {"x": 10.0, "y": 20.0, "w": 100.0, "h": 28.0}
    assert text_event.text.blocks[0].rect_norm == {"x": 10.0, "y": 20.0, "w": 100.0, "h": 28.0}
    assert text_event.text.blocks[0].coordinate_space == "image_pixels"
    assert any(ref.startswith("runtime/evidence/") for ref in text_event.evidence_refs)
    assert any("full" in ref for ref in text_event.evidence_refs)
    assert any("roi" in ref for ref in text_event.evidence_refs)
    for ref in text_event.evidence_refs:
        assert Path(ref).exists()


def test_runner_normalizes_vision_ocr_rectangles_to_pixels_and_ratios() -> None:
    class VisionLikeOCR:
        def recognize(self, image, options=None) -> OCRResult:
            return OCRResult(
                provider="vision",
                elapsed_ms=1,
                full_text="库存恢复",
                char_count=len("库存恢复"),
                blocks=[
                    OCRTextBlock(
                        text="库存恢复",
                        confidence=0.96,
                        bbox=[0.25, 0.50, 0.50, 0.20],
                        line_index=0,
                    )
                ],
            )

    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = VisionLikeOCR()
    events = runner.run_once(now=100.0)
    text_event = next(event for event in events if event.event_type == "text_change")
    block = text_event.text.blocks[0]
    assert block.rect == {"x": 0.5, "y": 1.0, "w": 1.0, "h": 0.4}
    assert block.rect_norm == {"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.2}
    assert block.coordinate_space == "image_pixels"


def test_runner_logs_vision_failure_when_enhancement_errors() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "fake-vision-model",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 12,
                "max_calls_per_minute": 3,
            },
            "watch_intent": {"enabled": False},
        }
    )
    logs = []
    runner = WatchRunner(spec, log_sink=logs.append)
    runner.capture = FakeCapture()
    runner.ocr = SparseOCR()
    runner.vision = FailingVision()
    events = runner.run_once(now=100.0)
    assert not any(event.event_type == "visual_summary" for event in events)
    assert any(item["category"] == "vision" and item["level"] == "warning" for item in logs)
    assert any("mock vision failure" in item["message"] for item in logs)


def test_runner_throttles_vision_enhancement_by_calls_per_minute() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "fake-vision-model",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 12,
                "max_calls_per_minute": 1,
            },
            "watch_intent": {"enabled": False},
        }
    )
    logs = []
    runner = WatchRunner(spec, log_sink=logs.append)
    runner.capture = FakeCapture()
    runner.ocr = SparseOCR()
    runner.vision = FakeVision()
    first_events = runner.run_once(now=100.0)
    second_events = runner.run_once(now=101.0)
    assert any(event.event_type == "visual_summary" for event in first_events)
    assert not any(event.event_type == "visual_summary" for event in second_events)
    assert any(item["category"] == "vision" and "速率限制" in item["message"] for item in logs)


def test_runner_skips_vision_for_numeric_threshold_tasks_even_when_ocr_sparse() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "triggered",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "fake-vision-model",
                "trigger_when_ocr_sparse": True,
                "ocr_sparse_min_chars": 12,
                "disable_for_numeric_only_tasks": True,
                "disable_for_threshold_rules": True,
            },
            "watch_intent": {
                "enabled": True,
                "summary": "价格低于 299 时提醒",
                "queries": ["价格低于 299"],
                "rules": [{"type": "numeric_threshold", "field": "price", "operator": "lt", "value": 299}],
            },
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = SparseOCR()
    runner.vision = FakeVision()
    events = runner.run_once(now=100.0)
    assert not any(event.event_type == "visual_summary" for event in events)
    decision = next(event for event in events if event.event_type == "vision_skipped")
    assert "threshold_rule_disabled" in (decision.visual.attributes.get("vision_blocked_reason") or "")


def test_runner_uses_vision_every_n_runs_when_enabled_by_user_policy() -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {
                "type": "screen",
                "screen_id": 1,
                "regions": [{"region_id": "roi_chart", "name": "图表区", "x": 0, "y": 0, "w": 1, "h": 1}],
            },
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "vision": {
                "enabled": True,
                "provider": "ollama",
                "model": "fake-vision-model",
                "trigger_on_visual_regions": True,
                "sampling_every_n_runs": 3,
            },
            "watch_intent": {"enabled": False},
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = SparseOCR()
    runner.vision = FakeVision()
    first = runner.run_once(now=100.0)
    second = runner.run_once(now=101.0)
    third = runner.run_once(now=102.0)
    assert not any(event.event_type == "visual_summary" for event in first)
    assert not any(event.event_type == "visual_summary" for event in second)
    assert any(event.event_type == "visual_summary" for event in third)


def test_runner_cleans_expired_evidence_files_but_keeps_recent_ones(tmp_path) -> None:
    spec = WatchSpec.from_dict(
        {
            "spec_version": "1.0",
            "mode": "observe",
            "target": {"type": "screen", "screen_id": 1},
            "sampling": {
                "screenshot_interval_ms": 1,
                "ocr_interval_ms": 1,
                "change_detection_interval_ms": 1,
                "max_fps": 2,
                "skip_ocr_when_no_change": False,
            },
            "watch_intent": {"enabled": False},
            "memory": {
                "short_term": {
                    "enabled": True,
                    "retain_minutes": 1,
                    "detail_level": "high",
                }
            },
        }
    )
    logs = []
    runner = WatchRunner(spec, log_sink=logs.append)
    runner.capture = FakeCapture()
    runner.ocr = FakeOCR()
    runner._evidence_dir = tmp_path / "evidence"
    runner._evidence_dir.mkdir(parents=True, exist_ok=True)

    old_file = runner._evidence_dir / "old.png"
    old_file.write_bytes(make_png_bytes("red"))
    stale_ts = 100.0 - (spec.memory.short_term.retain_minutes * 60) - 301
    os.utime(old_file, (stale_ts, stale_ts))

    # 构造足够多的新文件，覆盖“保留最新 40 个文件”的保守策略。
    for index in range(45):
        extra_file = runner._evidence_dir / f"fresh_{index}.png"
        extra_file.write_bytes(make_png_bytes("green"))
        extra_ts = 100.0 - 20 + index * 0.001
        os.utime(extra_file, (extra_ts, extra_ts))

    preserved_file = runner._evidence_dir / "fresh.png"
    preserved_file.write_bytes(make_png_bytes("blue"))
    fresh_ts = 100.0 - 30
    os.utime(preserved_file, (fresh_ts, fresh_ts))

    runner.run_once(now=100.0)

    assert not old_file.exists()
    assert preserved_file.exists()
    assert any(item["category"] == "system" and "已清理过期证据文件" in item["message"] for item in logs)
