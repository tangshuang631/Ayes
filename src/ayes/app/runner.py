"""Minimal watch runner for MVP."""

from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import replace
import json
import os
from pathlib import Path
import re
from typing import Callable, List, Optional
from io import BytesIO
from uuid import uuid4

from ayes.alerting.notifier import WebhookNotifier
from ayes.capture.models import CaptureFrame, CaptureResult
from ayes.capture.screen import MacOSScreenCapture
from ayes.capture.ticker import SamplingTicker
from ayes.config.models import TargetRegion, WatchSpec
from ayes.detect.diff import ByteDiffDetector
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region, WatchMatch
from ayes.memory.short_term import QueryResult, ShortTermMemoryStore
from ayes.observation.fusion import build_structured_observation, merge_vision_observation
from ayes.ocr.models import ImageInput
from ayes.ocr.service import OCRService
from ayes.targets.discovery.macos import MacOSWindowDiscovery
from ayes.vision.ollama import OllamaService
from PIL import Image


class WatchRunner:
    def __init__(
        self,
        spec: WatchSpec,
        *,
        task_id: str = "task_mvp",
        event_sink: Optional[Callable] = None,
        log_sink: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.spec = spec
        self.task_id = task_id
        self.event_sink = event_sink
        self.log_sink = log_sink
        self.capture = MacOSScreenCapture()
        self.ocr = OCRService()
        self.diff = ByteDiffDetector()
        self.discovery = MacOSWindowDiscovery()
        self.vision = OllamaService()
        self.memory = ShortTermMemoryStore(retain_seconds=spec.memory.short_term.retain_minutes * 60)
        self.ticker = SamplingTicker(
            screenshot_interval_ms=spec.sampling.screenshot_interval_ms,
            ocr_interval_ms=spec.sampling.ocr_interval_ms,
            change_detection_interval_ms=spec.sampling.change_detection_interval_ms,
        )
        self._previous_frame: Optional[CaptureFrame] = None
        self._last_captured_frame: Optional[CaptureFrame] = None
        self._events = []
        self._last_match_event_id: Optional[str] = None
        self._last_refresh_click_at: Optional[float] = None
        self._last_run_at: Optional[float] = None
        self._last_event_at: Optional[float] = None
        self._last_alert_at: Optional[float] = None
        self._last_alert_key: Optional[str] = None
        self._vision_call_timestamps: List[float] = []
        self._evidence_dir = Path("runtime/evidence")
        self._last_evidence_cleanup_at: Optional[float] = None
        self._last_process_window_signature: Optional[tuple[int, str]] = None
        self._alert_notifier = WebhookNotifier()

    @property
    def events(self):
        return list(self._events)

    @property
    def last_run_at(self) -> Optional[float]:
        return self._last_run_at

    @property
    def last_event_at(self) -> Optional[float]:
        return self._last_event_at

    @property
    def last_captured_frame(self) -> Optional[CaptureFrame]:
        return self._last_captured_frame

    def run_once(self, *, now: Optional[float] = None) -> List[object]:
        now = now or time.time()
        self._last_run_at = now
        now_ms = int(now * 1000)
        emitted = []
        if not self.ticker.should_capture(now_ms):
            return emitted
        self.ticker.mark_capture(now_ms)
        refresh_event = self._maybe_build_refresh_click_event(now)
        if refresh_event is not None:
            self._record_event(refresh_event)
            emitted.append(refresh_event)
        capture_result = self._capture_target(now)
        if not capture_result.ok or capture_result.frame is None:
            self._write_log(
                category="capture",
                level="warning",
                message=capture_result.message or capture_result.status,
                metadata={
                    "status": capture_result.status,
                    "target_type": self.spec.target.type,
                    "process_name": self.spec.target.process_name,
                    "process_id": self.spec.target.process_id,
                    "window_id": self.spec.target.window_id,
                    "screen_id": self.spec.target.screen_id,
                },
            )
            event = self._build_capture_status_event(now, capture_result.status, capture_result.message)
            self._record_event(event)
            return [event]
        frame = capture_result.frame
        self._last_captured_frame = frame
        target_switched_event = self._maybe_build_target_switched_event(now, frame)
        if target_switched_event is not None:
            self._record_event(target_switched_event)
            emitted.append(target_switched_event)
        if self._previous_frame is not None and self.ticker.should_run_diff(now_ms):
            self.ticker.mark_diff(now_ms)
            diff_stats = self.diff.compare(self._previous_frame, frame)
            if not diff_stats.changed and self.spec.sampling.skip_ocr_when_no_change:
                event = self._build_visual_event(now, frame, "visual_change", "未检测到显著变化")
                self._record_event(event)
                self._previous_frame = frame
                return [event]
        if self.ticker.should_run_ocr(now_ms):
            self.ticker.mark_ocr(now_ms)
            regions = self._effective_regions(frame)
            for region in regions:
                cropped = self._crop_frame_to_region(frame, region)
                ocr_result = self.ocr.recognize(
                    ImageInput(
                        image_bytes=cropped.image_bytes,
                        width=cropped.width,
                        height=cropped.height,
                        source="screen_capture",
                        timestamp=now,
                        region_id=region.region_id if region else None,
                    )
                )
                event = self._build_ocr_event(
                    now,
                    cropped,
                    ocr_result.full_text,
                    ocr_result.provider,
                    blocks=ocr_result.blocks,
                    region=region,
                    target_frame=frame,
                )
                self._record_event(event)
                emitted.append(event)
                match_events = self._maybe_build_watch_match_events(event)
                emitted.extend(match_events)
                emitted.extend(self._maybe_emit_alert_events(match_events))
                should_run_vision, vision_reasons, vision_blocked_reason = self._evaluate_vision_enhancement(
                    region=region,
                    ocr_char_count=ocr_result.char_count,
                )
                if vision_reasons:
                    vision_audit_event = self._build_vision_decision_event(
                        now=now,
                        frame=frame,
                        region=region,
                        triggered=should_run_vision,
                        reasons=vision_reasons,
                        blocked_reason=vision_blocked_reason,
                    )
                    self._record_event(vision_audit_event)
                    emitted.append(vision_audit_event)
                if should_run_vision:
                    vision_event = self._maybe_build_vision_event(
                        now=now,
                        frame=cropped,
                        region=region,
                        target_frame=frame,
                    )
                    if vision_event is not None:
                        self._record_event(vision_event)
                        emitted.append(vision_event)
                        vision_match_events = self._maybe_build_watch_match_events(vision_event)
                        emitted.extend(vision_match_events)
                        emitted.extend(self._maybe_emit_alert_events(vision_match_events))
        self._cleanup_expired_evidence(now=now)
        self._previous_frame = frame
        return emitted

    def run_for_iterations(self, *, iterations: int, sleep_seconds: float = 0.0) -> List[object]:
        emitted = []
        for _ in range(iterations):
            emitted.extend(self.run_once())
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        return emitted

    def ask_recent(
        self,
        *,
        minutes: int,
        keyword: Optional[str] = None,
        question: Optional[str] = None,
        now: Optional[float] = None,
    ) -> QueryResult:
        return self.memory.query(now=now or time.time(), minutes=minutes, keyword=keyword, question=question)

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
            task_id=self.task_id,
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="capture",
            event_type="capture_status",
            priority="medium",
            confidence=1.0,
            target=self._default_event_target(),
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
                return CaptureResult(
                    ok=False,
                    status="window_not_found",
                    message=f"窗口 {self.spec.target.window_id} 当前未发现，无法继续采集",
                )
            return self._capture_window_candidate(candidate, now=now)
        if self.spec.target.type == "process":
            candidate = self.discovery.get_primary_window_for_process(
                process_name=self.spec.target.process_name,
                process_id=self.spec.target.process_id,
                only_observable=self.spec.target.only_observable_windows,
            )
            if candidate is None:
                process_label = self.spec.target.process_name or str(self.spec.target.process_id)
                return CaptureResult(
                    ok=False,
                    status="process_window_not_found",
                    message=f"进程 {process_label} 当前未找到可采集业务窗口",
                )
            return self._capture_window_candidate(candidate, now=now)
        result = self.capture.capture_main_display(timestamp=now)
        if result.ok and result.frame is not None:
            frame = replace(
                result.frame,
                metadata={
                    **(result.frame.metadata or {}),
                    "screen_id": self.spec.target.screen_id,
                },
            )
            return replace(result, frame=frame)
        return result

    def _capture_window_candidate(self, candidate, *, now: float) -> CaptureResult:
        result = self.capture.capture_window(candidate, timestamp=now)
        if not result.ok or result.frame is None:
            return result
        frame = replace(
            result.frame,
            metadata={
                **(result.frame.metadata or {}),
                "process_id": candidate.process_id,
                "process_name": candidate.process_name,
                "window_id": candidate.window_id,
                "window_title": candidate.title,
                "window_state": "onscreen" if candidate.is_onscreen else "offscreen",
                "screen_id": self.spec.target.screen_id,
            },
        )
        return replace(result, frame=frame)

    def _default_event_target(self) -> EventTarget:
        return EventTarget(
            type=self.spec.target.type,
            process_name=self.spec.target.process_name,
            process_id=self.spec.target.process_id,
            window_id=self.spec.target.window_id,
            screen_id=self.spec.target.screen_id,
        )

    def _event_target_from_frame(self, frame: Optional[CaptureFrame]) -> EventTarget:
        if frame is None:
            return self._default_event_target()
        metadata = frame.metadata or {}
        return EventTarget(
            type=self.spec.target.type,
            process_name=metadata.get("process_name") or self.spec.target.process_name,
            process_id=metadata.get("process_id") or self.spec.target.process_id,
            window_id=metadata.get("window_id") or self.spec.target.window_id,
            screen_id=metadata.get("screen_id") or self.spec.target.screen_id,
            window_title=str(metadata.get("window_title") or ""),
            window_state=str(metadata.get("window_state") or "unknown"),
        )

    def _process_window_signature(self, frame: Optional[CaptureFrame]) -> Optional[tuple[int, str]]:
        if self.spec.target.type != "process" or frame is None:
            return None
        metadata = frame.metadata or {}
        window_id = metadata.get("window_id")
        if window_id is None:
            return None
        return (int(window_id), str(metadata.get("window_title") or ""))

    def _maybe_build_target_switched_event(self, now: float, frame: CaptureFrame):
        signature = self._process_window_signature(frame)
        if signature is None:
            return None
        previous_signature = self._last_process_window_signature
        self._last_process_window_signature = signature
        if previous_signature is None or previous_signature == signature:
            return None
        previous_window_id, previous_title = previous_signature
        current_window_id, current_title = signature
        previous_label = previous_title or f"window_id={previous_window_id}"
        current_label = current_title or f"window_id={current_window_id}"
        summary = f"进程 {self.spec.target.process_name or current_window_id} 代表窗口切换: {previous_label} ({previous_window_id}) -> {current_label} ({current_window_id})"
        self._write_log(
            category="capture",
            level="info",
            message=summary,
            metadata={
                "event_type": "target_switched",
                "process_name": self.spec.target.process_name,
                "previous_window_id": previous_window_id,
                "previous_window_title": previous_title,
                "current_window_id": current_window_id,
                "current_window_title": current_title,
            },
        )
        event = build_event(
            task_id=self.task_id,
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="capture",
            event_type="target_switched",
            priority="medium",
            confidence=1.0,
            target=self._event_target_from_frame(frame),
            observability=Observability(
                has_metadata=True,
                has_pixels=True,
                is_onscreen=True,
                is_observable_candidate=True,
                capture_status="ok",
            ),
            summary=summary,
        )
        return replace(event, tags=["process_target", "target_switched"])

    def _build_visual_event(self, now: float, frame: CaptureFrame, event_type: str, summary: str):
        return build_event(
            task_id=self.task_id,
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="diff",
            event_type=event_type,
            priority="low",
            confidence=0.9,
            target=self._event_target_from_frame(frame),
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

    def _build_ocr_event(
        self,
        now: float,
        frame: CaptureFrame,
        text: str,
        provider: str,
        *,
        blocks=None,
        region: Optional[TargetRegion] = None,
        target_frame: Optional[CaptureFrame] = None,
    ):
        event = build_event(
            task_id=self.task_id,
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="ocr",
            event_type="text_change",
            priority="medium",
            confidence=0.88 if text else 0.55,
            target=self._event_target_from_frame(target_frame or frame),
            observability=Observability(
                has_metadata=True,
                has_pixels=True,
                is_onscreen=True,
                is_observable_candidate=True,
                capture_status="ok",
            ),
            summary=text[:120] if text else f"OCR 未识别到文本 ({provider})",
        )
        event_region = self._event_region_from_target_region(region, target_frame or frame)
        evidence_refs = self._write_event_evidence(
            event_id=event.event_id,
            target_frame=target_frame or frame,
            region_frame=frame,
            region=region,
        )
        block_items = list(blocks or [])
        event_text_blocks = [
            EventTextBlock(
                text=item.text,
                confidence=item.confidence,
                bbox=list(item.bbox),
                rect=self._compute_block_rect(item.bbox, frame.width, frame.height),
                rect_norm=self._compute_block_rect_norm(item.bbox, frame.width, frame.height),
                coordinate_space=getattr(item, "coordinate_space", "image_pixels"),
                line_index=item.line_index,
                block_type=item.block_type,
            )
            for item in block_items
        ]
        avg_confidence = 0.0
        if block_items:
            avg_confidence = sum(float(item.confidence) for item in block_items) / len(block_items)
        char_count = len((text or "").strip())
        sparse_text = char_count < int(self.spec.vision.ocr_sparse_min_chars or 12)
        event_region = self._event_region_from_target_region(region, target_frame or frame)
        structured_observation = build_structured_observation(
            region=asdict(event_region),
            full_text=text,
            provider=provider,
            blocks=event_text_blocks,
        )
        return replace(
            event,
            region=event_region,
            text=EventText(
                ocr_text=text,
                normalized_text=text.lower(),
                blocks=event_text_blocks,
            ),
            visual=EventVisual(
                summary=(
                    f"OCR {provider} | 字符 {char_count} | 块 {len(block_items)} | 平均置信度 {avg_confidence:.2f}"
                    + (" | 稀疏" if sparse_text else "")
                ),
                labels=[label for label in ["ocr_sparse" if sparse_text else "", "ocr_empty" if not text else ""] if label],
                attributes={
                    "ocr_provider": provider,
                    "ocr_char_count": char_count,
                    "ocr_block_count": len(block_items),
                    "ocr_avg_confidence": round(avg_confidence, 4),
                    "ocr_sparse": sparse_text,
                    "structured_observation": structured_observation,
                },
                provider=provider,
            ),
            tags=["ocr", provider],
            evidence_refs=evidence_refs,
        )

    def _effective_regions(self, frame: CaptureFrame) -> List[Optional[TargetRegion]]:
        enabled_regions = [region for region in self.spec.target.regions if region.enabled]
        return enabled_regions or [None]

    def _crop_frame_to_region(self, frame: CaptureFrame, region: Optional[TargetRegion]) -> CaptureFrame:
        if region is None:
            return frame
        image = Image.open(BytesIO(frame.image_bytes))
        left = max(0, min(region.x, frame.width - 1))
        top = max(0, min(region.y, frame.height - 1))
        right = max(left + 1, min(region.x + region.w, frame.width))
        bottom = max(top + 1, min(region.y + region.h, frame.height))
        cropped = image.crop((left, top, right, bottom))
        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        return CaptureFrame(
            frame_id=f"{frame.frame_id}:{region.region_id}",
            timestamp=frame.timestamp,
            target_type=frame.target_type,
            target_id=frame.target_id,
            width=right - left,
            height=bottom - top,
            image_bytes=buffer.getvalue(),
            metadata={**frame.metadata, "region_id": region.region_id, "region_name": region.name},
        )

    def _event_region_from_target_region(self, region: Optional[TargetRegion], frame: CaptureFrame) -> Region:
        if region is None:
            return Region(x=0, y=0, w=frame.width, h=frame.height, coordinate_space="target", x_norm=0.0, y_norm=0.0, w_norm=1.0, h_norm=1.0)
        return Region(
            region_id=region.region_id,
            name=region.name,
            x=region.x,
            y=region.y,
            w=region.w,
            h=region.h,
            coordinate_space=region.coordinate_space,
            x_norm=(region.x / frame.width) if frame.width else 0.0,
            y_norm=(region.y / frame.height) if frame.height else 0.0,
            w_norm=(region.w / frame.width) if frame.width else 0.0,
            h_norm=(region.h / frame.height) if frame.height else 0.0,
        )

    def _compute_block_rect(self, bbox: List[float], width: int, height: int) -> dict:
        if not bbox:
            return {}
        values = [float(value) for value in bbox]
        if len(values) == 4:
            x, y, w, h = values
            if self._bbox_is_normalized(values):
                return {"x": x * width, "y": y * height, "w": w * width, "h": h * height}
            return {"x": x, "y": y, "w": w, "h": h}
        xs = values[0::2]
        ys = values[1::2]
        if self._bbox_is_normalized(values):
            min_x = min(xs) * width
            max_x = max(xs) * width
            min_y = min(ys) * height
            max_y = max(ys) * height
        else:
            min_x = min(xs)
            max_x = max(xs)
            min_y = min(ys)
            max_y = max(ys)
        return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}

    def _compute_block_rect_norm(self, bbox: List[float], width: int, height: int) -> dict:
        if not bbox:
            return {}
        values = [float(value) for value in bbox]
        if self._bbox_is_normalized(values):
            if len(values) == 4:
                x, y, w, h = values
                return {"x": x, "y": y, "w": w, "h": h}
            xs = values[0::2]
            ys = values[1::2]
            return {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs), "h": max(ys) - min(ys)}
        rect = self._compute_block_rect(values, width, height)
        return {
            "x": (rect["x"] / width) if width else 0.0,
            "y": (rect["y"] / height) if height else 0.0,
            "w": (rect["w"] / width) if width else 0.0,
            "h": (rect["h"] / height) if height else 0.0,
        }

    def _bbox_is_normalized(self, values: List[float]) -> bool:
        return bool(values) and all(0.0 <= value <= 1.0 for value in values)

    def _evaluate_vision_enhancement(self, *, region: Optional[TargetRegion], ocr_char_count: int):
        if not self.spec.vision.enabled:
            return False, [], "vision_disabled"
        if self._is_vision_rate_limited():
            self._write_log(
                category="vision",
                level="info",
                message="视觉增强命中速率限制，当前轮次跳过",
                metadata={"max_calls_per_minute": self.spec.vision.max_calls_per_minute},
            )
            return False, ["rate_limited"], "rate_limited"
        reasons = []
        if self.spec.vision.trigger_when_ocr_sparse and ocr_char_count < self.spec.vision.ocr_sparse_min_chars:
            reasons.append("ocr_sparse")
        if self.spec.vision.trigger_on_visual_regions and region is not None:
            region_name = (region.name or "").lower()
            visual_keywords = ["图", "图表", "图片", "chart", "image", "icon", "按钮"]
            if any(keyword in region_name for keyword in visual_keywords):
                reasons.append("visual_region")
        if self.spec.vision.trigger_on_watch_intent and self.spec.watch_intent.enabled:
            haystack = " ".join(self.spec.watch_intent.queries).lower()
            visual_keywords = ["图", "图表", "图片", "chart", "image", "icon", "颜色", "按钮"]
            if any(keyword in haystack for keyword in visual_keywords):
                reasons.append("watch_intent_visual")
        return bool(reasons), reasons, ""

    def _build_vision_decision_event(
        self,
        *,
        now: float,
        frame: CaptureFrame,
        region: Optional[TargetRegion],
        triggered: bool,
        reasons: List[str],
        blocked_reason: str,
    ):
        event_type = "vision_triggered" if triggered else "vision_skipped"
        summary = (
            f"视觉增强已触发: {', '.join(reasons)}"
            if triggered
            else f"视觉增强已跳过: {blocked_reason or ', '.join(reasons) or 'no_reason'}"
        )
        event = build_event(
            task_id=self.task_id,
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="vision",
            event_type=event_type,
            priority="medium",
            confidence=0.82 if triggered else 0.76,
            target=self._event_target_from_frame(frame),
            observability=Observability(True, True, True, True, "ok"),
            summary=summary,
        )
        event_region = self._event_region_from_target_region(region, frame)
        return replace(
            event,
            region=event_region,
            visual=EventVisual(
                summary=summary,
                labels=[event_type, *reasons],
                attributes={
                    "vision_triggered": triggered,
                    "vision_reasons": reasons,
                    "vision_blocked_reason": blocked_reason,
                    "vision_model": self.spec.vision.model,
                    "vision_provider": self.spec.vision.provider,
                },
                provider=self.spec.vision.provider,
            ),
            tags=["vision", event_type, *reasons],
        )

    def _maybe_build_vision_event(
        self,
        *,
        now: float,
        frame: CaptureFrame,
        region: Optional[TargetRegion],
        target_frame: CaptureFrame,
    ):
        try:
            self._mark_vision_call(now)
            result = self.vision.generate_vision_summary(
                model=self.spec.vision.model,
                image_bytes=frame.image_bytes,
                prompt="请用一句简洁中文描述该区域中除文字外最重要的视觉信息，尽量包含图表、颜色状态、按钮、图标或弹窗结构。",
            )
        except Exception as exc:
            self._write_log(
                category="vision",
                level="warning",
                message=f"视觉增强执行失败: {exc}",
                metadata={
                    "model": self.spec.vision.model,
                    "region_id": region.region_id if region else "",
                },
            )
            return None
        if not result.summary:
            self._write_log(
                category="vision",
                level="info",
                message="视觉增强返回为空摘要，已跳过事件写入",
                metadata={
                    "model": self.spec.vision.model,
                    "region_id": region.region_id if region else "",
                },
            )
            return None
        event = build_event(
            task_id=self.task_id,
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="tagger",
            event_type="visual_summary",
            priority="medium",
            confidence=0.68,
            target=self._event_target_from_frame(target_frame),
            observability=Observability(
                has_metadata=True,
                has_pixels=True,
                is_onscreen=True,
                is_observable_candidate=True,
                capture_status="ok",
            ),
            summary=result.summary[:120],
        )
        return replace(
            event,
            region=self._event_region_from_target_region(region, target_frame),
            visual=EventVisual(
                summary=result.summary,
                labels=result.labels,
                attributes={
                    **result.attributes,
                    "structured_observation": merge_vision_observation(
                        build_structured_observation(
                            region=asdict(self._event_region_from_target_region(region, target_frame)),
                            full_text="",
                            provider="",
                            blocks=[],
                        ),
                        result=result,
                        fusion_notes=["OCR 文本较稀疏，已补充视觉摘要"],
                    ),
                },
                provider=result.provider,
            ),
            tags=["vision", result.provider, self.spec.vision.model],
            evidence_refs=self._write_event_evidence(
                event_id=event.event_id,
                target_frame=target_frame,
                region_frame=frame,
                region=region,
            ),
        )

    def _write_event_evidence(
        self,
        *,
        event_id: str,
        target_frame: CaptureFrame,
        region_frame: CaptureFrame,
        region: Optional[TargetRegion],
    ) -> List[str]:
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        refs: List[str] = []
        stamp = f"{int(target_frame.timestamp * 1000)}_{uuid4().hex[:8]}"
        full_name = f"{event_id}_{stamp}_full.png"
        full_path = self._evidence_dir / full_name
        full_path.write_bytes(target_frame.image_bytes)
        refs.append(str(full_path).replace("\\", "/"))
        if region is not None:
            roi_name = f"{event_id}_{stamp}_roi_{region.region_id}.png"
            roi_path = self._evidence_dir / roi_name
            roi_path.write_bytes(region_frame.image_bytes)
            refs.append(str(roi_path).replace("\\", "/"))
        return refs

    def _is_vision_rate_limited(self) -> bool:
        cutoff = (self._last_run_at or time.time()) - 60
        self._vision_call_timestamps = [item for item in self._vision_call_timestamps if item >= cutoff]
        return len(self._vision_call_timestamps) >= self.spec.vision.max_calls_per_minute

    def _cleanup_expired_evidence(self, *, now: float) -> None:
        if self._last_evidence_cleanup_at is not None and (now - self._last_evidence_cleanup_at) < 60:
            return
        self._last_evidence_cleanup_at = now
        if not self._evidence_dir.exists():
            return
        retain_seconds = self.spec.memory.short_term.retain_minutes * 60
        grace_seconds = 5 * 60
        keep_latest_files = 40
        cutoff = now - retain_seconds - grace_seconds
        candidates = sorted(
            [path for path in self._evidence_dir.glob("*.png") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        removed = 0
        for index, path in enumerate(candidates):
            if index < keep_latest_files:
                continue
            if path.stat().st_mtime >= cutoff:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                self._write_log(
                    category="system",
                    level="warning",
                    message=f"证据清理失败: {exc}",
                    metadata={"path": str(path).replace('\\', "/")},
                )
        if removed:
            self._write_log(
                category="system",
                level="info",
                message=f"已清理过期证据文件 {removed} 个",
                metadata={
                    "evidence_dir": str(self._evidence_dir).replace("\\", "/"),
                    "retain_minutes": self.spec.memory.short_term.retain_minutes,
                    "grace_seconds": grace_seconds,
                    "keep_latest_files": keep_latest_files,
                },
            )

    def _mark_vision_call(self, now: float) -> None:
        cutoff = now - 60
        self._vision_call_timestamps = [item for item in self._vision_call_timestamps if item >= cutoff]
        self._vision_call_timestamps.append(now)

    def _write_log(
        self,
        *,
        category: str,
        level: str,
        message: str,
        metadata: Optional[dict] = None,
    ) -> None:
        if self.log_sink is None:
            return
        self.log_sink(
            {
                "category": category,
                "level": level,
                "message": message,
                "task_id": self.task_id,
                "timestamp": time.time(),
                "metadata": metadata or {},
            }
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
                        task_id=self.task_id,
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
                        watch_match=WatchMatch(
                            matched=True,
                            score=0.9,
                            matched_query=query,
                            matched_rule="query_contains",
                        ),
                    ),
                    related_event_ids=[event.event_id],
                    tags=["watch_match", query],
                )
                self._record_event(match_event)
                emitted.append(match_event)
        for rule in self.spec.watch_intent.rules:
            if rule.type != "numeric_threshold":
                continue
            extracted_numbers = self._extract_numeric_candidates_from_event(
                event=event,
                field_name=rule.field or "",
                unit=rule.unit or "",
            )
            for candidate in extracted_numbers:
                if not self._compare_numeric_rule(candidate, rule.operator or "eq", rule.value or 0.0):
                    continue
                match_event = replace(
                    build_event(
                        task_id=self.task_id,
                        spec_version=self.spec.spec_version,
                        task_mode=self.spec.mode,
                        timestamp=event.timestamp,
                        source="semantic_match",
                        event_type="semantic_match",
                        priority="high",
                        confidence=0.92,
                        target=event.target,
                        observability=event.observability,
                        summary=(
                            f"命中数值阈值规则: {rule.field or 'numeric_field'} "
                            f"{rule.operator} {rule.value}，当前识别值 {candidate:g}"
                        ),
                        watch_match=WatchMatch(
                            matched=True,
                            score=1.0,
                            matched_rule=f"numeric_threshold:{rule.field or 'numeric_field'}:{rule.operator}:{rule.value}",
                            matched_value=candidate,
                            matched_unit=rule.unit or "",
                            matched_field=rule.field or "numeric_field",
                        ),
                    ),
                    related_event_ids=[event.event_id],
                    tags=["watch_match", "numeric_threshold", rule.field or "numeric_field"],
                )
                self._record_event(match_event)
                emitted.append(match_event)
                break
        return emitted

    def _extract_numeric_candidates_from_event(self, *, event, field_name: str, unit: str) -> List[float]:
        observation = ((event.visual.attributes or {}).get("structured_observation") or {})
        entities = observation.get("entities") or []
        matched_from_entities: List[float] = []
        for entity in entities:
            if str(entity.get("type") or "") != "numeric":
                continue
            entity_field = str(entity.get("field") or "").lower()
            if field_name and entity_field != field_name.lower():
                continue
            try:
                matched_from_entities.append(float(entity.get("value")))
            except (TypeError, ValueError):
                continue
        if matched_from_entities:
            return matched_from_entities
        return self._extract_numeric_candidates(
            event.text.ocr_text,
            field_name=field_name,
            unit=unit,
        )

    def _extract_numeric_candidates(self, text: str, *, field_name: str = "", unit: str = "") -> List[float]:
        if not text:
            return []
        normalized = text.replace(",", "").replace("，", "")
        contextual_candidates = self._extract_contextual_numeric_candidates(normalized, field_name=field_name, unit=unit)
        if contextual_candidates:
            return contextual_candidates
        candidates: List[float] = []
        for raw in re.findall(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?", normalized):
            try:
                candidates.append(float(raw))
            except ValueError:
                continue
        return candidates

    def _extract_contextual_numeric_candidates(self, text: str, *, field_name: str, unit: str) -> List[float]:
        aliases = self._numeric_field_aliases(field_name=field_name, unit=unit)
        if not aliases:
            return []
        candidates: List[float] = []
        for alias in aliases:
            patterns = [
                rf"{re.escape(alias)}\s*[:：=]?\s*[¥￥$]?\s*(-?\d+(?:\.\d+)?)",
                rf"[¥￥$]\s*(-?\d+(?:\.\d+)?)\s*(?:{re.escape(alias)})",
            ]
            for pattern in patterns:
                for raw in re.findall(pattern, text, flags=re.IGNORECASE):
                    try:
                        candidates.append(float(raw))
                    except ValueError:
                        continue
        return candidates

    def _numeric_field_aliases(self, *, field_name: str, unit: str) -> List[str]:
        field = (field_name or "").strip().lower()
        aliases: List[str] = []
        if field == "price":
            aliases.extend(["price", "价格", "售价", "现价", "到手价"])
            aliases.extend(["¥", "￥", "$"])
        elif field == "stock":
            aliases.extend(["stock", "库存", "余量", "剩余"])
        elif field:
            aliases.append(field)
        if unit:
            lowered_unit = unit.strip().lower()
            if lowered_unit == "cny":
                aliases.extend(["¥", "￥", "元"])
            elif lowered_unit not in aliases:
                aliases.append(lowered_unit)
        # 保持顺序并去重
        unique: List[str] = []
        for alias in aliases:
            if alias and alias not in unique:
                unique.append(alias)
        return unique

    def _compare_numeric_rule(self, candidate: float, operator: str, threshold: float) -> bool:
        if operator == "lt":
            return candidate < threshold
        if operator == "lte":
            return candidate <= threshold
        if operator == "gt":
            return candidate > threshold
        if operator == "gte":
            return candidate >= threshold
        if operator == "eq":
            return candidate == threshold
        return False

    def _maybe_emit_alert_events(self, match_events):
        if not match_events:
            return []
        if self.spec.mode != "triggered" or not self.spec.alert.enabled:
            return []
        emitted = []
        for match_event in match_events:
            threshold_met = self._priority_value(match_event.priority) >= self._priority_value(self.spec.alert.priority_threshold)
            if not threshold_met:
                continue
            alert_key = self._build_alert_dedupe_key(match_event)
            if self._is_alert_suppressed(alert_key=alert_key, now=match_event.timestamp):
                event = self._build_alert_audit_event(
                    match_event=match_event,
                    event_type="alert_suppressed",
                    summary="告警命中冷却或去重窗口，已抑制",
                )
                self._record_event(event)
                emitted.append(event)
                continue
            ok, detail = self._send_alert(match_event)
            event_type = "alert_sent" if ok else "alert_failed"
            summary = f"告警发送成功: {match_event.summary}" if ok else f"告警发送失败: {detail}"
            event = self._build_alert_audit_event(match_event=match_event, event_type=event_type, summary=summary)
            self._record_event(event)
            emitted.append(event)
            if ok:
                self._last_alert_at = match_event.timestamp
                self._last_alert_key = alert_key
        return emitted

    def _maybe_build_refresh_click_event(self, now: float):
        refresh = self.spec.actions.refresh_click
        if not refresh.enabled:
            return None
        if self._last_refresh_click_at is None or (now - self._last_refresh_click_at) >= refresh.interval_sec:
            self._last_refresh_click_at = now
            return build_event(
                task_id=self.task_id,
                spec_version=self.spec.spec_version,
                task_mode=self.spec.mode,
                timestamp=now,
                source="action",
                event_type="refresh_click",
                priority="low",
                confidence=1.0,
                target=self._default_event_target(),
                observability=Observability(
                    has_metadata=True,
                    has_pixels=False,
                    is_onscreen=True,
                    is_observable_candidate=True,
                    capture_status="ok",
                ),
                summary=f"执行刷新点击: ({refresh.point.x},{refresh.point.y})/{refresh.coordinate_space}",
            )
        return build_event(
            task_id=self.task_id,
            spec_version=self.spec.spec_version,
            task_mode=self.spec.mode,
            timestamp=now,
            source="action",
            event_type="refresh_click_skipped",
            priority="low",
            confidence=1.0,
            target=self._default_event_target(),
            observability=Observability(
                has_metadata=True,
                has_pixels=False,
                is_onscreen=True,
                is_observable_candidate=True,
                capture_status="ok",
            ),
            summary="刷新点击处于冷却期，已跳过",
        )

    def _record_event(self, event) -> None:
        self.memory.append(event)
        self._events.append(event)
        self._last_event_at = event.timestamp
        if self.event_sink is not None:
            self.event_sink(event)

    def _send_alert(self, event):
        return self._alert_notifier.send(event=event, alert_config=self.spec.alert)

    def _build_alert_dedupe_key(self, event) -> str:
        matched_query = event.watch_match.matched_query or "-"
        return f"{event.task_id}|{event.target.type}|{matched_query}|{(event.summary or '').strip().lower()}"

    def _is_alert_suppressed(self, *, alert_key: str, now: float) -> bool:
        if self._last_alert_key and self._last_alert_key == alert_key and self._last_alert_at is not None:
            if (now - self._last_alert_at) < self.spec.alert.dedupe_window_sec:
                return True
        if self._last_alert_at is not None and (now - self._last_alert_at) < self.spec.alert.cooldown_sec:
            return True
        return False

    def _build_alert_audit_event(self, *, match_event, event_type: str, summary: str):
        return replace(
            build_event(
                task_id=self.task_id,
                spec_version=self.spec.spec_version,
                task_mode=self.spec.mode,
                timestamp=match_event.timestamp,
                source="alert",
                event_type=event_type,
                priority=match_event.priority,
                confidence=match_event.confidence,
                target=match_event.target,
                observability=match_event.observability,
                summary=summary,
            ),
            related_event_ids=[match_event.event_id],
            watch_match=replace(match_event.watch_match, matched=True),
            tags=["alert", event_type],
        )

    def _priority_value(self, priority: str) -> int:
        mapping = {"low": 1, "medium": 2, "high": 3}
        return mapping.get(priority, 0)
