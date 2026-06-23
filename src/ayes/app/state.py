"""Shared application state for API and Web UI."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Optional

from ayes.app.runner import WatchRunner
from ayes.api.contracts import build_task_payload
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
        self.log_store.write(category="system", level="info", message="Ayes AppState 初始化完成")

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
        self.log_store.write(category="watch", level="info", message="监控任务已装载", task_id=task_id)
        return self.current_runner

    def clear_runner(self) -> None:
        self.stop_background_watch()
        if self.current_runner is not None and self.current_runner.events:
            summary = build_long_term_summary(task_id=self.current_task_id or "task_web", events=self.current_runner.events)
            self.sqlite_store.insert_long_term_summary(
                summary_id=summary["summary_id"],
                task_id=summary["task_id"],
                window_start=summary["window_start"],
                window_end=summary["window_end"],
                summary=summary["summary"],
                payload=summary,
            )
        self.current_runner = None
        self.current_spec = None
        self.current_task_id = None
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

    def status(self) -> dict:
        action_count = 0
        match_count = 0
        alert_count = 0
        last_match_at = None
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
            "last_error": self.last_error,
            "log_count": len(self.log_store.list_entries()),
            "last_screenshot_path": self.last_screenshot_path,
            "updated_at": time.time(),
        }
