from ayes.app.runner import WatchRunner
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.config.models import WatchSpec
from ayes.ocr.models import OCRResult, OCRTextBlock
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
