"""Sampling tick planner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SamplingTicker:
    screenshot_interval_ms: int
    ocr_interval_ms: int
    change_detection_interval_ms: int
    _last_screenshot_ms: Optional[int] = None
    _last_ocr_ms: Optional[int] = None
    _last_diff_ms: Optional[int] = None

    def should_capture(self, now_ms: int) -> bool:
        return self._should_fire(now_ms, self.screenshot_interval_ms, self._last_screenshot_ms)

    def should_run_ocr(self, now_ms: int) -> bool:
        return self._should_fire(now_ms, self.ocr_interval_ms, self._last_ocr_ms)

    def should_run_diff(self, now_ms: int) -> bool:
        return self._should_fire(now_ms, self.change_detection_interval_ms, self._last_diff_ms)

    def mark_capture(self, now_ms: int) -> None:
        self._last_screenshot_ms = now_ms

    def mark_ocr(self, now_ms: int) -> None:
        self._last_ocr_ms = now_ms

    def mark_diff(self, now_ms: int) -> None:
        self._last_diff_ms = now_ms

    @staticmethod
    def _should_fire(now_ms: int, interval_ms: int, last_ms: Optional[int]) -> bool:
        if last_ms is None:
            return True
        return (now_ms - last_ms) >= interval_ms
