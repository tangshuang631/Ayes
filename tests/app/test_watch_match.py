from ayes.app.runner import WatchRunner
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.config.models import WatchSpec
from ayes.ocr.models import OCRResult


class FakeCapture:
    def capture_main_display(self, *, timestamp: float) -> CaptureResult:
        return CaptureResult(
            ok=True,
            status="ok",
            frame=CaptureFrame(
                frame_id="frame_1",
                timestamp=timestamp,
                target_type="screen",
                target_id="main",
                width=2,
                height=2,
                image_bytes=b"watch-match",
            ),
        )


class FakeOCR:
    def recognize(self, image, options=None) -> OCRResult:
        return OCRResult(provider="fake", elapsed_ms=1, full_text="库存恢复，立即下单")


def test_runner_emits_watch_match_event_when_query_hits() -> None:
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
                "summary": "有货提醒",
                "queries": ["库存恢复"],
            },
        }
    )
    runner = WatchRunner(spec)
    runner.capture = FakeCapture()
    runner.ocr = FakeOCR()
    events = runner.run_once(now=100.0)
    assert any(event.event_type == "semantic_match" for event in events)
