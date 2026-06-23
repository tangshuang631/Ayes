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
from ayes.capture.models import CaptureFrame
from ayes.capture.screen import MacOSScreenCapture
from ayes.capture.ticker import SamplingTicker
from ayes.config.models import TargetRegion, WatchSpec
from ayes.detect.diff import ByteDiffDetector
from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability, Region, WatchMatch
from ayes.memory.short_term import QueryResult, ShortTermMemoryStore
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
            event = self._build_capture_status_event(now, capture_result.status, capture_result.message)
            self._record_event(event)
            return [event]
        frame = capture_result.frame
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
                if self._should_run_vision_enhancement(region=region, ocr_char_count=ocr_result.char_count):
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
            task_id=self.task_id,
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
            task_id=self.task_id,
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
        event_region = self._event_region_from_target_region(region, target_frame or frame)
        evidence_refs = self._write_event_evidence(
            event_id=event.event_id,
            target_frame=target_frame or frame,
            region_frame=frame,
            region=region,
        )
        return replace(
            event,
            region=event_region,
            text=EventText(
                ocr_text=text,
                normalized_text=text.lower(),
                blocks=[
                    EventTextBlock(
                        text=item.text,
                        confidence=item.confidence,
                        bbox=list(item.bbox),
                        line_index=item.line_index,
                        block_type=item.block_type,
                    )
                    for item in (blocks or [])
                ],
            ),
            visual=EventVisual(),
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

    def _should_run_vision_enhancement(self, *, region: Optional[TargetRegion], ocr_char_count: int) -> bool:
        if not self.spec.vision.enabled:
            return False
        if self._is_vision_rate_limited():
            self._write_log(
                category="vision",
                level="info",
                message="视觉增强命中速率限制，当前轮次跳过",
                metadata={"max_calls_per_minute": self.spec.vision.max_calls_per_minute},
            )
            return False
        if self.spec.vision.trigger_when_ocr_sparse and ocr_char_count < self.spec.vision.ocr_sparse_min_chars:
            return True
        if self.spec.vision.trigger_on_visual_regions and region is not None:
            region_name = (region.name or "").lower()
            visual_keywords = ["图", "图表", "图片", "chart", "image", "icon", "按钮"]
            if any(keyword in region_name for keyword in visual_keywords):
                return True
        if self.spec.vision.trigger_on_watch_intent and self.spec.watch_intent.enabled:
            haystack = " ".join(self.spec.watch_intent.queries).lower()
            visual_keywords = ["图", "图表", "图片", "chart", "image", "icon", "颜色", "按钮"]
            if any(keyword in haystack for keyword in visual_keywords):
                return True
        return False

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
            target=EventTarget(type=self.spec.target.type, process_name=self.spec.target.process_name, screen_id=self.spec.target.screen_id),
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
                attributes=result.attributes,
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
        extracted_numbers = self._extract_numeric_candidates(event.text.ocr_text)
        for rule in self.spec.watch_intent.rules:
            if rule.type != "numeric_threshold":
                continue
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

    def _extract_numeric_candidates(self, text: str) -> List[float]:
        if not text:
            return []
        normalized = text.replace(",", "").replace("，", "")
        candidates: List[float] = []
        for raw in re.findall(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?", normalized):
            try:
                candidates.append(float(raw))
            except ValueError:
                continue
        return candidates

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
                target=EventTarget(type=self.spec.target.type, process_name=self.spec.target.process_name, screen_id=self.spec.target.screen_id),
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
            target=EventTarget(type=self.spec.target.type, process_name=self.spec.target.process_name, screen_id=self.spec.target.screen_id),
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
        if not os.environ.get(self.spec.alert.webhook_url_env):
            return False, f"未配置 webhook 环境变量: {self.spec.alert.webhook_url_env}"
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
