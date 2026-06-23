"""Minimal watch runner for MVP."""

from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import replace
import json
from pathlib import Path
from typing import List, Optional

from ayes.capture.models import CaptureFrame
from ayes.capture.screen import MacOSScreenCapture
from ayes.capture.ticker import SamplingTicker
from ayes.config.models import WatchSpec
from ayes.detect.diff import ByteDiffDetector
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, Observability
from ayes.memory.short_term import QueryResult, ShortTermMemoryStore
from ayes.ocr.models import ImageInput
from ayes.ocr.service import OCRService
from ayes.targets.discovery.macos import MacOSWindowDiscovery


class WatchRunner:
    def __init__(self, spec: WatchSpec) -> None:
        self.spec = spec
        self.capture = MacOSScreenCapture()
        self.ocr = OCRService()
        self.diff = ByteDiffDetector()
        self.discovery = MacOSWindowDiscovery()
        self.memory = ShortTermMemoryStore(retain_seconds=spec.memory.short_term.retain_minutes * 60)
        self.ticker = SamplingTicker(
            screenshot_interval_ms=spec.sampling.screenshot_interval_ms,
            ocr_interval_ms=spec.sampling.ocr_interval_ms,
            change_detection_interval_ms=spec.sampling.change_detection_interval_ms,
        )
        self._previous_frame: Optional[CaptureFrame] = None
        self._events = []
        self._last_match_event_id: Optional[str] = None

    @property
    def events(self):
        return list(self._events)

    def run_once(self, *, now: Optional[float] = None) -> List[object]:
        now = now or time.time()
        now_ms = int(now * 1000)
        emitted = []
        if not self.ticker.should_capture(now_ms):
            return emitted
        self.ticker.mark_capture(now_ms)
        capture_result = self._capture_target(now)
        if not capture_result.ok or capture_result.frame is None:
            event = self._build_capture_status_event(now, capture_result.status, capture_result.message)
            self.memory.append(event)
            self._events.append(event)
            return [event]
        frame = capture_result.frame
        if self._previous_frame is not None and self.ticker.should_run_diff(now_ms):
            self.ticker.mark_diff(now_ms)
            diff_stats = self.diff.compare(self._previous_frame, frame)
            if not diff_stats.changed and self.spec.sampling.skip_ocr_when_no_change:
                event = self._build_visual_event(now, frame, "visual_change", "未检测到显著变化")
                self.memory.append(event)
                self._events.append(event)
                self._previous_frame = frame
                return [event]
        ocr_result = None
        if self.ticker.should_run_ocr(now_ms):
            self.ticker.mark_ocr(now_ms)
            ocr_result = self.ocr.recognize(
                ImageInput(
                    image_bytes=frame.image_bytes,
                    width=frame.width,
                    height=frame.height,
                    source="screen_capture",
                    timestamp=now,
                )
            )
            event = self._build_ocr_event(now, frame, ocr_result.full_text, ocr_result.provider)
            self.memory.append(event)
            self._events.append(event)
            emitted.append(event)
            emitted.extend(self._maybe_build_watch_match_events(event))
        self._previous_frame = frame
        return emitted

    def run_for_iterations(self, *, iterations: int, sleep_seconds: float = 0.0) -> List[object]:
        emitted = []
        for _ in range(iterations):
            emitted.extend(self.run_once())
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        return emitted

    def ask_recent(self, *, minutes: int, keyword: Optional[str] = None, now: Optional[float] = None) -> QueryResult:
        return self.memory.query(now=now or time.time(), minutes=minutes, keyword=keyword)

    def check_watch_condition_recent(self, *, minutes: int, now: Optional[float] = None) -> QueryResult:
        queries = self.spec.watch_intent.queries if self.spec.watch_intent.enabled else []
        keyword = queries[0] if queries else None
        return self.memory.query(now=now or time.time(), minutes=minutes, keyword=keyword)

    def dump_events(self, path: str) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([asdict(event) for event in self._events], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_capture_status_event(self, now: float, status: str, message: str):
        return build_event(
            task_id="task_mvp",
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="capture",
            event_type="capture_status",
            priority="medium",
            confidence=1.0,
            target=EventTarget(type=self.spec.target.type, process_name=self.spec.target.process_name, screen_id=self.spec.target.screen_id),
            observability=Observability(
                has_metadata=True,
                has_pixels=False,
                is_onscreen=True,
                is_observable_candidate=True,
                capture_status=status,
            ),
            summary=message or status,
        )

    def _capture_target(self, now: float):
        if self.spec.target.type == "window" and self.spec.target.window_id is not None:
            candidate = self.discovery.get_window_by_id(self.spec.target.window_id)
            if candidate is None:
                return self.capture.capture_main_display(timestamp=now)
            return self.capture.capture_window(candidate, timestamp=now)
        return self.capture.capture_main_display(timestamp=now)

    def _build_visual_event(self, now: float, frame: CaptureFrame, event_type: str, summary: str):
        return build_event(
            task_id="task_mvp",
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="diff",
            event_type=event_type,
            priority="low",
            confidence=0.9,
            target=EventTarget(type=self.spec.target.type, process_name=self.spec.target.process_name, screen_id=self.spec.target.screen_id),
            observability=Observability(
                has_metadata=True,
                has_pixels=True,
                is_onscreen=True,
                is_observable_candidate=True,
                capture_status="ok",
            ),
            summary=summary,
            event_id=None,
        )

    def _build_ocr_event(self, now: float, frame: CaptureFrame, text: str, provider: str):
        event = build_event(
            task_id="task_mvp",
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=0.88 if text else 0.55,
            target=EventTarget(type=self.spec.target.type, process_name=self.spec.target.process_name, screen_id=self.spec.target.screen_id),
            observability=Observability(
                has_metadata=True,
                has_pixels=True,
                is_onscreen=True,
                is_observable_candidate=True,
                capture_status="ok",
            ),
            summary=text[:120] if text else f"OCR 未识别到文本 ({provider})",
        )
        return replace(
            event,
            text=EventText(
                ocr_text=text,
                normalized_text=text.lower(),
                blocks=[],
            ),
            tags=["ocr", provider],
        )

    def _maybe_build_watch_match_events(self, event):
        if not self.spec.watch_intent.enabled:
            return []
        haystack = f"{event.summary}\n{event.text.ocr_text}\n{event.text.normalized_text}".lower()
        emitted = []
        for query in self.spec.watch_intent.queries:
            if query.lower() in haystack:
                match_event = replace(
                    build_event(
                        task_id="task_mvp",
                        spec_version=self.spec.spec_version,
                        task_mode=self.spec.mode,
                        timestamp=event.timestamp,
                        source="semantic_match",
                        event_type="semantic_match",
                        priority="high",
                        confidence=0.9,
                        target=event.target,
                        observability=event.observability,
                        summary=f"命中监控关键词: {query}",
                    ),
                    related_event_ids=[event.event_id],
                    tags=["watch_match", query],
                )
                self.memory.append(match_event)
                self._events.append(match_event)
                emitted.append(match_event)
        return emitted
