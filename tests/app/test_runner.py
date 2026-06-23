from ayes.app.runner import WatchRunner
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.config.models import WatchSpec
from ayes.ocr.models import OCRResult


class FakeCapture:
    def __init__(self) -> None:
        self.calls = 0

    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        self.calls += 1
        payload = b"frame-1" if self.calls == 1 else b"frame-2-with-change"
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
        return OCRResult(provider="fake", elapsed_ms=1, full_text="库存恢复")


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
