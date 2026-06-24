"""Shared application state for API and Web UI."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Optional

from ayes.app.runner import WatchRunner
from ayes.api.contracts import _describe_direction, build_task_payload, describe_location_summary
from ayes.config.models import WatchSpec
from ayes.logs.store import LogStore
from ayes.memory.long_term import build_long_term_summary
from ayes.storage.sqlite_store import SQLiteStore
from ayes.targets.discovery.macos import MacOSWindowDiscovery


class AppState:
    def __init__(self) -> None:
        self.sqlite_store = SQLiteStore()
        self.log_store = LogStore(sink=self.sqlite_store.insert_log)
        self.window_discovery = MacOSWindowDiscovery()
        self.current_runner: Optional[WatchRunner] = None
        self.current_spec: Optional[WatchSpec] = None
        self.current_task_id: Optional[str] = None
        self.last_task_id: Optional[str] = None
        self.last_screenshot_path: Optional[str] = None
        self.last_error: Optional[str] = None
        self._frontend_sessions: dict[str, float] = {}
        self._frontend_session_ttl_sec = 30.0
        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_long_term_summary_at: Optional[float] = None
        self._last_long_term_event_index: int = 0
        self.log_store.write(category="system", level="info", message="Ayes AppState 初始化完成")

    def _build_task_snapshot(self) -> Optional[dict]:
        if self.current_spec is None:
            return None
        enabled_regions = [region for region in self.current_spec.target.regions if region.enabled]
        return {
            "mode": self.current_spec.mode,
            "target_type": self.current_spec.target.type,
            "target_label": self.current_spec.target.process_name or self.current_spec.target.window_id or self.current_spec.target.screen_id,
            "region_count": len(enabled_regions),
            "region_names": [region.name for region in enabled_regions],
            "sampling": {
                "screenshot_interval_ms": self.current_spec.sampling.screenshot_interval_ms,
                "ocr_interval_ms": self.current_spec.sampling.ocr_interval_ms,
                "change_detection_interval_ms": self.current_spec.sampling.change_detection_interval_ms,
                "skip_ocr_when_no_change": self.current_spec.sampling.skip_ocr_when_no_change,
            },
            "vision_enabled": self.current_spec.vision.enabled,
            "vision_model": self.current_spec.vision.model if self.current_spec.vision.enabled else "",
            "alert_enabled": self.current_spec.alert.enabled,
            "refresh_click_enabled": self.current_spec.actions.refresh_click.enabled,
            "short_term_minutes": self.current_spec.memory.short_term.retain_minutes,
            "long_term_hours": self.current_spec.memory.long_term.retain_hours,
        }

    def _prune_expired_long_term_summaries(self, *, task_id: str, now: Optional[float] = None) -> int:
        if self.current_spec is None or not self.current_spec.memory.long_term.enabled:
            return 0
        current_now = now if now is not None else time.time()
        cutoff_timestamp = current_now - (self.current_spec.memory.long_term.retain_hours * 60 * 60)
        removed = self.sqlite_store.delete_long_term_summaries_before(task_id=task_id, cutoff_timestamp=cutoff_timestamp)
        if removed:
            self.log_store.write(
                category="watch",
                level="info",
                message=f"已清理过期长期摘要 {removed} 条",
                task_id=task_id,
                metadata={
                    "cutoff_timestamp": cutoff_timestamp,
                    "retain_hours": self.current_spec.memory.long_term.retain_hours,
                },
            )
        return removed

    def _runner_log_sink(self, payload: dict) -> None:
        self.log_store.write(
            category=str(payload.get("category") or "system"),
            level=str(payload.get("level") or "info"),
            message=str(payload.get("message") or ""),
            task_id=payload.get("task_id"),
            metadata=payload.get("metadata") or {},
            timestamp=payload.get("timestamp"),
        )

    def set_runner(self, spec: WatchSpec, task_id: str = "task_web") -> WatchRunner:
        self.current_spec = spec
        self.current_task_id = task_id
        self.last_task_id = task_id
        self.current_runner = WatchRunner(
            spec,
            task_id=task_id,
            event_sink=self.sqlite_store.insert_event,
            log_sink=self._runner_log_sink,
        )
        task_payload = build_task_payload(task_id=task_id, spec=spec)
        self.sqlite_store.upsert_task(
            task_id=task_payload["task_id"],
            mode=task_payload["mode"],
            target=task_payload["target"],
            spec=task_payload["spec"],
            created_at=task_payload["created_at"],
        )
        self._last_long_term_summary_at = None
        self._last_long_term_event_index = 0
        self.log_store.write(category="watch", level="info", message="监控任务已装载", task_id=task_id)
        return self.current_runner

    def _flush_long_term_summary(self, *, force: bool = False) -> None:
        if self.current_runner is None or self.current_spec is None or self.current_task_id is None:
            return
        if not self.current_spec.memory.long_term.enabled:
            return
        events = self.current_runner.events
        if not events:
            return
        summary_interval_seconds = max(int(self.current_spec.memory.long_term.summary_interval_minutes), 1) * 60
        latest_event_at = events[-1].timestamp
        if not force and self._last_long_term_summary_at is not None:
            if latest_event_at - self._last_long_term_summary_at < summary_interval_seconds:
                return
        if self._last_long_term_event_index >= len(events):
            return
        pending_events = events[self._last_long_term_event_index :]
        if not pending_events:
            return
        summary = build_long_term_summary(task_id=self.current_task_id, events=pending_events)
        self.sqlite_store.insert_long_term_summary(
            summary_id=summary["summary_id"],
            task_id=summary["task_id"],
            window_start=summary["window_start"],
            window_end=summary["window_end"],
            summary=summary["summary"],
            payload=summary,
        )
        self._prune_expired_long_term_summaries(task_id=self.current_task_id, now=summary["window_end"])
        self._last_long_term_summary_at = summary["window_end"]
        self._last_long_term_event_index = len(events)
        self.log_store.write(
            category="watch",
            level="info",
            message="长期摘要已生成",
            task_id=self.current_task_id,
            metadata={
                "window_start": summary["window_start"],
                "window_end": summary["window_end"],
                "event_count": summary["event_count"],
                "forced": force,
            },
        )

    def clear_runner(self) -> None:
        self.stop_background_watch()
        self._flush_long_term_summary(force=True)
        self.current_runner = None
        self.current_spec = None
        self.current_task_id = None
        self._last_long_term_summary_at = None
        self._last_long_term_event_index = 0
        self.log_store.write(category="watch", level="info", message="监控任务已停止")

    def start_background_watch(self) -> bool:
        if self.current_runner is None:
            return False
        if self._background_thread is not None and self._background_thread.is_alive():
            return True
        self._stop_event.clear()
        interval_sec = max(self.current_spec.sampling.screenshot_interval_ms / 1000.0, 0.2) if self.current_spec else 1.0

        def _loop() -> None:
            self.log_store.write(category="watch", level="info", message="后台持续监控已启动", task_id=self.current_task_id)
            while not self._stop_event.is_set() and self.current_runner is not None:
                try:
                    events = self.current_runner.run_once()
                    for event in events:
                        if getattr(event, "source", "") == "action":
                            self.log_store.write(
                                category="action",
                                level="info",
                                message=event.summary or event.event_type,
                                task_id=self.current_task_id,
                                metadata={"event_type": event.event_type},
                            )
                    self._flush_long_term_summary(force=False)
                except Exception as exc:  # pragma: no cover - defensive logging path
                    self.log_store.write(
                        category="watch",
                        level="error",
                        message="后台持续监控执行失败",
                        task_id=self.current_task_id,
                        metadata={"error": str(exc)},
                    )
                    self.last_error = str(exc)
                    break
                self._stop_event.wait(interval_sec)
            self.log_store.write(category="watch", level="info", message="后台持续监控已结束", task_id=self.current_task_id)

        self._background_thread = threading.Thread(target=_loop, name="ayes-watch-loop", daemon=True)
        self._background_thread.start()
        return True

    def stop_background_watch(self) -> None:
        self._stop_event.set()
        if self._background_thread is not None and self._background_thread.is_alive():
            self._background_thread.join(timeout=1.0)
        self._background_thread = None

    def is_background_running(self) -> bool:
        return self._background_thread is not None and self._background_thread.is_alive()

    def _prune_frontend_sessions(self) -> None:
        now = time.time()
        expired = [session_id for session_id, updated_at in self._frontend_sessions.items() if now - updated_at > self._frontend_session_ttl_sec]
        for session_id in expired:
            self._frontend_sessions.pop(session_id, None)

    def register_frontend_session(self, session_id: str) -> int:
        self._prune_frontend_sessions()
        self._frontend_sessions[session_id] = time.time()
        return len(self._frontend_sessions)

    def touch_frontend_session(self, session_id: str) -> int:
        self._prune_frontend_sessions()
        if session_id in self._frontend_sessions:
            self._frontend_sessions[session_id] = time.time()
        return len(self._frontend_sessions)

    def unregister_frontend_session(self, session_id: str) -> int:
        self._frontend_sessions.pop(session_id, None)
        self._prune_frontend_sessions()
        return len(self._frontend_sessions)

    def connected_frontends(self) -> int:
        self._prune_frontend_sessions()
        return len(self._frontend_sessions)

    def can_shutdown_service(self) -> bool:
        return (not self.is_background_running()) and self.connected_frontends() == 0

    def _build_health_summary(self, *, task_id: Optional[str]) -> dict:
        if not task_id:
            return {
                "last_match": None,
                "last_alert": None,
                "recent_memory": {"count": 0, "latest_timestamp": None},
                "recent_logs": {"count": 0, "error_count": 0, "warn_count": 0, "latest_timestamp": None},
            }
        recent_events = self.sqlite_store.query_events(task_id=task_id, minutes=15, limit=200)
        recent_logs = self.sqlite_store.list_logs(task_id=task_id, since_timestamp=time.time() - (15 * 60), limit=200)
        last_match = None
        last_alert = None
        for item in recent_events:
            source = str(item.get("source") or "")
            if source == "semantic_match":
                last_match = {
                    "summary": item.get("summary") or item.get("event_type") or "",
                    "event_type": item.get("event_type") or "",
                    "timestamp": item.get("timestamp"),
                }
            if source == "alert":
                last_alert = {
                    "summary": item.get("summary") or item.get("event_type") or "",
                    "event_type": item.get("event_type") or "",
                    "timestamp": item.get("timestamp"),
                }
        error_count = 0
        warn_count = 0
        latest_log_timestamp = None
        for entry in recent_logs:
            level = str(entry.get("level") or "").lower()
            if level == "error":
                error_count += 1
            elif level in {"warn", "warning"}:
                warn_count += 1
            entry_timestamp = entry.get("timestamp")
            if entry_timestamp is not None:
                latest_log_timestamp = entry_timestamp
        latest_memory_timestamp = recent_events[-1].get("timestamp") if recent_events else None
        return {
            "last_match": last_match,
            "last_alert": last_alert,
            "recent_memory": {
                "count": len(recent_events),
                "latest_timestamp": latest_memory_timestamp,
            },
            "recent_logs": {
                "count": len(recent_logs),
                "error_count": error_count,
                "warn_count": warn_count,
                "latest_timestamp": latest_log_timestamp,
            },
        }

    def _build_latest_key_event(self) -> Optional[dict]:
        if self.current_runner is None or not self.current_runner.events:
            return None
        ignored_sources = {"capture", "diff", "action"}
        ignored_event_types = {"vision_triggered", "vision_skipped"}
        for event in reversed(self.current_runner.events):
            if event.source in ignored_sources:
                continue
            if event.event_type in ignored_event_types:
                continue
            payload = asdict(event)
            text_preview = (
                ((payload.get("text") or {}).get("ocr_text") or payload.get("summary") or "")
                .strip()
                [:160]
            )
            target = payload.get("target") or {}
            region = payload.get("region") or {}
            return {
                "event_id": payload.get("event_id"),
                "source": payload.get("source"),
                "event_type": payload.get("event_type"),
                "summary": payload.get("summary") or payload.get("event_type") or "",
                "timestamp": payload.get("timestamp"),
                "location_summary": describe_location_summary(payload),
                "text_preview": text_preview,
                "region_name": region.get("name") or region.get("region_id") or "",
                "target_label": target.get("process_name")
                or target.get("window_title")
                or (f"screen:{target.get('screen_id')}" if target.get("screen_id") is not None else ""),
            }
        return None

    def _build_recent_ocr_read(self) -> Optional[dict]:
        if self.current_runner is None or not self.current_runner.events:
            return None
        for event in reversed(self.current_runner.events):
            if event.source != "ocr":
                continue
            payload = asdict(event)
            blocks = ((payload.get("text") or {}).get("blocks") or [])[:3]
            return {
                "summary": payload.get("summary") or "",
                "full_text": ((payload.get("text") or {}).get("ocr_text") or "").strip(),
                "location_summary": describe_location_summary(payload),
                "timestamp": payload.get("timestamp"),
                "provider": ((payload.get("visual") or {}).get("attributes") or {}).get("ocr_provider"),
                "blocks_preview": [
                    {
                        "text": block.get("text") or "",
                        "confidence": block.get("confidence"),
                        "direction": _describe_direction(block.get("rect_norm") or {}),
                        "rect_norm": block.get("rect_norm") or {},
                    }
                    for block in blocks
                ],
            }
        return None

    def status(self) -> dict:
        action_count = 0
        match_count = 0
        alert_count = 0
        last_match_at = None
        last_ocr_quality = None
        last_vision_summary = None
        last_vision_decision = None
        last_capture_target = None
        last_capture_status = None
        resolved_task_id = self.current_task_id or self.last_task_id
        if self.current_runner is not None:
            for event in self.current_runner.events:
                source = getattr(event, "source", "")
                if source == "action":
                    action_count += 1
                if source == "semantic_match":
                    match_count += 1
                    last_match_at = event.timestamp
                if source == "alert":
                    alert_count += 1
                if source == "ocr":
                    attrs = getattr(getattr(event, "visual", None), "attributes", {}) or {}
                    last_ocr_quality = {
                        "summary": getattr(getattr(event, "visual", None), "summary", "") or getattr(event, "summary", ""),
                        "provider": attrs.get("ocr_provider"),
                        "char_count": attrs.get("ocr_char_count"),
                        "block_count": attrs.get("ocr_block_count"),
                        "avg_confidence": attrs.get("ocr_avg_confidence"),
                        "sparse": attrs.get("ocr_sparse"),
                        "timestamp": getattr(event, "timestamp", None),
                    }
                if source == "vision" and getattr(event, "event_type", "") not in {"vision_triggered", "vision_skipped"}:
                    attrs = getattr(getattr(event, "visual", None), "attributes", {}) or {}
                    last_vision_summary = {
                        "summary": getattr(getattr(event, "visual", None), "summary", "") or getattr(event, "summary", ""),
                        "detail_lines": attrs.get("detail_lines") or [],
                        "provider": getattr(getattr(event, "visual", None), "provider", "") or attrs.get("vision_provider"),
                        "timestamp": getattr(event, "timestamp", None),
                    }
                if source == "vision" and getattr(event, "event_type", "") in {"vision_triggered", "vision_skipped"}:
                    attrs = getattr(getattr(event, "visual", None), "attributes", {}) or {}
                    last_vision_decision = {
                        "event_type": getattr(event, "event_type", ""),
                        "summary": getattr(event, "summary", ""),
                        "reasons": attrs.get("vision_reasons") or [],
                        "blocked_reason": attrs.get("vision_blocked_reason") or "",
                        "model": attrs.get("vision_model") or "",
                        "provider": attrs.get("vision_provider") or "",
                        "timestamp": getattr(event, "timestamp", None),
                    }
            for event in reversed(self.current_runner.events):
                if last_capture_status is None:
                    last_capture_status = getattr(getattr(event, "observability", None), "capture_status", None)
                target = getattr(event, "target", None)
                if last_capture_target is None and target is not None:
                    if any(
                        [
                            getattr(target, "window_id", None),
                            getattr(target, "window_title", ""),
                            getattr(target, "process_name", ""),
                            getattr(target, "screen_id", None),
                        ]
                    ):
                        last_capture_target = asdict(target)
                if last_capture_status is not None and last_capture_target is not None:
                    break
        health_summary = self._build_health_summary(task_id=resolved_task_id)
        latest_key_event = self._build_latest_key_event()
        recent_ocr_read = self._build_recent_ocr_read()
        return {
            "has_runner": self.current_runner is not None,
            "is_running": self.is_background_running(),
            "can_shutdown_service": self.can_shutdown_service(),
            "connected_frontends": self.connected_frontends(),
            "task_id": self.current_task_id,
            "last_task_id": self.last_task_id,
            "target": asdict(self.current_spec.target) if self.current_spec else None,
            "spec": asdict(self.current_spec) if self.current_spec else None,
            "mode": self.current_spec.mode if self.current_spec else None,
            "event_count": len(self.current_runner.events) if self.current_runner else 0,
            "action_count": action_count,
            "match_count": match_count,
            "alert_count": alert_count,
            "last_run_at": self.current_runner.last_run_at if self.current_runner else None,
            "last_event_at": self.current_runner.last_event_at if self.current_runner else None,
            "last_match_at": last_match_at,
            "last_ocr_quality": last_ocr_quality,
            "last_vision_summary": last_vision_summary,
            "last_vision_decision": last_vision_decision,
            "last_capture_target": last_capture_target,
            "last_capture_status": last_capture_status,
            "latest_key_event": latest_key_event,
            "recent_ocr_read": recent_ocr_read,
            "task_snapshot": self._build_task_snapshot(),
            "health_summary": health_summary,
            "last_error": self.last_error,
            "log_count": len(self.log_store.list_entries()),
            "last_screenshot_path": self.last_screenshot_path,
            "updated_at": time.time(),
        }
