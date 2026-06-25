"""Shared application state for API and Web UI."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Optional

from ayes.app.runner import WatchRunner
from ayes.app.paths import runtime_root
from ayes.api.contracts import _describe_direction, build_task_payload, describe_location_summary
from ayes.config.models import TargetRegion, WatchSpec
from ayes.logs.store import LogStore
from ayes.memory.long_term import build_long_term_summary
from ayes.storage.sqlite_store import SQLiteStore
from ayes.targets.discovery.macos import MacOSWindowDiscovery


class AppState:
    def __init__(self) -> None:
        self.runtime_dir = runtime_root()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_store = SQLiteStore()
        self.log_store = LogStore(sink=self.sqlite_store.insert_log)
        self.window_discovery = MacOSWindowDiscovery()
        self.current_runner: Optional[WatchRunner] = None
        self.current_spec: Optional[WatchSpec] = None
        self.current_task_id: Optional[str] = None
        self.last_task_id: Optional[str] = None
        self.last_screenshot_path: Optional[str] = None
        self.last_screenshot_width: Optional[int] = None
        self.last_screenshot_height: Optional[int] = None
        self.last_error: Optional[str] = None
        self._frontend_sessions: dict[str, float] = {}
        self._frontend_session_ttl_sec = 30.0
        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._paused_at: Optional[float] = None
        self._pause_reason: Optional[str] = None
        self._last_region_binding_context: Optional[dict] = None
        self._last_cleanup_reminder_check_at: Optional[float] = None
        self._last_long_term_summary_at: Optional[float] = None
        self._last_long_term_event_index: int = 0
        self._ensure_cleanup_reminder_defaults()
        self._ensure_vision_enhancement_defaults()
        self._ensure_app_settings_defaults()
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
            runtime_dir=self.runtime_dir,
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

    def set_region_binding_context(self, context: Optional[dict]) -> None:
        self._last_region_binding_context = context

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
        self._pause_event.clear()
        self._paused_at = None
        self._pause_reason = None
        self._last_region_binding_context = None
        self.log_store.write(category="watch", level="info", message="监控任务已停止")

    def switch_task(self, task_id: str) -> Optional[dict]:
        task = self.sqlite_store.get_task(task_id)
        if task is None:
            return None
        spec = WatchSpec.from_dict(task["spec"])
        self.clear_runner()
        self.set_runner(spec, task_id=task_id)
        self.log_store.write(category="watch", level="info", message="已切换到历史任务", task_id=task_id)
        return self.sqlite_store.get_task(task_id)

    def list_tasks(self, *, limit: int = 100) -> list[dict]:
        items = self.sqlite_store.list_tasks(limit=limit)
        current_task_id = self.current_task_id
        last_task_id = self.last_task_id
        normalized = []
        for item in items:
            payload = dict(item)
            payload["is_current"] = payload["task_id"] == current_task_id
            payload["is_last_active"] = payload["task_id"] == last_task_id
            normalized.append(payload)
        return normalized

    def delete_task(self, task_id: str) -> dict:
        if task_id == self.current_task_id:
            self.clear_runner()
        deleted = self.sqlite_store.delete_task_data(task_id)
        if task_id == self.last_task_id:
            self.last_task_id = None
        self.log_store.write(category="watch", level="info", message="已删除任务及相关记忆", task_id=task_id, metadata=deleted)
        return deleted

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
                if self._pause_event.is_set():
                    self._stop_event.wait(0.2)
                    continue
                try:
                    events = self.current_runner.run_once()
                    self.persist_latest_screenshot()
                    self._maybe_check_cleanup_reminder(now=time.time())
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

    def remember_screenshot(self, *, path: str, width: Optional[int], height: Optional[int]) -> None:
        self.last_screenshot_path = path
        self.last_screenshot_width = width
        self.last_screenshot_height = height

    def persist_latest_screenshot(self) -> Optional[dict]:
        if self.current_runner is None or self.current_runner.last_captured_frame is None:
            return None
        frame = self.current_runner.last_captured_frame
        latest_dir = self.runtime_dir / "latest"
        latest_dir.mkdir(parents=True, exist_ok=True)
        safe_frame_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(frame.frame_id or "frame"))
        timestamp_ms = int(float(frame.timestamp or time.time()) * 1000)
        screenshot_name = f"latest-frame-{timestamp_ms}-{safe_frame_id}.png"
        screenshot_path = latest_dir / screenshot_name
        screenshot_path.write_bytes(frame.image_bytes)
        compatibility_path = self.runtime_dir / "web-last-frame.png"
        compatibility_path.write_bytes(frame.image_bytes)
        self.remember_screenshot(path=f"runtime/latest/{screenshot_name}", width=frame.width, height=frame.height)
        return {
            "path": str(screenshot_path),
            "compatibility_path": str(compatibility_path),
            "image_width": frame.width,
            "image_height": frame.height,
            "timestamp": frame.timestamp,
        }

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

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def pause_all_watches(self, *, reason: str = "manual", now: Optional[float] = None) -> dict:
        paused_at = now if now is not None else time.time()
        self._pause_event.set()
        self._paused_at = paused_at
        self._pause_reason = reason
        task_id = self.current_task_id or self.last_task_id
        self.log_store.write(
            category="watch",
            level="info",
            message="后台监控已暂停",
            task_id=task_id,
            metadata={"event_type": "watch_paused", "reason": reason},
            timestamp=paused_at,
        )
        return self.control_status()

    def resume_all_watches(self, *, now: Optional[float] = None) -> dict:
        resumed_at = now if now is not None else time.time()
        self._pause_event.clear()
        previous_reason = self._pause_reason
        self._paused_at = None
        self._pause_reason = None
        task_id = self.current_task_id or self.last_task_id
        self.log_store.write(
            category="watch",
            level="info",
            message="后台监控已恢复",
            task_id=task_id,
            metadata={"event_type": "watch_resumed", "reason": previous_reason or "manual"},
            timestamp=resumed_at,
        )
        return self.control_status()

    def control_status(self) -> dict:
        runtime_root = self._runtime_root()
        cleanup_dir = runtime_root / "archive"
        cleanup_dir.mkdir(parents=True, exist_ok=True)
        return {
            "is_paused": self.is_paused(),
            "paused_at": self._paused_at,
            "pause_reason": self._pause_reason,
            "has_runner": self.current_runner is not None,
            "is_running": self.is_background_running(),
            "task_id": self.current_task_id or self.last_task_id,
            "data_dir": str(runtime_root),
            "archive_dir": str(cleanup_dir),
            "cleanup_reminder": self.get_cleanup_reminder(),
        }

    def _runtime_root(self):
        return self.runtime_dir

    def _ensure_cleanup_reminder_defaults(self) -> None:
        if self.sqlite_store.get_cleanup_reminder() is not None:
            return
        archive_dir = self._runtime_root() / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_store.upsert_cleanup_reminder(
            enabled=True,
            last_prompt_at=None,
            snoozed_until=None,
            suppress_forever=False,
            data_dir=str(archive_dir),
            next_check_after_days=7,
        )

    def get_cleanup_reminder(self) -> dict:
        payload = self.sqlite_store.get_cleanup_reminder()
        if payload is None:
            self._ensure_cleanup_reminder_defaults()
            payload = self.sqlite_store.get_cleanup_reminder() or {}
        return payload

    def _ensure_vision_enhancement_defaults(self) -> None:
        if self.sqlite_store.get_vision_enhancement_settings() is not None:
            return
        self.sqlite_store.upsert_vision_enhancement_settings(
            enabled=False,
            provider="ollama",
            model="qwen2.5vl:7b",
            auto_use_when_available=True,
        )

    def get_vision_enhancement_settings(self) -> dict:
        payload = self.sqlite_store.get_vision_enhancement_settings()
        if payload is None:
            self._ensure_vision_enhancement_defaults()
            payload = self.sqlite_store.get_vision_enhancement_settings() or {}
        return payload

    def update_vision_enhancement_settings(
        self,
        *,
        enabled: Optional[bool] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        auto_use_when_available: Optional[bool] = None,
    ) -> dict:
        current = self.get_vision_enhancement_settings()
        self.sqlite_store.upsert_vision_enhancement_settings(
            enabled=bool(enabled) if enabled is not None else bool(current.get("enabled", False)),
            provider=str(provider or current.get("provider") or "ollama"),
            model=str(model or current.get("model") or "qwen2.5vl:7b"),
            auto_use_when_available=bool(auto_use_when_available)
            if auto_use_when_available is not None
            else bool(current.get("auto_use_when_available", True)),
        )
        return self.get_vision_enhancement_settings()

    def _default_app_settings(self) -> dict:
        return {
            "capture_screen_when_display_sleep": False,
            "cleanup_reminder_days": 7,
            "capture_sleep_note": "进程或窗口监控优先使用窗口捕获；整屏熄屏监控依赖 macOS 是否仍提供可读显示帧，不可用时会建议切换到进程监控。",
        }

    def _ensure_app_settings_defaults(self) -> None:
        if self.sqlite_store.get_app_settings() is not None:
            return
        self.sqlite_store.upsert_app_settings(self._default_app_settings())

    def get_app_settings(self) -> dict:
        payload = self.sqlite_store.get_app_settings()
        if payload is None:
            self._ensure_app_settings_defaults()
            payload = self.sqlite_store.get_app_settings() or {}
        defaults = self._default_app_settings()
        merged = {**defaults, **payload}
        return merged

    def update_app_settings(
        self,
        *,
        capture_screen_when_display_sleep: Optional[bool] = None,
        cleanup_reminder_days: Optional[int] = None,
    ) -> dict:
        current = self.get_app_settings()
        next_payload = dict(current)
        if capture_screen_when_display_sleep is not None:
            next_payload["capture_screen_when_display_sleep"] = bool(capture_screen_when_display_sleep)
        if cleanup_reminder_days is not None:
            next_payload["cleanup_reminder_days"] = max(int(cleanup_reminder_days), 1)
            self.update_cleanup_reminder(next_check_after_days=next_payload["cleanup_reminder_days"])
        self.sqlite_store.upsert_app_settings(next_payload)
        self.log_store.write(
            category="control",
            level="info",
            message="应用设置已更新",
            task_id=self.current_task_id or self.last_task_id,
            metadata={"settings": next_payload},
        )
        return self.get_app_settings()

    def _replace_current_regions(self, regions: list[TargetRegion]) -> dict:
        if self.current_spec is None or self.current_task_id is None:
            raise RuntimeError("当前没有已装载监控任务")
        was_running = self.is_background_running()
        was_paused = self.is_paused()
        if was_running:
            self.stop_background_watch()
        updated_target = replace(self.current_spec.target, regions=regions)
        updated_spec = replace(self.current_spec, target=updated_target)
        self.set_runner(updated_spec, task_id=self.current_task_id)
        if was_paused:
            self.pause_all_watches(reason="roi_update_restore_pause")
        if was_running:
            self.start_background_watch()
        return asdict(updated_target)

    def add_current_region(self, region_payload: dict) -> dict:
        if self.current_spec is None:
            raise RuntimeError("当前没有已装载监控任务")
        region = TargetRegion.from_dict(region_payload)
        existing = [item for item in self.current_spec.target.regions if item.region_id != region.region_id]
        target_payload = self._replace_current_regions([*existing, region])
        self.log_store.write(
            category="watch",
            level="info",
            message="当前任务 ROI 已添加",
            task_id=self.current_task_id,
            metadata={"region": asdict(region)},
        )
        return target_payload

    def delete_current_region(self, region_id: str) -> dict:
        if self.current_spec is None:
            raise RuntimeError("当前没有已装载监控任务")
        remaining = [item for item in self.current_spec.target.regions if item.region_id != region_id]
        target_payload = self._replace_current_regions(remaining)
        self.log_store.write(
            category="watch",
            level="info",
            message="当前任务 ROI 已删除",
            task_id=self.current_task_id,
            metadata={"region_id": region_id},
        )
        return target_payload

    def update_cleanup_reminder(
        self,
        *,
        suppress_forever: Optional[bool] = None,
        snoozed_until: Optional[float] = None,
        last_prompt_at: Optional[float] = None,
        next_check_after_days: Optional[int] = None,
    ) -> dict:
        current = self.get_cleanup_reminder()
        self.sqlite_store.upsert_cleanup_reminder(
            enabled=bool(current.get("enabled", True)),
            last_prompt_at=last_prompt_at if last_prompt_at is not None else current.get("last_prompt_at"),
            snoozed_until=snoozed_until if snoozed_until is not None else current.get("snoozed_until"),
            suppress_forever=bool(suppress_forever) if suppress_forever is not None else bool(current.get("suppress_forever", False)),
            data_dir=str(current.get("data_dir") or (self._runtime_root() / "archive")),
            next_check_after_days=int(next_check_after_days if next_check_after_days is not None else (current.get("next_check_after_days") or 7)),
        )
        return self.get_cleanup_reminder()

    def check_cleanup_reminder_due(self, *, now: Optional[float] = None) -> dict:
        current_now = now if now is not None else time.time()
        reminder = self.get_cleanup_reminder()
        if not reminder.get("enabled", True) or reminder.get("suppress_forever", False):
            return {"status": "disabled", "cleanup_reminder": reminder}
        snoozed_until = reminder.get("snoozed_until")
        if snoozed_until is not None and float(snoozed_until) > current_now:
            return {"status": "snoozed", "cleanup_reminder": reminder}
        last_prompt_at = float(reminder.get("last_prompt_at") or 0.0)
        interval_seconds = int(reminder.get("next_check_after_days") or 7) * 24 * 60 * 60
        if last_prompt_at <= 0 or (current_now - last_prompt_at) >= interval_seconds:
            self.log_store.write(
                category="control",
                level="info",
                message="数据清理提醒已到期",
                task_id=self.current_task_id or self.last_task_id,
                metadata={"event_type": "cleanup_reminder_due"},
                timestamp=current_now,
            )
            updated = self.update_cleanup_reminder(last_prompt_at=current_now)
            return {"status": "prompt_due", "cleanup_reminder": updated}
        return {"status": "not_due", "cleanup_reminder": reminder}

    def _maybe_check_cleanup_reminder(self, *, now: float) -> None:
        if self._last_cleanup_reminder_check_at is not None and (now - self._last_cleanup_reminder_check_at) < 60:
            return
        self._last_cleanup_reminder_check_at = now
        self.check_cleanup_reminder_due(now=now)

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

    def _build_activity_status(self, *, now: float) -> dict:
        if self.current_runner is None:
            return {
                "state": "not_running",
                "summary": "当前未装载监控任务",
                "seconds_since_run": None,
                "seconds_since_event": None,
            }
        last_run_at = self.current_runner.last_run_at
        last_event_at = self.current_runner.last_event_at
        seconds_since_run = round(now - last_run_at, 2) if last_run_at is not None else None
        seconds_since_event = round(now - last_event_at, 2) if last_event_at is not None else None
        run_interval_sec = max(float(self.current_spec.sampling.screenshot_interval_ms if self.current_spec else 1000) / 1000.0, 0.2)
        fresh_threshold = max(run_interval_sec * 3.0, 3.0)
        stale_threshold = max(run_interval_sec * 10.0, 10.0)
        if seconds_since_run is None:
            return {
                "state": "idle",
                "summary": "任务已装载，尚未执行采样",
                "seconds_since_run": None,
                "seconds_since_event": seconds_since_event,
            }
        if seconds_since_event is not None and seconds_since_event <= fresh_threshold:
            return {
                "state": "fresh",
                "summary": f"最近 {seconds_since_event:.1f} 秒内仍有新事件，监控链路活跃",
                "seconds_since_run": seconds_since_run,
                "seconds_since_event": seconds_since_event,
            }
        if seconds_since_run <= stale_threshold:
            return {
                "state": "idle",
                "summary": f"最近 {seconds_since_run:.1f} 秒内执行过采样，但暂无更新事件",
                "seconds_since_run": seconds_since_run,
                "seconds_since_event": seconds_since_event,
            }
        return {
            "state": "stale",
            "summary": f"距离最近一次采样已 {seconds_since_run:.1f} 秒，需检查监控是否停滞",
            "seconds_since_run": seconds_since_run,
            "seconds_since_event": seconds_since_event,
        }

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
        now = time.time()
        health_summary = self._build_health_summary(task_id=resolved_task_id)
        latest_key_event = self._build_latest_key_event()
        recent_ocr_read = self._build_recent_ocr_read()
        activity_status = self._build_activity_status(now=now)
        task_context = {
            "current_task_id": self.current_task_id,
            "last_task_id": self.last_task_id,
            "current_task_available": self.current_task_id is not None,
            "last_task_available": self.last_task_id is not None,
            "recent_tasks": [
                {
                    "task_id": item["task_id"],
                    "mode": item["mode"],
                    "target": item["target"],
                    "created_at": item["created_at"],
                    "is_current": item["is_current"],
                    "is_last_active": item["is_last_active"],
                }
                for item in self.list_tasks(limit=5)
            ],
        }
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
            "activity_status": activity_status,
            "task_snapshot": self._build_task_snapshot(),
            "task_context": task_context,
            "health_summary": health_summary,
            "last_error": self.last_error,
            "log_count": len(self.log_store.list_entries()),
            "last_screenshot_path": self.last_screenshot_path,
            "updated_at": now,
        }
