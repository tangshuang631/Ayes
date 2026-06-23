from ayes.app.runner import WatchRunner
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.config.models import WatchSpec
from ayes.ocr.models import OCRResult, OCRTextBlock
from ayes.vision.models import VisionResult
from PIL import Image
from io import BytesIO


def make_png_bytes(color: str) -> bytes:
    image = Image.new("RGB", (2, 2), color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeCapture:
    def __init__(self) -> None:
        self.calls = 0

    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        self.calls += 1
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
    assert len(first) == 1
    assert len(second) == 1
    result = runner.ask_recent(minutes=5, keyword="库存", now=102.0)
    assert len(result.matched_events) >= 1
    assert "库存" in result.answer


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
