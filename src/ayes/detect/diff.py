"""Lightweight byte-level diff detector."""

from __future__ import annotations

from ayes.capture.models import CaptureFrame
from ayes.detect.models import DiffStats


class ByteDiffDetector:
    def __init__(self, *, change_threshold: float = 0.01) -> None:
        self.change_threshold = change_threshold

    def compare(self, previous: CaptureFrame, current: CaptureFrame) -> DiffStats:
        if previous.width != current.width or previous.height != current.height:
            return DiffStats(
                changed_pixels=max(previous.width * previous.height, current.width * current.height),
                total_pixels=max(previous.width * previous.height, current.width * current.height),
                change_ratio=1.0,
                changed=True,
            )
        prev_bytes = previous.image_bytes
        curr_bytes = current.image_bytes
        sample_length = min(len(prev_bytes), len(curr_bytes))
        if sample_length == 0:
            return DiffStats(changed_pixels=0, total_pixels=0, change_ratio=0.0, changed=False)
        changed_bytes = sum(1 for index in range(sample_length) if prev_bytes[index] != curr_bytes[index])
        total_pixels = previous.width * previous.height
        change_ratio = changed_bytes / sample_length
        return DiffStats(
            changed_pixels=changed_bytes,
            total_pixels=total_pixels,
            change_ratio=change_ratio,
            changed=change_ratio >= self.change_threshold,
        )
