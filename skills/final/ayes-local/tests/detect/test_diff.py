from ayes.capture.models import CaptureFrame
from ayes.detect.diff import ByteDiffDetector


def test_byte_diff_detector_detects_changes_above_threshold() -> None:
    previous = CaptureFrame(
        frame_id="frame_1",
        timestamp=1.0,
        target_type="screen",
        target_id="main",
        width=2,
        height=2,
        image_bytes=b"\x00\x00\x00\x00",
    )
    current = CaptureFrame(
        frame_id="frame_2",
        timestamp=2.0,
        target_type="screen",
        target_id="main",
        width=2,
        height=2,
        image_bytes=b"\x00\x01\x00\x01",
    )
    stats = ByteDiffDetector(change_threshold=0.25).compare(previous, current)
    assert stats.changed is True
    assert stats.changed_pixels == 2
    assert stats.change_ratio == 0.5


def test_byte_diff_detector_returns_full_change_for_size_mismatch() -> None:
    previous = CaptureFrame(
        frame_id="frame_1",
        timestamp=1.0,
        target_type="screen",
        target_id="main",
        width=2,
        height=2,
        image_bytes=b"\x00\x00\x00\x00",
    )
    current = CaptureFrame(
        frame_id="frame_2",
        timestamp=2.0,
        target_type="screen",
        target_id="main",
        width=3,
        height=2,
        image_bytes=b"\x00\x00\x00\x00\x00\x00",
    )
    stats = ByteDiffDetector().compare(previous, current)
    assert stats.changed is True
    assert stats.change_ratio == 1.0
